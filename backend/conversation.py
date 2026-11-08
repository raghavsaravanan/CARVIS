"""Authoritative state for a hands-free conversation, shared by the app, Vapi, and this server.

The model decides what to say. This module decides what is true: which vehicle was confirmed
aloud, what the mechanic is working on, which camera request a photo belongs to, and which
technical text may be spoken. Local chat history on the phone is display only.

Sessions live in this process's memory (one Uvicorn worker). Photos are never stored.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from spec_extract import COMPONENTS
from spec_retrieval import LookupResult, SpecificationRefusal, ungrounded_numbers
from spec_schema import VARIANTS, Vehicle

logger = logging.getLogger("carvis.conversation")

SESSION_TTL_SECONDS = 4 * 60 * 60
MAX_SESSIONS = 256
# Whole budget for one look: reaching the phone, a fresh capture, upload, and vision.
# The tool's Vapi server timeout must be longer than this (see vapi_assistant.py).
CAMERA_DEADLINE_SECONDS = 30.0
MAX_TRACE = 200

# These only make sense inside a session. lookup_spec also serves the sessionless assistant.
SESSION_ONLY_TOOLS = ("confirm_vehicle", "set_work_context", "look_at_part")
OPERATIONS = ("inspection", "installation", "alignment", "oil_and_filter", "oil_only", "overhaul_fill")
SPEC_TYPES = ("torque", "fluid_capacity", "dimension", "tolerance")

LookupFn = Callable[[str, "ConversationSession", dict], Awaitable[LookupResult]]
IdentifyFn = Callable[[bytes, str, "ConversationSession"], Awaitable[dict]]


class CameraFailure(RuntimeError):
    """The photo didn't arrive in time, or the phone reported it couldn't take one."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


class StaleCameraResult(RuntimeError):
    """A result for a request that is finished, cancelled, or from an earlier call."""


@dataclass
class CameraRequest:
    request_id: str
    generation: int
    tool_call_id: str
    question: str
    created_at: float
    deadline: float
    future: asyncio.Future
    # queued -> delivered -> processing -> done, or failed / expired / cancelled
    state: str = "queued"

    @property
    def is_open(self) -> bool:
        return self.state in ("queued", "delivered", "processing")


def _resolve(request: CameraRequest, state: str, *, result: dict | None = None,
             error: Exception | None = None) -> None:
    request.state = state
    if request.future.done():
        return
    if error is not None:
        request.future.set_exception(error)
        # The waiting tool call may already have timed out; never log it as unretrieved.
        request.future.exception()
    else:
        request.future.set_result(result or {})


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class ConversationSession:
    session_id: str
    token_digest: str
    owner_name: str
    vehicle: Vehicle
    vehicle_confirmed: bool = False
    component: str | None = None
    operation: str | None = None
    spec_type: str | None = None
    pending_question: str | None = None
    grounded_answer: dict | None = None
    visual: dict | None = None
    # Increases with every call, so anything from an earlier call can be recognized and refused.
    generation: int = 0
    call_active: bool = False
    vapi_call_id: str | None = None
    requests: dict[str, CameraRequest] = field(default_factory=dict)
    by_tool_call: dict[str, CameraRequest] = field(default_factory=dict)
    tool_results: dict[str, dict] = field(default_factory=dict)
    camera_event: asyncio.Event = field(default_factory=asyncio.Event)
    last_seen: float = field(default_factory=time.monotonic)
    trace: list[dict] = field(default_factory=list)

    def note(self, stage: str, **details: Any) -> None:
        self.trace.append({"at": round(time.time(), 3), "generation": self.generation, "stage": stage, **details})
        del self.trace[:-MAX_TRACE]
        logger.info("conversation session=%s gen=%s stage=%s %s", self.session_id[:8], self.generation, stage, details)

    @property
    def owner_first_name(self) -> str:
        return (self.owner_name.split() or [""])[0]

    def vehicle_summary(self) -> str:
        v = self.vehicle
        model = v.model.upper() if len(v.model) <= 4 else v.model.title()
        details = [f"{v.year} {v.make.title()} {model}"]
        if v.trim:
            details.append(v.trim.title())
        if v.transmission:
            details.append(v.transmission.upper())
        if v.wheel_size:
            details.append(f"{v.wheel_size} wheels")
        return ", ".join(details)

    def memory_summary(self) -> str:
        """What a new call in this session should know. Never carries specification values."""
        parts = [f"Vehicle on file: {self.vehicle_summary()}. "
                 + ("The mechanic already confirmed it aloud in this session."
                    if self.vehicle_confirmed else "It has not been confirmed aloud yet.")]
        if self.component:
            parts.append(f"Working on: {self.component.replace('_', ' ')}"
                         + (f", {self.operation.replace('_', ' ')}." if self.operation else "."))
        if self.visual:
            parts.append(f"Last look at the part suggested: {self.visual.get('component')} (not confirmed).")
        if self.pending_question:
            parts.append(f"Unanswered question from earlier: {self.pending_question}")
        if self.grounded_answer:
            parts.append("An answer was already given for that item. To repeat it, call lookup_spec again.")
        return " ".join(parts)

    def view(self) -> dict:
        return {
            "session_id": self.session_id,
            "generation": self.generation,
            "call_active": self.call_active,
            "owner_first_name": self.owner_first_name,
            "vehicle": self.vehicle.model_dump(),
            "vehicle_summary": self.vehicle_summary(),
            "vehicle_confirmed": self.vehicle_confirmed,
            "component": self.component,
            "operation": self.operation,
            "spec_type": self.spec_type,
            "pending_question": self.pending_question,
            "grounded_answer": self.grounded_answer,
            "visual": self.visual,
            "trace": self.trace[-40:],
        }

    def memory_for_model(self) -> dict:
        return {
            "vehicle": self.vehicle_summary(),
            "vehicle_confirmed": self.vehicle_confirmed,
            "component": self.component,
            "operation": self.operation,
            "pending_question": self.pending_question,
        }

    # MARK: Memory changes

    def invalidate_work(self, reason: str, *, keep_pending: bool = True) -> None:
        """A correction makes anything that depended on the old facts unusable."""
        self.component = self.operation = self.spec_type = None
        self.grounded_answer = None
        self.visual = None
        if not keep_pending:
            self.pending_question = None
        self.note("memory_invalidated", reason=reason)

    def apply_vehicle(self, updates: dict[str, str]) -> set[str]:
        """Record a spoken confirmation or correction. Returns the fields that changed."""
        current = self.vehicle.model_dump()
        changed = {key for key, value in updates.items() if value != current.get(key)}
        # Filling in a detail that was unknown contradicts nothing; replacing one does.
        contradicted = {key for key in changed if current.get(key) is not None}
        merged = {**current, **updates}
        if changed & {"year", "make", "model"}:
            # A different car: variants confirmed for the old one don't carry over.
            for variant in VARIANTS:
                if variant not in updates:
                    merged[variant] = None
        vehicle = Vehicle(**merged)  # raises ValueError for an unusable identity
        self.vehicle = vehicle
        self.vehicle_confirmed = True
        if contradicted:
            self.invalidate_work("vehicle corrected: " + ", ".join(sorted(contradicted)))
        self.note("vehicle_confirmed", vehicle=self.vehicle_summary(), changed=sorted(changed))
        return changed

    def apply_app_vehicle(self, vehicle: Vehicle) -> None:
        """The profile was edited on the phone. It must be confirmed aloud again."""
        if vehicle == self.vehicle:
            return
        self.vehicle = vehicle
        self.vehicle_confirmed = False
        self.invalidate_work("vehicle edited in the app")

    # MARK: Calls and camera requests

    def begin_call(self, pending_question: str | None) -> int:
        self.cancel_camera("superseded by a new call")
        self.generation += 1
        self.call_active = True
        self.vapi_call_id = None
        self.tool_results.clear()
        self.by_tool_call.clear()
        if pending_question:
            self.pending_question = pending_question
        self.note("call_started", has_opening_question=bool(pending_question))
        return self.generation

    def end_call(self, reason: str, generation: int | None = None) -> bool:
        if generation is not None and generation != self.generation:
            return False
        if not self.call_active:
            return False
        self.call_active = False
        self.cancel_camera(reason)
        self.note("call_ended", reason=reason)
        return True

    def cancel_camera(self, reason: str) -> None:
        for request in self.requests.values():
            if request.is_open:
                _resolve(request, "cancelled", error=CameraFailure("cancelled", reason))
        self.camera_event.set()

    def expire_camera(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        for request in self.requests.values():
            if request.is_open and request.state != "processing" and now >= request.deadline:
                _resolve(request, "expired", error=CameraFailure("timeout", "No photo arrived before the deadline."))
                self.note("camera_expired", request_id=request.request_id)
        # Old finished requests aren't needed once they can't be confused with a live one.
        finished = [key for key, r in self.requests.items() if not r.is_open and r.generation < self.generation]
        for key in finished:
            del self.requests[key]

    def request_camera(self, tool_call_id: str, question: str) -> CameraRequest:
        """One request per tool call: a repeated webhook joins the one already running."""
        existing = self.by_tool_call.get(tool_call_id)
        if existing is not None and existing.generation == self.generation:
            self.note("camera_duplicate_tool_call", request_id=existing.request_id)
            return existing
        now = time.monotonic()
        request = CameraRequest(request_id=uuid.uuid4().hex, generation=self.generation, tool_call_id=tool_call_id,
                                question=question, created_at=now, deadline=now + CAMERA_DEADLINE_SECONDS,
                                future=asyncio.get_running_loop().create_future())
        self.requests[request.request_id] = request
        self.by_tool_call[tool_call_id] = request
        self.camera_event.set()
        self.note("camera_requested", request_id=request.request_id)
        return request

    async def next_camera_command(self, wait_seconds: float) -> CameraRequest | None:
        """Hand the phone the next command, waiting up to `wait_seconds` (long poll)."""
        give_up = time.monotonic() + wait_seconds
        while True:
            self.last_seen = time.monotonic()
            self.expire_camera()
            for request in self.requests.values():
                if request.state == "queued" and request.generation == self.generation:
                    request.state = "delivered"
                    self.note("camera_delivered", request_id=request.request_id)
                    return request
            remaining = give_up - time.monotonic()
            if remaining <= 0:
                return None
            self.camera_event.clear()
            try:
                await asyncio.wait_for(self.camera_event.wait(), timeout=min(remaining, 1.0))
            except asyncio.TimeoutError:
                pass

    def open_request_for_result(self, request_id: str) -> CameraRequest:
        """The request a photo answers. Anything finished or from another call is refused."""
        self.expire_camera()
        request = self.requests.get(request_id)
        if request is None or request.generation != self.generation or request.state != "delivered":
            raise StaleCameraResult(request_id)
        return request


class ConversationStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ConversationSession] = {}
        self._calls: dict[str, tuple[str, int]] = {}

    def _evict(self) -> None:
        now = time.monotonic()
        for key, session in list(self._sessions.items()):
            if now - session.last_seen > SESSION_TTL_SECONDS:
                session.cancel_camera("session expired")
                del self._sessions[key]
        while len(self._sessions) >= MAX_SESSIONS:
            oldest = min(self._sessions, key=lambda key: self._sessions[key].last_seen)
            self._sessions.pop(oldest).cancel_camera("session evicted")

    def create(self, owner_name: str, vehicle: Vehicle) -> tuple[ConversationSession, str]:
        self._evict()
        # Good for this one session only. It is not a backend API key.
        token = secrets.token_urlsafe(32)
        session = ConversationSession(session_id=uuid.uuid4().hex, token_digest=_digest(token),
                                      owner_name=owner_name.strip(), vehicle=vehicle)
        self._sessions[session.session_id] = session
        session.note("session_created", vehicle=session.vehicle_summary())
        return session, token

    def authenticate(self, session_id: str, token: str) -> ConversationSession | None:
        session = self._sessions.get(session_id)
        if session is None or not hmac.compare_digest(session.token_digest, _digest(token)):
            return None
        session.last_seen = time.monotonic()
        return session

    def bind_call(self, session: ConversationSession, generation: int, vapi_call_id: str) -> bool:
        if generation != session.generation or not session.call_active:
            return False
        session.vapi_call_id = vapi_call_id
        self._calls[vapi_call_id] = (session.session_id, generation)
        session.note("call_bound", vapi_call_id=vapi_call_id)
        return True

    def session_for_webhook(self, payload: dict) -> tuple[ConversationSession | None, bool]:
        """Find the session for a Vapi webhook. Returns (session, is_from_an_earlier_call)."""
        message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        call = message.get("call") if isinstance(message.get("call"), dict) else payload.get("call")
        call = call if isinstance(call, dict) else {}
        call_id = str(call.get("id") or "")
        bound = self._calls.get(call_id)
        if bound:
            session = self._sessions.get(bound[0])
            if session is None:
                return None, False
            session.last_seen = time.monotonic()
            return session, bound[1] != session.generation
        # The webhook can beat the phone's bind call. The ID was set on this call by the app.
        overrides = call.get("assistantOverrides") if isinstance(call.get("assistantOverrides"), dict) else {}
        variables = overrides.get("variableValues") if isinstance(overrides.get("variableValues"), dict) else {}
        session = self._sessions.get(str(variables.get("carvis_session_id") or ""))
        if session is None:
            return None, False
        session.last_seen = time.monotonic()
        if call_id and session.call_active and not session.vapi_call_id:
            self.bind_call(session, session.generation, call_id)
        return session, False

    def handle_call_event(self, payload: dict) -> None:
        """Vapi says the call is over: stop anything still waiting on the phone."""
        message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        kind = message.get("type")
        if kind == "status-update" and message.get("status") != "ended":
            return
        session, stale = self.session_for_webhook(payload)
        if session is not None and not stale:
            session.end_call(f"vapi {kind}")


def tool_name(tool_call: dict) -> str:
    function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
    return str(function.get("name") or tool_call.get("name") or "")


def tool_arguments(tool_call: dict) -> dict:
    function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
    for raw in (function.get("arguments"), function.get("parameters"), tool_call.get("arguments"), tool_call.get("parameters")):
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                continue
        if isinstance(raw, dict):
            return raw
    return {}


def tool_call_id(tool_call: dict, index: int) -> str:
    value = tool_call.get("id") or tool_call.get("toolCallId")
    return value.strip() if isinstance(value, str) and value.strip() else f"tool-call-{index}"


def _text(args: dict, key: str) -> str:
    value = args.get(key)
    return value.strip() if isinstance(value, str) else ("" if value is None else str(value).strip())


_MEASUREMENT = re.compile(r"\b\d+(?:\.\d+)?\s*(?:mm|cm|m|in|inch(?:es)?|ft|feet|lbs?|nm|n·m|newton|psi|kpa|qt|quarts?|l|liters?|litres?|°|degrees?)\b", re.I)


def scrub_measurements(text: str) -> str:
    """Vision output may guess numbers. A guess must never reach the mechanic as a spec."""
    kept = [s for s in re.split(r"(?<=[.!?])\s+", text or "") if not _MEASUREMENT.search(s)]
    return " ".join(kept).strip()


def normalized_variant(key: str, value: str) -> str:
    value = value.strip().lower()
    if key == "wheel_size":
        match = re.search(r"\d{2}", value)
        return f"{match.group(0)}-inch" if match else value
    if key == "transmission":
        if re.search(r"\bcvt\b", value):
            return "cvt"
        if re.search(r"6\s*-?\s*(?:mt|speed)|manual", value):
            return "6mt"
    return value


class ConversationTools:
    """The server side of the assistant's tools. Results are facts; the model words them."""

    def __init__(self, lookup: LookupFn, identify: IdentifyFn):
        self._lookup = lookup
        self._identify = identify

    @staticmethod
    def _entry(name: str, call_id: str, payload: dict, *, spoken: str | None = None) -> dict:
        entry: dict[str, Any] = {"name": name, "toolCallId": call_id,
                                 "result": json.dumps(payload, ensure_ascii=False)}
        if spoken:
            # Vapi speaks this exact text and doesn't ask the model to respond, so validated
            # technical data can't be paraphrased, rounded, or embellished on the way out.
            entry["message"] = {"type": "request-complete", "role": "assistant", "content": spoken}
        return entry

    async def handle(self, session: ConversationSession | None, stale: bool, call: dict, index: int) -> dict:
        name = tool_name(call)
        call_id = tool_call_id(call, index)
        if session is None:
            return self._entry(name, call_id, {"status": "no_session", "reason": "This call has no Carvis session."})
        if stale or not session.call_active:
            session.note("tool_rejected_stale", tool=name)
            return self._entry(name, call_id, {"status": "stale_call", "reason": "This request is from a call that has ended."})
        cached = session.tool_results.get(call_id)
        if cached is not None:
            session.note("tool_duplicate", tool=name)
            return cached
        args = tool_arguments(call)
        handler = {"confirm_vehicle": self._confirm_vehicle, "set_work_context": self._set_work_context,
                   "lookup_spec": self._lookup_spec, "look_at_part": self._look_at_part}.get(name)
        if handler is None:
            return self._entry(name, call_id, {"status": "unknown_tool"})
        result = await handler(session, name, call_id, args)
        session.tool_results[call_id] = result
        return result

    async def _confirm_vehicle(self, session, name, call_id, args) -> dict:
        updates = {key: _text(args, key).lower() for key in ("year", "make", "model") if _text(args, key)}
        updates.update({key: normalized_variant(key, _text(args, key)) for key in VARIANTS if _text(args, key)})
        try:
            changed = session.apply_vehicle(updates)
        except ValueError:
            return self._entry(name, call_id, {"status": "invalid_vehicle",
                                               "reason": "A four-digit year, make, and model are required."})
        return self._entry(name, call_id, {"status": "confirmed", "changed": sorted(changed), "memory": session.memory_for_model()})

    async def _set_work_context(self, session, name, call_id, args) -> dict:
        component = _text(args, "component").lower().replace(" ", "_")
        operation = _text(args, "operation").lower().replace(" ", "_")
        changed = (component and session.component and component != session.component) \
            or (operation and session.operation and operation != session.operation)
        if args.get("clear") is True or changed:
            session.invalidate_work("spoken correction of the work context")
        if component:
            session.component = component
        if operation:
            session.operation = operation
        session.note("work_context", component=session.component, operation=session.operation)
        return self._entry(name, call_id, {"status": "remembered", "memory": session.memory_for_model()})

    async def _lookup_spec(self, session, name, call_id, args) -> dict:
        query = _text(args, "query")
        if not query:
            return self._entry(name, call_id, {"status": "invalid_request", "reason": "A question is required."})
        if not session.vehicle_confirmed:
            session.pending_question = query
            return self._entry(name, call_id, {"status": "vehicle_unconfirmed", "vehicle_on_file": session.vehicle_summary()})
        for key in ("year", "make", "model"):
            spoken_value = _text(args, key).lower()
            if spoken_value and spoken_value != getattr(session.vehicle, key):
                return self._entry(name, call_id, {"status": "vehicle_conflict", "confirmed_vehicle": session.vehicle_summary(),
                                                   "reason": "The request names a different vehicle than the confirmed one."})
        context = {key: value for key in VARIANTS if (value := getattr(session.vehicle, key))}
        if _text(args, "component").lower() in COMPONENTS:
            context["component"] = _text(args, "component").lower()
        if _text(args, "operation").lower() in OPERATIONS:
            context["operation"] = _text(args, "operation").lower()
        if _text(args, "spec_type").lower() in SPEC_TYPES:
            context["spec_type"] = _text(args, "spec_type").lower()
        try:
            result = await self._lookup(query, session, context)
        except SpecificationRefusal as exc:
            session.pending_question = query
            session.note("lookup_refused", code=exc.code)
            return self._entry(name, call_id, {"status": exc.code, "reason": str(exc), "source_grounded": False})
        except Exception as exc:  # noqa: BLE001 - a lookup outage is reported, never guessed around
            logger.error("Carvis lookup failed: %s", type(exc).__name__)
            return self._entry(name, call_id, {"status": "lookup_failed", "source_grounded": False})
        extra = ungrounded_numbers(result.answer, result.records)
        if extra:
            logger.error("Refused to speak ungrounded numbers: %s", extra)
            session.note("speech_rejected", numbers=extra)
            return self._entry(name, call_id, {"status": "unverified", "source_grounded": False})
        record = result.records[0]
        new_work = (record.component, record.operation)
        if session.grounded_answer and new_work != (session.component, session.operation):
            session.grounded_answer = None
        session.component, session.operation, session.spec_type = record.component, record.operation, record.spec_type
        session.pending_question = None
        session.grounded_answer = {"query": query, "text": result.answer, "sources": result.sources}
        session.note("lookup_answered", component=record.component, spec_type=record.spec_type, page=record.source_page)
        return self._entry(name, call_id, {"status": "answered", "source_grounded": True, "answer": result.answer,
                                           "source": result.source}, spoken=result.answer)

    async def _look_at_part(self, session, name, call_id, args) -> dict:
        question = _text(args, "question")
        if not question:
            return self._entry(name, call_id, {"status": "invalid_request", "reason": "A question is required."})
        if not session.vehicle_confirmed:
            return self._entry(name, call_id, {"status": "vehicle_unconfirmed", "vehicle_on_file": session.vehicle_summary()})
        request = session.request_camera(call_id, question)
        try:
            remaining = max(0.0, request.deadline - time.monotonic())
            visual = await asyncio.wait_for(asyncio.shield(request.future), timeout=remaining + 1.0)
        except asyncio.TimeoutError:
            _resolve(request, "expired", error=CameraFailure("timeout"))
            session.note("camera_expired", request_id=request.request_id)
            return self._entry(name, call_id, {"status": "camera_timeout"})
        except CameraFailure as exc:
            session.note("camera_failed", request_id=request.request_id, code=exc.code)
            return self._entry(name, call_id, {"status": f"camera_{exc.code}", "reason": str(exc)})
        return self._entry(name, call_id, {"status": "identified", "visual_hypothesis": visual,
                                           "note": "A visual hypothesis only. It is not a confirmed part and it carries no specifications."})

    async def receive_photo(self, session: ConversationSession, request_id: str, image: bytes) -> dict:
        """A fresh photo answers its request: identify it and release the waiting tool call."""
        request = session.open_request_for_result(request_id)
        request.state = "processing"
        session.note("camera_image_received", request_id=request_id, bytes=len(image))
        try:
            budget = max(1.0, request.deadline - time.monotonic())
            raw = await asyncio.wait_for(self._identify(image, request.question, session), timeout=budget)
        except asyncio.TimeoutError:
            _resolve(request, "failed", error=CameraFailure("vision_timeout", "Identifying the part took too long."))
            session.note("vision_timeout", request_id=request_id)
            raise
        except Exception as exc:
            _resolve(request, "failed", error=CameraFailure("vision_failed", "Couldn't identify the part."))
            session.note("vision_failed", request_id=request_id, error=type(exc).__name__)
            raise
        if not request.is_open:
            raise StaleCameraResult(request_id)  # cancelled while vision was running
        visual = {"component": scrub_measurements(str(raw.get("component", ""))),
                  "confidence": raw.get("confidence", 0.0),
                  "visual_context": scrub_measurements(str(raw.get("visual_context", ""))),
                  "uncertainty": scrub_measurements(str(raw.get("uncertainty", "")))}
        session.visual = visual
        _resolve(request, "done", result=visual)
        session.note("vision_done", request_id=request_id, component=visual["component"], confidence=visual["confidence"])
        return visual

    @staticmethod
    def report_camera_failure(session: ConversationSession, request_id: str, reason: str) -> None:
        request = session.open_request_for_result(request_id)
        _resolve(request, "failed", error=CameraFailure("unavailable", reason[:200]))
        session.note("camera_unavailable", request_id=request_id, reason=reason[:200])

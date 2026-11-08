"""Carvis API: visual context and exact, source-reviewed specification retrieval."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastembed import TextEmbedding
from pydantic import BaseModel
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from conversation import (SESSION_ONLY_TOOLS, ConversationSession, ConversationStore, ConversationTools,
                          StaleCameraResult, tool_name)
from ingest import expand_mechanical_units, run_ingest
from qdrant_v2 import READ_COLLECTION, STAGING_COLLECTION
from spec_schema import Vehicle, VARIANTS
from spec_retrieval import LookupResult, SpecificationRefusal, lookup, normalize_request
from spec_extract import COMPONENTS, component_from_text

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

logger = logging.getLogger("carvis.main")

QDRANT_PATH = PROJECT_ROOT / "carvis_mvp_db"
COLLECTION_NAME = READ_COLLECTION
_VISION_CLIENT = None
EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"
DEFAULT_SHOP_ID = "shop_demo"
MAX_VISION_IMAGE_BYTES = 8 * 1024 * 1024
VISION_MODEL_NAME = os.getenv("VISION_MODEL", "gpt-5.5")
VISION_PROVIDER = (os.getenv("VISION_PROVIDER") or "nemotron").strip().lower()
NEMOTRON_MODEL_NAME = os.getenv(
    "NEMOTRON_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
)
NEMOTRON_BASE_URL = os.getenv(
    "NEMOTRON_BASE_URL", "https://integrate.api.nvidia.com/v1"
).strip()

SPACETIMEDB_URI = (os.getenv("SPACETIMEDB_URI") or "").strip().rstrip("/")
SPACETIMEDB_DB_NAME = (os.getenv("SPACETIMEDB_DB_NAME") or "hackutd").strip()
SPACETIMEDB_TOKEN = (os.getenv("SPACETIMEDB_TOKEN") or "").strip()


async def _spacetime_call_reducer(reducer_name: str, args: list[Any]) -> None:
    """Best-effort async call to SpacetimeDB HTTP reducer endpoint."""
    if not SPACETIMEDB_URI or not SPACETIMEDB_DB_NAME or not SPACETIMEDB_TOKEN:
        return
    url = f"{SPACETIMEDB_URI}/v1/database/{SPACETIMEDB_DB_NAME}/call/{reducer_name}"
    headers = {
        "Authorization": f"Bearer {SPACETIMEDB_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(url, headers=headers, json=args)
            if resp.status_code >= 400:
                logger.warning(
                    "SpacetimeDB reducer %s returned %d: %s",
                    reducer_name,
                    resp.status_code,
                    resp.text[:200],
                )
    except Exception as exc:  # noqa: BLE001 - telemetry writes must never break queries
        logger.debug("SpacetimeDB telemetry write skipped: %s", exc)


# In-memory vehicle context keyed by Vapi callId (single-process demo/prod hop).
_CALL_SESSIONS: dict[str, "CallSession"] = {}
# shop_id → makes/models/years discovered from uploaded Qdrant payloads.
_SHOP_CATALOGS: dict[str, "ShopVehicleCatalog"] = {}

_DIGIT_GAP_RE = re.compile(r"(?<=\d)[.\s]+(?=\d)")
# Dotted part-number groups like "226.020" / "12.13" (not single-digit decimals).
_PART_NUMBER_DOT_RE = re.compile(r"(?<=\d{2})\.(?=\d{2})")
# Contiguous digit runs for TTS digit-spelling (years excluded in helper).
_PART_NUMBER_RUN_RE = re.compile(r"\d{4,}")
_YEAR_LIKE_RE = re.compile(r"^(?:19|20|21)\d{2}$")
_VEHICLE_TYPO_RULES: Sequence[tuple[re.Pattern[str], str]] = (
    (re.compile(r"\bbr[\s\-]?30\b", re.IGNORECASE), "vr30"),
    (re.compile(r"\bdr[\s\-]?30\b", re.IGNORECASE), "vr30"),
    (re.compile(r"\bv[\s\.\-]*r[\s\.\-]*30\b", re.IGNORECASE), "vr30"),
    (re.compile(r"\bfuel[\s\-]?pro\b", re.IGNORECASE), "fel-pro"),
    (re.compile(r"\bfell[\s\-]?pro\b", re.IGNORECASE), "fel-pro"),
    (re.compile(r"\bfelpro\b", re.IGNORECASE), "fel-pro"),
    (re.compile(r"\bchevy\b", re.IGNORECASE), "chevrolet"),
    (re.compile(r"\bsilverad[ao]\b", re.IGNORECASE), "silverado"),
)

_CAUTION_QUERY_HINTS = (
    "warning",
    "caution",
    "safety",
    "tips",
    "tip",
)
_SEQUENCE_QUERY_HINTS = (
    "sequence",
    "pattern",
    "cross pattern",
    "cross-pattern",
    "tightening order",
    "torque sequence",
    "bolt order",
)

_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEPARATOR_RE = re.compile(
    r"^\s*\|?(?:\s*:?-+:?\s*\|)+\s*:?-+:?\s*\|?\s*$"
)
_HTML_ENTITY_RE = re.compile(r"&#x[0-9a-fA-F]+;|&[a-zA-Z]+;")
_MARKDOWN_EMPHASIS_RE = re.compile(r"\*+")
_MULTI_SPACE_RE = re.compile(r"\s+")
_UNIT_TOKEN_RE = re.compile(
    r"foot-pounds|inch-pounds|newton-meters",
    re.IGNORECASE,
)
_CAUTION_START_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\*{0,2})?(?:WARNING|CAUTION|NOTE|IMPORTANT)"
    r"(?:\*{0,2})?\s*[:\-–]?\s*(.*)$",
    re.IGNORECASE,
)
_QUERY_TORQUE_HINTS = (
    "torque",
    "final",
    "initial",
    "first",
    "pass",
    "fastener",
    "bolt",
    "tighten",
    "spec",
)


@dataclass
class SpokenAnswer:
    tool_call_id: str
    ok: bool
    result: str | None = None
    error: str | None = None

    def to_vapi_result(self) -> dict[str, str]:
        payload: dict[str, str] = {"toolCallId": self.tool_call_id}
        if self.ok and self.result is not None:
            payload["result"] = to_single_line(self.result)
        else:
            payload["error"] = to_single_line(
                self.error or "Unable to resolve specification."
            )
        return payload


@dataclass
class CallSession:
    """Per-call vehicle memory for hands-free follow-up questions."""

    make: str = ""
    model: str = ""
    year: str = ""


@dataclass(frozen=True)
class ShopVehicleCatalog:
    """Vehicles present in a shop's uploaded Qdrant corpus (the living brain)."""

    makes: frozenset[str]
    models: frozenset[str]
    years: frozenset[str]
    # (year, make, model) triples as stored on points
    triples: frozenset[tuple[str, str, str]]

    @property
    def is_empty(self) -> bool:
        return not self.triples and not self.makes and not self.models


def get_shop_vehicle_catalog(
    client: QdrantClient,
    shop_id: str,
    *,
    force_refresh: bool = False,
) -> ShopVehicleCatalog:
    """Build (and cache) make/model/year sets from Qdrant payloads for one shop."""
    tenant = (shop_id or DEFAULT_SHOP_ID).strip().lower() or DEFAULT_SHOP_ID
    if not force_refresh and tenant in _SHOP_CATALOGS:
        return _SHOP_CATALOGS[tenant]

    makes: set[str] = set()
    models: set[str] = set()
    years: set[str] = set()
    triples: set[tuple[str, str, str]] = set()

    shop_filter = qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="shop_id",
                match=qmodels.MatchValue(value=tenant),
            )
        ]
    )
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=shop_filter,
            limit=128,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            payload = getattr(point, "payload", None) or {}
            if not isinstance(payload, dict):
                continue
            year = str(payload.get("year") or "").strip().lower()
            make = str(payload.get("make") or "").strip().lower()
            model = str(payload.get("model") or "").strip().lower()
            if make:
                makes.add(make)
            if model:
                models.add(model)
            if year:
                years.add(year)
            if make or model or year:
                triples.add((year, make, model))
        if offset is None:
            break

    catalog = ShopVehicleCatalog(
        makes=frozenset(makes),
        models=frozenset(models),
        years=frozenset(years),
        triples=frozenset(triples),
    )
    _SHOP_CATALOGS[tenant] = catalog
    logger.info(
        "shop catalog ready shop_id=%r makes=%s models=%s years=%s triples=%d",
        tenant,
        sorted(makes),
        sorted(models),
        sorted(years),
        len(triples),
    )
    return catalog


def invalidate_shop_catalog(shop_id: str | None = None) -> None:
    """Drop cached catalog(s) after a re-ingest so the brain refreshes."""
    if shop_id:
        _SHOP_CATALOGS.pop(
            (shop_id or DEFAULT_SHOP_ID).strip().lower() or DEFAULT_SHOP_ID,
            None,
        )
    else:
        _SHOP_CATALOGS.clear()


def query_normalizer(query: str) -> str:
    """Repair STT digit gaps and common vehicle/brand mishears before search."""
    text = (query or "").strip()
    if not text:
        return ""

    # "20. 19" -> "2019", "226. 042" -> "226042"
    text = _DIGIT_GAP_RE.sub("", text)

    for pattern, replacement in _VEHICLE_TYPO_RULES:
        text = pattern.sub(replacement, text)

    return _MULTI_SPACE_RE.sub(" ", text).strip()


def _extract_call_id(payload: dict[str, Any]) -> str:
    for key in ("callId", "call_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    call = payload.get("call")
    if isinstance(call, dict):
        for key in ("id", "callId", "call_id"):
            value = call.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    message = payload.get("message")
    if isinstance(message, dict):
        nested_call = message.get("call")
        if isinstance(nested_call, dict):
            for key in ("id", "callId", "call_id"):
                value = nested_call.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        for key in ("callId", "call_id"):
            value = message.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return ""


def _extract_tool_call_id(payload: dict[str, Any]) -> str:
    """Prefer Vapi toolCall.id; never confuse with session callId."""
    for key in ("toolCallId", "tool_call_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    tool_calls = extract_tool_call_list(payload)
    if tool_calls:
        return extract_tool_call_id(tool_calls[0], 0)

    return "vapi-call"


def _get_or_create_session(call_id: str) -> CallSession | None:
    if not call_id:
        return None
    session = _CALL_SESSIONS.get(call_id)
    if session is None:
        session = CallSession()
        _CALL_SESSIONS[call_id] = session
    return session


def _apply_session_vehicle_fields(
    call_id: str,
    make: str,
    model: str,
    year: str,
) -> tuple[str, str, str]:
    """Fill missing make/model/year from the in-memory call session."""
    session = _get_or_create_session(call_id)
    if session is None:
        return make, model, year

    if any((value and value != getattr(session, field)) for field, value in
           (("make", make), ("model", model), ("year", year))):
        # Switching cars requires a complete new identity; never mix sessions.
        return make, model, year
    make_out = make or session.make
    model_out = model or session.model
    year_out = year or session.year
    return make_out, model_out, year_out


def _update_session_vehicle_fields(
    call_id: str,
    make: str,
    model: str,
    year: str,
) -> None:
    session = _get_or_create_session(call_id)
    if session is None:
        return
    if make:
        session.make = make
    if model:
        session.model = model
    if year:
        session.year = year


def _should_include_caution(query: str) -> bool:
    lowered = (query or "").lower()
    if any(hint in lowered for hint in _CAUTION_QUERY_HINTS):
        return True
    if any(hint in lowered for hint in _SEQUENCE_QUERY_HINTS):
        return True
    return False


def to_single_line(text: str) -> str:
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = cleaned.replace("\n", " ").replace("\t", " ")
    cleaned = _HTML_ENTITY_RE.sub(" ", cleaned)
    cleaned = _MARKDOWN_EMPHASIS_RE.sub("", cleaned)
    # Collapse dotted part-number sequences: "226.020" -> "226020", "12.13" -> "1213".
    # Requires 2+ digits on each side so values like "1.5" stay intact.
    cleaned = _PART_NUMBER_DOT_RE.sub("", cleaned)
    cleaned = _MULTI_SPACE_RE.sub(" ", cleaned).strip()
    return cleaned


def format_number_for_speech(text: str) -> str:
    """Spell part-number digit runs individually for TTS clarity.

    Sequences of 4+ digits (except years like 2019) become spaced digits so
    "1213" is spoken as "1 2 1 3" rather than "one thousand two hundred thirteen".
    """

    def _replace_run(match: re.Match[str]) -> str:
        digits = match.group(0)
        if _YEAR_LIKE_RE.fullmatch(digits):
            return digits
        # Prefer explicit 4-5 digit part numbers; longer OEM application
        # codes (e.g. 226042) are also digit-spelled for the same reason.
        if len(digits) < 4:
            return digits
        return " ".join(digits)

    return _PART_NUMBER_RUN_RE.sub(_replace_run, text or "")


def _split_table_cells(row: str) -> list[str]:
    stripped = row.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_separator_row(row: str) -> bool:
    return bool(_TABLE_SEPARATOR_RE.match(row.strip()))


def _parse_table_and_caution(chunk_text: str) -> tuple[list[list[str]], str]:
    lines = chunk_text.splitlines()
    table_rows: list[list[str]] = []
    caution_parts: list[str] = []
    past_table = False

    for raw_line in lines:
        line = raw_line.rstrip()
        if not past_table and _TABLE_ROW_RE.match(line):
            if _is_separator_row(line):
                continue
            cells = _split_table_cells(line)
            if cells:
                table_rows.append(cells)
            continue

        if table_rows:
            past_table = True

        if not past_table:
            continue

        if not line.strip():
            continue

        caution_match = _CAUTION_START_RE.match(line)
        if caution_match is not None:
            remainder = caution_match.group(1).strip()
            if remainder:
                caution_parts.append(remainder)
            continue

        caution_parts.append(line.strip())

    caution_text = to_single_line(" ".join(caution_parts)) if caution_parts else ""
    return table_rows, caution_text


def _header_map(header_cells: Sequence[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, cell in enumerate(header_cells):
        key = cell.strip().lower()
        if key:
            mapping[key] = index
    return mapping


def _cell_at(row: Sequence[str], mapping: dict[str, int], *names: str) -> str:
    for name in names:
        index = mapping.get(name)
        if index is not None and index < len(row):
            return row[index].strip()
    return ""


def _row_has_unit(row_text: str) -> bool:
    return bool(_UNIT_TOKEN_RE.search(row_text))


def _query_hint_tokens(query: str) -> set[str]:
    lowered = query.lower()
    return {hint for hint in _QUERY_TORQUE_HINTS if hint in lowered}


def _query_content_tokens(query: str) -> set[str]:
    stop = {
        "a", "an", "the", "for", "and", "or", "of", "to", "on", "in", "what",
        "whats", "is", "are", "me", "my", "please", "spec", "specs",
    }
    tokens = set()
    for raw in query.lower().replace("/", " ").replace("-", " ").split():
        token = "".join(ch for ch in raw if ch.isalnum())
        if len(token) >= 3 and token not in stop:
            tokens.add(token)
    return tokens


def _score_row(
    application: str,
    notes: str,
    torque: str,
    hints: set[str],
    query_tokens: set[str] | None = None,
) -> int:
    haystack = f"{application} {notes} {torque}".lower()
    score = 0
    if _row_has_unit(haystack):
        score += 10
    for hint in hints:
        if hint in haystack:
            score += 5
    if query_tokens:
        for token in query_tokens:
            if token in haystack:
                score += 8
    if "final" in haystack:
        score += 3
    if "initial" in haystack or "first" in haystack:
        score += 2
    return score


def _compose_spec_sentence(application: str, torque: str, notes: str) -> str:
    application = to_single_line(application)
    torque = to_single_line(torque)
    notes = to_single_line(notes)

    if torque and application:
        app_lower = application.lower()
        if "final" in app_lower:
            sentence = f"The final torque is {torque}."
        elif "initial" in app_lower or "first" in app_lower:
            sentence = f"The initial torque is {torque}."
        else:
            sentence = f"{application}: {torque}."
    elif torque:
        sentence = f"The specification is {torque}."
    elif application and notes:
        sentence = f"{application}: {notes}."
    elif notes:
        sentence = notes if notes.endswith(".") else f"{notes}."
    elif application:
        sentence = application if application.endswith(".") else f"{application}."
    else:
        sentence = "The matching specification table was found but had no readable values."

    sentence = expand_mechanical_units(sentence)
    if notes and torque and notes.lower() not in sentence.lower():
        if "follow" in notes.lower() or "sequence" in notes.lower():
            note_clause = notes if notes.endswith(".") else f"{notes}."
            sentence = f"{sentence.rstrip('.')}."
            sentence = f"{sentence} {note_clause}"
    return to_single_line(sentence)


def _compose_warning_sentence(caution_text: str) -> str:
    caution = to_single_line(expand_mechanical_units(caution_text))
    caution = re.sub(
        r"^(?:warning|caution|note|important)\b\s*[:\-!]+\s*",
        "",
        caution,
        flags=re.I,
    )
    caution = caution.strip(" \t:-*!")
    # Drop truncated / empty cautions like "!" left over from OCR noise.
    if len(caution) < 12:
        return ""
    body = caution
    if not body.lower().startswith(("warning", "caution", "note", "important")):
        body = f"Caution: {body}"
    if not body.endswith("."):
        body = f"{body}."
    return to_single_line(body)


def format_voice_answer(chunk_text: str, query: str) -> str:
    """Format v2 results directly; retain the legacy formatter for offline compatibility tests."""
    if isinstance(chunk_text, LookupResult):
        return chunk_text.answer
    expanded_chunk = expand_mechanical_units(chunk_text)
    table_rows, caution_text = _parse_table_and_caution(expanded_chunk)

    if not table_rows:
        fallback = to_single_line(expanded_chunk)
        if not fallback:
            return "No readable specification text was available."
        sentences = [
            part.strip()
            for part in re.split(r"(?<=[.!?])\s+", fallback)
            if part.strip()
        ]
        return format_number_for_speech(to_single_line(" ".join(sentences[:2])))

    header = table_rows[0]
    body_rows = table_rows[1:] if len(table_rows) > 1 else []
    mapping = _header_map(header)

    looks_like_header = any(
        key in mapping for key in ("application", "torque", "notes", "gasket", "cfm")
    )
    if not looks_like_header:
        body_rows = table_rows
        mapping = {}

    hints = _query_hint_tokens(query)
    query_tokens = _query_content_tokens(query)
    scored: list[tuple[int, str, str, str]] = []

    for row in body_rows:
        if mapping:
            application = _cell_at(row, mapping, "application", "item", "fastener")
            torque = _cell_at(row, mapping, "torque", "spec", "specification", "english units")
            notes = _cell_at(row, mapping, "notes", "note", "gasket", "cfm")
            if not torque and len(row) >= 2:
                torque = row[1].strip()
            if not application and row:
                application = row[0].strip()
            if not notes and len(row) >= 3:
                notes = row[-1].strip()
        else:
            application = row[0].strip() if row else ""
            torque = row[1].strip() if len(row) > 1 else ""
            notes = row[2].strip() if len(row) > 2 else ""

        joined = f"{application} {torque} {notes}"
        score = _score_row(
            application,
            notes,
            torque,
            hints,
            query_tokens=query_tokens,
        )
        if score <= 0 and not _row_has_unit(joined) and not hints:
            score = 1
        scored.append((score, application, torque, notes))

    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        primary = "The matching specification table was found but had no data rows."
    else:
        _, application, torque, notes = scored[0]
        primary = _compose_spec_sentence(application, torque, notes)

        # Prefer a final-pass line as second factual sentence when the top hit is initial.
        if "initial" in application.lower() or "first" in application.lower():
            for score, app2, torque2, notes2 in scored[1:]:
                if score <= 0:
                    break
                if "final" in app2.lower() and torque2:
                    second_fact = _compose_spec_sentence(app2, torque2, notes2)
                    primary = to_single_line(f"{primary} {second_fact}")
                    break

    warning = ""
    if _should_include_caution(query):
        warning = _compose_warning_sentence(caution_text)

    if warning and warning.lower() not in primary.lower():
        combined = to_single_line(f"{primary} {warning}")
    else:
        combined = to_single_line(primary)

    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+", combined)
        if part.strip()
    ]
    clipped = " ".join(sentences[:2])
    spoken = to_single_line(expand_mechanical_units(clipped))
    return format_number_for_speech(spoken)


def _payload_text(hit: Any) -> str | None:
    payload = getattr(hit, "payload", None) or {}
    if not isinstance(payload, dict):
        return None
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    return text


def _hit_score(hit: Any) -> float | None:
    score = getattr(hit, "score", None)
    if score is None:
        return None
    try:
        return float(score)
    except (TypeError, ValueError):
        return None


def _vehicle_fields_in_catalog(
    catalog: ShopVehicleCatalog,
    year: str,
    make: str,
    model: str,
) -> bool:
    """False when requested make/model/year is not present in uploaded shop data."""
    if catalog.is_empty:
        return False
    if make and make not in catalog.makes:
        return False
    if model and model not in catalog.models:
        return False
    if year and year not in catalog.years:
        return False
    if year and make and model:
        return (year, make, model) in catalog.triples
    if make and model:
        if not any(t[1] == make and t[2] == model for t in catalog.triples):
            return False
    return True


def _payload_vehicle_matches(
    hit: Any,
    year: str,
    make: str,
    model: str,
) -> bool:
    """Reject hits whose payload vehicle tags contradict explicit request fields."""
    payload = getattr(hit, "payload", None) or {}
    if not isinstance(payload, dict):
        return False
    if make:
        hit_make = str(payload.get("make") or "").strip().lower()
        if hit_make and hit_make != make:
            return False
    if model:
        hit_model = str(payload.get("model") or "").strip().lower()
        if hit_model and hit_model != model:
            return False
    if year:
        hit_year = str(payload.get("year") or "").strip().lower()
        if hit_year and hit_year != year:
            return False
    return True


def _accept_hit(
    hit: Any,
    *,
    min_score: float | None,
    year: str,
    make: str,
    model: str,
    pass_name: str,
) -> str | None:
    text = _payload_text(hit)
    if not text:
        return None
    if not _payload_vehicle_matches(hit, year, make, model):
        logger.info(
            "reject %s: vehicle payload mismatch year=%r make=%r model=%r",
            pass_name,
            year or None,
            make or None,
            model or None,
        )
        return None
    if min_score is not None:
        score = _hit_score(hit)
        if score is None or score < min_score:
            logger.info(
                "reject %s: score=%s below min=%.3f",
                pass_name,
                score,
                min_score,
            )
            return None
        logger.info("accept %s: score=%.4f", pass_name, score)
    return text


def _query_vector_for(
    embedder: TextEmbedding,
    query: str,
    year: str,
    make: str,
    model: str,
) -> list[float] | None:
    # Fold vehicle context into the embedding so semantic fallback still
    # prefers chunks that mention related applications / torque language.
    vehicle_bits = [part for part in (year, make, model) if part]
    embed_text = query
    if vehicle_bits:
        embed_text = f"{query} {' '.join(vehicle_bits)}".strip()

    vectors = list(embedder.embed([embed_text]))
    if not vectors:
        return None
    return list(vectors[0])


def _search_points(
    client: QdrantClient,
    query_vector: list[float],
    query_filter: qmodels.Filter | None,
    limit: int = 16,
) -> list[Any]:
    response = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        query_filter=query_filter,
        limit=limit,
        with_payload=True,
    )
    if response is None or not response.points:
        return []
    return list(response.points)


def _shop_id_condition(shop_id: str) -> qmodels.FieldCondition:
    tenant = (shop_id or DEFAULT_SHOP_ID).strip().lower() or DEFAULT_SHOP_ID
    return qmodels.FieldCondition(
        key="shop_id",
        match=qmodels.MatchValue(value=tenant),
    )


def _search_top_chunk_sync(
    client, embedder, query: str, year: str, make: str, model: str,
    shop_id: str = DEFAULT_SHOP_ID, context: dict | None = None,
) -> LookupResult:
    try:
        vehicle = Vehicle(shop_id=shop_id, year=year, make=make, model=model)
    except ValueError as exc:
        raise SpecificationRefusal("Please confirm the exact year, make, and model.", "clarification") from exc
    return lookup(client, embedder, COLLECTION_NAME, query, vehicle, context)


async def search_top_chunk(
    client, embedder, query: str, year: str, make: str, model: str,
    shop_id: str = DEFAULT_SHOP_ID, context: dict | None = None,
) -> LookupResult:
    return await asyncio.to_thread(
        _search_top_chunk_sync, client, embedder, query, year, make, model, shop_id, context,
    )


def _coerce_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        parts = [_coerce_string(item) for item in value]
        return " ".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        return ""
    return str(value).strip()


def extract_tool_arguments(tool_call: dict[str, Any]) -> dict[str, str]:
    """Pull query/make/model/year/shop_id from a Vapi toolCallList entry safely."""
    raw_args: Any = tool_call.get("parameters")
    if raw_args is None:
        raw_args = tool_call.get("arguments")

    if isinstance(raw_args, str):
        import json

        try:
            parsed = json.loads(raw_args)
        except json.JSONDecodeError:
            parsed = {}
        raw_args = parsed

    if not isinstance(raw_args, dict):
        function_block = tool_call.get("function")
        if isinstance(function_block, dict):
            nested = function_block.get("arguments") or function_block.get("parameters")
            if isinstance(nested, str):
                import json

                try:
                    nested = json.loads(nested)
                except json.JSONDecodeError:
                    nested = {}
            raw_args = nested if isinstance(nested, dict) else {}
        else:
            raw_args = {}

    return {
        "query": _coerce_string(raw_args.get("query")),
        "make": _coerce_string(raw_args.get("make")).lower(),
        "model": _coerce_string(raw_args.get("model")).lower(),
        "year": _coerce_string(raw_args.get("year")).lower(),
        "shop_id": _coerce_string(raw_args.get("shop_id")).lower(),
        **{k: _coerce_string(raw_args.get(k)).lower() for k in (*VARIANTS, "component", "operation", "spec_type")},
    }


def normalize_vapi_lookup_payload(payload: dict[str, Any]) -> dict[str, str]:
    """Accept flat apiRequest bodies or nested message.toolCallList webhooks."""
    query = str(payload.get("query") or "").strip()
    make = str(payload.get("make") or "").strip().lower()
    model = str(payload.get("model") or "").strip().lower()
    year = str(payload.get("year") or "").strip().lower()
    shop_id = str(payload.get("shop_id") or "").strip().lower()
    tool_call_id = _extract_tool_call_id(payload)

    if not query:
        tool_calls = extract_tool_call_list(payload)
        if tool_calls:
            first = tool_calls[0]
            tool_call_id = extract_tool_call_id(first, 0)
            args = extract_tool_arguments(first)
            query = args.get("query") or ""
            make = make or args.get("make") or ""
            model = model or args.get("model") or ""
            year = year or args.get("year") or ""
            shop_id = shop_id or args.get("shop_id") or ""

    optional = {k: _coerce_string(payload.get(k)).lower() for k in (*VARIANTS, "component", "operation", "spec_type")}
    calls = extract_tool_call_list(payload)
    if calls:
        arguments = extract_tool_arguments(calls[0])
        optional = {k: v or arguments.get(k, "") for k, v in optional.items()}

    # Some apiRequest configs nest fields under "parameters".
    if not query:
        nested = payload.get("parameters")
        if isinstance(nested, str):
            import json

            try:
                nested = json.loads(nested)
            except json.JSONDecodeError:
                nested = {}
        if isinstance(nested, dict):
            optional = {k: v or _coerce_string(nested.get(k)).lower() for k, v in optional.items()}
            query = str(nested.get("query") or "").strip()
            make = make or str(nested.get("make") or "").strip().lower()
            model = model or str(nested.get("model") or "").strip().lower()
            year = year or str(nested.get("year") or "").strip().lower()
            shop_id = shop_id or str(nested.get("shop_id") or "").strip().lower()

    return {
        "query": query,
        "make": make,
        "model": model,
        "year": year,
        "shop_id": shop_id or DEFAULT_SHOP_ID,
        "tool_call_id": tool_call_id or "vapi-call",
        **optional,
    }


def extract_tool_call_id(tool_call: dict[str, Any], index: int) -> str:
    tool_call_id = tool_call.get("id") or tool_call.get("toolCallId")
    if isinstance(tool_call_id, str) and tool_call_id.strip():
        return tool_call_id.strip()
    return f"tool-call-{index}"


def extract_tool_call_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect tool-call dicts from common Vapi webhook shapes."""

    def _from_list(raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, dict)]

    # Flat / legacy: toolCallList at payload root.
    top = _from_list(payload.get("toolCallList")) or _from_list(
        payload.get("toolCalls")
    )
    if top:
        return top

    message = payload.get("message")
    if not isinstance(message, dict):
        return []

    tool_call_list = _from_list(message.get("toolCallList")) or _from_list(
        message.get("toolCalls")
    )
    if tool_call_list:
        return tool_call_list

    tool_with_list = message.get("toolWithToolCallList")
    if isinstance(tool_with_list, list):
        recovered: list[dict[str, Any]] = []
        for item in tool_with_list:
            if not isinstance(item, dict):
                continue
            nested = item.get("toolCall")
            if isinstance(nested, dict):
                merged = dict(nested)
                if "name" not in merged and "name" in item:
                    merged["name"] = item["name"]
                if "parameters" not in merged and "parameters" in item:
                    merged["parameters"] = item["parameters"]
                # Older embeds: toolCall.function.parameters
                function_block = nested.get("function")
                if isinstance(function_block, dict):
                    if "parameters" not in merged and "parameters" in function_block:
                        merged["parameters"] = function_block["parameters"]
                    if "arguments" not in merged and "arguments" in function_block:
                        merged["arguments"] = function_block["arguments"]
                recovered.append(merged)
            else:
                recovered.append(item)
        return recovered

    return []


def handle_tool_call(
    tool_call: dict[str, Any],
    index: int,
    client: QdrantClient,
    embedder: TextEmbedding,
) -> SpokenAnswer:
    tool_call_id = extract_tool_call_id(tool_call, index)
    args = extract_tool_arguments(tool_call)

    missing = [
        name
        for name in ("query", "make", "model", "year")
        if not args.get(name)
    ]
    if missing:
        return SpokenAnswer(
            tool_call_id=tool_call_id,
            ok=False,
            error=(
                "Missing required tool parameters: "
                + ", ".join(missing)
                + "."
            ),
        )

    try:
        chunk_text = _search_top_chunk_sync(
            client=client,
            embedder=embedder,
            query=args["query"],
            year=args["year"],
            make=args["make"],
            model=args["model"],
            shop_id=args.get("shop_id") or DEFAULT_SHOP_ID,
            context={k: args.get(k) for k in (*VARIANTS, "component", "operation", "spec_type")},
        )
    except Exception as exc:  # noqa: BLE001 - surface as Vapi tool error string
        return SpokenAnswer(
            tool_call_id=tool_call_id,
            ok=False,
            error=f"Specification lookup failed: {exc}.",
        )

    if chunk_text is None:
        return SpokenAnswer(
            tool_call_id=tool_call_id,
            ok=False,
            error="No specification found for that year make and model.",
        )

    spoken = format_voice_answer(chunk_text, args["query"])
    if not spoken:
        return SpokenAnswer(
            tool_call_id=tool_call_id,
            ok=False,
            error="Specification found but could not be formatted for speech.",
        )

    return SpokenAnswer(tool_call_id=tool_call_id, ok=True, result=spoken)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        )
    logger.setLevel(logging.INFO)
    logger.info("Carvis webhook starting up")

    # On Render, cloud Qdrant is mandatory — never fall back to a missing local path.
    on_render = bool((os.getenv("RENDER") or "").strip())
    qdrant_url = (os.getenv("QDRANT_URL") or "").strip()
    qdrant_api_key = (os.getenv("QDRANT_API_KEY") or "").strip()

    if on_render and not (qdrant_url and qdrant_api_key):
        raise RuntimeError(
            "Render deploy requires QDRANT_URL and QDRANT_API_KEY environment variables."
        )

    embedder = TextEmbedding(model_name=EMBEDDING_MODEL_NAME)

    if qdrant_url and qdrant_api_key:
        client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key, timeout=10.0)
        collection_location = qdrant_url
    else:
        if not QDRANT_PATH.exists():
            raise RuntimeError(
                f"Qdrant path does not exist: {QDRANT_PATH}. Run ingest.py first."
            )
        client = QdrantClient(path=str(QDRANT_PATH), timeout=10.0)
        collection_location = str(QDRANT_PATH)

    if not client.collection_exists(COLLECTION_NAME):
        client.close()
        raise RuntimeError(
            f"Qdrant collection '{COLLECTION_NAME}' was not found at "
            f"{collection_location}."
        )

    logger.info("Qdrant ready at %s collection=%s", collection_location, COLLECTION_NAME)
    invalidate_shop_catalog()
    app.state.embedder = embedder
    app.state.qdrant = client
    try:
        yield
    finally:
        global _VISION_CLIENT
        if _VISION_CLIENT is not None:
            await _VISION_CLIENT.close()
            _VISION_CLIENT = None
        client.close()
        invalidate_shop_catalog()
        logger.info("Carvis webhook shut down")


app = FastAPI(
    title="Carvis Vapi Tool Webhook",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness endpoint for Render / load balancers."""
    return {"status": "ok", "service": "carvis"}


class VisionConfigurationError(RuntimeError):
    """Raised when the configured vision provider cannot be used."""


def _validate_jpeg(image_bytes: bytes, content_type: str | None) -> None:
    """Reject missing, oversized, or non-JPEG uploads before inference."""
    if not image_bytes:
        raise HTTPException(status_code=400, detail="A JPEG image is required.")
    if len(image_bytes) > MAX_VISION_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Image must be {MAX_VISION_IMAGE_BYTES // (1024 * 1024)} MB or smaller.",
        )
    normalized_type = (content_type or "").lower().split(";", 1)[0].strip()
    if normalized_type not in {"image/jpeg", "image/jpg"}:
        raise HTTPException(status_code=415, detail="Only image/jpeg uploads are supported.")
    if not image_bytes.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid JPEG.")


def _parse_vision_result(raw_text: str) -> dict[str, Any]:
    """Parse the deliberately small JSON contract returned by the vision model."""
    cleaned = (raw_text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise VisionConfigurationError("Vision model returned invalid JSON.") from exc
    if not isinstance(parsed, dict):
        raise VisionConfigurationError("Vision model returned an invalid object.")

    component = str(parsed.get("component") or "").strip()
    visual_context = str(parsed.get("visual_context") or "").strip()
    uncertainty = str(parsed.get("uncertainty") or "").strip()
    try:
        confidence = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    if not component or not visual_context:
        raise VisionConfigurationError("Vision model omitted component context.")
    proposed = parsed.get("request_interpretation")
    interpretation = {}
    if isinstance(proposed, dict):
        allowed = {"component": set(COMPONENTS),
                   "operation": {"oil_and_filter", "oil_only", "overhaul_fill", "installation", "alignment", "inspection"},
                   "spec_type": {"torque", "fluid_capacity", "dimension"}}
        for key, options in allowed.items():
            if isinstance(proposed.get(key), str) and proposed[key] in options:
                interpretation[key] = proposed[key]
    return {
        "component": component[:120],
        "confidence": max(0.0, min(1.0, confidence)),
        "visual_context": visual_context[:500],
        "uncertainty": uncertainty[:300],
        "request_interpretation": interpretation,
    }


async def identify_component(
    image_bytes: bytes,
    question: str,
    year: str,
    make: str,
    model: str,
) -> dict[str, Any]:
    """Use a vision-capable model for component context, never vehicle proof."""
    api_key = (
        os.getenv("NVIDIA_API_KEY" if VISION_PROVIDER == "nemotron" else "OPENAI_API_KEY")
        or ""
    ).strip()
    if not api_key:
        variable = "NVIDIA_API_KEY" if VISION_PROVIDER == "nemotron" else "OPENAI_API_KEY"
        raise VisionConfigurationError(f"{variable} is not configured.")

    try:
        from openai import AsyncOpenAI
    except ImportError as exc:  # pragma: no cover - dependency installation issue
        raise VisionConfigurationError("The openai package is not installed.") from exc

    image_data_url = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")
    instructions = (
        "You identify automotive components from a mechanic's JPEG. "
        "Return JSON only with keys component, confidence, visual_context, uncertainty, request_interpretation. "
        "Do not infer or claim vehicle year, make, or model from the image. "
        "Do not provide torque values, repair steps, safety instructions, or part numbers. "
        "Use a confidence number from 0 to 1 and plainly describe uncertainty. "
        "Interpret the mechanic's wording in request_interpretation using nullable keys component, operation, spec_type. "
        f"Component vocabulary: {', '.join(COMPONENTS)}. "
        "Operations: oil_and_filter, oil_only, overhaul_fill, installation, alignment, inspection. "
        "Specification types: torque, fluid_capacity, dimension. "
        "These are unconfirmed proposals only. Never infer filter replacement or vehicle variants from the photo."
    )
    prompt = (
        f"Question: {question}\n"
        f"Explicit vehicle context supplied by the mechanic: {year} {make} {model}.\n"
        "Describe only the likely visible component and useful visual search context."
    )
    global _VISION_CLIENT
    if _VISION_CLIENT is None:
        _VISION_CLIENT = AsyncOpenAI(
            api_key=api_key, base_url=NEMOTRON_BASE_URL if VISION_PROVIDER == "nemotron" else None,
            # Two short tries fit inside the camera tool's deadline; one long hang would not.
            timeout=12.0, max_retries=1,
        )
    client = _VISION_CLIENT
    try:
        if VISION_PROVIDER == "nemotron":
            response = await client.chat.completions.create(
                model=NEMOTRON_MODEL_NAME,
                temperature=0,
                max_tokens=int(os.getenv("NEMOTRON_MAX_TOKENS", "2048")),
                # Reasoning took this model past half a minute on a real glasses photo, and the
                # mechanic is waiting on a live call. Without it the same photo takes seconds.
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                messages=[
                    {"role": "system", "content": instructions},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": image_data_url},
                            },
                        ],
                    },
                ],
            )
            raw_text = response.choices[0].message.content or ""
        else:
            response = await client.responses.create(
                model=VISION_MODEL_NAME,
                instructions=instructions,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt},
                            {"type": "input_image", "image_url": image_data_url},
                        ],
                    }
                ],
            )
            raw_text = response.output_text
    except Exception as exc:  # noqa: BLE001 - provider errors become safe API errors
        raise VisionConfigurationError("Vision model request failed.") from exc
    return _parse_vision_result(raw_text)


@app.post("/vision-query")
async def vision_query(
    request: Request,
    file: UploadFile = File(...),
    question: str = Form(...),
    year: str = Form(...),
    make: str = Form(...),
    model: str = Form(...),
    session_id: str = Form(...),
    shop_id: str = Form(DEFAULT_SHOP_ID),
    transmission: str | None = Form(None),
    engine_code: str | None = Form(None),
    trim: str | None = Form(None),
    market: str | None = Form(None),
    wheel_size: str | None = Form(None),
    component: str | None = Form(None),
    operation: str | None = Form(None),
    spec_type: str | None = Form(None),
) -> JSONResponse:
    """Recognize context when needed; authoritative values require verified v2 evidence."""
    started = time.perf_counter()
    question, session_id = question.strip(), session_id.strip()
    if not question or not session_id:
        raise HTTPException(status_code=400, detail="question and session_id are required.")
    try:
        vehicle = Vehicle(shop_id=shop_id, year=year, make=make, model=model,
                          transmission=transmission, engine_code=engine_code, trim=trim, market=market,
                          wheel_size=wheel_size)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Confirm explicit year, make, model and vehicle variants.") from exc
    image_bytes = await file.read(MAX_VISION_IMAGE_BYTES + 1)
    await file.close()
    _validate_jpeg(image_bytes, file.content_type)
    context = {k: getattr(vehicle, k) for k in VARIANTS}
    context.update(component=component, operation=operation, spec_type=spec_type)
    inference_ms = 0.0
    visual = {"component": component or "not analyzed", "confidence": 0.0,
              "visual_context": "Explicit request used; image inference skipped.",
              "uncertainty": "Vehicle and component require mechanic confirmation."}
    query_id = str(uuid.uuid4())
    asyncio.create_task(
        _spacetime_call_reducer(
            "start_shop_query",
            [
                query_id,
                session_id,
                vehicle.year,
                vehicle.make,
                vehicle.model,
                question,
            ],
        )
    )
    try:
        try:
            slots = normalize_request(question, context)
            visual["component"] = slots["component"]
        except SpecificationRefusal:
            if component or component_from_text(question):
                # Missing operation/variant cannot be established by a photo.
                raise
            # Vision can propose a component, but its hypothesis never supplies exact filters.
            inference_start = time.perf_counter()
            visual = await identify_component(image_bytes, question, vehicle.year, vehicle.make, vehicle.model)
            inference_ms = (time.perf_counter() - inference_start) * 1000
            normalize_request(question, context)
        result = await search_top_chunk(
            request.app.state.qdrant, request.app.state.embedder, question,
            vehicle.year, vehicle.make, vehicle.model, vehicle.shop_id, context)
    except SpecificationRefusal as exc:
        total_ms = (time.perf_counter() - started) * 1000
        asyncio.create_task(
            _spacetime_call_reducer(
                "record_shop_query_result",
                [
                    query_id,
                    visual.get("component") or "unidentified",
                    float(visual.get("confidence") or 0.0),
                    "refused",
                    str(exc),
                    "none",
                    False,
                    max(1, int(round(total_ms))),
                ],
            )
        )
        return JSONResponse(status_code=404, content={
            "session_id": session_id, "error": str(exc), "status": exc.code,
            "component": visual, "source_grounded": False,
            "timings_ms": {"inference": inference_ms, "total": total_ms}})
    except VisionConfigurationError as exc:
        total_ms = (time.perf_counter() - started) * 1000
        asyncio.create_task(
            _spacetime_call_reducer(
                "record_shop_query_result",
                [
                    query_id,
                    visual.get("component") or "error",
                    0.0,
                    "failed",
                    str(exc),
                    "none",
                    False,
                    max(1, int(round(total_ms))),
                ],
            )
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        total_ms = (time.perf_counter() - started) * 1000
        asyncio.create_task(
            _spacetime_call_reducer(
                "record_shop_query_result",
                [
                    query_id,
                    visual.get("component") or "error",
                    0.0,
                    "failed",
                    "Specification lookup is temporarily unavailable.",
                    "none",
                    False,
                    max(1, int(round(total_ms))),
                ],
            )
        )
        logger.error("Carvis specification lookup unavailable: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Specification lookup is temporarily unavailable.") from exc
    timings = {**result.timings_ms, "inference": inference_ms,
               "total": (time.perf_counter()-started)*1000}
    logger.info("Carvis vision-query timings_ms=%s", timings)
    asyncio.create_task(
        _spacetime_call_reducer(
            "record_shop_query_result",
            [
                query_id,
                visual.get("component") or "confirmed",
                float(visual.get("confidence") or 0.0),
                "answered",
                result.answer,
                result.source or "verified_manual",
                True,
                max(1, int(round(timings["total"]))),
            ],
        )
    )
    return JSONResponse(content={
        "session_id": session_id, "vehicle": vehicle.model_dump(), "component": visual,
        "answer": result.answer, "source_grounded": True, "source": result.source,
        "sources": result.sources, "status": "answered", "timings_ms": timings,
    })


async def _ingest_upload_job(
    temp_path: Path,
    year: str,
    make: str,
    model: str,
    shop_id: str,
    embedder: TextEmbedding,
    client: QdrantClient,
    variants: dict | None = None,
) -> None:
    """Background: LlamaParse → chunks → embed → Qdrant upsert, then delete temp."""
    tenant = (shop_id or DEFAULT_SHOP_ID).strip().lower() or DEFAULT_SHOP_ID
    try:
        count = await run_ingest(
            temp_path, year, make, model, embedding_model=embedder, shop_id=tenant,
            client=client, collection=STAGING_COLLECTION, **(variants or {}),
        )
        logger.info("Carvis upload staged %d records for source review", count)
    except SystemExit as exc:
        logger.error(
            "upload job aborted path=%s shop_id=%s err=%s",
            temp_path,
            tenant,
            exc,
        )
    except Exception:
        logger.exception("upload job failed path=%s shop_id=%s", temp_path, tenant)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
            parent = temp_path.parent
            if parent.name.startswith("carvis_upload_"):
                parent.rmdir()
        except OSError:
            logger.warning("could not delete temp upload %s", temp_path)


@app.post("/upload")
async def upload_manual(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(...),
    year: str = Form(...),
    make: str = Form(...),
    model: str = Form(...),
    shop_id: str = Form(DEFAULT_SHOP_ID),
    transmission: str | None = Form(None),
    engine_code: str | None = Form(None),
    trim: str | None = Form(None),
    market: str | None = Form(None),
) -> JSONResponse:
    """Accept a PDF and ingest it into Qdrant in the background."""
    if not year.strip() or not make.strip() or not model.strip():
        return JSONResponse(
            status_code=400,
            content={"detail": "year, make, and model are required."},
        )

    try:
        validated = Vehicle(shop_id=shop_id, year=year, make=make, model=model,
                            transmission=transmission, engine_code=engine_code, trim=trim, market=market)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid vehicle metadata.") from exc
    filename = (file.filename or "upload.pdf").strip()
    if not filename.lower().endswith(".pdf"):
        return JSONResponse(
            status_code=400,
            content={"detail": "Only PDF uploads are supported."},
        )

    safe_name = Path(filename).name
    tmp_dir = Path(tempfile.mkdtemp(prefix="carvis_upload_"))
    temp_path = tmp_dir / safe_name
    try:
        with temp_path.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
    finally:
        await file.close()

    client: QdrantClient = request.app.state.qdrant
    embedder: TextEmbedding = request.app.state.embedder
    background_tasks.add_task(
        _ingest_upload_job,
        temp_path,
        year.strip(),
        make.strip(),
        model.strip(),
        (shop_id or DEFAULT_SHOP_ID).strip() or DEFAULT_SHOP_ID,
        embedder,
        client,
        {k: getattr(validated, k) for k in VARIANTS},
    )
    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "message": "Manual queued for staging and source review.",
            "verification_status": "pending_review",
            "filename": safe_name,
            "shop_id": (shop_id or DEFAULT_SHOP_ID).strip().lower() or DEFAULT_SHOP_ID,
            "year": year.strip().lower(),
            "make": make.strip().lower(),
            "model": model.strip().lower(),
        },
    )


def _infer_vehicle_fields(
    query: str,
    make: str,
    model: str,
    year: str,
    catalog: ShopVehicleCatalog | None = None,
) -> tuple[str, str, str]:
    """Fill missing make/model/year only from tags present in the shop catalog."""
    q = (query or "").lower()
    make_out, model_out, year_out = make, model, year
    if catalog is None or catalog.is_empty:
        return make_out, model_out, year_out

    if not model_out:
        for candidate in sorted(catalog.models, key=len, reverse=True):
            if candidate and candidate in q:
                model_out = candidate
                break

    if not make_out:
        for candidate in sorted(catalog.makes, key=len, reverse=True):
            if candidate and candidate in q:
                make_out = candidate
                break

    # Spelling aliases — only if the canonical tag exists in this shop's brain.
    if not make_out and "chevy" in q and "chevrolet" in catalog.makes:
        make_out = "chevrolet"
    if not model_out and "ams" in q and "vr30" in catalog.models:
        model_out = "vr30"
    if not make_out and model_out == "vr30" and "nissan" in catalog.makes:
        make_out = "nissan"

    if not year_out:
        for candidate in sorted(catalog.years, key=len, reverse=True):
            if candidate and candidate in q:
                year_out = candidate
                break

    # If model is known, fill make/year from the only matching uploaded triple(s).
    if model_out:
        matches = [t for t in catalog.triples if t[2] == model_out]
        if matches:
            if not make_out:
                makes = {t[1] for t in matches if t[1]}
                if len(makes) == 1:
                    make_out = next(iter(makes))
            if not year_out:
                years = {t[0] for t in matches if t[0]}
                if len(years) == 1:
                    year_out = next(iter(years))

    if make_out and not model_out:
        matches = [t for t in catalog.triples if t[1] == make_out]
        if len(matches) == 1:
            y, _m, mo = matches[0]
            if mo and not model_out:
                model_out = mo
            if y and not year_out:
                year_out = y

    return make_out, model_out, year_out


conversations = ConversationStore()


async def _conversation_lookup(query: str, session: ConversationSession, context: dict) -> LookupResult:
    v = session.vehicle
    return await search_top_chunk(app.state.qdrant, app.state.embedder, query,
                                  v.year, v.make, v.model, v.shop_id, context)


async def _conversation_identify(image: bytes, question: str, session: ConversationSession) -> dict:
    v = session.vehicle
    return await identify_component(image, question, v.year, v.make, v.model)


conversation_tools = ConversationTools(_conversation_lookup, _conversation_identify)


class VehicleBody(BaseModel):
    year: str
    make: str
    model: str
    trim: str | None = None
    engine_code: str | None = None
    transmission: str | None = None
    market: str | None = None
    wheel_size: str | None = None
    shop_id: str = DEFAULT_SHOP_ID

    def to_vehicle(self) -> Vehicle:
        try:
            return Vehicle(**self.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="A four-digit year, make, and model are required.") from exc


class SessionCreateBody(BaseModel):
    owner_name: str
    vehicle: VehicleBody


class CallStartBody(BaseModel):
    opening_question: str | None = None


class CallBindBody(BaseModel):
    vapi_call_id: str


class CallEndBody(BaseModel):
    reason: str = "app"


class CameraFailureBody(BaseModel):
    reason: str


def _session_or_401(session_id: str, authorization: str | None) -> ConversationSession:
    token = (authorization or "").removeprefix("Bearer ").strip()
    session = conversations.authenticate(session_id, token) if token else None
    if session is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return session


@app.post("/conversation/sessions")
async def create_conversation(body: SessionCreateBody) -> dict[str, Any]:
    session, token = conversations.create(body.owner_name, body.vehicle.to_vehicle())
    return {"session_id": session.session_id, "device_token": token, "state": session.view()}


@app.get("/conversation/sessions/{session_id}")
async def conversation_state(session_id: str, authorization: str | None = Header(None)) -> dict[str, Any]:
    return _session_or_401(session_id, authorization).view()


@app.put("/conversation/sessions/{session_id}/vehicle")
async def update_conversation_vehicle(session_id: str, body: VehicleBody,
                                      authorization: str | None = Header(None)) -> dict[str, Any]:
    session = _session_or_401(session_id, authorization)
    session.apply_app_vehicle(body.to_vehicle())
    return session.view()


@app.post("/conversation/sessions/{session_id}/calls")
async def start_conversation_call(session_id: str, body: CallStartBody,
                                  authorization: str | None = Header(None)) -> dict[str, Any]:
    session = _session_or_401(session_id, authorization)
    question = (body.opening_question or "").strip() or None
    generation = session.begin_call(question)
    # The memory is summarized before this call's own opening question is delivered by the
    # app, so the model hears it once as the mechanic's words rather than again in the prompt.
    carried = session.memory_summary() if not question else session.memory_summary().replace(
        f"Unanswered question from earlier: {question}", "").strip()
    return {"generation": generation, "variable_values": {
        "carvis_session_id": session.session_id,
        "owner_first_name": session.owner_first_name,
        "vehicle_summary": session.vehicle_summary(),
        "vehicle_model": session.vehicle_model(),
        "vehicle_confirmed": "yes" if session.vehicle_confirmed else "no",
        "memory_summary": carried,
    }}


@app.post("/conversation/sessions/{session_id}/calls/{generation}/bind")
async def bind_conversation_call(session_id: str, generation: int, body: CallBindBody,
                                 authorization: str | None = Header(None)) -> dict[str, bool]:
    session = _session_or_401(session_id, authorization)
    if not conversations.bind_call(session, generation, body.vapi_call_id):
        raise HTTPException(status_code=409, detail="stale call")
    return {"bound": True}


@app.post("/conversation/sessions/{session_id}/calls/{generation}/end")
async def end_conversation_call(session_id: str, generation: int, body: CallEndBody,
                                authorization: str | None = Header(None)) -> dict[str, bool]:
    session = _session_or_401(session_id, authorization)
    return {"ended": session.end_call(body.reason, generation)}


@app.get("/conversation/sessions/{session_id}/camera/next")
async def next_camera_command(session_id: str, wait: float = 20.0,
                              authorization: str | None = Header(None)) -> Response:
    session = _session_or_401(session_id, authorization)
    command = await session.next_camera_command(min(max(wait, 0.0), 25.0))
    if command is None:
        return Response(status_code=204)
    return JSONResponse(content={
        "request_id": command.request_id, "generation": command.generation, "question": command.question,
        "seconds_remaining": max(0.0, command.deadline - time.monotonic()),
    })


@app.post("/conversation/sessions/{session_id}/camera/{request_id}/photo")
async def receive_camera_photo(session_id: str, request_id: str, file: UploadFile = File(...),
                               authorization: str | None = Header(None)) -> dict[str, Any]:
    session = _session_or_401(session_id, authorization)
    image_bytes = await file.read(MAX_VISION_IMAGE_BYTES + 1)
    await file.close()
    _validate_jpeg(image_bytes, file.content_type)
    try:
        visual = await conversation_tools.receive_photo(session, request_id, image_bytes)
    except StaleCameraResult as exc:
        raise HTTPException(status_code=409, detail="This photo's request is no longer active.") from exc
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Identifying the part took too long.") from exc
    except VisionConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "identified", "visual": visual}


@app.post("/conversation/sessions/{session_id}/camera/{request_id}/failure")
async def report_camera_failure(session_id: str, request_id: str, body: CameraFailureBody,
                                authorization: str | None = Header(None)) -> dict[str, bool]:
    session = _session_or_401(session_id, authorization)
    try:
        conversation_tools.report_camera_failure(session, request_id, body.reason)
    except StaleCameraResult as exc:
        raise HTTPException(status_code=409, detail="This request is no longer active.") from exc
    return {"recorded": True}


@app.post("/vapi-tool")
async def vapi_tool(request: Request) -> JSONResponse:
    """Accept Vapi lookup requests; reuse only explicitly confirmed session identity."""
    started = time.perf_counter()
    outcome = "error"

    webhook_secret = (os.getenv("VAPI_WEBHOOK_SECRET") or "").strip()
    if webhook_secret:
        incoming_secret = request.headers.get("x-vapi-secret")
        if incoming_secret != webhook_secret:
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
            )

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - still return Vapi-shaped 200
        return JSONResponse(
            status_code=200,
            content={
                "results": [
                    {
                        "toolCallId": "vapi-call",
                        "error": "Request body must be valid JSON.",
                    }
                ]
            },
        )

    if not isinstance(payload, dict):
        return JSONResponse(
            status_code=200,
            content={
                "results": [
                    {
                        "toolCallId": "vapi-call",
                        "error": "Request JSON must be an object.",
                    }
                ]
            },
        )

    message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
    if message.get("type") in ("end-of-call-report", "status-update"):
        conversations.handle_call_event(payload)
        return JSONResponse(content={})

    tool_calls = extract_tool_call_list(payload)
    if tool_calls:
        session, stale = conversations.session_for_webhook(payload)
        if session is not None or any(tool_name(call) in SESSION_ONLY_TOOLS for call in tool_calls):
            # A model turn can request several tools at once; each gets its own correlated result.
            results = await asyncio.gather(*(conversation_tools.handle(session, stale, call, index)
                                             for index, call in enumerate(tool_calls)))
            return JSONResponse(content={"results": list(results)})

    fields = normalize_vapi_lookup_payload(payload)
    query = fields["query"]
    make = fields["make"]
    model = fields["model"]
    year = fields["year"]
    shop_id = fields["shop_id"] or DEFAULT_SHOP_ID
    raw_call_id = _extract_call_id(payload)
    call_id = f"{shop_id}:{raw_call_id}" if raw_call_id else ""
    tool_call_id = fields["tool_call_id"]

    logger.info(
        "vapi_tool inbound keys=%s tool_calls=%d has_query=%s "
        "query_preview=%r shop_id=%r toolCallId=%r",
        sorted(payload.keys()),
        len(extract_tool_call_list(payload)),
        bool(query),
        (query[:120] if query else None),
        shop_id,
        tool_call_id,
    )

    if not query:
        return JSONResponse(
            status_code=200,
            content={
                "results": [
                    {
                        "toolCallId": tool_call_id,
                        "error": "Missing required field: query.",
                    }
                ]
            },
        )

    try:
        query = query.strip()
        make, model, year = _apply_session_vehicle_fields(call_id, make, model, year)
        context = {key: fields.get(key) for key in (*VARIANTS, "component", "operation", "spec_type")}
        try:
            result = await search_top_chunk(
                request.app.state.qdrant, request.app.state.embedder, query,
                year, make, model, shop_id, context)
        except SpecificationRefusal as exc:
            outcome = exc.code
            return JSONResponse(content={"results": [{
                "toolCallId": tool_call_id, "result": str(exc),
                "status": exc.code, "source_grounded": False,
            }]})
        except Exception as exc:
            outcome = "lookup_failed"
            logger.error("Carvis lookup failed: %s", type(exc).__name__)
            return JSONResponse(content={"results": [{
                "toolCallId": tool_call_id, "error": "Specification lookup is temporarily unavailable.",
            }]})
        _update_session_vehicle_fields(call_id, make, model, year)
        outcome = "ok"
        return JSONResponse(content={"results": [{
            "toolCallId": tool_call_id, "result": result.answer,
            "source": result.source, "sources": result.sources, "source_grounded": True,
            "timings_ms": result.timings_ms,
        }]})
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.info(
            "vapi_tool outcome=%s elapsed_ms=%.1f query=%r year=%r make=%r "
            "model=%r shop_id=%r",
            outcome,
            elapsed_ms,
            query,
            year or None,
            make or None,
            model or None,
            shop_id,
        )


if __name__ == "__main__":
    port = int((os.getenv("PORT") or "8000").strip() or "8000")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)

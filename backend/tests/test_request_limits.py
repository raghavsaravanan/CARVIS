"""M2 Track A6: request bodies are capped while they stream, per route, without changing shapes.

Requests go through the full ASGI app with a counting ``receive``, so the tests prove how much of a
body the server pulls, not only the status code. Nothing contacts a provider.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.routing import APIRoute

import main
from request_limits import DEFAULT_BODY_LIMIT_BYTES, INVALID_LENGTH_DETAIL, MULTIPART_ENVELOPE_BYTES, TOO_LARGE_DETAIL
from tests.test_conversation import SECRET, Phone, api, client, webhook  # noqa: F401  (api is a fixture)
from upload_security import OperatorUploadRoute

MiB = 1024 * 1024
BOUNDARY = "carvis-limit-test"
IMAGE_BODY_CAP = main.MAX_VISION_IMAGE_BYTES + MULTIPART_ENVELOPE_BYTES
PHOTO_PATH = "/conversation/sessions/{session_id}/camera/{request_id}/photo"
VISION_FIELDS = {"question": "ride height tolerance", "session_id": "s-1", "year": "2022", "make": "subaru",
                 "model": "wrx"}


def run(coro):
    return asyncio.run(coro)


async def raw_request(path, chunks, *, headers=(), content_type="application/json", method="POST"):
    """Send ``chunks`` through the ASGI app; report status, body and how much the app consumed."""
    source = iter(chunks)
    consumed = {"bytes": 0, "exhausted": False}
    pending = next(source, None)

    async def receive():
        nonlocal pending
        if pending is None:
            consumed["exhausted"] = True
            return {"type": "http.disconnect"}
        body, pending = pending, next(source, None)
        consumed["bytes"] += len(body)
        return {"type": "http.request", "body": body, "more_body": pending is not None}

    sent = []

    async def send(message):
        sent.append(message)

    raw_headers = [(b"content-type", content_type.encode())]
    raw_headers += [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers]
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
             "scheme": "http", "path": path, "raw_path": path.encode(), "root_path": "", "query_string": b"",
             "headers": raw_headers, "client": ("127.0.0.1", 5000), "server": ("carvis", 80)}
    await main.app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    raw_request.last_headers = {k.decode(): v.decode() for k, v in start.get("headers", [])}
    return start["status"], body, consumed


def zeros(total, chunk=MiB):
    sent = 0
    while sent < total:
        size = min(chunk, total - sent)
        yield b"\0" * size
        sent += size


def jpeg_multipart(image_chunks, fields=VISION_FIELDS):
    for name, value in fields.items():
        yield f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
    yield (f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"frame.jpg\"\r\n"
           "Content-Type: image/jpeg\r\n\r\n").encode()
    yield b"\xff\xd8\xff\xe0"
    yield from image_chunks
    yield f"\r\n--{BOUNDARY}--\r\n".encode()


MULTIPART = f"multipart/form-data; boundary={BOUNDARY}"
IMAGE_TOO_LARGE = json.dumps({"detail": main.IMAGE_TOO_LARGE_DETAIL}, separators=(",", ":")).encode()
BODY_TOO_LARGE = json.dumps({"detail": TOO_LARGE_DETAIL}, separators=(",", ":")).encode()


@pytest.fixture
def no_work(api, monkeypatch):
    """Fail loudly if a rejected request reaches inference or retrieval."""
    async def forbidden(*args, **kwargs):
        raise AssertionError("an over-cap request must not reach inference or retrieval")
    monkeypatch.setattr(main, "identify_component", forbidden)
    monkeypatch.setattr(main, "search_top_chunk", forbidden)
    return api


# --- Route wiring --------------------------------------------------------------------------------


def test_every_app_route_is_body_capped():
    """A route added before the route class was set, or on another router, would escape the cap."""
    routes = [route for route in main.app.routes if isinstance(route, APIRoute)]
    assert routes
    for route in routes:
        if route.path == "/upload":
            assert isinstance(route, OperatorUploadRoute)
        else:
            assert type(route).__name__ == "BodyLimitedRoute", route.path
    for path in main.BODY_LIMITS:
        assert path in {route.path for route in routes}, f"BODY_LIMITS names unknown path {path}"


# --- /vision-query and camera photos --------------------------------------------------------------


def test_vision_query_declared_oversize_is_refused_before_reading(no_work):
    headers = [("content-length", str(IMAGE_BODY_CAP + 1))]
    status, body, consumed = run(raw_request("/vision-query", jpeg_multipart(zeros(20 * MiB)), headers=headers,
                                             content_type=MULTIPART))
    assert (status, body) == (413, IMAGE_TOO_LARGE)
    assert consumed["bytes"] == 0


@pytest.mark.parametrize("declared", [None, "2048"], ids=["no-content-length", "understated"])
def test_vision_query_streamed_oversize_stops_at_the_cap(no_work, declared):
    headers = [] if declared is None else [("content-length", declared)]
    status, body, consumed = run(raw_request("/vision-query", jpeg_multipart(zeros(40 * MiB)), headers=headers,
                                             content_type=MULTIPART))
    assert (status, body) == (413, IMAGE_TOO_LARGE)
    assert IMAGE_BODY_CAP < consumed["bytes"] <= IMAGE_BODY_CAP + MiB
    assert not consumed["exhausted"], "the rest of the body must not be read"


def test_vision_query_image_at_the_file_cap_is_still_accepted_by_the_body_cap(no_work):
    """An image exactly at the 8 MiB file cap fits the body cap; the handler still validates it."""
    image = zeros(main.MAX_VISION_IMAGE_BYTES - 4)  # plus the 4-byte JPEG marker
    status, body, _ = run(raw_request("/vision-query", jpeg_multipart(image), content_type=MULTIPART))
    assert status != 413, body
    # It reached the handler: retrieval was attempted (and refused by the no_work guard).
    assert status == 503 and json.loads(body) == {"detail": main.LOOKUP_UNAVAILABLE_DETAIL}


def test_camera_photo_oversize_is_refused(api):
    async def scenario():
        async with client() as http:
            phone = Phone(http)
            await phone.start()
            return phone
    phone = run(scenario())
    path = PHOTO_PATH.format(session_id=phone.id, request_id="r-1")
    headers = [(k, v) for k, v in phone.auth.items()]
    status, body, consumed = run(raw_request(path, jpeg_multipart(zeros(40 * MiB), fields={}), headers=headers,
                                             content_type=MULTIPART))
    assert (status, body) == (413, IMAGE_TOO_LARGE)
    assert consumed["bytes"] <= IMAGE_BODY_CAP + MiB


# --- /vapi-tool ------------------------------------------------------------------------------------


def test_unauthenticated_vapi_tool_still_gets_401_without_reading(api):
    """The cap is checked when the body is first read, so authentication still answers first."""
    headers = [("content-length", str(500 * MiB))]
    status, body, consumed = run(raw_request("/vapi-tool", zeros(500 * MiB), headers=headers))
    assert (status, json.loads(body)) == (401, {"detail": "Unauthorized"})
    assert consumed["bytes"] == 0


@pytest.mark.parametrize("declared", [True, False], ids=["declared", "streamed"])
def test_authorized_oversized_vapi_tool_body_is_413_not_a_vapi_error(no_work, declared):
    """/vapi-tool catches body errors to answer Vapi-shaped 200s; an over-cap body must still be 413."""
    total = main.VAPI_TOOL_BODY_LIMIT_BYTES + 1
    headers = [("x-vapi-secret", SECRET)] + ([("content-length", str(total))] if declared else [])
    status, body, consumed = run(raw_request("/vapi-tool", zeros(total, chunk=256 * 1024), headers=headers))
    assert (status, body) == (413, BODY_TOO_LARGE)
    assert consumed["bytes"] == (0 if declared else total)


@pytest.mark.parametrize("path, headers", [("/conversation/sessions", []),
                                           ("/vapi-tool", [("x-vapi-secret", SECRET)])])
def test_rejections_close_the_connection(api, path, headers):
    """Without Connection: close the server keeps reading and discarding the declared body."""
    status, _, _ = run(raw_request(path, [b"{}"], headers=headers + [("content-length", str(500 * MiB))]))
    assert status == 413
    assert raw_request.last_headers.get("connection") == "close"


def test_unread_announced_body_closes_the_connection(api):
    """An unauthenticated /vapi-tool request is answered unread; the server must not drain 500 MiB."""
    status, _, consumed = run(raw_request("/vapi-tool", zeros(MiB), headers=[("content-length", str(500 * MiB))]))
    assert status == 401
    assert consumed["bytes"] == 0
    assert raw_request.last_headers.get("connection") == "close"


def test_accepted_requests_keep_the_connection_open(api):
    status, _, _ = run(raw_request("/conversation/sessions", [json.dumps(
        {"owner_name": "Gabriel", "vehicle": {"year": "2022", "make": "Subaru", "model": "WRX"}}).encode()]))
    assert status == 200
    assert "connection" not in raw_request.last_headers


def test_vapi_tool_body_under_the_cap_is_unchanged(api):
    chunk = json.dumps(webhook(("c-1", "lookup_spec", {"query": "ride height tolerance"}))).encode()
    status, body, _ = run(raw_request("/vapi-tool", [chunk], headers=[("x-vapi-secret", SECRET)]))
    assert status == 200
    assert "results" in json.loads(body)


# --- Default cap (conversation JSON) ---------------------------------------------------------------


def test_default_cap_applies_to_conversation_json(api):
    oversized = b'{"owner_name": "' + b"x" * DEFAULT_BODY_LIMIT_BYTES + b'"}'
    status, body, _ = run(raw_request("/conversation/sessions", [oversized]))
    assert (status, body) == (413, BODY_TOO_LARGE)


def test_body_exactly_at_the_default_cap_is_not_refused(api):
    body_json = json.dumps({"owner_name": "Gabriel", "vehicle": {"year": "2022", "make": "Subaru", "model": "WRX"}})
    padded = body_json.encode() + b" " * (DEFAULT_BODY_LIMIT_BYTES - len(body_json))
    assert len(padded) == DEFAULT_BODY_LIMIT_BYTES
    status, body, _ = run(raw_request("/conversation/sessions", [padded]))
    assert status == 200, body


@pytest.mark.parametrize("value", ["abc", "-1", "1.5", ""], ids=["text", "negative", "decimal", "empty"])
def test_malformed_content_length_is_refused(api, value):
    status, body, consumed = run(raw_request("/conversation/sessions", [b"{}"], headers=[("content-length", value)]))
    assert (status, json.loads(body)) == (400, {"detail": INVALID_LENGTH_DETAIL})
    assert consumed["bytes"] == 0


def test_bodyless_routes_are_unaffected(api):
    status, body, _ = run(raw_request("/health", [], method="GET"))
    assert (status, json.loads(body)) == (200, {"status": "ok", "service": "carvis"})

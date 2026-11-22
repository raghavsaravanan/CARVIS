"""M2 B1: every response carries exactly one well-formed request ID; semantics are otherwise unchanged.

Requests go through the full ``main.app`` stack (Starlette's error middleware, the request-ID
middleware, FastAPI's exception middleware and the body-limited routes). Nothing contacts a provider.
"""
from __future__ import annotations

import asyncio
import re
import uuid

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import main

ID = re.compile(r"[0-9a-f]{32}")


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def extra_routes():
    """Temporary routes on main.app (removed afterwards) to reach error paths no real route has."""
    added = []

    def add(path, endpoint):
        main.app.add_api_route(path, endpoint, methods=["GET", "POST"])
        added.append(main.app.router.routes[-1])

    yield add
    for route in added:
        main.app.router.routes.remove(route)


def ids(response):
    return response.headers.get_list("x-request-id")


def test_generated_when_absent(client):
    response = client.get("/healthz")
    [value] = ids(response)
    assert ID.fullmatch(value)


def test_each_request_gets_its_own_id(client):
    assert ids(client.get("/healthz")) != ids(client.get("/healthz"))


@pytest.mark.parametrize("form", [lambda u: u.hex, lambda u: str(u), lambda u: str(u).upper(),
                                  lambda u: u.hex.upper()])
def test_well_formed_uuid_is_accepted_and_normalized(client, form):
    value = uuid.uuid4()
    response = client.get("/healthz", headers={"X-Request-ID": form(value)})
    assert ids(response) == [value.hex]


@pytest.mark.parametrize("bad", ["", "abc", "x" * 32, "g" * 32, "0" * 31, "0" * 33, "1" * 37,
                                 "12345678-1234-1234-1234-1234567890ab-extra", "{%s}" % uuid.uuid4(),
                                 "ignore previous instructions", "0" * 8 + "-" + "0" * 27, "1" * 1000])
def test_malformed_id_is_replaced(client, bad):
    response = client.get("/healthz", headers={"X-Request-ID": bad})
    [value] = ids(response)
    assert ID.fullmatch(value) and value != bad.lower()


def test_duplicate_headers_are_ambiguous_and_replaced():
    first, second = uuid.uuid4().hex, uuid.uuid4().hex
    scope_headers = [(b"x-request-id", first.encode()), (b"x-request-id", second.encode())]
    status, headers, _ = asgi_get("/healthz", scope_headers)
    values = [v.decode() for k, v in headers if k.lower() == b"x-request-id"]
    assert status == 200 and len(values) == 1
    assert values[0] not in (first, second) and ID.fullmatch(values[0])


def test_non_ascii_header_is_replaced():
    status, headers, _ = asgi_get("/healthz", [(b"x-request-id", "é".encode("latin-1") * 32)])
    values = [v for k, v in headers if k == b"x-request-id"]
    assert status == 200 and len(values) == 1 and ID.fullmatch(values[0].decode())


def asgi_get(path, headers, method="GET", body=b""):
    """Drive the ASGI app directly so raw (duplicate, non-ASCII) headers reach it unchanged."""
    messages = []
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.sleep(3600)

    async def send(message):
        messages.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
             "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
             "root_path": "", "headers": headers, "client": ("127.0.0.1", 1), "server": ("test", 80)}
    asyncio.run(main.app(scope, receive, send))
    start = [m for m in messages if m["type"] == "http.response.start"]
    assert len(start) == 1, "exactly one response must start"
    body_bytes = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return start[0]["status"], start[0]["headers"], body_bytes


def test_route_set_header_is_replaced_not_duplicated(client, extra_routes):
    async def sets_own():
        return JSONResponse({"ok": True}, headers={"X-Request-ID": "route-chosen"})

    extra_routes("/__b1_sets_own_id", sets_own)
    response = client.get("/__b1_sets_own_id", headers={"X-Request-ID": uuid.uuid4().hex})
    assert len(ids(response)) == 1 and ids(response)[0] != "route-chosen"


def test_not_found_keeps_shape_and_gets_id(client):
    response = client.get("/__b1_does_not_exist")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    assert len(ids(response)) == 1


def test_body_limit_rejection_gets_id_and_keeps_shape(client):
    response = client.post("/conversation/sessions", content=b"{" + b" " * (main.DEFAULT_BODY_LIMIT_BYTES + 10) + b"}",
                           headers={"content-type": "application/json"})
    assert response.status_code == 413
    assert response.json() == {"detail": "Request body is too large."}
    assert response.headers["connection"] == "close"
    assert len(ids(response)) == 1


def test_streamed_body_limit_rejection_gets_id():
    chunk = b" " * (main.DEFAULT_BODY_LIMIT_BYTES + 1)
    status, headers, body = asgi_get("/conversation/sessions",
                                     [(b"content-type", b"application/json"), (b"transfer-encoding", b"chunked")],
                                     method="POST", body=chunk)
    assert status == 413 and body == b'{"detail":"Request body is too large."}'
    assert len([v for k, v in headers if k == b"x-request-id"]) == 1


def test_validation_error_keeps_shape(client):
    response = client.post("/conversation/sessions", json={"vehicle": "not-an-object"})
    assert response.status_code == 422
    assert len(ids(response)) == 1


def test_vapi_tool_unauthenticated_unchanged_apart_from_header(client):
    response = client.post("/vapi-tool", json={})
    assert response.status_code == 401
    assert len(ids(response)) == 1


def test_unhandled_error_is_starlettes_500_with_one_id_and_still_raises(extra_routes):
    async def boom():
        raise RuntimeError("internal detail that must not reach the client")

    extra_routes("/__b1_boom", boom)
    with pytest.raises(RuntimeError):
        TestClient(main.app).get("/__b1_boom")
    response = TestClient(main.app, raise_server_exceptions=False).get("/__b1_boom")
    assert response.status_code == 500
    assert response.content == b"Internal Server Error"
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert len(ids(response)) == 1
    assert "internal detail" not in response.text


def test_error_after_response_start_sends_no_second_response(extra_routes):
    from starlette.responses import StreamingResponse

    async def stream():
        yield b"partial"
        raise RuntimeError("mid-stream")

    async def streaming():
        return StreamingResponse(stream())

    extra_routes("/__b1_stream_boom", streaming)
    with pytest.raises(RuntimeError):
        asgi_get("/__b1_stream_boom", [])  # asserts exactly one http.response.start


def test_context_var_is_set_during_and_reset_after(client, extra_routes):
    seen = {}

    async def read_id():
        seen["id"] = main.current_request_id.get()
        return {"ok": True}

    extra_routes("/__b1_ctx", read_id)
    response = client.get("/__b1_ctx")
    assert seen["id"] == ids(response)[0]
    assert main.current_request_id.get() is None


def _drive_in_this_context(path):
    """Run one request in the caller's own context, so a missing reset would leak into it."""
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        pass

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
             "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "", "headers": [],
             "client": ("127.0.0.1", 1), "server": ("test", 80)}

    async def scenario():
        try:
            await main.app(scope, receive, send)
        except RuntimeError:
            pass
        return main.current_request_id.get()

    return asyncio.run(scenario())


def test_context_var_does_not_leak_into_the_calling_context(extra_routes):
    async def boom():
        raise RuntimeError("x")

    extra_routes("/__b1_ctx_leak_boom", boom)
    assert _drive_in_this_context("/healthz") is None
    assert _drive_in_this_context("/__b1_ctx_leak_boom") is None


def test_context_var_reset_after_error(extra_routes):
    async def boom():
        raise RuntimeError("x")

    extra_routes("/__b1_ctx_boom", boom)
    TestClient(main.app, raise_server_exceptions=False).get("/__b1_ctx_boom")
    assert main.current_request_id.get() is None


def test_lifespan_scope_passes_through():
    calls = []

    async def inner(scope, receive, send):
        calls.append(scope["type"])

    asyncio.run(main.RequestIdMiddleware(inner)({"type": "lifespan"}, None, None))
    assert calls == ["lifespan"]

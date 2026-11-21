"""M2 Track A2: /upload is operator-gated, size-capped, and PDF-only before any ingestion work.

Request level: only an exact, constant-time match of ``X-Carvis-Operator-Token`` against a
configured ``CARVIS_OPERATOR_TOKEN`` is authorized; unset or blank configuration rejects everything.
Unauthorized and declared-oversized requests are answered before a single body byte is read, an
undeclared or lying body stops streaming at the cap, and a file over 50 MiB or without the
``%PDF-`` magic is refused. No rejected request schedules ingestion or reaches LlamaParse, and none
leaves a temporary file behind. Behavior for an authorized, valid PDF is unchanged.
"""
from __future__ import annotations

import asyncio
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import main
import upload_security
from qdrant_v2 import STAGING_COLLECTION
from upload_security import (MAX_UPLOAD_BODY_BYTES, MAX_UPLOAD_BYTES, NOT_A_PDF_DETAIL, OPERATOR_TOKEN_ENV,
                             OPERATOR_TOKEN_HEADER, TOO_LARGE_DETAIL)

TOKEN = "carvis-operator-test-token-0123456789"
UNAUTHORIZED = {"detail": "Unauthorized"}
TOO_LARGE = {"detail": TOO_LARGE_DETAIL}
NOT_A_PDF = {"detail": NOT_A_PDF_DETAIL}
PDF = b"%PDF-1.7\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"
VEHICLE = {"year": "2022", "make": "Subaru", "model": "WRX"}
MiB = 1024 * 1024


def run(coro):
    return asyncio.run(coro)


def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://carvis", timeout=60)


def authorized(**extra):
    return {OPERATOR_TOKEN_HEADER: TOKEN, **extra}


async def upload(http, headers=None, *, content=PDF, filename="manual.pdf", data=None, params=None):
    return await http.post("/upload", headers=headers or {}, params=params,
                           files={"file": (filename, content, "application/pdf")},
                           data=VEHICLE if data is None else data)


@pytest.fixture
def app_state():
    """Snapshot and restore app.state. pytest's monkeypatch records Starlette ``State`` attributes as
    unset (they live in ``State._state``) and would delete them on undo."""
    saved = dict(main.app.state._state)
    yield main.app.state
    main.app.state._state.clear()
    main.app.state._state.update(saved)


@pytest.fixture
def spies(monkeypatch, tmp_path, app_state):
    """Fake ingestion and isolate temporary upload directories.

    ``run_ingest`` is the only path to LlamaParse (``ingest.parse_pdf_pages``), so "never scheduled
    ingestion" is the guarantee that a rejected request never reached LlamaParse.
    """
    monkeypatch.delenv(OPERATOR_TOKEN_ENV, raising=False)
    staged: dict[str, object] = {}

    async def fake_ingest(path, *args, **kwargs):
        staged["bytes"] = Path(path).read_bytes()
        staged["path"] = Path(path)
        return 1

    ingest = AsyncMock(side_effect=fake_ingest)
    monkeypatch.setattr(main, "run_ingest", ingest)
    app_state.qdrant = MagicMock(name="qdrant")
    app_state.embedder = MagicMock(name="embedder")
    temp_root = tmp_path / "tmp"
    temp_root.mkdir()
    monkeypatch.setattr(main.tempfile, "tempdir", str(temp_root))
    return types.SimpleNamespace(ingest=ingest, staged=staged, temp_root=temp_root)


def leftover_uploads(spies):
    return sorted(spies.temp_root.glob("carvis_upload_*"))


def assert_rejected_without_work(spies):
    assert not spies.ingest.called, "a rejected upload must never schedule ingestion"
    assert leftover_uploads(spies) == []


# --- Raw ASGI harness: observe exactly how much of the body the app consumes --------------------


BOUNDARY = "carvisboundary7MA4YWxk"


def multipart_stream(file_chunks, *, fields=VEHICLE, filename="manual.pdf"):
    for name, value in fields.items():
        yield (f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n").encode()
    yield (f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
           "Content-Type: application/pdf\r\n\r\n").encode()
    yield from file_chunks
    yield f"\r\n--{BOUNDARY}--\r\n".encode()


def pdf_chunks(total, chunk=MiB):
    yield PDF[:5]
    sent = 5
    while sent < total:
        size = min(chunk, total - sent)
        yield b"\0" * size
        sent += size


async def raw_post(headers, chunks, *, path="/upload", method="POST"):
    """POST /upload through the full ASGI stack, counting body bytes the app pulls."""
    source = iter(chunks)
    consumed = {"messages": 0, "bytes": 0, "exhausted": False}
    pending = next(source, None)

    async def receive():
        nonlocal pending
        if pending is None:
            consumed["exhausted"] = True
            return {"type": "http.disconnect"}
        body, pending = pending, next(source, None)
        consumed["messages"] += 1
        consumed["bytes"] += len(body)
        return {"type": "http.request", "body": body, "more_body": pending is not None}

    sent = []

    async def send(message):
        sent.append(message)

    raw_headers = [(b"content-type", f"multipart/form-data; boundary={BOUNDARY}".encode())]
    pairs = headers if isinstance(headers, list) else list(headers.items())
    raw_headers += [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in pairs]
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
             "scheme": "http", "path": path, "raw_path": path.encode(), "root_path": "",
             "query_string": b"", "headers": raw_headers, "client": ("127.0.0.1", 5000),
             "server": ("carvis", 80)}
    await main.app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    raw_post.last_headers = {k.decode().lower(): v.decode() for k, v in start.get("headers", [])}
    return start["status"], body, consumed


# --- Authentication ----------------------------------------------------------------------------


@pytest.mark.parametrize("configured", [None, "", "   ", "\t\n"], ids=["unset", "empty", "spaces", "whitespace"])
def test_unconfigured_token_rejects_every_upload(spies, monkeypatch, configured):
    """Previously /upload had no authentication at all."""
    if configured is not None:
        monkeypatch.setenv(OPERATOR_TOKEN_ENV, configured)

    async def scenario():
        async with client() as http:
            for headers in ({}, {OPERATOR_TOKEN_HEADER: ""}, {OPERATOR_TOKEN_HEADER: "   "},
                            {OPERATOR_TOKEN_HEADER: TOKEN}, {OPERATOR_TOKEN_HEADER: "anything"}):
                response = await upload(http, headers)
                assert response.status_code == 401, headers
                assert response.json() == UNAUTHORIZED
    run(scenario())
    assert_rejected_without_work(spies)


@pytest.mark.parametrize("presented", [
    None, "", "wrong", TOKEN[:-1], TOKEN + "x", TOKEN.upper(), "x" + TOKEN, TOKEN[1:],
    "Bearer " + TOKEN, TOKEN + "é", "é" * 40,
], ids=["missing", "empty", "wrong", "prefix", "suffix", "uppercase", "prepended", "truncated",
        "bearer-prefixed", "non-ascii-suffix", "non-ascii"])
def test_wrong_or_missing_token_is_rejected(spies, monkeypatch, presented):
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)

    async def scenario():
        async with client() as http:
            if presented is None:
                return await upload(http)
            # httpx would refuse to encode non-ASCII as a str header; send the raw UTF-8 bytes.
            return await upload(http, {OPERATOR_TOKEN_HEADER: presented.encode("utf-8")})
    response = run(scenario())
    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED
    assert_rejected_without_work(spies)


def test_token_in_the_wrong_place_is_rejected(spies, monkeypatch):
    """Only the dedicated header counts: not Authorization, the query string, a form field, or a cookie."""
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)

    async def scenario():
        async with client() as http:
            responses = [
                await upload(http, {"authorization": f"Bearer {TOKEN}"}),
                await upload(http, {"x-vapi-secret": TOKEN}),
                await upload(http, params={"token": TOKEN, OPERATOR_TOKEN_HEADER: TOKEN}),
                await upload(http, data={**VEHICLE, "operator_token": TOKEN, OPERATOR_TOKEN_HEADER: TOKEN}),
                await upload(http, {"cookie": f"{OPERATOR_TOKEN_HEADER}={TOKEN}"}),
            ]
            return responses
    for response in run(scenario()):
        assert response.status_code == 401
        assert response.json() == UNAUTHORIZED
    assert_rejected_without_work(spies)


def test_vapi_secret_does_not_authorize_uploads(spies, monkeypatch):
    """The webhook credential and the operator credential are separate."""
    monkeypatch.setenv("VAPI_WEBHOOK_SECRET", TOKEN)
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, "a-different-operator-token")

    async def scenario():
        async with client() as http:
            return await upload(http, {OPERATOR_TOKEN_HEADER: TOKEN, "x-vapi-secret": TOKEN})
    assert run(scenario()).status_code == 401
    assert_rejected_without_work(spies)


def test_authentication_precedes_every_other_check(spies, monkeypatch):
    """No validation detail (missing fields, bad file, size) leaks to an unauthenticated caller."""
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)

    async def scenario():
        async with client() as http:
            return [
                await upload(http, data={}),
                await upload(http, content=b"not a pdf"),
                await upload(http, filename="manual.exe"),
                await upload(http, data={"year": "19", "make": "x", "model": "y"}),
                await http.post("/upload", content=b"{}", headers={"content-type": "application/json"}),
            ]
    for response in run(scenario()):
        assert response.status_code == 401
        assert response.json() == UNAUTHORIZED
    assert_rejected_without_work(spies)


def test_unauthorized_request_is_answered_without_reading_the_body(spies, monkeypatch):
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)
    status, body, consumed = run(raw_post({OPERATOR_TOKEN_HEADER: "wrong"},
                                          multipart_stream(pdf_chunks(200 * MiB))))
    assert status == 401
    assert body == b'{"detail":"Unauthorized"}'
    assert consumed["messages"] == 0 and consumed["bytes"] == 0
    assert_rejected_without_work(spies)


@pytest.mark.parametrize("order", [[TOKEN, "wrong"], ["wrong", TOKEN], [TOKEN, TOKEN]],
                         ids=["valid-first", "valid-second", "both-valid"])
def test_duplicate_token_headers_are_rejected(spies, monkeypatch, order):
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)
    headers = [(OPERATOR_TOKEN_HEADER, value) for value in order]
    status, _, consumed = run(raw_post(headers, multipart_stream(pdf_chunks(1024))))
    assert status == 401
    assert consumed["bytes"] == 0
    assert_rejected_without_work(spies)


def test_non_ascii_configured_token_matches_the_utf8_bytes_sent(spies, monkeypatch):
    """Fails closed for every other encoding; no 500 for any byte sequence."""
    configured = "tökén-operator-credential"
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, configured)

    async def scenario():
        async with client() as http:
            return [await upload(http, {OPERATOR_TOKEN_HEADER: configured.encode("utf-8")}),
                    await upload(http, {OPERATOR_TOKEN_HEADER: configured.encode("latin-1")}),
                    await upload(http, {OPERATOR_TOKEN_HEADER: b"\xff\xfe\x00"})]
    assert [r.status_code for r in run(scenario())] == [202, 401, 401]
    assert spies.ingest.await_count == 1


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "PUT", "DELETE", "PATCH"])
def test_other_methods_do_not_reach_the_upload_handler(spies, monkeypatch, method):
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)
    status, _, consumed = run(raw_post({}, multipart_stream(pdf_chunks(1024)), method=method))
    assert status == 405
    assert consumed["bytes"] == 0
    assert_rejected_without_work(spies)


@pytest.mark.parametrize("path, status", [("/upload/", 307), ("//upload", 404), ("/UPLOAD", 404),
                                          ("/upload/extra", 404)])
def test_path_variants_do_not_bypass_the_guard(spies, monkeypatch, path, status):
    """A trailing slash redirects (without reading the body) to the guarded route; nothing else matches."""
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)
    got, _, consumed = run(raw_post({}, multipart_stream(pdf_chunks(1024)), path=path))
    assert got == status
    assert consumed["bytes"] == 0
    assert_rejected_without_work(spies)


def test_configured_token_is_trimmed_and_header_name_is_case_insensitive(spies, monkeypatch):
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, f"  {TOKEN}\n")

    async def scenario():
        async with client() as http:
            return await upload(http, {"X-CARVIS-OPERATOR-TOKEN": TOKEN})
    assert run(scenario()).status_code == 202


def test_token_is_read_per_request_so_rotation_needs_no_restart(spies, monkeypatch):
    async def scenario():
        async with client() as http:
            monkeypatch.setenv(OPERATOR_TOKEN_ENV, "old-operator-token")
            assert (await upload(http, {OPERATOR_TOKEN_HEADER: "old-operator-token"})).status_code == 202
            monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)
            assert (await upload(http, {OPERATOR_TOKEN_HEADER: "old-operator-token"})).status_code == 401
            assert (await upload(http, authorized())).status_code == 202
    run(scenario())
    assert spies.ingest.await_count == 2


def test_authorization_uses_a_constant_time_comparison(monkeypatch):
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)
    calls = []
    real = upload_security.hmac.compare_digest
    monkeypatch.setattr(upload_security.hmac, "compare_digest",
                        lambda a, b: calls.append((a, b)) or real(a, b))
    assert upload_security.operator_request_authorized(TOKEN)
    assert not upload_security.operator_request_authorized("nope")
    assert calls == [(TOKEN.encode(), TOKEN.encode()), (b"nope", TOKEN.encode())]


def test_unconfigured_or_absent_values_never_reach_the_comparison(monkeypatch):
    monkeypatch.delenv(OPERATOR_TOKEN_ENV, raising=False)
    assert not upload_security.operator_request_authorized("")
    assert not upload_security.operator_request_authorized(None)
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)
    assert not upload_security.operator_request_authorized(None)


# --- Size cap ----------------------------------------------------------------------------------


def test_declared_oversized_body_is_refused_before_it_is_read(spies, monkeypatch):
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)
    headers = authorized(**{"content-length": str(MAX_UPLOAD_BODY_BYTES + 1)})
    status, body, consumed = run(raw_post(headers, multipart_stream(pdf_chunks(200 * MiB))))
    assert status == 413
    assert body.decode() == f'{{"detail":"{TOO_LARGE_DETAIL}"}}'
    assert consumed["bytes"] == 0
    assert_rejected_without_work(spies)


@pytest.mark.parametrize("value", ["abc", "-1", "1.5", "1e9", "", "١٢"], ids=["text", "negative", "decimal",
                                                                            "exponent", "empty", "non-ascii-digits"])
def test_malformed_content_length_is_refused(spies, monkeypatch, value):
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)
    headers = authorized(**{"content-length": value.encode("utf-8").decode("latin-1")})
    status, body, consumed = run(raw_post(headers, multipart_stream(pdf_chunks(1024))))
    assert status == 400
    assert consumed["bytes"] == 0
    assert_rejected_without_work(spies)


@pytest.mark.parametrize("declared", [None, "1024"], ids=["no-content-length", "understated-content-length"])
def test_streamed_body_over_the_cap_stops_reading_at_the_cap(spies, monkeypatch, declared):
    """Chunked bodies, or ones that understate Content-Length, are counted as they arrive."""
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)
    headers = authorized() if declared is None else authorized(**{"content-length": declared})
    status, body, consumed = run(raw_post(headers, multipart_stream(pdf_chunks(200 * MiB))))
    assert status == 413
    assert body.decode() == f'{{"detail":"{TOO_LARGE_DETAIL}"}}'
    assert MAX_UPLOAD_BODY_BYTES < consumed["bytes"] <= MAX_UPLOAD_BODY_BYTES + MiB
    assert not consumed["exhausted"], "the rest of the stream must not be read"
    assert_rejected_without_work(spies)


def test_file_of_exactly_50_mib_is_accepted(spies, monkeypatch):
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)
    content = PDF + b"\0" * (MAX_UPLOAD_BYTES - len(PDF))

    async def scenario():
        async with client() as http:
            return await upload(http, authorized(), content=content)
    response = run(scenario())
    assert response.status_code == 202, response.text
    assert spies.staged["bytes"] == content
    assert leftover_uploads(spies) == []


def test_file_one_byte_over_50_mib_is_refused(spies, monkeypatch):
    """Within the multipart envelope allowance, so this exercises the exact per-file cap."""
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)
    content = PDF + b"\0" * (MAX_UPLOAD_BYTES + 1 - len(PDF))

    async def scenario():
        async with client() as http:
            return await upload(http, authorized(), content=content)
    response = run(scenario())
    assert response.status_code == 413
    assert response.json() == TOO_LARGE
    assert_rejected_without_work(spies)


def test_limits_are_the_documented_values():
    assert MAX_UPLOAD_BYTES == 50 * 1024 * 1024
    assert MAX_UPLOAD_BYTES < MAX_UPLOAD_BODY_BYTES <= MAX_UPLOAD_BYTES + 64 * 1024
    assert TOO_LARGE_DETAIL == "PDF must be 50 MiB or smaller."


# --- PDF magic ---------------------------------------------------------------------------------


@pytest.mark.parametrize("content", [
    b"", b"%PDF", b"%PD", b" %PDF-1.7\n", b"\n%PDF-1.7\n", b"%pdf-1.7\n", b"%PDF 1.7\n",
    b"\xff\xd8\xff\xe0JFIF", b"PK\x03\x04", b"<html><body>%PDF-1.7</body></html>", b"\xef\xbb\xbf%PDF-1.7",
], ids=["empty", "truncated", "truncated-more", "leading-space", "leading-newline", "lowercase", "no-dash",
        "jpeg", "zip", "html-containing-magic", "bom-prefixed"])
def test_file_without_pdf_magic_is_refused(spies, monkeypatch, content):
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)

    async def scenario():
        async with client() as http:
            return await upload(http, authorized(), content=content)
    response = run(scenario())
    assert response.status_code == 400
    assert response.json() == NOT_A_PDF
    assert_rejected_without_work(spies)


def test_pdf_content_type_does_not_substitute_for_magic(spies, monkeypatch):
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)

    async def scenario():
        async with client() as http:
            return await http.post("/upload", headers=authorized(), data=VEHICLE,
                                   files={"file": ("manual.pdf", b"MZ\x90\x00binary", "application/pdf")})
    assert run(scenario()).status_code == 400
    assert_rejected_without_work(spies)


def test_magic_is_authoritative_over_the_part_content_type(spies, monkeypatch):
    """Existing behavior: clients that label the part octet-stream still upload a real PDF."""
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)

    async def scenario():
        async with client() as http:
            return await http.post("/upload", headers=authorized(), data=VEHICLE,
                                   files={"file": ("manual.pdf", PDF, "application/octet-stream")})
    assert run(scenario()).status_code == 202
    assert spies.staged["bytes"] == PDF


# --- Preserved behavior for authorized requests -------------------------------------------------


def test_authorized_valid_upload_is_unchanged(spies, monkeypatch):
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)

    async def scenario():
        async with client() as http:
            return await upload(http, authorized(), data={**VEHICLE, "shop_id": " Shop_A ",
                                                          "transmission": "Manual", "trim": "Base"})
    response = run(scenario())
    assert response.status_code == 202
    assert response.json() == {
        "status": "accepted", "message": "Manual queued for staging and source review.",
        "verification_status": "pending_review", "filename": "manual.pdf", "shop_id": "shop_a",
        "year": "2022", "make": "subaru", "model": "wrx",
    }
    spies.ingest.assert_awaited_once()
    args, kwargs = spies.ingest.await_args
    assert args[1:] == ("2022", "Subaru", "WRX")
    assert args[0].name == "manual.pdf" and args[0].parent.name.startswith("carvis_upload_")
    assert kwargs["shop_id"] == "shop_a"
    assert kwargs["collection"] == STAGING_COLLECTION
    assert kwargs["client"] is main.app.state.qdrant
    assert kwargs["embedding_model"] is main.app.state.embedder
    assert kwargs["transmission"] == "manual" and kwargs["trim"] == "base"
    assert kwargs["engine_code"] is None and kwargs["market"] is None
    assert spies.staged["bytes"] == PDF, "the staged file must be byte-identical to the upload"
    assert leftover_uploads(spies) == [], "the background job still removes its temporary file"


def test_authorized_multi_chunk_upload_is_byte_identical(spies, monkeypatch):
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)
    content = PDF + bytes(range(256)) * (3 * 4096 + 7)

    async def scenario():
        async with client() as http:
            return await upload(http, authorized(), content=content)
    assert run(scenario()).status_code == 202
    assert spies.staged["bytes"] == content


def test_authorized_streamed_upload_without_content_length_is_accepted(spies, monkeypatch):
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)
    status, body, consumed = run(raw_post(authorized(), multipart_stream(pdf_chunks(3 * MiB))))
    assert status == 202, body
    assert consumed["bytes"] > 3 * MiB
    assert spies.staged["bytes"] == b"".join(pdf_chunks(3 * MiB))


def test_filename_is_reduced_to_its_basename(spies, monkeypatch):
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)

    async def scenario():
        async with client() as http:
            return await upload(http, authorized(), filename="../../etc/manual.pdf")
    response = run(scenario())
    assert response.status_code == 202
    assert response.json()["filename"] == "manual.pdf"
    assert spies.staged["path"].parent.parent == spies.temp_root


@pytest.mark.parametrize("data, status, detail", [
    ({"year": " ", "make": "subaru", "model": "wrx"}, 400, "year, make, and model are required."),
    ({"year": "22", "make": "subaru", "model": "wrx"}, 400, "Invalid vehicle metadata."),
], ids=["blank-field", "invalid-year"])
def test_authorized_invalid_metadata_keeps_its_existing_response(spies, monkeypatch, data, status, detail):
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)

    async def scenario():
        async with client() as http:
            return await upload(http, authorized(), data=data)
    response = run(scenario())
    assert response.status_code == status
    assert response.json() == {"detail": detail}
    assert_rejected_without_work(spies)


def test_authorized_missing_fields_keep_fastapi_validation(spies, monkeypatch):
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)

    async def scenario():
        async with client() as http:
            missing_vehicle = await upload(http, authorized(), data={"year": "2022"})
            missing_file = await http.post("/upload", headers=authorized(), data=VEHICLE)
            return missing_vehicle, missing_file
    for response in run(scenario()):
        assert response.status_code == 422
        assert "detail" in response.json()
    assert_rejected_without_work(spies)


def test_authorized_non_pdf_extension_keeps_its_existing_response(spies, monkeypatch):
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)

    async def scenario():
        async with client() as http:
            return await upload(http, authorized(), filename="manual.txt")
    response = run(scenario())
    assert response.status_code == 400
    assert response.json() == {"detail": "Only PDF uploads are supported."}
    assert_rejected_without_work(spies)


def test_failure_while_staging_removes_the_temporary_file(spies, monkeypatch):
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)
    real_open = Path.open

    def failing_open(self, mode="r", *args, **kwargs):
        if "w" in mode and self.parent.name.startswith("carvis_upload_"):
            handle = real_open(self, mode, *args, **kwargs)
            handle.close()
            raise OSError("disk full")
        return real_open(self, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", failing_open)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app, raise_app_exceptions=False),
                                     base_url="http://carvis") as http:
            return await upload(http, authorized())
    assert run(scenario()).status_code == 500
    assert_rejected_without_work(spies)


def test_other_routes_are_not_operator_gated(monkeypatch):
    monkeypatch.delenv(OPERATOR_TOKEN_ENV, raising=False)

    async def scenario():
        async with client() as http:
            return await http.get("/health")
    assert run(scenario()).json() == {"status": "ok", "service": "carvis"}


# --- Boot and secret hygiene -------------------------------------------------------------------


class FakeQdrant:
    def __init__(self, *args, **kwargs):
        pass

    def collection_exists(self, name):
        return True

    def close(self):
        pass


@pytest.fixture
def boot(monkeypatch, app_state):
    """Run the real lifespan with the embedding model and Qdrant faked; never touches a provider."""
    for name in ("CARVIS_ENV", "RENDER", OPERATOR_TOKEN_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("VAPI_WEBHOOK_SECRET", "webhook-secret-for-boot")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant.invalid")
    monkeypatch.setenv("QDRANT_API_KEY", "test-only")
    # A non-local deployment must name its shop and collection explicitly (M2 A4).
    monkeypatch.setenv("CARVIS_DEFAULT_SHOP_ID", "shop_test")
    monkeypatch.setenv("CARVIS_QDRANT_COLLECTION", "carvis_specs_v2")
    for name in ("SPACETIMEDB_URI", "SPACETIMEDB_TOKEN", "SPACETIMEDB_DB_NAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(main, "TextEmbedding", MagicMock(name="TextEmbedding"))
    monkeypatch.setattr(main, "QdrantClient", FakeQdrant)
    monkeypatch.setattr(main, "_VISION_CLIENT", None)
    level = main.logger.level

    async def start():
        async with main.lifespan(main.app):
            return True

    yield lambda: run(start())
    main.logger.setLevel(level)


@pytest.mark.parametrize("environment", ["local", "staging", "production"])
def test_boot_without_a_token_warns_and_keeps_uploads_closed(boot, monkeypatch, caplog, environment):
    """Missing operator token is not a boot failure (uploads are optional); /upload simply stays closed."""
    monkeypatch.setenv("CARVIS_ENV", environment)
    with caplog.at_level("WARNING", logger="carvis.main"):
        assert boot()
    assert f"{OPERATOR_TOKEN_ENV} is not set; /upload will reject every request" in caplog.text


def test_token_never_appears_in_logs_or_rejections(boot, spies, monkeypatch, caplog):
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)
    with caplog.at_level("DEBUG"):
        boot()

        async def scenario():
            async with client() as http:
                return [await upload(http, {OPERATOR_TOKEN_HEADER: TOKEN[:-1]}),
                        await upload(http, authorized(), content=b"nope"),
                        await upload(http, authorized())]
        responses = run(scenario())
    assert "not set" not in caplog.text
    assert TOKEN not in caplog.text
    for response in responses:
        assert TOKEN not in response.text


# --- Connection closing (M2 A6) ------------------------------------------------------------------


@pytest.mark.parametrize("headers, status", [
    ({}, 401),
    ({OPERATOR_TOKEN_HEADER: "wrong-token"}, 401),
    ([(OPERATOR_TOKEN_HEADER, TOKEN), (OPERATOR_TOKEN_HEADER, TOKEN)], 401),
    (authorized(**{"content-length": "abc"}), 400),
    (authorized(**{"content-length": str(MAX_UPLOAD_BODY_BYTES + 1)}), 413),
], ids=["no-token", "wrong-token", "duplicate-token", "malformed-length", "declared-oversize"])
def test_early_rejections_close_the_connection_unread(spies, monkeypatch, headers, status):
    """Without Connection: close the server reads and discards a declared-huge body on keep-alive."""
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)
    if isinstance(headers, dict) and "content-length" not in {k.lower() for k in headers}:
        headers = {**headers, "content-length": str(500 * MiB)}
    elif isinstance(headers, list):
        headers = headers + [("content-length", str(500 * MiB))]
    returned, _, consumed = run(raw_post(headers, multipart_stream(pdf_chunks(200 * MiB))))
    assert returned == status
    assert consumed["bytes"] == 0
    assert raw_post.last_headers.get("connection") == "close"
    assert_rejected_without_work(spies)


@pytest.mark.parametrize("declared", [None, "1024"], ids=["no-content-length", "understated-content-length"])
def test_streamed_oversize_rejection_closes_the_connection(spies, monkeypatch, declared):
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)
    headers = authorized() if declared is None else authorized(**{"content-length": declared})
    status, body, consumed = run(raw_post(headers, multipart_stream(pdf_chunks(200 * MiB))))
    assert status == 413
    assert body.decode() == f'{{"detail":"{TOO_LARGE_DETAIL}"}}'
    assert MAX_UPLOAD_BODY_BYTES < consumed["bytes"] <= MAX_UPLOAD_BODY_BYTES + MiB
    assert not consumed["exhausted"]
    assert raw_post.last_headers.get("connection") == "close"
    assert_rejected_without_work(spies)


def test_accepted_upload_keeps_the_connection_open(spies, monkeypatch):
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)
    chunks = list(multipart_stream(pdf_chunks(MiB)))
    status, _, consumed = run(raw_post(authorized(), chunks))
    assert status == 202
    assert consumed["bytes"] == sum(len(chunk) for chunk in chunks), "the whole body was read"
    assert "connection" not in raw_post.last_headers


def test_unparseable_streamed_body_closes_the_connection(spies, monkeypatch):
    """FastAPI's 400 for a body it cannot parse arrives mid-stream; the rest must not be drained."""
    monkeypatch.setenv(OPERATOR_TOKEN_ENV, TOKEN)
    garbage = (b"not multipart at all " + b"\0" * MiB for _ in range(200))
    status, _, consumed = run(raw_post(authorized(**{"content-length": str(40 * MiB)}), garbage))
    assert status == 400
    assert not consumed["exhausted"]
    assert raw_post.last_headers.get("connection") == "close"
    assert_rejected_without_work(spies)

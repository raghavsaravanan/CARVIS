# Carvis architecture

## Product boundary

Carvis has one user-facing application: the native SwiftUI iOS app. FastAPI owns API and
webhook orchestration, Qdrant stores reviewed automotive evidence, Vapi provides current voice
infrastructure, Nemotron supplies optional non-authoritative visual context, and Meta Wearables
is an optional future device capability. The retained SpacetimeDB module is reserved for future
native shop intelligence; it has no browser client and is not yet integrated into iOS.

## Request flow

Meta glasses → native iPhone companion → JPEG/question + explicit vehicle → FastAPI → NVIDIA Nemotron visual context when needed → exact structured Qdrant filters → Python evidence/conflict validation → cited specification → app speech output.

This describes the currently implemented glasses path, not the complete target product. The
approved product direction is phone-first native iOS audio with glasses isolated as an optional
adapter. Phone-first audio and production identity are not implemented by the repository cleanup.

## Backend modules

- `ingest.py`: validates explicit CLI/manifest metadata, caches numbered LlamaParse pages by PDF SHA-256 and parser configuration, extracts pending records, embeds and stages.
- `spec_schema.py`: strict schema version 2, Decimal strings, source-cell/unit/variant validation and review digests.
- `schemas/specification-v2.json`: generated JSON Schema matching the Pydantic payload.
- `spec_extract.py`: conservative atomic row/variant extraction, warnings, split variant headers and ordered torque stages. Empty merged cells stay unavailable.
- `qdrant_v2.py`: staging collection/vector/index configuration and deterministic idempotent upserts. All embeddings are validated before writes. Existing source review decisions survive re-ingestion.
- `spec_retrieval.py`: request normalization, exact filters, complete scoped candidate evaluation, ranking, and deterministic speech formatting.
- `migrate_v2.py`: legacy backup, review exports, original-PDF-bound approval, acceptance validation, atomic alias activation and rollback.
- `main.py`: compatible FastAPI routes, Nemotron adapter, short-lived confirmed vehicle sessions and timings.
- `purge_db.py`: retired compatibility entry point; no deletion is performed.

## Data and provenance

Records include shop/year/make/model and optional trim/engine/transmission/market; component aliases, operation and specification type; numeric value or range, unit and raw cell; conditions/warnings/notes; PDF hash, filename, page, section, table, row, header, excerpt and parser/extraction metadata.

Unavailable values remain null. Both searchable text and original row evidence are retained; full parsed pages remain in the local content-hash cache. A transcription fallback must identify its transcriber and match the original PDF hash. It creates pending records, never verified answers.

OCR, including a visually plausible number, is pending review. An identified source reviewer compares applicability, values, units, warnings, source location, table spans and complete procedure stages against the original. Approval binds the entire evidence payload digest. Changes after review invalidate approval. This digest detects changes; it is not a cryptographic reviewer identity or proof that OCR is correct. Access to review tooling must be limited to trusted operators.

## Retrieval safety

1. Require explicit vehicle identity, or reuse a previously confirmed complete identity in the same shop/call. A partial vehicle change cannot inherit unrelated session fields.
2. Normalize supported component aliases and operation/specification/transmission intent. Conflicting explicit context requests clarification.
3. Exact-filter shop, year, make, model, component, operation, spec type, supplied variants, schema version and verified status.
4. Enumerate the complete matching scope up to 256 points. Overflows refuse for clarification. This prevents a conflicting record outside semantic top-k from being hidden.
5. Revalidate applicability, source cell and unit, review digest, source revisions and candidate conflicts in Python. Missing relevant variants ask for confirmation even when the documented values are equal.
6. Rank up to 16 exact-filtered candidates using the existing BAAI/bge-small-en-v1.5 embeddings (384 dimensions, Cosine). Similarity only chooses among previously validated evidence.
7. Format exact values in Python with actual citations. Ordered steps and warnings are preserved without voice-length truncation.

There is no cross-vehicle fallback, inferred vehicle identity, model-generated numerical answer or unit conversion. Unknown components/operations refuse or require explicit canonical context. The controlled vocabulary is intentionally limited; extending it requires evidence-backed records and tests.

## API contracts

`/vision-query` retains file/question/year/make/model/session_id. Optional form fields are shop_id, transmission, engine_code, trim, market, component, operation, spec_type. Success retains answer, vehicle, component and source, and adds sources/status/source_grounded/timings_ms. Refusals retain HTTP 404 with error/component and add a machine-readable status.

`/vapi-tool` accepts flat JSON, nested parameters, and existing Vapi tool-call shapes. Variants may be in structured fields or the question. It preserves results/toolCallId/result and adds source evidence. It never passes numeric answers through the legacy free-text torque formatter.

`/upload` requires the operator token (`X-Carvis-Operator-Token` matching `CARVIS_OPERATOR_TOKEN`; unset rejects every upload), accepts only files that begin with `%PDF-` and are at most 50 MiB, and rejects anything else before ingestion is scheduled. Unauthorized and declared-oversized requests are answered before the body is read; undeclared bodies stop streaming at the cap. It stages pending records and returns HTTP 202. It no longer deletes a document before replacement. Background failures leave existing data intact. Large batch writes are not transactional: a network failure may leave additional pending points, but no old points are removed. Rerunning the same ingestion is safe.

`/conversation/sessions…` keeps its request and success shapes. Interim abuse limits (M2 A3, until Track B identity and durable sessions):

- **Creation limits.** Unauthenticated session creation allows 20 sessions per 60 s, counted across all clients, because behind Render's proxy every caller shares one peer address. It is also capped at 256 live sessions.
- **429 instead of eviction.** When either limit is hit, creation returns HTTP 429 `{"detail": …}` with `Retry-After`. Live sessions are never evicted to make room; expired sessions (4 h idle) are removed first.
  - Trade-off: a sustained anonymous flood, or sessions kept alive by polling, can hold every slot. Legitimate *new* sessions are then refused until slots expire, but existing sessions and calls are untouched. Previously, LRU eviction kept creation available by ending other people's sessions.
- **Call binding.** A Vapi call ID binds to one session and call generation only. Binding it to another session, or to a later call of the same session, returns 409 `stale call`. Repeating the same binding succeeds.
- **One current call per generation.** When the phone binds a different ID, for example after a webhook auto-bound another one, the earlier ID is retired: it stays stale and can never be bound again.
- **Pruning.** Each session remembers its 16 most recent call IDs, and they are pruned when the session expires. Once the session is bound, a webhook carrying an unknown call ID for it is treated as stale.
- **Accepted operational decisions (owner, 2026-11-16).** Keep the interim limits (20 creations per minute globally, 256 live sessions) until Track B authentication and durable sessions, then revisit them. Keep refuse-instead-of-evict: protecting existing conversations takes priority over admitting new sessions when capacity is exhausted. These are working rules; they resolve no roadmap owner decision (D-item), and formal records in `docs/decisions/` remain authoritative.
- **Residual until Track B5.** Before the phone binds, the existing webhook-before-bind path still trusts the payload's `carvis_session_id`. A call ID that was never bound, or was pruned, can therefore act during that short window.

Request limits, errors and logs (M2 A6). These leave request and success shapes unchanged.

- **Body caps.** `backend/request_limits.py` caps every route's body while it streams. Above the cap, the route returns HTTP 413 `{"detail": …}` with `Connection: close` and reads no more of the body.
  - This is an application-level cap: the server still receives whatever the client sends before the connection closes.
  - `/vision-query` and camera photos: the 8 MiB image cap plus 64 KiB of form fields, with the existing image detail. The 8 MiB per-image check is unchanged.
  - `/vapi-tool`: 4 MiB.
  - Every other route: 64 KiB.
  - `/upload` keeps its own 50 MiB operator-gated cap (A2). Its early 401, malformed-length 400 and declared-oversize 413, its streamed 413 at the cap, and a parse-error 400 raised mid-body all carry `Connection: close`. Authentication, PDF validation and the file and body caps are unchanged.
- **Auth ordering.** The declared `Content-Length` is checked when the body is first read.
  - **`/vapi-tool`**, which authenticates before reading, still answers an unauthenticated request with its own 401 and never reads the body. Because that body was announced but not read, the response also carries `Connection: close`.
  - **Conversation and camera routes** have bodies that FastAPI parses before the handler checks the session token. An over-cap unauthenticated request to them now gets 413 instead of 401. Within the cap they still answer 401.
- **No swallowed 413s.** An over-cap `/vapi-tool` body gets 413, not the Vapi-shaped "invalid JSON" 200 that the handler returns for parse errors.
- **Malformed `Content-Length`.** Uvicorn answers it with a plain-text 400 before the app runs; the route's JSON 400 covers servers that do not.
- **Generic failures.** These responses carry a fixed message and never exception text, which can name configuration or providers. The reason is logged on the server.
  - `/vision-query` and camera-photo vision failures: 503 `Image identification is temporarily unavailable.`
  - Lookup failures: 503 `Specification lookup is temporarily unavailable.`, and the same text as the Vapi tool error.
  - Designed refusal and clarification reasons are unchanged.
- **Logging scaffold.** `backend/log_config.py` writes one JSON object per line, or the previous text format with `CARVIS_LOG_FORMAT=text`.
  - **Allowlist, not filter.** `log_event` logs only field names listed in `FIELD_POLICY`, each with a rule:
    - **Measurements and flags.**
    - **Exact shapes** for server-generated values: 8-hex session prefixes, 32-hex camera request IDs, setting names, lowercase codes and exception type names.
    - **Closed vocabularies** registered by their owning module: component, operation, spec type, tool name, internal reasons, vehicle fields, and the configured default shop.
    - **Fingerprints** for caller-supplied identifiers (Vapi call IDs, tool-call IDs, any other `shop_id`): `fp:` plus 12 hex digits of an HMAC-SHA-256 of the field name and value, keyed with a random per-process salt. A fingerprint correlates lines for one field within one process and cannot be reversed. A log reader cannot confirm a guessed value, but someone who can also send requests can, by sending the guess and comparing. Fingerprints protect content, not secrets.
  - Any other name is dropped (`dropped_fields`). A value that fails its rule becomes `"[redacted]"` (`redacted_fields`). Nested payloads, free text, model output and exception messages never pass.
  - **Request paths log no conversation content.** The `/vapi-tool`, vision-query, camera, conversation, retrieval and upload-job paths log through `log_event` or with fixed messages, exception type names and counts. Exception messages and tracebacks are no longer logged there. The vision errors log a code and the missing setting's name instead.
  - **What is no longer logged:**
    - the mechanic's question;
    - webhook payload keys, make and model;
    - caller-supplied IDs (now fingerprints);
    - unknown tool names;
    - the request vehicle in retrieval decisions;
    - the shop catalog's values (counts only);
    - phone-supplied call-end and camera-failure reasons;
    - model-supplied work context;
    - vision-model output;
    - the vehicle summary;
    - refused answer numbers;
    - SpacetimeDB error bodies.
  - **The phone's trace is separate.** `GET /conversation/sessions/{id}` still returns every note detail to the phone, unchanged.
  - **Tests.** `backend/tests/test_logging_privacy.py` puts canaries in the question and in the other request-controlled fields and fails if one reaches any log record, at any level, from any logger.
    - Free-text fields: the camera and call-end reasons, work context, vision output and vehicle trim.
    - Identifiers, tested as a sentence, as a single token, and joined by `.:-_`: tool names, phone-bind and webhook call IDs, and legacy `shop_id` and tool-call IDs.
  - **Residual limits.**
    - Plain `logger.*` calls bypass the policy. The remaining ones on request paths carry only type names, counts, constants or server timings, and a new request-path log must use `log_event`.
    - Loggers Carvis does not configure are outside the policy: uvicorn's `uvicorn` and `uvicorn.access`, httpx and openai. Uvicorn access lines carry each request's path and query string as sent, including session IDs and any caller-chosen text in them. Uvicorn's "Exception in ASGI application" traceback for an unhandled error can quote that error's message. httpx logs provider request URLs at INFO. Configuring these is still open; it is not part of the B1 contract.
    - Fingerprints change on restart, so correlation spans one process only.
    - B1 adds request IDs to responses (below); stamping them on every log line, call IDs and metrics are still open.

## PostgreSQL foundation (M2 B1)

Implements the B1 row of [the M2 roadmap](../architecture/12-m2-roadmap.md) under ADR-0001. It is vendor-independent: nothing assumes a host, issuer, pooler mode or connection-string shape (those are B2, D-2). No route reads or writes PostgreSQL yet.

- **Settings** (`backend/settings.py`). `load_settings()` is the startup entry point. It runs the existing guards unchanged and in their original order (webhook secret and environment, then the explicit shop, collection and SpacetimeDB names), then validates `CARVIS_DATABASE_URL`. It reads only `os.environ`, the source those guards read. The URL is optional in B1 by owner decision (requiring it outside local would refuse boot on the current deployment); missing or invalid never yields readiness, and invalid refuses boot outside local. Supported schemes normalize to `postgresql+psycopg`. The value is held in a wrapper whose `repr`/`str` are redacted, and errors name the setting only (the parse error that could quote the URL is discarded, not chained).
- **Engine and session factory** (`backend/db/engine.py`). Built lazily at startup when the URL is configured (no connection at boot), disposed at shutdown; pre-ping, rollback on return, psycopg prepared statements disabled, bound parameters hidden from errors. No route uses it in B1.
- **Readiness** (`backend/db/readiness.py`, `GET /readyz`). Ready means the recorded revision in `carvis_migrations.alembic_version` equals this build's single head. The probe is a coroutine using psycopg's async connection (connect and query on the event loop) under one 2-second `asyncio.timeout`; on expiry it is cancelled and the connection closed. Host names are resolved by the probe's own one-thread resolver, never psycopg or the shared default executor that the voice path's lookups use: a blocking `getaddrinfo` cannot be cancelled, so while one lookup is still running no new one starts or queues and the probe answers `database_unreachable` at once. Every address a name resolves to (IPv6 and IPv4) becomes its own connection attempt with `hostaddr` set and `host` kept for TLS verification, in libpq's order (several hosts, matching ports, unresolvable hosts skipped, `load_balance_hosts=random` shuffled); within the single 2-second deadline each remaining address gets a fair share of the time left, less a query reserve, so a first address that refuses or silently drops packets falls back to a later reachable one. At most one resolver thread and one connection exist during any outage. Limitation: a lookup still hung at shutdown keeps its one thread until the system resolver returns; the lifespan does not wait for it, but the interpreter joins it at exit, so process exit can be delayed by up to the resolver's own timeout. Each probe opens one connection; at most one probe runs at a time and concurrent requests share it; a client disconnecting does not cancel the shared probe. `statement_timeout` and `lock_timeout` are `SET LOCAL`. A missing schema or table, no row, several rows or another revision is `migrations_pending`; any other failure is `database_unreachable`, logged by exception type name only. `/healthz` is liveness with no dependency; `/health` is unchanged and remains the deployment's health check.
- **Request IDs** (`RequestIdMiddleware` in `backend/main.py`). Pure ASGI, inside Starlette's error middleware and outside FastAPI's exception middleware and the body-limited routes. A caller's `X-Request-ID` is accepted only if exactly one is present and it is a UUID; it is normalized to 32 lowercase hex, otherwise replaced by a new `uuid4`. Duplicates are treated as ambiguous and replaced. Exactly one header is set on every response the app produces (any header a route set is replaced), including 404, 413, 422 and errors. For an unhandled exception before the response starts, the middleware sends Starlette's own plain-text 500 (identical bytes) with the header and re-raises, so the error middleware does not send a second response. The ID is available as `request.state.request_id` and the `main.current_request_id` context variable, reset after each request. Responses the ASGI server generates before the app runs (uvicorn's 400 for a malformed `Content-Length`) cannot carry it.
- **Migrations** (`backend/migrations/`). One linear Alembic chain (`python -m db.history` and CI fail on more than one head, base, merge or branch). The URL comes only from `CARVIS_MIGRATION_DATABASE_URL`; offline mode is refused. The version table lives in the CARVIS-owned `carvis_migrations` schema, named explicitly so `search_path` never matters; `env.py` creates that schema after checking `CREATE` on the database, and refuses one owned by another login. `0001_baseline` is empty. `0002_roles`:
  - creates `carvis_owner` (owns CARVIS schema objects; migrations only), `carvis_app` (API runtime) and `carvis_worker` (tenant-scoped jobs), all `NOLOGIN`, no superuser, createdb, createrole, replication or `BYPASSRLS`, each marked with a role comment;
  - validates any pre-existing CARVIS role and fails closed, without modifying it, if it has an elevated attribute, is a member of any role, can log in (owner decision: no CARVIS role may have `LOGIN` in B1), or has any member other than the migration login's own administrative grant (no runtime login is approved in B1, so an existing member of `carvis_app` or `carvis_worker` is refused); a non-superuser login also needs `ADMIN OPTION` on every pre-existing role, and `CREATEROLE` to create the rest;
  - refuses a pre-existing `carvis` schema, then creates it owned by `carvis_owner` (`USAGE` for the runtime roles, nothing for `PUBLIC`), running owner-scoped statements under `SET LOCAL ROLE carvis_owner`;
  - grants the migration login `carvis_owner` with `SET TRUE, INHERIT FALSE` (non-superusers), so later revisions create objects as `carvis_owner` (`db.roles.as_owner`) and ownership never depends on which login ran them;
  - grants the runtime roles `USAGE` on `carvis_migrations` and `SELECT` on its version table, so readiness needs no elevation. Nothing is granted or revoked in `public`, on the database, or on any issuer- or host-specific role.
  - Downgrade revokes those grants, drops the marked `carvis` schema (no `CASCADE`), revokes the login's grant and drops only marked roles. `downgrade base` leaves the empty `carvis_migrations` schema and version table.
  - Roles are cluster-wide, so one CARVIS database per PostgreSQL cluster is supported. PostgreSQL 16 or later.
- **Open items.** `/readyz` requires the exact head, so a previous image is not ready on an expanded schema; reconcile with ADR-0001's rollback model before `/readyz` becomes the deployment health check (B10). `CARVIS_DATABASE_URL` becomes required outside local in B2/B10 (owner action). Role logins and credentials, which login runs migrations, the version table's owner when that login changes, and issuer-specific grants are B2 (D-2).

## Nemotron and latency

A reused NVIDIA-compatible AsyncOpenAI client provides visual recognition with bounded timeouts and no repair-fact authority. Complete explicit requests skip unnecessary inference. Ambiguous requests can return a visual hypothesis for mechanic confirmation; hypotheses never become unconfirmed exact component filters.

Responses track inference, embedding, retrieval, verification and total milliseconds. An exact candidate scan adds a network round trip so hidden conflicts cannot be missed. Cold model startup, NVIDIA inference, and network latency are not covered by a sub-second guarantee.

## Deployment boundary

The legacy collection remains intact. New ingestion targets `carvis_specs_v2`; `carvis_specs_active` is the future stable alias. Mutating an aliased collection is forbidden by tooling. Build a new staging generation for updates.

The v2 application refuses legacy numeric answers until migration is complete. Do not deploy the changed backend alone while leaving production pointed at the legacy collection. Follow [the migration runbook](qdrant-v2-migration.md), validate original sources and acceptance cases, activate the alias, then configure/deploy the new backend. Keep the prior deployed application available for operational rollback. V2 rollback should use a previously validated v2 generation, never an unsafe fallback.

## Open architecture decisions

- Select the P0 authentication provider and canonical transactional store.
- Decide whether SpacetimeDB is the P1 realtime shop store and whether future iOS access is direct
  or mediated through authenticated FastAPI. No integration is approved yet.
- Approve the phone-first Vapi/audio lifecycle and transcript/audio retention policy.
- Define rights-cleared pilot vehicle and repair-information coverage.
- Decide whether guided-repair and simulated shop UI remain development-only or become future
  source-grounded product features.

Secrets remain server-side and captured images are intended to remain ephemeral. The retained
SpacetimeDB module and optional best-effort backend telemetry do not yet establish end-user iOS
identity. Meta SDK lifecycle code remains isolated in the native application.


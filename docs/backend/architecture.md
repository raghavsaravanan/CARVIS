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
    - Loggers Carvis does not configure are outside the policy: uvicorn's `uvicorn` and `uvicorn.access`, httpx and openai. Uvicorn access lines carry each request's path and query string as sent, including session IDs and any caller-chosen text in them. Uvicorn's "Exception in ASGI application" traceback for an unhandled error can quote that error's message. httpx logs provider request URLs at INFO. Configuring these is deferred to Track B1.
    - Fingerprints change on restart, so correlation spans one process only.
    - Request IDs, call IDs and metrics arrive with Track B1.

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


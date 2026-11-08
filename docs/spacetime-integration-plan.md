# Deferred SpacetimeDB integration plan

SpacetimeDB is deferred for the current HackUTD demo. If the product later needs persistent multi-device state or a live shop workflow, it can become Carvis's operational state layer. It will not replace Qdrant, which remains the source of truth for service-manual chunks and embeddings.

## What SpacetimeDB does

SpacetimeDB should own the data that changes during a mechanic session:

- active mechanic sessions and confirmed vehicle context;
- vision-query lifecycle and errors;
- sanitized component-identification metadata;
- source-grounded result metadata and latency;
- connected-client/demo-dashboard state.

It must not store API keys, raw JPEGs, service-manual PDFs, Qdrant vectors, or unredacted credentials. The image is sent to Carvis for inference and is discarded after the request.

## Request flow

```text
Web/native client
  ├─ connect to SpacetimeDB and create/update session state
  └─ POST JPEG + question + explicit vehicle identity to Carvis
       ├─ Nemotron proposes visual component context
       ├─ Qdrant retrieves matching manual content
       └─ Carvis returns source-grounded answer
  └─ record sanitized result and subscribe to live state
```

The explicit year, make, and model remain authoritative. Visual identification is probabilistic context only.

## Module design

Create a dedicated top-level `spacetime/` TypeScript module using the official SpacetimeDB TypeScript module template. Keep generated client bindings out of hand-written source and regenerate them after every published module schema change.

Recommended tables:

```text
mechanic_session
  id, shop_id, vehicle_year, vehicle_make, vehicle_model,
  status, created_at, last_seen_at

vision_query
  id, session_id, question, component, confidence,
  status, created_at, completed_at

query_result
  id, query_id, answer, source_ref, source_grounded,
  latency_ms, created_at
```

Recommended reducers/functions:

```text
create_session(shop_id, year, make, model)
touch_session(session_id)
start_query(session_id, question)
mark_identifying(query_id, component, confidence)
mark_retrieving(query_id)
record_result(query_id, answer, source_ref, latency_ms)
mark_refused(query_id, reason)
mark_failed(query_id, safe_error)
```

Reducers should validate IDs, enforce bounded string lengths, and reject raw image data or credentials. `source_ref` should be a safe document reference or section label, never a PDF upload or secret.

## Client architecture

The browser/native client is the simplest SpacetimeDB client because the official TypeScript SDK provides the connection, reducer invocation, and subscription path. It receives only:

```env
VITE_SPACETIMEDB_ENABLED=true
VITE_SPACETIMEDB_URI=https://maincloud.spacetimedb.com
VITE_SPACETIMEDB_DB_NAME=carvis-hackutd
```

Do not put `NVIDIA_API_KEY`, `QDRANT_API_KEY`, `LLAMA_CLOUD_API_KEY`, `VAPI_WEBHOOK_SECRET`, or an admin token in Vite environment variables. Use the SDK's supported anonymous/authenticated flow. If authentication is added, tokens are obtained at runtime and are not committed or hard-coded.

Carvis remains the trusted boundary for Nemotron and Qdrant. The client writes only lifecycle metadata before and after the API call. The returned answer is displayed and spoken only after Carvis marks it `source_grounded`.

## Backend contract changes

Keep `/vapi-tool`, `/upload`, and the current `/vision-query` inputs backward-compatible. Additive changes only:

1. Accept a client-provided query ID or generate one server-side.
2. Return `query_id` in both success and safe refusal responses.
3. Return a sanitized `status` value such as `answered`, `refused`, or `failed`.
4. Keep SpacetimeDB credentials out of the FastAPI process for the first implementation; the client can record state through reducers.

If a trusted server-side writer becomes necessary, add a separate adapter and a server-only `SPACETIMEDB_TOKEN`. Do not make the answer path depend on SpacetimeDB availability: if the state service is unavailable, Carvis must still answer from the matching manual and the UI must show degraded telemetry.

## Future implementation phases

### S1 — Bootstrap the module

- Install the current Spacetime CLI.
- Authenticate with `spacetime login`.
- Create `spacetime/` from the official TypeScript module template.
- Define the tables and reducers above.
- Run the local module and publish the database as `carvis-hackutd` or another lowercase, hyphenated name.

Acceptance: the module starts locally, publishes successfully, and a generated TypeScript client can connect and subscribe.

### S2 — Add the frontend client

- Add the official TypeScript client dependency to `frontend/`.
- Generate bindings into a clearly named generated directory.
- Create one `spacetimeClient` module; do not connect from React components directly.
- Create/touch one session per browser/device session.
- Record query lifecycle changes around the existing `/vision-query` request.

Acceptance: opening two clients shows the same active session/query state without exposing a secret.

### S3 — Make the API correlation-safe

- Add `query_id` to `/vision-query` responses.
- Correlate the SpacetimeDB `vision_query` row with the Carvis request.
- Record only the detected component, confidence, status, source label, and latency.
- Preserve manual-match refusal behavior and existing `/vapi-tool` behavior.

Acceptance: a successful answer, missing-manual refusal, provider failure, and validation failure each produce the correct safe state.

### S4 — Demo dashboard and resilience

- Add a small live session/query panel to the web app.
- Show `identifying → retrieving → answered/refused/failed`.
- Make telemetry writes best-effort with visible degraded-state logging.
- Never block a source-grounded Carvis answer because a dashboard subscription is down.

Acceptance: the demo can be run with SpacetimeDB online, and the core answer path fails safely when SpacetimeDB is temporarily unavailable.

## Verification checklist

- `backend/tests/` remains green.
- `npm run build` remains green in `frontend/`.
- Existing `/vapi-tool` and `/upload` smoke tests still work.
- A matching manual produces a source-grounded answer.
- A nonmatching vehicle produces a refusal, not a guessed repair fact.
- No raw image, API key, PDF, vector, or admin token is written to SpacetimeDB.
- `.env` files remain ignored and are never included in commits.

## Reference documentation

- [SpacetimeDB TypeScript quickstart](https://spacetimedb.com/docs/quickstarts/typescript)
- [SpacetimeDB client SDKs](https://spacetimedb.com/docs/clients/)
- [SpacetimeDB authorization](https://spacetimedb.com/docs/http/authorization/)
- [Carvis architecture](./architecture.md)
- [Nemotron and SpacetimeDB decisions](./nemotron-spacetime.md)

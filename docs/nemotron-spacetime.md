# Nemotron and SpacetimeDB deferred option

## Decision

Use NVIDIA Nemotron for visual component context and Qdrant as the manual retrieval store. SpacetimeDB is deferred and is not part of the current runtime.

NVIDIA's current Nemotron 3 Nano Omni model accepts image and text input and exposes an OpenAI-compatible chat-completions endpoint. George's adapter uses that endpoint, so the iPhone/web client contract stays unchanged:

```text
JPEG + explicit vehicle context + question
  → Nemotron component context
  → George query enrichment
  → Qdrant manual retrieval
  → existing source-grounded formatter
```

## Why SpacetimeDB is separate from Qdrant

- Qdrant already stores the embedded service-manual chunks and vehicle metadata.
- Nemotron is an inference provider, not a transactional store.
- A vision query can be answered statelessly from the JPEG, explicit vehicle fields, and Qdrant.
- SpacetimeDB is not a replacement for Qdrant: it stores sessions, status, and result metadata while Qdrant stores manual chunks and vectors.

## Deferred SpacetimeDB role

Use SpacetimeDB for operational state that benefits from real-time subscriptions:

- mechanic sessions and active vehicle context;
- query lifecycle (`captured`, `identifying`, `retrieving`, `answered`, `refused`, `failed`);
- result metadata and latency metrics;
- connected device/app status;
- a live shop/demo dashboard.

Do not store raw images, API keys, manual PDFs, or Qdrant vectors there. Store an image hash or object reference only if an audit trail is explicitly required.

Suggested TypeScript module tables:

```text
mechanic_session(id, shop_id, vehicle_year, vehicle_make, vehicle_model, created_at, last_seen_at)
vision_query(id, session_id, question, component, confidence, status, created_at)
query_result(id, query_id, answer, source_ref, latency_ms, created_at)
```

The FastAPI endpoint remains the trusted inference/retrieval boundary. The simplest hackathon integration is a browser TypeScript client connected to the published SpacetimeDB module; it records sanitized lifecycle/result events and subscribes to live state through generated bindings. The browser receives only the public host and database name, never NVIDIA, Qdrant, LlamaParse, Vapi, or admin credentials.

## Configuration

```text
VISION_PROVIDER=nemotron
NVIDIA_API_KEY=
NEMOTRON_MODEL=nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
NEMOTRON_BASE_URL=https://integrate.api.nvidia.com/v1
```

If a future scope requires SpacetimeDB, its frontend values would be:

```env
VITE_GEORGE_API_URL=/api
VITE_SPACETIMEDB_ENABLED=true
VITE_SPACETIMEDB_URI=https://maincloud.spacetimedb.com
VITE_SPACETIMEDB_DB_NAME=george-hackutd
```

Do not add a SpacetimeDB admin token to the frontend environment. This configuration is intentionally not present in the current [`frontend/.env`](../frontend/.env).

For local/self-hosted NIM, change only `NEMOTRON_BASE_URL` and `NEMOTRON_MODEL`; the adapter uses the same OpenAI-compatible chat request shape.

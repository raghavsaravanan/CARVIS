# Nemotron and SpacetimeDB integration plan

## Decision

Use NVIDIA Nemotron for visual component context and keep Qdrant as the manual retrieval store. Do not add SpacetimeDB to the critical answer path yet.

NVIDIA's current Nemotron 3 Nano Omni model accepts image and text input and exposes an OpenAI-compatible chat-completions endpoint. George's adapter uses that endpoint, so the iPhone/web client contract stays unchanged:

```text
JPEG + explicit vehicle context + question
  → Nemotron component context
  → George query enrichment
  → Qdrant manual retrieval
  → existing source-grounded formatter
```

## Why a second database is not required

- Qdrant already stores the embedded service-manual chunks and vehicle metadata.
- Nemotron is an inference provider, not a transactional store.
- A vision query can be answered statelessly from the JPEG, explicit vehicle fields, and Qdrant.
- Adding SpacetimeDB now would add deployment, auth, generated bindings, and a second write path before the demo needs them.

## Where SpacetimeDB fits later

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

The FastAPI endpoint remains the trusted inference/retrieval boundary. It can later publish sanitized lifecycle/result events to SpacetimeDB, while the browser subscribes to those events through generated TypeScript bindings. This avoids exposing NVIDIA credentials or moving retrieval security into the browser.

## Configuration

```text
VISION_PROVIDER=nemotron
NVIDIA_API_KEY=
NEMOTRON_MODEL=nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
NEMOTRON_BASE_URL=https://integrate.api.nvidia.com/v1
```

For local/self-hosted NIM, change only `NEMOTRON_BASE_URL` and `NEMOTRON_MODEL`; the adapter uses the same OpenAI-compatible chat request shape.

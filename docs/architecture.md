# George glasses copilot architecture

Status: Phase 0 complete; the web-first Phase 2 vertical slice is implemented; SpacetimeDB is deferred; native glasses capture remains hardware-gated.

## Current workspace

The existing application is split into the following top-level areas:

- [`backend/main.py`](../backend/main.py) owns the FastAPI app, the existing `/vapi-tool` webhook, `/upload`, `/health`, `/vision-query`, vehicle-session handling, Qdrant retrieval, and source-to-speech formatting.
- [`backend/ingest.py`](../backend/ingest.py) parses service-manual PDFs with LlamaParse, expands mechanical units, chunks tables, embeds with FastEmbed, and upserts into Qdrant collection `george_specs`.
- [`backend/tests/test_main.py`](../backend/tests/test_main.py) covers the safety-critical speech formatting and vehicle-catalog guards without requiring Qdrant.
- [`frontend/`](../frontend/) is the Vite/React web client. It is not the native glasses companion.
- [`ios/`](../ios/) contains the official Meta CameraAccess handoff for the future native capture bridge.

The demo expects an intake-manifold guide tagged `2019 / chevrolet / silverado` and an AMS VR30 guide tagged `2016 / nissan / vr30`. Those PDFs are local-only inputs and are not currently present in the repository; Qdrant must be seeded before live answers can work. `.env`, local Qdrant data, and parse caches are also local-only artifacts.

## Target request flow

```text
Meta Ray-Ban glasses
  camera + supported mic/audio
        │ Meta Wearables Device Access Toolkit
        ▼
Native SwiftUI iPhone companion
  capture JPEG + question + explicit year/make/model + session ID
        │ HTTPS multipart POST
        ▼
George FastAPI /vision-query
  vision model proposes component context
  (never proves vehicle identity)
        │ query + visual context + explicit vehicle fields
        ▼
Existing George retrieval seam: search_top_chunk(...)
  strict metadata → soft vehicle match → shop-scoped semantic fallback
        ▼
Existing source-grounded formatter
        │ structured JSON
        ▼
iPhone UI + verified audio route
        └─ preferably glasses; otherwise clearly labeled phone fallback
```

## Integration points and invariants

### Backend

[`backend/main.py`](../backend/main.py) now exposes an additive `/vision-query` route. It accepts:

- a JPEG upload;
- `question`;
- explicit `year`, `make`, and `model` fields;
- `session_id` and optionally `shop_id`.

The vision model output is context only: for example, “likely intake manifold.” It does not overwrite or infer the vehicle fields used to select manuals. Retrieval continues through the existing `search_top_chunk(...)` path, and the final answer uses the existing `format_voice_answer(...)` rules. A missing manual match is a refusal, not a best-effort automotive answer. The endpoint rejects non-JPEG uploads and caps the request at 8 MB; it does not persist the image.

The default provider is NVIDIA Nemotron 3 Nano Omni through NVIDIA's OpenAI-compatible `/v1/chat/completions` endpoint. The adapter sends a JPEG data URL plus text and asks for component context as JSON. `NVIDIA_API_KEY`, `NEMOTRON_MODEL`, and `NEMOTRON_BASE_URL` are environment variables only. An explicit `VISION_PROVIDER=openai` fallback remains available. The model is instructed to return component context as JSON and never return repair facts; those facts must come from George's manual chunk.

### Web-first client

[`frontend/`](../frontend/) is now a minimal Vite/React client for the first demo. It uses an iPhone/browser JPEG capture or file picker, asks for explicit vehicle identity, POSTs multipart form data to `/vision-query`, displays the visual context and answer, and uses browser speech synthesis as the initial audio fallback. In development, Vite proxies `/api` to the local FastAPI server. The Meta CameraAccess sample can later feed the same request contract from a thin native bridge.

`/vapi-tool` remains unchanged and must continue to pass the existing tests.

### Deferred SpacetimeDB option

SpacetimeDB is not used for the current runtime. Qdrant is sufficient for manual retrieval, and the request/session flow remains short-lived. The deferred design for persistent sessions, live multi-device state, or shop workflow is documented in [`docs/spacetime-integration-plan.md`](./spacetime-integration-plan.md), but no SpacetimeDB credentials, client, module, or deployment are required now.

### iOS / glasses

Phase 1 must start from Meta's official sample at:

- Repository: <https://github.com/meta/meta-wearables-dat-ios>
- Sample: <https://github.com/meta/meta-wearables-dat-ios/tree/main/samples/CameraAccess>
- Developer docs: <https://wearables.developer.meta.com/docs/develop/>

The sample's documented lifecycle is the source of truth: connect/register, start device session, start preview, capture photo, stop preview, end session, and disconnect. Preserve its permission handling, lifecycle/background cleanup, error states, firmware/update handling, and attribution/license. Add George-specific networking only after the sample builds and captures a JPEG on the target iPhone.

The current official sample README lists iOS 17.2+, Xcode 26.4+, Swift 6.3+, and a supported Meta AI glasses device for hardware validation. This workspace host currently has no active Xcode developer directory, so no native build has been claimed here.

## Phase gates

1. **Phase 0:** workspace map, integration contract, prerequisites, and repository rules — complete.
2. **Phase 1:** clone/open the official sample, select the team's bundle identifier, build, connect actual glasses, stream preview, and capture a JPEG — blocked locally until Xcode is installed/selected and hardware is available.
3. **Phase 2:** `/vision-query` and the web-first vertical slice — implemented; install dependencies and test with a configured NVIDIA API key plus an ingested local/cloud manual.
4. **Phase 3:** connect the official CameraAccess capture output to the same multipart request contract; the web UI remains the fallback.
5. **Phase 4:** verify an actual audio route to glasses; retain push-to-talk or phone input/audio fallback when the route is unavailable.
6. **Phase 5:** run a full manual-backed demo and document setup without storing user images or credentials.

## Security and safety

- Do not commit API keys, Meta credentials, Vapi secrets, Qdrant credentials, real user images, or local vector stores.
- Treat visual identification as probabilistic context, never proof of year/make/model.
- Do not return torque, safety, part-number, or repair-procedure claims unless the matching uploaded manual chunk supports them.
- Keep uploads bounded and temporary; delete temporary image files after inference.
- Use a request/session ID for correlation, but do not persist raw images by default.

## Phase 1 handoff

The exact on-device run is in [`ios/README.md`](../ios/README.md). Once Xcode is available, the next change should be made by copying or branching the official `CameraAccess` sample into an app target and proving capture first. Do not add George networking until that capture proof is complete.


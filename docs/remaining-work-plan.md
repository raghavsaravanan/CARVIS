# Remaining work plan

George is split into three workstreams. They can proceed in parallel after the shared API contract is kept stable.

## Workstream 1 — Backend and manual retrieval

Owner: backend/data engineer

Goal: prove that George can safely answer from the correct uploaded manual.

### Tasks

1. Verify the local environment in [`backend/.env`](../backend/.env) without printing credentials.
2. Confirm the Qdrant Cloud collection and ingest at least one known service manual.
3. Run the existing backend tests in [`backend/tests/`](../backend/tests/).
4. Smoke test `/health`, `/upload`, and `/vapi-tool`.
5. Smoke test `/vision-query` with a real JPEG and explicit year/make/model.
6. Verify Nemotron returns component context only and never supplies repair facts.
7. Verify missing vehicle/manual matches produce safe refusals.
8. Add an additive `query_id` to `/vision-query` only if the client needs stronger request correlation.

### Done when

- A matching manual returns a concise, source-grounded answer.
- A nonmatching vehicle returns a refusal.
- Existing `/vapi-tool` and `/upload` behavior remains intact.
- No image is persisted after inference.
- Tests and health checks pass.

### Dependencies

- Valid Qdrant credentials.
- At least one correctly tagged service-manual PDF.
- Valid NVIDIA credentials and network access.

## Workstream 2 — Client capture and audio

Owner: client/mobile engineer

Goal: capture the mechanic’s visual context and deliver the answer through the most reliable available audio route.

### Tasks

1. Continue using the web client in [`frontend/`](../frontend/) as the immediate fallback.
2. Install/select Xcode and open Meta’s official CameraAccess sample.
3. Build the sample on an iPhone simulator first.
4. Pair the physical Ray-Ban Meta glasses through the Meta AI app.
5. Verify registration, permissions, device session, preview, and JPEG capture.
6. Preserve the official sample’s lifecycle and error handling.
7. Add a thin networking adapter that sends the captured JPEG to `/vision-query`.
8. Display component context, vehicle context, answer, loading state, and refusal/error state.
9. Verify audio output to the glasses; retain iPhone/browser speech fallback.

### Done when

- The glasses produce a JPEG on the target iPhone.
- The JPEG reaches `/vision-query` with the question and explicit vehicle identity.
- The answer is visible in the app and audible through a verified route.
- The app behaves safely when glasses, network, Nemotron, or manuals are unavailable.

### Dependencies

- Xcode and iOS SDK installed and selected.
- Apple signing team and development iPhone.
- Physical Ray-Ban Meta glasses and Meta AI pairing.
- Workstream 1’s stable `/vision-query` contract.

## Workstream 3 — Integration, demo, and release readiness

Owner: integration/demo engineer

Goal: make the system repeatable, understandable, and compelling during judging.

### Tasks

1. Keep the shared request contract documented in [`docs/architecture.md`](./architecture.md).
2. Run the web flow and native flow against the same `/vision-query` endpoint.
3. Add a deterministic demo vehicle/manual pair with known supported questions.
4. Add visible states for `capturing`, `identifying`, `retrieving`, `answered`, `refused`, and `failed`.
5. Confirm browser/native clients never receive backend secrets.
6. Confirm SpacetimeDB remains absent from the active runtime unless a fundamental multi-device requirement appears.
7. Run focused backend tests and the frontend production build.
8. Test network loss, unsupported image type, missing manual, invalid vehicle identity, and provider failure.
9. Prepare a short demo script and record exact setup commands.
10. Review the repository for secrets, captured images, PDFs, caches, build output, and accidental generated files.

### Done when

- A new teammate can start the backend and frontend from the README.
- The demo succeeds repeatedly with the known manual-backed scenario.
- Failure behavior is safe and visible.
- Tests/builds pass and no secret or user image is tracked.
- The presentation clearly distinguishes visual confidence from manual authority.

### Dependencies

- Workstreams 1 and 2 each have a working vertical slice.
- One stable demo vehicle and manual.
- A reachable backend URL for the iPhone.

## Recommended sequence

```text
Backend smoke test ───────────────┐
                                  ├─ Shared /vision-query contract ── End-to-end demo
Web fallback validation ──────────┘                 │
                                                   ▼
                                Native CameraAccess + audio verification
```

### Immediate next actions

1. Workstream 1: run backend tests and verify one Qdrant-backed `/vision-query` request.
2. Workstream 2: install/select Xcode and prove the official CameraAccess sample captures a JPEG.
3. Workstream 3: choose the exact demo vehicle/manual/question and create the final runbook.

## Scope decision

SpacetimeDB is deliberately out of scope for this implementation. It becomes worth adding only if the demo fundamentally requires persistent multi-device state, shared shop sessions, or a real-time dashboard. If that changes, use the deferred design in [`spacetime-integration-plan.md`](./spacetime-integration-plan.md) without placing it in the answer-critical path.

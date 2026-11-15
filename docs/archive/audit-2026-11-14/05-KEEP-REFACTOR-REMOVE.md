# Keep, refactor, remove, defer/isolate

No files should be deleted during the audit or before the target architecture and PRD are approved. “Not needed for v1” is treated as isolation, not deletion.

## KEEP

| Component | Why it should remain substantially intact | Required guardrails |
| --- | --- | --- |
| `backend/spec_schema.py` | Strong evidence/applicability model, exact decimals, review digest, stable IDs. | Add persistence/reviewer audit around it; preserve compatibility tests. |
| `backend/spec_retrieval.py` | Exact filtering, complete-scope conflict checks, deterministic formatting/refusal. | Put behind `KnowledgeService`; expand tests, do not weaken filters. |
| `backend/qdrant_v2.py` | Non-destructive staging writes and alias safety. | Follow migration runbook; never point writes at alias/legacy. |
| `backend/ingest.py`, `spec_extract.py`, schema JSON | Conservative extraction, hash cache, explicit transcription and pending review. | Move execution behind authorized durable jobs; keep all new records pending. |
| `backend/migrate_v2.py`, `docs/backend/qdrant-v2-migration.md` | Protects legacy collection and controlled cutover. | Require source review and acceptance suite before any production action. |
| `backend/conversation.py` camera correlation and deterministic tool result logic | Good generation/deadline/idempotency behavior with extensive tests. | Separate durable facts from transient futures; preserve route contracts. |
| `ConversationMachine.swift` and tests | Clean pure state machine with 66 passing checks. | Generalize route policy for phone-first and keep glasses mode. |
| `GlassesController`, `CarvisWakeListener`, wake matcher | Valuable official Meta sample-derived work and local tests. | Optional adapter; do not invent SDK lifecycle calls; physical revalidation required. |
| `VisionClient` response handling and Nemotron safety prompt | Explicit vehicle is carried separately; refusal reaches UI; vision is non-authoritative. | Add authentication, shared contracts, and optional camera behavior. |
| SwiftUI design system/onboarding/dashboard components | Polished native foundation and some accessibility/reduced-motion support. | Rewire to real domain/auth state and validate mechanic usability. |

## REFACTOR

| Component | Problem | Incremental target |
| --- | --- | --- |
| `backend/main.py` | 1,936-line composition root with routes, services, providers, globals and legacy paths. | Thin app factory plus route modules and injected services; retain `/vapi-tool`, `/upload`, `/vision-query` contracts during migration. |
| `ConversationStore` | In-memory authoritative state. | Repository-backed conversations/calls/tool executions with optimistic versioning; transient camera wait registry only. |
| iOS root state construction | Root view owns device, account, data and orchestration objects. | `AppContainer`/protocol-based dependencies and feature stores; SwiftUI remains. |
| `AccountStore`, `CarProfileStore`, `ChatHistory`, `JobHistory` | Plain local JSON, one vehicle, no identity/sync/errors. | Auth session in Keychain; API repositories; offline cache with migrations/file protection. |
| `CarvisConversationCoordinator` | 727-line main-actor class combines wake, audio, Vapi, backend, camera, UI, timers. | Separate phone audio, provider call, camera command, session sync, and presentation state; retain pure machine. |
| `VapiAgent` | SDK-specific event and audio assumptions leak into product flow. | `VoiceProvider` protocol with Vapi adapter and transcript/tool lifecycle contract. |
| FastAPI configuration | Import-time globals and permissive defaults. | Typed settings, startup validation, environment-specific config, fail-closed secrets. |
| API schemas | Hand-coded/duplicated contracts. | Versioned Pydantic schemas plus Swift contract tests/generated types where practical. |
| Tests | Good backend focus, limited app/integration/release coverage. | Layered unit/contract/integration/device/evaluation suites in CI. |

## DEFER / ISOLATE

| Exact scope | Why deferred | Isolation boundary | Restore/advance path |
| --- | --- | --- | --- |
| `ios/Carvis/Carvis/Glasses/**` and glasses-specific coordinator effects | Useful, but phone audio is the v1 launch path. | `WearableInput` and `VisionCapture` adapters behind feature flags. | Re-enable per user/device after phone pilot; run official Meta sample and physical acceptance suite. |
| Nemotron image inference and `look_at_part` | Not a launch blocker; adds latency, cost and privacy surface. | `VisionProvider` and optional camera tool. No vehicle/spec authority. | Enable for approved users after image retention/DPA/device tests. |
| `backend/spacetimedb/**` and the removed `frontend/**` | Shop workspace is disconnected from iOS identity and not necessary for Tyler-ready phone pilot. | Separate deployable experiment; no P0 backend dependency. | Decide SpacetimeDB role, authenticate iOS, and add integration tests before reconnection. |
| `ShopStore.swift`, `ShopViews.swift` | Simulated shop crew, not real collaboration. | Development-only feature flag or excluded pilot navigation. | Replace simulation with an approved durable shop model. |
| `MockBackendClient.swift`, guided `RepairSession`/procedure UI | Demonstration workflow contains non-source-backed repair steps. | Development/demo-only build configuration. | Reintroduce only with reviewed procedure evidence and safety UX. |

## REMOVE candidates — only after characterization and approval

### Candidate R-01: duplicate deployment shims

- **Exact files:** `backend/Procfile`, `backend/runtime.txt` (root `Procfile`, `runtime.txt`, and `render.yaml` already drive the root Render layout).
- **Why potentially unnecessary:** the active `render.yaml` uses root-relative commands and root runtime metadata; duplicates can drift.
- **References/consumers:** no repository code references the backend copies; external Render service configuration might still point at them.
- **Tests/docs depending on them:** none found.
- **Functionality lost:** a deployment configured with `backend/` as its root could stop discovering its Procfile/runtime.
- **Safe removal gate:** inspect every Render service setting and deploy logs; consolidate deployment docs; validate a preview deployment.
- **Restore:** recover the two files from Git history or recreate the one-line Uvicorn command/runtime.

### Candidate R-02: retired `backend/purge_db.py`

- **Exact file:** `backend/purge_db.py`.
- **Why potentially unnecessary:** it only exits with a message and performs no operation.
- **References/consumers:** referenced by `docs/backend/architecture.md` and `docs/backend/qdrant-v2-migration.md` as a safety compatibility entry point; no code imports it.
- **Tests/docs depending on it:** no automated test; migration documentation relies on its presence to explain that purge is disabled.
- **Functionality lost:** old operator commands would fail with “file not found” rather than a safe explanatory refusal.
- **Recommendation:** keep through the migration/pilot. Remove only after old runbooks/scripts are proven gone and replace documentation with an explicit prohibition.
- **Restore:** recover from Git; it is nine lines.

### Candidate R-03: generated frontend bindings during regeneration

- **Exact scope:** `frontend/src/module_bindings/**` only if SpacetimeDB remains and bindings become reproducibly generated in CI.
- **Why potentially unnecessary:** generated code creates review noise and can drift from the module.
- **References/consumers:** `frontend/src/spacetimeClient.ts` imports it directly; frontend cannot build without it today.
- **Tests/docs depending on it:** frontend build and runtime.
- **Functionality lost:** all SpacetimeDB TypeScript compilation until regenerated.
- **Recommendation:** do **not** remove now. First document/pin the exact generation command and verify a clean checkout can regenerate byte-equivalent output.
- **Restore:** regenerate from the pinned module/CLI or recover from Git.

## Explicitly not removal candidates

- The legacy Qdrant collection identifier and migration tooling: compatibility and rollback require them.
- Meta glasses and vision code: preserve as future capabilities.
- Existing backend routes and tests: compatibility requirements explicitly protect them.
- Removed `frontend/` and `backend/spacetimedb/`: retain the latter as a separate server-side experiment until the shop decision; absence from v1 is not evidence of dead code.
- Static guided procedure code: potentially unsafe for pilot presentation, but first hide/feature-flag and determine whether reviewed procedure support is desired.

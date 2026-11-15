# Repository inventory and current architecture

## Repository state

- Branch: `main`, tracking `origin/main` at `39b9a7f`.
- Pre-existing working-tree change: `backend/.env.example` is deleted. The audit did not restore or modify it; its tracked `HEAD` content was inspected without displaying any secrets.
- Ignored local secret file: `backend/.env`. It was deliberately not read.
- No `docs/PRD.md` exists in the working tree or in `HEAD`.
- No CI workflow exists under `.github/workflows/`.

## Top-level map

| Path | Actual role | Entry points |
| --- | --- | --- |
| `backend/` | FastAPI API, Vapi tools, Qdrant retrieval, vision adapter, PDF ingestion and migration tooling | `backend/main.py`, `backend/ingest.py`, `backend/migrate_v2.py`, `backend/vapi_assistant.py` |
| `ios/` | Native SwiftUI demo app, local profile/history, Meta glasses camera/speech, Vapi/Daily audio | `ios/Carvis/Carvis/MyApp.swift`, Xcode project |
| `backend/spacetimedb/` | SpacetimeDB shop/profile/invite/query schema and reducers | `backend/spacetimedb/module/src/index.ts` |
| `frontend/` | React/Vite companion vision and shop console, directly connected to SpacetimeDB | `frontend/src/main.tsx`, `frontend/src/App.tsx` |
| `docs/` | Backend, iOS, migration, and prior validation notes | `docs/backend/architecture.md`, `docs/backend/qdrant-v2-migration.md` |
| root deployment | Render single FastAPI service | `render.yaml`, `Procfile`, root `requirements.txt` |

There are no checked-in database migrations for a general application database, no container definition, no release automation, and no root application task runner.

## Backend call paths

### Startup and configuration

`backend/main.py` loads `backend/.env`, initializes FastEmbed, and connects to either Qdrant Cloud or a local Qdrant path during FastAPI lifespan ([`main.py`](../../../backend/main.py#L38-L60), [`main.py`](../../../backend/main.py#L1087-L1139)). Render requires Qdrant credentials, but the default read collection remains the protected legacy identifier unless `CARVIS_QDRANT_COLLECTION` is explicitly changed ([`qdrant_v2.py`](../../../backend/qdrant_v2.py#L17-L21)).

Configuration is import-time global state. There is no typed settings object, environment validation report, environment separation, or dependency injection boundary for providers.

### Typed/photo query

1. iOS `AskView` asks `CarvisConversationCoordinator` to capture a fresh glasses JPEG.
2. `CarvisVisionClient` sends multipart `file`, question, explicit vehicle fields, and a client-generated session ID to `POST /vision-query` ([`VisionClient.swift`](../../../ios/Carvis/Carvis/Backend/VisionClient.swift#L70-L83)).
3. FastAPI validates basic JPEG signature/size and the explicit `Vehicle`.
4. `normalize_request` resolves controlled component/operation/specification slots. Vision runs only if the component is absent, and its hypothesis cannot populate exact authoritative filters ([`main.py`](../../../backend/main.py#L1366-L1381)).
5. `spec_retrieval.lookup` exact-filters reviewed v2 records, enumerates the full scope, validates conflicts/applicability/evidence, then uses embeddings only to rank already-valid candidates ([`spec_retrieval.py`](../../../backend/spec_retrieval.py#L221-L255)).
6. The API returns a deterministic answer/source or a structured 404 refusal.

This route is unauthenticated and accepts caller-supplied `shop_id` and `session_id`.

### Voice conversation

1. Starting a repair job activates `CarvisConversationCoordinator` from `ContentView` ([`ContentView.swift`](../../../ios/Carvis/Carvis/ContentView.swift#L45-L53)).
2. The coordinator requires a configured Vapi agent, a complete local vehicle, and connected glasses before arming wake speech ([`CarvisConversationCoordinator.swift`](../../../ios/Carvis/Carvis/Assistant/CarvisConversationCoordinator.swift#L219-L239)).
3. It creates an unauthenticated server session via `POST /conversation/sessions`; the server returns a random per-session bearer token ([`main.py`](../../../backend/main.py#L1696-L1707)).
4. On wake, the app releases wake listeners, forces a glasses Bluetooth HFP input, starts a backend call generation, and starts Vapi ([`CarvisConversationCoordinator.swift`](../../../ios/Carvis/Carvis/Assistant/CarvisConversationCoordinator.swift#L318-L386)).
5. Vapi invokes `/vapi-tool`. Session-bound tools confirm vehicle, set work context, look at a part, and look up a specification. `lookup_spec` uses the deterministic retrieval formatter and supplies exact speech.
6. A server-side `look_at_part` tool long-polls the phone. The phone captures and uploads a request-correlated photo; stale/duplicate/late results are rejected.
7. The app polls conversation state every 1.5 seconds. Both app and backend state disappear after app/backend lifecycle changes.

The pure `ConversationMachine` is well isolated and locally tested. The surrounding SDK/audio/network coordinator is not part of an XCTest target and has not been validated as a phone-only flow.

### Ingestion and review

1. CLI or unauthenticated `/upload` supplies an explicit PDF plus vehicle metadata.
2. LlamaParse pages are cached by PDF hash and parser configuration; an explicit hash-bound transcription fallback is supported ([`ingest.py`](../../../backend/ingest.py#L90-L128), [`ingest.py`](../../../backend/ingest.py#L129-L169)).
3. Conservative extraction creates schema-v2 pending-review records.
4. `qdrant_v2.upsert_records` validates every embedding, forbids legacy/aliased targets, and preserves previous review decisions on idempotent re-ingestion.
5. `migrate_v2.py` supports export, review, acceptance validation, alias activation, and rollback checks.

The endpoint has no authorization, content-length quota, malware scanning, durable job status, retry queue, or operator review UI. FastAPI background tasks are lost on process exit.

### Vision

`identify_component` uses an OpenAI-compatible client configured for NVIDIA Nemotron by default. The system instruction forbids vehicle identity, numeric specs, procedures, safety claims, and part numbers. The client is reused and time-bounded. Provider calls are tested with fakes only; no live inference ran in this audit.

### SpacetimeDB

The TypeScript module defines user profiles, shops, invitations, vision queries, and query results with sender-scoped views and reducer authorization ([`index.ts`](../../../backend/spacetimedb/module/src/index.ts#L11-L94)). At the time of this audit, the React workspace connected directly and stored identity tokens in browser `localStorage` in `frontend/src/spacetimeClient.ts`. That historical file was removed by the approved native-iOS consolidation.

FastAPI emits best-effort reducer HTTP calls with one server token ([`main.py`](../../../backend/main.py#L63-L83)), whereas reducers derive caller/shop from `ctx.sender`. This does not establish an iOS user's identity and can either fail for an unregistered server identity or attribute all backend events to that identity. The React client separately writes query telemetry under its own identity. These are two competing integration paths.

## iOS application structure

### Startup and state ownership

`MyApp` configures Meta Wearables once and presents `ContentView`. `ContentView` manually constructs six long-lived observable stores/controllers: repair session, glasses, local account, local chat history, simulated shop, and conversation coordinator ([`ContentView.swift`](../../../ios/Carvis/Carvis/ContentView.swift#L7-L33)). This is understandable for a prototype but tightly couples product state and device integrations to the root view.

### User/account data

- `AccountStore`: one local name/mode plus optional server override, serialized to `account.json`.
- `CarProfileStore`: one local vehicle and maintenance profile, serialized to `car-profile.json`.
- `ChatHistory`: up to 50 local typed question/reply pairs in `chat-history.json`.
- `JobHistory`: local repair-job records.

There is no Keychain identity/session, backend account, token refresh, multi-device sync, data export/delete, multi-vehicle list, or server-backed history.

### UI

The app contains polished onboarding, dashboard, vehicle editor, guided mock procedures, ask/result screens, history, shop simulation, and diagnostics. Several repair procedures are static UI demonstrations. They must not be presented as authoritative service instructions; only Qdrant-backed answers have the evidence boundary.

### Voice and hardware

- Meta `MWDATCore`, `MWDATCamera`, and `MWDATSpeech` 1.0.1 are pinned through SwiftPM.
- Vapi and Daily carry live audio.
- Wake detection prefers Meta Speech, then Apple Speech on the glasses Bluetooth microphone.
- The coordinator rejects phone microphone/speaker routes for hands-free calls.
- Background/locked-screen wake is intentionally unsupported.

This preserves valuable glasses work, but it conflicts with the phone-first pilot requirement.

## Tests and validation commands

| Check | Result in this audit | Dependency type | What remains |
| --- | --- | --- | --- |
| `python3 -m pytest backend/tests -q` | **112 passed, 2 failed**, 1 warning; 114 collected | Local fakes/in-memory Qdrant; no paid services | Failures are `ModuleNotFoundError: openai`; real Qdrant/Nemotron/Vapi not tested. |
| Swift compile/run `ConversationMachineTests.swift` | **66 checks passed** | Pure local state machine | No SDK, network, audio route, app lifecycle, or device. |
| Swift compile/run `WakePhraseMatcherTests.swift` | **29 checks passed** | Pure local matcher | No recognition, permission, camera concurrency, or device. |
| `plutil -lint ...Info.plist ...project.pbxproj` | **Passed** | Static syntax | Not an iOS build. |
| `python3 -m compileall -q backend` | **Passed** | Syntax/import compilation | Not runtime/provider validation. |
| `npm run build` in `frontend/` | **Blocked/failed**: `tsc: command not found` | Dependencies absent; not installed by audit | Install from lockfile with approval, then build/test. |
| `xcodebuild ...` | **Blocked**: selected developer dir is Command Line Tools | Full Xcode unavailable | Simulator build, archive, signing, TestFlight, and physical device. |
| SpacetimeDB module build | Not run | CLI/dependencies not established | Local module build and reducer integration tests. |

The historical README claim of “113 backend tests” is stale relative to the currently collected 114, and “passed” is not reproducible on this host without installing the declared `openai` dependency.

## Deployment

`render.yaml` deploys one free-plan FastAPI service in Oregon with Qdrant and Vapi secret variables. It does not configure the NVIDIA key, active v2 collection, SpacetimeDB settings, worker count, persistent application store, structured monitoring, release promotion, or rollback automation. `/health` only reports process liveness and does not check readiness of Qdrant/model/config.

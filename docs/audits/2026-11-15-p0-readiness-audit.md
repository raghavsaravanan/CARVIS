> **Historical snapshot — not current implementation truth.** This audit records the repository as
> observed on 2026-11-15 (after commit `4123a10`, before `d9d40eb`). Counts, statuses and
> "missing" items may be stale; re-verify against the code and tests before relying on them. The
> [PRD](../PRD.md) defines requirements and the
> [V1 Product Experience Contract](../product/v1-product-experience-contract.md) defines pilot
> scope. Provenance and the only edits made to the received text are listed in
> [`docs/README.md`](../README.md#provenance-of-imported-documents).

# CARVIS P0 Readiness Audit

## 1. Executive assessment

CARVIS’s technical voice-to-knowledge core works, but the backend is not complete for Tyler’s TestFlight pilot.

The validated path is real:

> iPhone → Vapi → FastAPI → Qdrant → deterministic verified answer/refusal → spoken response

The remaining work is not primarily UI polish. Significant P0 work remains in:

- Real authentication and backend authorization.
- Durable users, vehicles, conversations, responses, and feedback.
- VIN decoding and a real multi-vehicle Garage.
- Visible source evidence and verification state.
- Rights documentation and explicit knowledge coverage.
- Stable HTTPS deployment, monitoring, privacy, deletion, and release configuration.
- Physical-device interruption, accessory, and failure testing.

Do not rebuild the voice, Vapi, conversation-state, retrieval, verification, or Meta adapter architecture. Those are the strongest parts of the repository.

### Bottom line

CARVIS is suitable for an engineering demonstration with the current operator and narrow WRX corpus. It is not yet safe or complete enough for an independent mechanic TestFlight pilot.

---

## 2. Current architecture

### iOS

The native SwiftUI application owns:

- A shared `CarvisConversationCoordinator`.
- `ConversationMachine` lifecycle rules.
- `VoiceSessionController` for both phone and glasses calls.
- `PhoneAudioRoute` and `MetaGlassesAudioRoute` adapters.
- `VapiAgent` for Daily/Vapi transport and transcripts.
- Optional Meta camera and wake integration.
- Typed vision questions sent to `/vision-query`.

Phone voice is correctly independent of Meta. The prominent “Talk to Carvis” action and global end-call bar are implemented in `ios/Carvis/Carvis/Views/DashboardView.swift:184` and `ios/Carvis/Carvis/ContentView.swift:46`.

Audio behavior is appropriately divided:

- `ios/Carvis/Carvis/Speech/PhoneAudioRoute.swift:7` requests microphone permission and configures `.playAndRecord`/`.voiceChat`.
- It allows speaker, wired, USB, and supported Bluetooth routes.
- It observes route changes and interruptions.
- Vapi/Daily remains responsible for activating the audio session and selecting its active device.
- The microphone stays muted until the route is verified.

### FastAPI

FastAPI is a reasonable modular-monolith boundary and should remain so.

It currently owns:

- Conversation-session generation and Vapi call generations.
- Vapi webhook handling and optional webhook-secret verification.
- Confirmed vehicle context and follow-up memory.
- Tool idempotency and stale callback rejection.
- Camera-command correlation.
- Exact Qdrant retrieval and deterministic verification.
- Safe refusals.
- Optional Nemotron visual context.
- Best-effort SpacetimeDB telemetry.

The important limitation is that conversation state is in one Python process. `backend/conversation.py:307` has a four-hour TTL and maximum 256 sessions. A restart, redeploy, process change, or eviction loses the session.

### CARVIS Brain

The knowledge architecture is substantially stronger than a normal prototype:

- `ingest.py`: PDF hashing, LlamaParse caching, explicit vehicle metadata, staging-only ingestion.
- `spec_extract.py`: conservative atomic extraction and ordered procedure handling.
- `spec_schema.py`: strict evidence schema, quantities, source cells, variants, review metadata and digests.
- `qdrant_v2.py`: deterministic staging upserts and alias-mutation protection.
- `spec_retrieval.py`: exact applicability filters before semantic ranking, complete candidate enumeration, source-digest validation, revision/conflict detection and deterministic formatting.
- `migrate_v2.py`: review export, acceptance checks, activation and rollback workflow.

The live corpus inspected earlier contains 24 WRX records:

- 9 verified.
- 15 pending review.
- One supported vehicle: 2022 Subaru WRX.
- Verified coverage is limited to engine-oil capacity variants and suspension-height measurements/tolerance.

### SpacetimeDB

The retained module contains user/shop tables and authorization-aware reducers, but it is not an active iOS identity or persistence system.

FastAPI only makes optional service-token telemetry calls. Those calls do not establish the end user as the authenticated principal. No iOS client bindings or approved production deployment exist.

### Infrastructure

The successful live call used a temporary public tunnel. That proves the integration, not release infrastructure.

There is currently no evidenced:

- Stable backend hostname.
- Production deployment pipeline.
- Persistent transactional database.
- Operational dashboard or alerting.
- Crash reporting.
- Tested backup/recovery plan.
- TestFlight release configuration.

---

## 3. What the recent phases completed

| Phase | Assessment | Evidence and limitations |
|---|---|---|
| 1 — Regression protection | Substantially complete for the implemented core | Repository verification covered backend, conversation machine, voice controller, phone route policy, wake matching, TypeScript, Apple config, documentation and simulator build. Authentication, persistence and UI navigation naturally have no coverage because they are not implemented. |
| 2 — Voice decoupling | Complete | `VoiceSessionController` depends on injected provider/audio/backend interfaces; Meta is no longer the lifecycle owner. |
| 3 — Native iPhone voice | Implemented; edge cases insufficiently hardware-validated | Built-in iPhone route and live Vapi call passed on iPhone 15. Permission denial, interruption and accessory behavior are mocked/policy-tested, not all physically exercised. |
| 4 — Backend conversation integration | Core complete; production persistence/auth incomplete | Session binding, generation cleanup, cancellation, stale callbacks, context, tool idempotency and camera correlation have automated coverage. Sessions remain memory-only and are not account-authorized. |
| 5 — Physical voice-to-knowledge | Successfully demonstrated in narrow scope | A physical iPhone joined Vapi, bound to FastAPI, used the microphone/speaker, answered supported WRX questions and refused unsupported questions. This is live-provider/user-reported validation, not a formal pilot evaluation. |
| 6 — Optional Meta gating | Implemented but not freshly hardware-regressed | Phone calls do not require Meta. Existing glasses adapters and flows remain. No complete post-change physical glasses regression was recorded. |

Recorded verification evidence from the implementation work:

- 114 backend tests.
- 82 conversation-machine checks.
- 34 voice-session-controller checks after the final lifecycle additions.
- 12 phone-route-policy checks.
- 29 wake-phrase checks.
- SpacetimeDB TypeScript compilation.
- Apple plist/project lint.
- iOS Simulator build.
- Signed physical-device build.
- One successful live phone/Vapi/backend/knowledge path.

Not physically validated:

- Permission-denial recovery after changing Settings.
- Incoming phone-call/Siri/audio interruption recovery.
- Wired headset matrix.
- AirPods and other Bluetooth HFP transitions.
- Speaker/accessory switching during a live call.
- Network handoff and provider outage recovery.
- Background/foreground continuation—the app currently ends phone calls on backgrounding.
- Fresh Meta glasses regression.
- Repeated field use across days or app/backend restarts.

---

## 4. Exact P0 gap matrix

### Identity and workspace

| ID | Requirement | Status | Implementation evidence | Missing work | Priority |
|---|---|---|---|---|---|
| CAR-001 | Secure account registration and sign-in | Missing | Onboarding creates a local `Account`; `ios/Carvis/Carvis/Models/AppStores.swift:5` explicitly says no account server exists. | Identity provider, secure sign-in, token refresh, Keychain storage and backend verification. | Release blocker |
| CAR-002 | Persistent user profile and preferences | Partially implemented | `AccountStore` persists `account.json` locally. Voice preference uses `UserDefaults`. | Authenticated server profile, protected preferences, cross-install/reinstall semantics. | Release blocker |
| CAR-003 | Individual workspace with optional shop affiliation | Partially implemented | Personal/team mode and simulated `ShopStore`; unused SpacetimeDB shop schema. | Durable authenticated workspace and optional membership linked to the principal. | High |
| CAR-004 | Strict user and tenant authorization on backend resources | Missing | Session bearer token protects an individual ephemeral session, but session creation is unauthenticated. `/vision-query` and `/upload` trust caller-provided `shop_id`. | Authenticated principal on all protected APIs, server-derived tenant/vehicle authority and isolation tests. | Release blocker |
| CAR-005 | Account deletion and personal-data management | Missing | `signOut()` only removes the local account object; car/history remain. | Delete/export controls, backend deletion, local cache purge, provider-retention handling and privacy policy. | Release blocker |

### Vehicle management

| ID | Requirement | Status | Implementation evidence | Missing work | Priority |
|---|---|---|---|---|---|
| CAR-010 | VIN entry and format validation | Partially implemented | Free-text VIN field in `ios/Carvis/Carvis/Views/CarProfileEditor.swift:37`. | Length/check-digit/character validation and visible errors. | High |
| CAR-011 | VIN decoding through a supported service | Missing | No decoder client or backend route. | Approved VIN provider, typed response, failure and ambiguity handling. | High |
| CAR-012 | Manual vehicle configuration selection | Partially implemented | Local year/make/model/trim/transmission/wheel fields. | Supported-value selection, engine/market fields where required and backend persistence. | High |
| CAR-013 | Vehicle confirmation before technical lookup | Implemented and validated | `ConversationTools._lookup_spec` refuses before `vehicle_confirmed`; automated tests cover it and the live supported query required confirmation. | Preserve behavior when identity/persistence is introduced. | Preserve |
| CAR-014 | Saved vehicle garage | Partially implemented | One `CarProfileStore` saved as local JSON. | Multiple authenticated vehicles, add/edit/delete and server persistence. | Release blocker |
| CAR-015 | Active vehicle selection and safe context switching | Partially implemented | Backend invalidates dependent memory on vehicle edits; automated correction/switch tests exist. | Multi-vehicle selector, durable history separation and full end-to-end switch test. | High |
| CAR-016 | Ask for unresolved configuration details | Partially implemented | Retrieval detects missing/conflicting transmission, wheel size and other variants and returns clarification/refusal states. | Structured iOS clarification UX and persistence of confirmed configuration. | High |

### Voice and conversation

| ID | Requirement | Status | Implementation evidence | Missing work | Priority |
|---|---|---|---|---|---|
| CAR-020 | Explicitly initiated iPhone voice conversation | Implemented and validated | “Talk to Carvis,” shared lifecycle, simulator build and live physical-iPhone call. | TestFlight/release environment validation. | Preserve |
| CAR-021 | Speech-to-text and spoken responses | Implemented and validated | Vapi transcripts and provider speech; live two-way conversation confirmed. | Retention/privacy decision and formal field measurement. | Preserve |
| CAR-022 | Contextual follow-up questions | Implemented and validated | Backend session memory, `memory_summary`, multi-call tests and confirmed live conversational pipeline. | Durable recovery after backend restart. | High |
| CAR-023 | Clarification for ambiguous requests | Implemented but insufficiently validated | Backend ambiguity and variant handling have automated coverage. | Dedicated iOS state and curated live ambiguity evaluation. | High |
| CAR-024 | Interrupt, stop and restart controls | Partially implemented | Always-accessible end action; Vapi barge-in capability; repeat-call and rapid-tap tests. | Explicitly validate speech interruption, provider stop timing and restart on hardware. | High |
| CAR-025 | Microphone and network failure recovery | Partially implemented | Permission request, route/interruption observers, route recovery state, failure cleanup and mocks. | Physical interruption/accessory/network matrix and actionable retry UI. | Release blocker |
| CAR-026 | Clear listening, processing and speaking states | Partially implemented | Idle, connecting, listening, speaking, reconnecting, ending, ended and failed are event-backed. | Processing, clarification, verified and unsupported presentation for phone calls. | High |
| CAR-027 | Persistent conversation state | Partially implemented | Memory survives repeat calls within a four-hour in-process session. | Durable account-scoped conversations and restart/redeploy recovery. | Release blocker |

### Knowledge retrieval and verification

| ID | Requirement | Status | Implementation evidence | Missing work | Priority |
|---|---|---|---|---|---|
| CAR-030 | Search authorized repair-information sources | Partially implemented | Reviewed Qdrant corpus and safe retrieval are functional. | Document the right to ingest, index, display and speak each pilot source. Do not assume ALLDATA rights. | Release blocker |
| CAR-031 | Apply vehicle configuration filters | Implemented and validated | Exact shop/year/make/model/variant filtering plus Python revalidation. | Maintain negative evaluation set as coverage expands. | Preserve |
| CAR-032 | Match component, operation and specification | Implemented and validated | Controlled normalization and exact filters before ranking. | Expand only with evidence-backed vocabulary and tests. | Preserve |
| CAR-033 | Preserve source identity, location, revision and conditions | Partially implemented | Records preserve file, page, section, table, row, excerpt, hash, conditions and warnings. | Explicit publication revision and usage-rights metadata; durable document lifecycle. | Release blocker |
| CAR-034 | Validate numeric specifications before spoken output | Implemented and validated | Evidence validation plus `ungrounded_numbers()` before exact speech; extensive automated tests and narrow live success. | Curated pre-release safety evaluation. | Preserve |
| CAR-035 | Detect incompatible/conflicting evidence | Implemented and validated | Complete exact-scope enumeration, digest/revision checks and conflict refusal tests. | Expand adversarial test corpus as sources grow. | Preserve |
| CAR-036 | Refuse unsupported answers | Implemented and validated | Deterministic refusal paths; user confirmed unsupported live questions were refused. | Capture/report refusal reasons in pilot metrics. | Preserve |
| CAR-037 | Display source details alongside responses | Partially implemented | FastAPI/tool results carry source data; typed vision UI only says “From the service manual.” | Show actual source title/location/revision/conditions/verification in the CARVIS screen and history. Phone speech currently omits the citation. | Release blocker |
| CAR-038 | Track supported and unsupported coverage | Partially implemented | Qdrant contains queryable status and applicability metadata. | Authenticated coverage reporting, gap definitions and pilot-facing scope disclosure. | Release blocker |

### Conversation history and feedback

| ID | Requirement | Status | Implementation evidence | Missing work | Priority |
|---|---|---|---|---|---|
| CAR-050 | Store conversation metadata and approved response history | Partially implemented | Local `ChatHistory`, local job history and transient server traces. | Durable authenticated metadata, approved response, evidence snapshot and retention policy. | Release blocker |
| CAR-051 | Retrieve past sessions within authorized scope | Missing | Dashboard only shows up to two device-local typed-question entries. | Account-scoped history API and dedicated History destination. | Release blocker |
| CAR-052 | Associate sessions with vehicles | Partially implemented | Active session holds a vehicle; local jobs implicitly use the one local profile. | Durable vehicle/session foreign keys and safe historical switching. | High |
| CAR-053 | Report incorrect or unhelpful responses | Missing | No response feedback control or API. | Feedback UI, authenticated endpoint, evidence/response reference and triage state. | Release blocker |
| CAR-054 | Track response outcomes for internal evaluation | Partially implemented | Timings, refusal codes and optional best-effort Spacetime telemetry exist. | Durable authorized evaluation records, outcome schema and pilot reporting. | High |

### Vision and wearable constraints

| ID | Requirement | Status | Implementation evidence | Missing work | Priority |
|---|---|---|---|---|---|
| CAR-060 | Preserve vision integration behind an interface boundary | Implemented and validated | `VisionClient`, `GlassesController` and optional camera-command loop remain separate from phone voice. | Continue protecting the boundary. | Preserve |
| CAR-061 | Preserve existing glasses development work | Implemented but insufficiently validated | Meta route, wake, camera, correlation and runtime code remain; builds/tests pass. | Fresh physical Meta regression before claiming the glasses path remains operational. | Medium |

---

## 5. CARVIS Brain assessment

### Ready

- Safe staging-only ingestion.
- Structured atomic evidence records.
- Exact vehicle/applicability filtering.
- Review status and evidence-digest enforcement.
- Source-location preservation.
- Conflict and revision-hash detection.
- Deterministic numerical answers.
- Unsupported-question refusal.
- No cross-vehicle fallback.
- Semantic ranking only after exact verification.
- Controlled migration and rollback design.

### Not ready

- Source usage rights are not documented as pilot-approved.
- Coverage is much too narrow to imply general shop utility.
- No durable document registry exists for publication revision, rights, owner and invalidation state.
- Review is a manual CLI/export process.
- No authenticated coverage or evidence dashboard exists.
- The iOS phone experience does not present inspectable source evidence.
- There is no formal supported/unsupported evaluation suite tied to pilot coverage.
- The active backend reads the named collection directly; the planned stable alias lifecycle is not yet the demonstrated release path.

### Minimal CARVIS Brain Dashboard

A small internal, authenticated, read-only dashboard is justified. It should not become a general admin platform.

Minimum views:

- Supported vehicles and required variants.
- Components, operations and specification types per vehicle.
- Verified, pending, rejected, stale and conflicting record counts.
- Source documents, hashes, publication revisions and usage-rights status.
- Evidence drill-down: exact cell/excerpt/page, reviewer, digest and conditions.
- Explicit coverage gaps and negative evaluation cases.

Suggested internal APIs:

- `GET /internal/brain/vehicles`
- `GET /internal/brain/coverage`
- `GET /internal/brain/documents`
- `GET /internal/brain/records/{record_id}/evidence`
- `GET /internal/brain/gaps`

These must require an authenticated internal/admin principal. Qdrant can supply the evidence read model, but document rights and review audit history belong in the transactional database.

---

## 6. iOS/UI assessment

### Real and backend-connected

- Native iPhone Vapi conversation.
- Live transcripts and speaking/listening state.
- FastAPI session/call creation and binding.
- Phone route handling.
- Backend vehicle confirmation and knowledge lookup.
- Safe unsupported answers.
- Typed `/vision-query` when a valid backend and camera path are available.
- Optional Meta camera/wake integration.

### Local-only or simulated

- “Account” and sign-in.
- Personal/team workspace.
- One-car garage.
- Chat history.
- Service history.
- Maintenance schedule.
- User-entered “specs.”
- Shop floor and crew state.
- Guided repair steps.

`ios/Carvis/Carvis/RepairSession.swift:27` defaults to `MockBackendClient`, so the guided oil-change workflow is not the validated CARVIS Brain pipeline.

The default car profile also contains demonstration maintenance values, and the dashboard uses a WRX image regardless of selected vehicle. Those elements should be clearly marked development-only or removed from the pilot surface.

### Navigation gap

The PRD requires:

> Home · Garage · CARVIS · History · Profile

The current app has one long Dashboard inside a `NavigationStack`, with sheets and pushed screens. It does not provide those five principal destinations.

This is a meaningful P0 UX gap, but it should be corrected after the real authenticated data models exist. Building five polished tabs around local JSON demo stores would create rework.

### Evidence-display gap

The backend carries detailed citations, but the phone call UI only exposes call state and transcript. `serverState.grounded_answer.sources` is fetched but not presented.

The typed visual-answer card shows a generic “From the … service manual” label and a visual confidence percentage. It does not show the exact source reference, revision, conditions or verification status required by the PRD.

---

## 7. Security and persistence blockers

1. `/conversation/sessions` is unauthenticated and trusts caller-supplied owner and vehicle data.
2. A session device token protects that one session but is not a user identity or tenant authorization mechanism.
3. `/vision-query` is unauthenticated and accepts caller-supplied `shop_id`.
4. `/upload` is unauthenticated and can trigger ingestion/Qdrant writes using caller-supplied tenant metadata.
5. `VAPI_WEBHOOK_SECRET` is optional in code. Release startup should fail closed if it is absent.
6. Users, vehicles and conversations have no transactional durable store.
7. Local account, vehicle and history JSON files are caches masquerading as authoritative state.
8. Sign-out does not delete local vehicle or history data.
9. Transcript, Vapi provider, logging and diagnostic retention policies are undefined.
10. Conversation traces can include user questions and vehicle context; logging requires privacy review and redaction.
11. No stable release backend, monitoring, alerting, crash reporting or incident procedure is evidenced.
12. SpacetimeDB does not solve these issues in its current unintegrated, service-token telemetry role.
13. Source licensing/usage rights remain unproven.
14. The temporary tunnel and machine-specific base URL cannot be shipped as TestFlight infrastructure.

The currently observed tracked local edits are machine/release-sensitive files:

- `ios/Carvis/Carvis-Info.plist`
- `ios/Carvis/Carvis.entitlements`
- `ios/Carvis/Carvis.xcodeproj/project.pbxproj`

They should be reviewed separately and not swept into a future feature commit. Local Vapi and backend environment files remain excluded from source control.

---

## 8. Tyler readiness checklist

| Tyler experience | Current status |
|---|---|
| 1. Install through TestFlight | Not ready. Signed device builds work, but no verified TestFlight distribution/release environment exists. |
| 2. Sign in | Not implemented. Current onboarding is a local name/mode form. |
| 3. Identify and confirm a supported vehicle | Partial. Manual single-vehicle entry and spoken confirmation work; VIN decode, validation and saved Garage do not. |
| 4. Ask through iPhone audio | Working and live-validated. |
| 5. Receive verified spoken answers with source information | Partial. Verified values are spoken; actual source details are not spoken or shown in the phone experience. |
| 6. Receive explicit refusals | Working and live-validated. |
| 7. Ask contextual follow-ups | Core behavior works and is automated; durable restart recovery is absent. |
| 8. Access appropriate conversation history | Not implemented as authenticated history. |
| 9. Report errors and provide feedback | Not implemented. |
| 10. Demonstrate measurable value | Not yet. Coverage is narrow and the app lacks durable outcome/latency/feedback reporting. |

### Pilot safety blockers

Tyler should not receive the current build as an independent field pilot until:

- Identity and authorization are real.
- The backend is stable and monitored.
- The corpus is documented as rights-cleared.
- Supported coverage is disclosed.
- Source evidence is visible.
- Vehicle and conversation history are durable.
- Feedback and deletion paths exist.
- The physical audio failure matrix is completed.

---

## 9. Remaining roadmap

### A — Must complete before Tyler’s TestFlight

1. Authenticated pilot identity and transactional persistence.
2. Backend principal/tenant enforcement for all protected APIs.
3. Durable users, workspaces, vehicles, sessions, approved responses and feedback.
4. Multi-vehicle Garage with VIN validation/decoding and explicit confirmation.
5. Actual source/evidence display in the CARVIS voice screen and History.
6. Feedback/report-problem workflow.
7. Stable HTTPS deployment, secret management, monitoring and crash reporting.
8. Privacy disclosures, retention policy and account deletion.
9. Rights approval and explicit supported-coverage statement.
10. Physical iPhone permission/interruption/accessory/network test matrix.
11. TestFlight archive/install validation and incident/rollback procedure.

### B — CARVIS Brain preparation

1. Register each pilot document with origin, rights, revision and allowed uses.
2. Freeze a narrow Tyler pilot coverage set.
3. Build supported and adversarial question fixtures.
4. Review remaining pending records against original sources.
5. Add authenticated read-only coverage/evidence APIs.
6. Add a minimal internal Brain Dashboard.
7. Exercise revision invalidation and alias rollback in a non-production environment.
8. Record evidence and refusal metrics without retaining unnecessary personal content.

### C — UI/UX implementation

1. Introduce the five P0 destinations.
2. Keep the CARVIS voice action central.
3. Replace the local fake account flow with real auth state.
4. Connect Garage and History to authenticated backend data.
5. Add ready, processing, clarification, verified and unsupported voice states.
6. Present vehicle/configuration, value, units, conditions, exact source and verification status.
7. Add feedback and support controls.
8. Remove or clearly gate mocked repair/shop surfaces.
9. Preserve accessibility, workshop-sized controls and global end-call access.

### D — Future production platform

- Advanced shop memberships and multiple shops.
- Wider provider integrations after licensing.
- Expanded guided procedures and diagnostics.
- Production SpacetimeDB decision/integration.
- Advanced collaboration and repair-order workflows.
- Broader Meta/wearable capabilities.
- Scale-out architecture only when real load requires it.

Microservices are not warranted. FastAPI plus a transactional store, Qdrant and existing provider adapters is sufficient for the pilot.

---

## 10. Specific next Codex implementation task

### Task: Authenticated pilot account and vehicle vertical slice

This is the next bounded implementation. It fixes the largest trust boundary without touching the working voice or CARVIS Brain pipeline.

#### Scope

Backend:

- Add a provider-agnostic OIDC/JWT principal dependency.
- Add a transactional repository and migrations for:
  - users
  - workspaces/memberships
  - vehicles
  - active vehicle selection
- Require a principal for conversation-session creation and protected conversation APIs.
- Bind every conversation session to the authenticated user/workspace/vehicle.
- Derive tenant and owner authority server-side.
- Preserve `/vapi-tool`, Vapi binding, retrieval and response contracts.
- Make `/upload` internal/admin-only.
- Protect or retire unauthenticated `/vision-query` use.

iOS:

- Add `AuthSession` with Keychain-backed tokens.
- Replace the local onboarding “account” with real sign-in state.
- Add an authenticated Garage data client.
- Send the bearer token through conversation and vision clients.
- Keep existing voice UI and lifecycle unchanged.

Likely files:

- `backend/main.py`
- `backend/conversation.py`
- New `backend/auth.py`
- New persistence/repository and migration modules
- `backend/tests/test_conversation.py`
- New authentication/tenant-isolation tests
- `ios/Carvis/Carvis/Models/AppStores.swift`
- `ios/Carvis/Carvis/Backend/ConversationClient.swift`
- `ios/Carvis/Carvis/Backend/VisionClient.swift`
- New iOS authentication and Garage clients

#### Acceptance criteria

- A user signs in, relaunches, and remains signed in securely.
- The user creates and retrieves a persisted vehicle.
- Two test principals cannot read or mutate each other’s vehicles or sessions.
- Manipulating user, workspace, shop, vehicle or session identifiers cannot cross an authorization boundary.
- Conversation creation rejects unauthenticated requests.
- A Vapi call still starts, binds, answers and cleans up using the existing contract.
- Vehicle changes still invalidate stale conversation context.
- Existing voice, retrieval, verification and refusal tests remain green.
- No provider secret is stored in the app.
- Local JSON becomes a cache/migration source, not authority.
- No guided-repair, Meta or Brain refactor is included.

The prerequisite product decision is selecting the pilot OIDC provider and transactional database deployment. The implementation should use standard OIDC/JWT and repository boundaries so the voice pipeline remains provider-independent.

## Final recommendation

Implement authenticated identity plus durable vehicle ownership next. In parallel, document rights for the narrow WRX corpus.

After that, add durable conversation history, source presentation and feedback, then complete the five-screen P0 navigation around those real models. This moves CARVIS toward Tyler’s first useful field test without wasting time rebuilding the already working Vapi, FastAPI, Qdrant, verification, phone-audio or Meta adapter systems.

This audit was read-only; no repository files, services, Qdrant data, Vapi configuration or infrastructure were modified.
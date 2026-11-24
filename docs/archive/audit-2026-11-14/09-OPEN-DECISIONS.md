# Open decisions requiring owner approval

No cleanup or feature implementation should begin until decisions 1–6 are resolved. Recommended defaults are proposals, not assumed authorization.

| # | Decision requiring approval | Evidence / why it matters | Recommended default | Consequence if deferred |
| ---: | --- | --- | --- | --- |
| 1 | Supply and approve `docs/PRD.md`, including real P0 IDs and Tyler acceptance criteria | The named source does not exist; this audit uses provisional requirements. | Create/restore PRD before implementation and replace `BRIEF-*` rows. | Scope, estimate and “done” remain unverifiable. |
| 2 | Define the authorized automotive data source and pilot corpus | ALLDATA rights cannot be assumed; current evidence scope is tiny. | Obtain written licensed/API/manual rights and start with a narrow named vehicle/question set. | No safe useful pilot, regardless of app progress. |
| 3 | Choose end-user identity approach | iOS account is local-only; API has no user auth. | Standards-based OIDC/JWT with native secure flow and Keychain; choose vendor after cost/privacy review. | Backend cannot enforce user/shop isolation. |
| 4 | Choose the transactional application store | Conversation/history/vehicles need durability; Qdrant is not suitable. | Conventional managed relational store is baseline; time-box SpacetimeDB proof only if its real-time model is strategically desired. | Architecture cannot implement durable identity/context/history. |
| 5 | Approve Vapi for pilot audio and its data processing/retention | Current integration exists, but provider privacy, cost and production terms are not established. | Keep Vapi behind `VoiceProvider`; approve only after DPA/retention/cost review. | Phone-first voice milestone blocked; typed fallback could be separately approved. |
| 6 | Approve phone-first audio behavior | Current product refuses phone audio and requires glasses. | Tap-to-talk/full conversation on iPhone microphone/speaker; Bluetooth headsets allowed; no always-on background wake for v1. | P0-03 remains missing. |
| 7 | Define vehicle identity/applicability fields | Year/make/model may be insufficient for exact specs; VIN data may have licensing/coverage limits. | Require explicit Y/M/M plus relevant variants; optional licensed VIN decode; mechanic confirms normalized vehicle. | Incorrect/ambiguous applicability or excessive refusals. |
| 8 | Define supported technical question taxonomy for pilot | Current controlled vocabulary is narrow; open-ended “repair assistant” is unsafe. | Publish a finite question/component/operation list tied to reviewed evidence and explicit refusal outside it. | Cannot measure coverage or guarantee behavior. |
| 9 | Choose source reviewer authority and workflow | Existing digest proves evidence stability, not reviewer competence or identity. | Named authorized human reviewer; dual review for safety-critical procedures/numbers if practical; auditable decision record. | “Verified” remains a weak operational claim. |
| 10 | Decide whether static guided repair procedures appear in pilot | Current mock steps are not reviewed source evidence and include safety-relevant actions. | Hide guided procedures in pilot until evidence-backed. | Mechanics may mistake demo steps for authoritative guidance. |
| 11 | Approve privacy/retention rules | Audio/transcripts/questions/vehicle/user/image/provider data lack a policy. | No image persistence by default; minimize transcripts; short documented retention; user export/delete; redact logs; provider no-training/retention settings where available. | TestFlight/privacy review and mechanic consent blocked. |
| 12 | Decide SpacetimeDB/shop workspace disposition | Existing module/React app is disconnected from iOS identity and duplicates telemetry ownership. | Defer/isolate through pilot; reassess from shop feedback. | Ongoing dual-architecture complexity and attribution risk. |
| 13 | Decide Meta glasses and Nemotron pilot flags | Valuable work exists, but neither is a launch blocker and both add hardware/privacy failure modes. | Preserve, default off in first phone pilot; enable controlled visual experiment later. | If enabled prematurely, they can obscure core audio/retrieval failures. |
| 14 | Approve deployment environment and operational budget | Current Render free plan and one in-memory worker are demo constraints. | Separate dev/staging/pilot; paid service only after SLO/cost estimate; backups/monitoring and rollback owner. | Cold starts, data loss, capacity and incident response remain unmanaged. |
| 15 | Approve TestFlight ownership | Current project has prototype bundle/team settings; no App Store Connect/release owner is documented. | Organization-controlled bundle ID, Apple team, App Store Connect roles and support owner. | Cannot produce or sustain a pilot build. |
| 16 | Decide local-data migration for existing demo users | Local account/car/history formats exist but have no schema version. | Offer one-time user-reviewed vehicle import; do not upload old chat/job history by default. | Data surprises or accidental sensitive-data transfer. |
| 17 | Approve compatibility sunset criteria | Legacy routes and duplicate paths must be preserved now, but indefinite support increases risk. | Add consumer telemetry without content, document owners, remove only after two releases with zero use and explicit approval. | `main.py` remains coupled; premature deletion could break Vapi/demo flows. |
| 18 | Approve whether prior historical live-validation claims may count for release | Docs report cloud/device checks from 2026-11-07, but this audit did not reproduce them. | Treat them as historical evidence only; rerun relevant gates on the release candidate. | False confidence in environment-specific behavior. |

## Assumptions used by this blueprint

- Tyler is the first real mechanic pilot user; a narrow, reliable scope is preferable to broad unsupported answers.
- The existing Qdrant legacy collection must remain intact and no alias changes are authorized by this audit.
- iPhone foreground audio is sufficient for v1; locked-screen wake is not required unless the missing PRD says otherwise.
- Images are optional context and never vehicle/specification authority.
- A modular monolith is adequate for pilot scale.
- No access to third-party proprietary or confidential resources is needed, and none is permitted without explicit written authorization from its owner.

If any assumption is wrong, update the PRD and architecture decision record before implementation rather than silently adapting during a code change.

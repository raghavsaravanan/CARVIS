# Implementation roadmap to a Tyler-ready TestFlight pilot

This roadmap favors independently reviewable vertical slices. Complexity is relative (`S` days, `M` roughly one to two focused weeks, `L` multi-week or externally dependent) and is **not a delivery commitment**. Uncertainty is high until the missing PRD, identity/store choices and automotive data rights are resolved.

## Milestone 0 — Approve the pilot contract and external gates

- **Objective:** restore/approve `docs/PRD.md`; define Tyler's exact tasks, supported vehicles/questions, success/refusal behavior, data rights, privacy, identity, storage and voice-provider decisions.
- **Why:** implementation cannot be measured without acceptance criteria; useful answers cannot ship without licensed evidence.
- **Dependencies:** owner, Tyler/mechanic input, legal/data-provider confirmation.
- **Requirements:** all provisional `BRIEF-P0-*`, especially P0-04/05.
- **Retain:** existing audit, Qdrant migration safety rules, backend tests.
- **Modify/remove:** no production code.
- **New:** approved PRD, data-processing inventory, pilot corpus manifest, acceptance/evaluation suite.
- **Tests:** desk-review every requirement for unique ID, acceptance criteria and validation class.
- **Definition of done:** no provisional requirement IDs remain; each P0 has owner, acceptance test and dependency; written automotive-data authorization exists or pilot scope explicitly uses other licensed sources.
- **Risks:** external licensing may change product scope.
- **Complexity:** `M`, very high external uncertainty.

## Milestone 1 — Secure phone-first grounded conversation vertical slice

- **Objective:** one authenticated mechanic can onboard, save/confirm one vehicle, start a Vapi conversation using the iPhone microphone/speaker, ask one supported technical question, receive an exact cited answer or deterministic clarification/refusal, and see the durable conversation after restart.
- **Why:** this is the smallest slice that proves the actual pilot rather than the glasses demo.
- **Dependencies:** Milestone 0; approved identity and transactional store; Vapi/privacy approval; one reviewed licensed source slice.
- **Requirements:** P0-01 through P0-07, narrow happy/refusal path; NFR-01/02/03/05.
- **Retain:** `spec_schema.py`, `spec_retrieval.py`, Qdrant v2 rules, Vapi tool contract behavior, `ConversationMachine` concepts, SwiftUI onboarding/design.
- **Modify/isolate:** add authenticated `/v1`; move authoritative conversation facts out of memory; add phone route to coordinator; glasses remain optional/disabled for this slice; protect legacy routes.
- **New:** identity middleware, minimal durable schema/migrations, iOS Keychain session, vehicle/conversation repositories, phone audio adapter, standard knowledge result, CI baseline.
- **Tests:** auth and cross-tenant negative tests; schema migrations; idempotent call/tool tests; server restart/resume; Swift API/persistence tests; phone audio permission/interruption tests; one real reviewed evidence answer and refusal; signed Vapi webhook integration; physical iPhone smoke.
- **Definition of done:** clean checkout CI passes; app works without glasses; restart preserves user/vehicle/conversation; unsupported or ambiguous question refuses; no unauthenticated technical/admin route in the pilot path; citations display; pilot checklist passes on a physical iPhone.
- **Risks:** provider call lifecycle and iOS audio interruptions; data-store choice. Feature-flag and keep corpus narrow.
- **Complexity:** `L`, high uncertainty.

## Milestone 2 — Vehicle and history product completeness

- **Objective:** multi-vehicle save/select/edit/archive, explicit confirmation and safe switching; paginated conversation history and basic settings.
- **Why:** mechanics must not accidentally carry context across vehicles and must recover prior work.
- **Dependencies:** M1 durable identity/store.
- **Requirements:** P0-02, P0-07, P0-08.
- **Retain:** `CarProfile` UI concepts and backend invalidation semantics.
- **Modify/isolate:** replace single local profile authority; migrate old local profile only after user confirmation; keep local cache non-authoritative.
- **New:** vehicle revisions/snapshots, history APIs/views, settings/privacy screen, deletion/export hooks.
- **Tests:** ownership/isolation, switch-during-call, correction invalidation, local migration, pagination, offline/reconnect, accessibility.
- **Definition of done:** a vehicle switch cannot reuse old variants/component/answer; all history is correctly scoped and survives reinstall/sign-in according to policy.
- **Risks:** ambiguous vehicle variants and VIN-provider coverage.
- **Complexity:** `M`, medium uncertainty.

## Milestone 3 — Production knowledge operations and licensed pilot corpus

- **Objective:** authorized, reviewable, revision-aware corpus covering the approved pilot question set.
- **Why:** model UX is irrelevant if source coverage is absent or legally unusable.
- **Dependencies:** licensed source access; reviewer assignment; M0 scope.
- **Requirements:** P0-04/05/06; NFR-01/02/09.
- **Retain:** ingestion/extraction/v2 schema/retrieval/migration code and tests.
- **Modify:** move `/upload` behind admin auth and durable job state; add quotas, file validation, reviewer audit.
- **New:** source document/review/job models, reviewer UI or controlled CLI, coverage report, revision/revocation workflow.
- **Tests:** golden source cases, provenance tamper, conflicting revisions, missing variants, full procedure, job retry/idempotency, unauthorized upload/review, alias acceptance/rollback rehearsal.
- **Definition of done:** every supported answer maps to reviewed licensed evidence; all unsupported cases refuse; named human reviewer and source revision are auditable; migration runbook passes without touching legacy until approved cutover.
- **Risks:** OCR quality, data licensing, manual applicability complexity.
- **Complexity:** `L`, very high external uncertainty.

## Milestone 4 — Reliability, security and observability hardening

- **Objective:** make the vertical slice operationally safe under retries, restarts, abuse and provider failure.
- **Why:** a pilot in a shop cannot depend on one warm process and silent failures.
- **Dependencies:** M1–M3 architecture stable.
- **Requirements:** NFR-03/04/05/06/08.
- **Retain:** camera generation/idempotency ideas and current timing instrumentation.
- **Modify:** typed fail-closed settings; restricted CORS; required webhook verification; sanitized logs; readiness.
- **New:** rate/size/cost limits, structured metrics/traces, alerts, backup/restore drill, retention/deletion jobs, dependency/secret scanning, load and failure tests.
- **Tests:** duplicate/replayed webhook, multi-worker concurrency, restart, Qdrant/provider outage, timeout, network loss, authorization matrix, log redaction, backup restore.
- **Definition of done:** documented SLOs and dashboards; alerts reach an owner; restore rehearsal succeeds; security review has no open critical/high launch findings; data deletion is verified.
- **Risks:** free-tier hosting may not satisfy availability/monitoring needs.
- **Complexity:** `M–L`, medium uncertainty.

## Milestone 5 — TestFlight release candidate and Tyler field trial

- **Objective:** signed, privacy-reviewed internal TestFlight build exercised by Tyler on real jobs within approved scope.
- **Why:** physical audio, noisy-shop usability and trust cannot be proven in unit tests.
- **Dependencies:** M1–M4; Apple team and App Store Connect; support/incident owner.
- **Requirements:** all approved P0s; NFR-07/10.
- **Retain:** native design/accessibility work.
- **Modify/isolate:** release configuration; hide demo procedures/shop/glasses features unless explicitly enabled.
- **New:** XCTest/UI target, archive workflow, privacy manifest/policy, beta feedback/crash process, field-test script and rollback/kill switches.
- **Tests:** clean archive, install/update, permission denial, audio interruption/headset/no headset, poor network, app restart, account deletion, supported/refused question tasks, VoiceOver/Dynamic Type, Tyler usability session.
- **Definition of done:** Tyler completes the approved workflow without developer intervention; every technical answer is cited or refused; no wrong-vehicle carryover; failures are visible/recoverable; release and rollback checklists pass.
- **Risks:** provider latency/audio routing, shop connectivity, trust/usability.
- **Complexity:** `M`, high device/field uncertainty.

## Milestone 6 — Optional glasses and vision reintroduction

- **Objective:** enable Meta capture/wake and Nemotron context without changing the phone-first truth or knowledge boundary.
- **Why:** preserves the original differentiator after the base product is reliable.
- **Dependencies:** successful pilot, approved image/privacy processing, current official Meta docs/SDK support.
- **Requirements:** future capability, not v1 launch.
- **Retain:** Meta camera/speech controllers, wake matcher, correlated camera flow, vision prompt/scrubber.
- **Modify:** adapters and feature flags; remove glasses requirement from core coordinator.
- **Tests:** official sample parity, physical camera/audio concurrency, disconnect/reconnect, image expiry, provider timeout, no visual vehicle/spec authority.
- **Definition of done:** disabling/removing glasses does not affect audio pilot; visual hypotheses never authorize technical values.
- **Risks:** SDK beta/publication policy and physical-device variance.
- **Complexity:** `M–L`, high external uncertainty.

## Milestone 7 — Shop collaboration decision

- **Objective:** validate whether shared shop visibility is valuable, then either productionize or archive the SpacetimeDB/React experiment.
- **Why:** avoid carrying two identity/data architectures without demonstrated pilot need.
- **Dependencies:** Tyler/shop feedback and approved primary identity/store.
- **Requirements:** future shop features.
- **Retain:** reducer authorization ideas and existing workspace for evaluation.
- **Modify/remove:** only after a consumer/reference audit and explicit decision.
- **Tests:** identity propagation, role matrix, tenant isolation, migration, backup/restore, duplicate telemetry.
- **Definition of done:** one authoritative identity and query-history owner; no dual writes/attribution ambiguity.
- **Risks:** architectural duplication and operational burden.
- **Complexity:** `M–L`, high product uncertainty.

## Release gates

No milestone may weaken the reviewed-evidence rules, auto-verify OCR, mutate an aliased collection, or fall back across vehicles. Any Qdrant deployment change must follow `docs/backend/qdrant-v2-migration.md` and preserve the legacy cloud collection.

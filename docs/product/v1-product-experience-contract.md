# CARVIS — V1 Product Experience Contract

**Document revision:** 1.4 · Approved V1 scope; items marked Proposed or Open remain unresolved (1.2, 2026-11-22: §6.5 and gate additions; 1.3, 2026-11-23: the pilot participant is named by role, and D-11 and the matching §7 and §12 entries record their resolution by accepted ADR-0001 and ADR-0002; no decision ID, journey, acceptance criterion, or scope item changed; 1.4, 2026-11-24: owner direction of that date adds the conditional CAR-019 note to J-02 and the validation-stage labels to §6.5; no decision ID, acceptance criterion or scope item changed)  
**Date:** November 15, 2026 (terminology revised November 15, 2026)  
**Purpose:** Define the exact experience to validate whether CARVIS is useful to working automotive technicians before Claude Max designs the canonical multi-tenant platform and before the pilot technician receives an independent TestFlight build.  
**Authority:** CARVIS PRD (document revision 1.1; first drafted Nov 14, 2026); CARVIS P0 Readiness Audit (Nov 15, 2026); historical architecture/consolidation reports; verified phone-to-knowledge demonstration.  
**Status:** Product contract for implementation planning. Proposals and open items are explicitly labeled; this document is not evidence that missing capabilities have been implemented.  
**Terminology:** **V1** is the first complete field-testable CARVIS release, deployed through TestFlight for the pilot technician. Engineering work toward V1 is organized as milestones **M1–M5** (see PRD §6.5), not as separate product versions. **P0** marks requirements mandatory in V1; **P1–P3** are post-V1 priorities with no assigned product version. “Document revision” numbers edits of this contract and is unrelated to V1. Definitions: [`docs/README.md`](../README.md#terminology-and-milestones).

---

## 0. Executive decision

**The only product hypothesis V1 needs to test:** A mechanic can access correct, applicable, source-backed repair information **with less interruption and less elapsed effort** than through their existing shop workflow, and will voluntarily use CARVIS again.

**Product promise:** “Select the vehicle. Ask CARVIS. Hear the verified answer—or a clear reason CARVIS cannot answer.”

**V1 is not a shop-management system.** The V1 pilot is a narrow, trustworthy, voice-first iPhone application with a **preconfigured CARVIS Brain**. Mechanics do not upload manuals, curate evidence, administer users, or manage AI infrastructure. The builder/operator manages the pilot knowledge corpus. The shop owner receives a concise measured pilot review, not a complex management dashboard.

**V1 focus:** Phone-based natural conversation; confirmed vehicle; verified source/citation; correct clarification and refusal; useful follow-ups; durable history; feedback; privacy and secure access. A connected Bluetooth headset may be used as the active call's audio route. **Custom AirPods always-listening wake and Meta glasses remain outside V1.** Meta is presented as “Coming Soon” only if that entry is noninteractive and clear.

**Do not modify the proven voice-to-verification core without a demonstrated necessity.** Preserve Vapi, the VoiceSessionController/ConversationMachine boundary, FastAPI Vapi webhook contracts, Qdrant verification, and optional wearable adapters.

## 1. Decision register

| ID | Decision | State | Reason |
|---|---|---|---|
| D-01 | V1 success is real technician utility, not breadth of platform | **Confirmed by owner direction** | Test the value proposition first |
| D-02 | CARVIS Brain is preconfigured and reviewed by the CARVIS operator | **Confirmed by owner direction** | No PDF administration burden for the pilot technician |
| D-03 | Native iPhone audio is the default, with ordinary supported headsets | **Confirmed / implemented core** | Works without wearables |
| D-04 | Meta glasses appear as “Coming Soon”; no functional dependency | **Confirmed by owner direction** | Concentrate on voice AI |
| D-05 | P0 navigation = Home, Garage, CARVIS, History, Profile | **Specified in PRD** | Simple, mechanic-first navigation |
| D-06 | No owner dashboard, jobs, guided repair, analytics suite or Brain upload UI in V1 | **Proposed default for approval** | Avoid adding untested product complexity |
| D-07 | Shop association can be configured by an operator for the pilot | **Proposed default** | Avoid invitations and manager admin as a first-run obstacle |
| D-08 | V1 uses one transactional application store and server-enforced tenant scope | **Required principle; store accepted: PostgreSQL** (ADR-0001, owner 2026-11-22) | Privacy, durability, isolation |
| D-09 | Brain dashboard is internal/read-only and optional before the technician pilot | **Proposed default** | Coverage can initially be inspected with CLI/report |
| D-10 | Pilot sources must be specifically authorized for CARVIS's intended processing and presentation | **Required by PRD** | ALLDATA subscription is not permission to copy/index |
| D-11 | Provider-agnostic auth contracts; OIDC and database vendors | **Resolved:** database store PostgreSQL (ADR-0001, owner 2026-11-22); OIDC issuer Supabase Auth (ADR-0002, owner 2026-11-23, roadmap D-2); auth contracts stay provider-agnostic | Define experience before implementation |
| D-12 | Duration of conversation history, transcripts, feedback and raw audio retention | **Open policy choice** | Consent, deletion and vendor settings required |

**Change-control rule:** If a proposed default is rejected, change this contract and its entity/API implications **before** asking Claude to implement the database. Do not silently expand V1.

## 2. Users, permissions and commercial audience

### 2.1 Technician (primary V1 user)

Can sign in, maintain their permitted Garage, select/confirm a vehicle, ask CARVIS through iPhone audio, view citations, view own authorized history, provide feedback, configure voice/privacy preferences, and delete/manage their account. Sees only source coverage authorized for their workspace. Never sees Qdrant, LlamaParse, PDF ingestion controls, reviewer tools, or unauthorized shop data.

### 2.2 CARVIS pilot operator (internal role, not technician UI)

Can configure pilot user/workspace access, upload **authorized** documents through existing controlled operational tooling, check document rights, stage data, review evidence, activate approved Qdrant records, define supported vehicles and question categories, investigate feedback, and generate evaluation reports. Must have distinct privileges for review and publishing. Internal functions cannot be exposed by unauthenticated public endpoints.

### 2.3 Shop owner / evaluator (buyer, not required to log into V1)

Observes the pilot technician's demonstration and receives a concise report of real supported-task performance. V1 does not require an owner account, staff roster, assignments, repair orders, billing, or a company dashboard. A real owner account and management workspace may be considered after V1 if demand supports it.

### 2.4 Workspace model

At minimum every user belongs to an isolated personal or pilot shop context. The pilot technician may be associated with a pilot shop by the CARVIS operator; this **does not grant access** to other tenants. Backend authorization derives user and tenant identity from verified credentials and membership—not from caller-supplied `shop_id` or arbitrary identifiers. Preserve account and shop boundaries even with only one pilot shop.

## 3. Mechanic end-to-end journey — the V1 contract

### J-01 — Install, onboard and sign in

**Entry:** The pilot technician installs TestFlight build and opens CARVIS.  
**Flow:** Welcome with concise promise → create account/sign in using approved secure identity flow → choose or see operator-provisioned workspace → see supported-coverage disclosure → request microphone permission only when first needed → land on Home.  
**Visible system state:** signed out / authenticating / signed in / auth failure / connectivity failure.  
**Data:** verified user identity, workspace membership, preferences, consent state and timestamps. Tokens in iOS Keychain; app never stores provider private keys.  
**Acceptance:** app restart retains an authorized signed-in session; sign-out invalidates access and clears protected local caches per policy. Denied microphone permission does not make the app unusable: citation/history and optional typed fallback can remain accessible, subject to actual implementation.

### J-02 — Identify and confirm the vehicle

**Entry:** Home prompts “Which vehicle are you working on?” if no confirmed active vehicle.  
**Flow:** Select saved vehicle, enter VIN, or use manual year/make/model plus required engine, drivetrain, trim, wheel/market/production variants → show resolved configuration → explicit “Use this vehicle” confirmation. VIN decoding is an explicit PRD P0 requirement; a VIN result must not imply every service variant is known.  
**Data:** durable `Vehicle`, owner/workspace, normalized configuration, optional VIN reference, confirmation event, immutable conversation vehicle snapshot.  
**Acceptance:** cannot retrieve vehicle-specific technical values for an unconfirmed or ambiguous configuration. Duplicate or invalid VIN is handled visibly. Switching vehicles ends/invalidates current vehicle-scoped assumptions and stale tool results without deleting prior history.  
**Conditional V1 enhancement (PRD CAR-019, roadmap D-19):** a vehicle described in conversation may become an unconfirmed candidate; it is confirmed only through this journey's explicit in-app confirmation, never by the voice agent.

### J-03 — Start CARVIS voice

**Entry:** Primary prominent “Talk to CARVIS” control from Home and CARVIS tab.  
**Flow:** Confirm eligible vehicle → request microphone if needed → verify selected audio route → create authorized backend conversation/call generation → start existing Vapi transport → unmute only once the route is verified → show live state.  
**Audio:** iPhone mic/speaker default; wired, USB and compatible Bluetooth devices supported as permitted by actual audio route. Do not promise background custom wake, hands-free cold launch, or uninterrupted operation while locked.  
**States:** ready, permission required, connecting, listening, processing, speaking, reconnecting, failed, ending, ended. Always present End Call. No fabricated “connected” status.  
**Acceptance:** phone-only real call works without Meta pairing; cancellation/repeated taps do not create duplicate generations; route loss and network interruptions recover or end safely.

### J-04 — Ask a supported technical question

**Entry:** User speaks an actual question for a preconfigured supported vehicle/procedure.  
**Flow:** Speech → Vapi session/tool request → FastAPI verified session, vehicle context and intent normalization → authorized reviewed CARVIS Brain retrieval → exact applicability and evidence checks → server-final response → spoken answer and evidence card.  
**Evidence card:** specification and unit, vehicle + relevant configuration, condition/exception, source title, page/section/table or other inspectable locator, document revision when available, verification state, feedback action.  
**Acceptance:** no unreviewed numeric spec is spoken as verified; source drilldown is visible; spoken answer and displayed evidence refer to the same verified record/version; no generic model confidence percentage substitutes for provenance.

### J-05 — Clarification and refusal

**Entry:** Missing required vehicle variant, ambiguous request, conflicting specs, missing or unlicensed evidence, or source outage.  
**Flow:** CARVIS asks a specific clarification if resolving it could permit an answer; otherwise explains the supported reason it cannot answer. Preserve the distinction between “not in Brain,” “not applicable to vehicle,” “conflict,” and “service temporarily unavailable.”  
**Acceptance:** no plausible guessed torque, fluid quantity, dimension or procedure. A refusal is a **successful safe product outcome**, but does not count as a successful information lookup in time-savings measurement.

### J-06 — Follow up and switch cars

**Entry:** “What about the rear rotors?” or “Actually this is the other vehicle.”  
**Flow:** Keep confirmed context for follow-up; when changing car, re-confirm new vehicle and clear old vehicle-bound derived facts, requests and generations. Preserve each historical session with its original vehicle snapshot and evidence revision.  
**Acceptance:** adversarial cross-vehicle test cannot reuse incompatible values; backend restart/session recovery follows durable state policy rather than silently returning a different car's answer.

### J-07 — End, return, and review history

**Entry:** mechanic taps End Call or call ends normally.  
**Flow:** provider call closes → backend generation idempotently ends → audio route released → return to Home or CARVIS summary → History lists own prior sessions by vehicle/date → session detail shows question, final answer/refusal, evidence snapshot and feedback.  
**Data:** conversation, call generation, turns or approved summaries, answer outcome, source refs, timestamps, retention state. Raw audio is not retained by CARVIS by default; processor-side handling needs explicit review.  
**Acceptance:** a sign-out/sign-in or app restart recovers permitted history; another user's history is inaccessible.

### J-08 — Report an issue

**Entry:** “Incorrect,” “Not useful,” or “Missing information” on an answer/refusal.  
**Flow:** capture feedback category, linked vehicle snapshot and evidence/response ID; optional short comment; show confirmation. Internal reviewer can triage safely without exposing shop content across tenants. Feedback never automatically promotes a source or modifies a technical specification.  
**Acceptance:** feedback persists and can be counted in the pilot report; sensitive text retention is minimized.

## 4. Exact V1 screen map

**Primary navigation: Home · Garage · CARVIS · History · Profile.** The voice CTA is prominent on Home and central on CARVIS, not a sixth tab.

| ID | Destination/screen | Minimum production behavior | Primary data |
|---|---|---|---|
| P01 | Welcome / sign in | product promise, secure authentication, failure recovery | user session |
| P02 | Coverage disclosure / first-run setup | supported scope, privacy, optional workspace, microphone explanation | coverage version, consent |
| P03 | Home | active confirmed vehicle, call readiness, one obvious Talk CTA, recent authorized session | vehicle, call eligibility, last session |
| P04 | Garage list | saved cars, add/select/edit, empty state | authorized vehicle list |
| P05 | Add / edit vehicle | manual year/make/model/variants, VIN entry/validation/decode | vehicle fields and validation |
| P06 | Vehicle confirmation | explicit applicability attributes, missing-field questions | immutable snapshot intent |
| P07 | CARVIS ready / live | call statuses, transcript, End Call, current vehicle, mic route | live provider/session state |
| P08 | Verified answer | value, units, conditions, exact source, review status, feedback | verified answer + citation |
| P09 | Clarification / refusal / error | reason-specific UX, retry/choose vehicle or source explanation | reason code, prerequisites |
| P10 | History list | sessions grouped by date/vehicle, useful previews | authorized session summaries |
| P11 | History detail | transcript/approved response, citation snapshot, feedback | session, turns, evidence refs |
| P12 | Profile / settings | account, audio/privacy, support, sign-out, delete account | user settings and policy |
| P13 | Feedback sheet | category and optional comment | feedback record |
| P14 | Coming Soon information | Meta glasses explicitly unavailable for pilot | static feature flag only |

**Reusable global states:** initial loading, empty Garage, invalid/ambiguous VIN, wrong vehicle, no reviewed data, pending/conflicting evidence, denied permission, offline/backend error, Vapi failure, audio route lost, interrupted call, expired/revoked login, unavailable history, successful cleanup, and account deletion confirmation.

**Visual direction:** professional automotive workspace, warm-neutral or cool grey surfaces, crisp white cards, near-black voice surfaces, restrained blue identity accents, large thumb/glove-friendly touch areas and clear typographic hierarchy. AllTrails-style ease of navigation and polish; JARVIS-like helpful responsiveness without theatrical sci-fi clutter. Dynamic Type, VoiceOver, low-distraction motion and real workshop noise are first-class. Figma is reference design, not implementation truth; reconcile its broad 84-screen exploration with this smaller P0 contract.

## 5. CARVIS Brain — preconfigured pilot operating model

### 5.1 The pilot is *not* self-serve ingestion

**Operator preflight:** agree with the pilot technician on actual frequent vehicles and lookup categories → obtain specifically rights-cleared documents → register origin/allowed uses/revision → ingest to pending staging via existing tools → compare extracted fields against original pages → approve with reviewer identity → verify conflict/revision behavior → activate approved evidence → run golden positive/negative questions → publish the exact supported coverage description to app. This happens **before** the pilot technician's first independent test.

### 5.2 Brain lifecycle and state

Source document: received → rights checked → parsed → extraction staged → review pending → reviewed/approved or rejected → active/withdrawn/superseded. No “upload succeeded = available to assistant.” Each record retains source hash, page/table/row or excerpt, review digest, vehicle applicability, conditions, revision and reviewer record. Duplicate/re-ingestion cannot silently supersede a reviewer decision; revised sources can invalidate previously valid answers.

### 5.3 Brain dashboard decision

**V1 required:** reliable internal coverage manifest and audit query/report. **Optional only if low risk:** authenticated internal read-only Brain page showing supported vehicles, document rights/revisions, verified/pending/rejected/conflicted counts, evidence drilldown and unanswered-query categories. **V1 not required:** external customer document upload, manager approval flows, automatic provider ingestion, universal automotive catalog, ALLDATA browser extraction or self-serve knowledge configuration.

### 5.4 Pilot coverage disclosure

Publicly show only the supported configurations and categories actually reviewed. A vehicle appearing in Garage does **not** imply its service specifications are available. When data is missing, CARVIS distinguishes the absence of knowledge from a broken service. The repository audit reported **24 WRX records (9 verified, 15 pending) for a 2022 WRX** at audit time; these are not general automotive coverage, and counts must be refreshed before launch.

### 5.5 Rights boundary

The pilot shop uses ALLDATA, but its subscription does not itself establish permission for CARVIS to copy, index, cache, display or speak proprietary content. No scraping or Chrome-extension workaround. If suitable rights-cleared corpus cannot be obtained, **reduce the supported pilot scope or delay independent technical lookup**; do not invent data or silently use unauthorized sources.

## 6. Shop-owner demonstration and evaluation contract

### 6.1 Mechanic demonstration (real-task-first)

Ask the pilot technician to choose representative, authorized, supported questions from their normal repair workflow. Start with a genuinely relevant vehicle; let them use the app unaided. Observe if they find the voice action, whether the response is fast enough, how often clarification is needed, whether they trust citations, and whether they voluntarily repeat usage across different work sessions. Show one *intentional unsupported question* to demonstrate safe boundaries, but do not let scripted refusal dominate the demo.

### 6.2 Shop-owner demonstration (business evidence)

Present one side-by-side supported lookup using the shop's existing process versus CARVIS. Explain that the pilot covers a limited reviewed corpus, not all ALLDATA information. Provide a concise report of verified correctness, support/refusal mix, actual task time, voice completion, repeat usage, feedback, noteworthy failures and estimated total provider costs. Do **not** represent a curated demo as proof of universal utility.

### 6.3 Observation method

- Establish baseline on representative questions in the existing shop workflow; record time from need for information to usable answer.
- Run matched **supported** lookup tasks in CARVIS, with comparable vehicle and source availability; measure elapsed time and interruptions.
- Include deliberate unsupported, wrong-vehicle, missing-variant, conflict and connectivity tests as separate safety scenarios.
- Collect brief post-session usefulness feedback and observe voluntary reuse over multiple sessions/days.
- Record sample size, source/version, environment and limitations. Separate scripted acceptance tasks from genuinely spontaneous questions.

### 6.4 PRD pilot targets (hypotheses, not results)

| Measure | Proposed PRD target | Interpretation |
|---|---|---|
| Verified response correctness | ≥95% on curated supported questions | Evidence checked independently |
| Unsupported numerical answers | 0 in required negative/adversarial tests | Safety gate |
| Source traceability | 100% of answers labeled verified | Inspectable original evidence |
| Lookup time | ≥30% median reduction for matched supported tasks | Usability/value hypothesis |
| Voice task completion | ≥90% supported test interactions | Reliability measure |
| Technician adoption | The pilot technician uses CARVIS voluntarily again | Qualitative product signal |
| Buyer interest | Owner agrees to extend pilot or offers concrete purchasing assessment | Commercial signal |

### 6.5 Pilot technician workflow, proposed pilot coverage and acquisition gates (document revision 1.2, 2026-11-22)

**Workflow traceability.** The pilot technician's November 20 priorities map to PRD §6.1: exact vehicle-specific
specifications (lug-nut torque; brake service limits, rotor or pad to be confirmed) and EPB service
methods → J-04 and P07–P09 (CAR-030–037, CAR-041, CAR-043); manufacturer communications → conditional
CAR-042; Tekmetric shop history → deferred (PRD §16).

**Proposed pilot coverage targets (unconfirmed; D-16).** 3–5 exact vehicle configurations, at least
25 representative lookup tasks, 200–500 reviewed facts, 5–10 complete procedures, and at least 60%
coverage of the agreed representative tasks as a proposed minimum usefulness threshold. These are
planning targets, not quotas or achieved results; every mandatory pilot category needs meaningful
supported examples, and an unmet core task is never hidden by changing the denominator.

Three kinds of criteria stay separate. Separately, every pilot and product evaluation method and result in this
section (§6.1–§6.4 and the pilot utility targets) is labeled with its validation stage (PRD §14.0): S (experience,
real app, possibly labeled synthetic evidence), R (real technical, authorized reviewed evidence) or C (commercial).
Stage S results never satisfy a pilot utility target, a release blocker or an R or C measure. Engineering
validation is not stage-labeled.

- **Engineering validation:** the B7 acceptance cases, the R3 safety suite and the PRD §15.2 checks;
  synthetic fixtures may validate engineering but never support real repair advice.
- **Pilot utility targets:** §6.4 and the coverage targets above; hypotheses until measured.
- **Release blockers:** §10 gates plus these outstanding items: documented rights for every active
  source; a named qualified technical reviewer and publisher (D-17); pilot-technician-confirmed coverage;
  spoken-output integrity validated on staging and devices (D-14); accepted ADRs; Apple Developer
  account and budget; naming clearance before distribution; the pilot technician's and the shop's consent.

**Acquisition gates (all outstanding).** The owner or operator obtains representative tasks and
configurations without unnecessary customer data. The existing 2022 WRX corpus (audit-time 24
records, 9 verified, 15 pending) must be re-audited for counts, source identity, accuracy and
permission; it is not evidence of current coverage or rights. NHTSA vPIC may supply VIN context and
NHTSA datasets may support conditional recall or TSB discovery, subject to their terms and
document-specific rights. Manufacturer documents need affirmative permission to process, store and
present; public availability is not reuse permission. If rights-cleared coverage or qualified
review is insufficient, engineering continues on synthetic fixtures and the independent pilot is
narrowed with the pilot technician's agreement or delayed; limited licensed data (for example MOTOR or ALLDATA) is
an owner decision. No scraping, restricted subscriptions, employer data or web-search fallback.

**Decision after pilot:** Continue, modify focus, or stop. A useful positive signal is not merely a demo that works—it is repeated self-initiated use for actual problems and credible owner interest. Record unmet needs explicitly; these drive post-V1 priorities rather than being added speculatively now.

## 7. Platform and data contract — schema-independent

Design one canonical domain with additive V1 tables and planned post-V1 migrations. **Do not create two unrelated databases.** Qdrant remains a reviewed evidence index, not a source of truth for identity or transactions. FastAPI remains the policy enforcement point. Pick the canonical transactional store only after evaluating migrations, auth integration, backup/recovery, transaction guarantees, operational overhead, and multi-tenant constraints. (Resolved: that evaluation selected PostgreSQL in accepted ADR-0001.)

### 7.1 V1 domain entities and retention responsibilities

| Entity | Owner and key relationships | Essential invariants |
|---|---|---|
| User | verified auth subject | account lifecycle, deletion, consent |
| Workspace / Shop | platform | even one-shop pilot has stable tenant ID |
| Membership | user ↔ workspace | role, active state; principal-based authorization |
| Vehicle | user/workspace owned | normalized configuration, VIN reference, versions |
| VehicleSnapshot | conversation-owned | immutable confirmed applicability at query time |
| Conversation | user + workspace + vehicle snapshot | durable lifecycle, time, version, retention |
| Call | conversation | provider ID, generation, state, idempotency |
| Turn / AnswerOutcome | conversation | final response, refusal/clarification classification |
| EvidenceReference | answer outcome | source ID, revision, page/location, review digest |
| Feedback | user + answer outcome | category, optional text, triage status |
| SourceDocument | Brain internal | rights, owner, hash, revision, validity |
| EvidenceRecord | reviewed knowledge / Qdrant | exact applicability, approved state, provenance |
| ReviewDecision | reviewer + evidence version | identity, decision, time, reason; immutable audit |
| CoverageManifest | internal publication | precise vehicle/categories and revision date |
| UsageEvent | limited internal evaluation | latency/outcome only, no unnecessary audio/text |
| AuditEvent | security and reviewer actions | actor, tenant, operation, time, no secrets |

### 7.2 Access constraints

- iOS supplies a verified user bearer credential, never a trusted `user_id` or `shop_id`.
- FastAPI derives active membership and allowable workspace, validates ownership of every vehicle/session/feedback ID, and creates immutable query vehicle context.
- Vapi webhooks require authenticated/bound call identity, strict tool permissions, replay/idempotency protection and no arbitrary tenant expansion.
- Review and ingestion are internal/admin operations; public `/upload` and `/vision-query` cannot remain unauthenticated in the pilot.
- Tenant-isolation tests must prove that manipulated IDs cannot leak another shop's vehicles, conversations or evidence.
- Approved global evidence versus shop-specific licensed evidence must have explicit access policy; avoid assuming all knowledge is universal.

### 7.3 Data events that shape schema and APIs

| User/operator action | Write/read effect | Security/UX consequence |
|---|---|---|
| Sign in | upsert/get user and membership | bind token to principal |
| Save vehicle | create/version vehicle | authorize owner, validate VIN/config |
| Confirm vehicle | create immutable snapshot | prevent silent context shifts |
| Start call | create conversation/call generation | idempotency, provider binding |
| Ask question | tool execution and outcome | evidence/refusal classification |
| Show verified answer | read exact evidence refs | source traceability required |
| End call | finalize call and turn summary | release resources, safe repeat |
| Open History | list scoped sessions | persistence and pagination |
| Leave feedback | create feedback linked to answer | auditable corrections, no auto-approval |
| Publish Brain source | record review and activation revision | gated and auditable |
| Delete account | revoke identity/access, erase/anonymize policy-defined data | propagate local/provider retention handling |

**Implementation guidance:** Keep route/provider contracts stable or version them. Add actual database tables, indexes and migrations incrementally in a shadow development environment. Tests for restart durability, negative tenant access, idempotency and source revision validity precede the final UI wiring.

## 8. V1 and post-V1 boundaries

| Area | V1: prove mechanic utility | Post-V1 (P1 and later): only after evidence of demand |
|---|---|---|
| Authentication | real secure user + simple workspace | full manager invitations, SSO, multiple organizations |
| Vehicle | VIN/manual identify, Garage, confirmation | repair-order sync, automatic assignments |
| Voice | explicitly initiated iPhone/headset conversation | optional hands-free active-session wake, enhanced device features |
| Knowledge | pre-reviewed rights-cleared Brain corpus | provider agreements/adapters, self-serve review, broad coverage |
| Collaboration | no shop-floor management UI | team feeds, jobs, repair context sharing |
| History/feedback | user scoped, supported source history | shared records, detailed quality investigations |
| Owner value | manually prepared pilot report | authenticated adoption and ROI dashboards |
| Wearables | “Coming Soon,” code preserved | Meta and future devices after physical/privacy verification |
| Platform | one secure modular monolith + transactional DB + Qdrant | scale features justified by measured load |

**Product sequencing:** lock V1 journeys (this contract) → choose auth/store and API contracts (**M1 — Production Architecture**) → build secure durable vertical slice (**M2 — Backend and Database**) → preconfigure Brain and evaluate coverage (**M3 — CARVIS Brain Pilot Configuration**) → wire clean 5-tab interface (**M4 — Native iOS V1**) → run real-device and TestFlight gates (**M5 — Deployment and TestFlight Validation**) → **V1 — Technician Field Test** → decide post-V1 priorities from evidence. M3 may proceed in parallel with M2 once M1 settles the shared contracts; PRD §6.5 is the authoritative milestone definition.

## 9. Failure, safety and privacy acceptance matrix

| Failure/edge case | Required observable outcome |
|---|---|
| No vehicle or unconfirmed variant | request confirmation; don't fetch exact spec |
| VIN ambiguous or decoder unavailable | user can correct/select manually; no inference of missing variants |
| No reviewed evidence | clear unsupported result, never guessed number |
| Conflicting/revised/revoked source | safe refusal or clarification, affected citation flagged |
| Vapi or FastAPI unavailable | explicit retry/end state, no false connected state |
| Microphone permission denied | explain how to enable; no hidden recording |
| Headset disconnect / interruption | revalidate input and output or safely terminate |
| Rapid start/end taps | one active generation; idempotent cleanup |
| Backend restart | durable history retained; call state recovers or ends explicitly |
| User switches vehicles mid-call | old vehicle snapshot invalidated for new lookups |
| Unauthorized resource identifier | return forbidden/not found without leaking data |
| Sign out/delete account | safe termination, secure cache handling, documented deletion |
| Unsupported Bluetooth/background wake expectation | do not advertise absent custom wake functionality |
| Simulated guided repair steps | hidden in pilot; not presented as reviewed instruction |

**Privacy:** Define exactly which transcripts, provider call records, raw audio, images, identifiers and logs are stored, by whom, for how long, and how users can delete them. Raw recording is off by default unless a separately approved product need, permission and retention mechanism exist. Redact secrets and unnecessary speech content from logs.

## 10. Pilot release gates (no false completion)

These gates restate PRD §15 for the V1 field test. They are the completion test for milestones M1–M5; the groups below map approximately to M4 (Product), M2 (Backend/security), M3 (Brain), M5 (Device/release), and the pre-field-test commercial agreements. Finishing a milestone does not by itself satisfy a gate.

**Product:** real sign-in; real Garage + VIN/manual selection; voice; clarification/refusal; inspectable citations; History and feedback; settings/privacy; five primary destinations; optional Meta disabled.

**Backend/security:** authenticated principal and tenant authorization for every protected route; durable data and migrations; signed/bound Vapi tools; secure upload/review boundary; cross-tenant negative tests; restart resilience; secrets and retention policies; monitoring.

**Brain:** documented authorized rights for all active sources; exact scope disclosure; reviewer records; positive and adversarial evaluation; zero unsupported numerical answers on required suite; revision invalidation and recall plan; authoritative-scope acceptance cases ([07-brain.md](../architecture/07-brain.md)).

**Device/release:** actual spoken technical output preserves server-approved facts, units, qualifications and refusals (CAR-041, D-14), or a controlled delivery path is added, or technical voice release is blocked; physical iPhone mic/Bluetooth/interruption/network tests; stable HTTPS host (not Mac+ngrok); app signing/TestFlight install; crash reporting; rollback and incident owner.

**Commercial validation:** The pilot technician has agreed to the test, the shop authorizes the activity, baseline tasks/time are recorded, and a method for feedback/repeat-use measurement exists. PRD targets are not marked achieved before measurement.

## 11. Claude Max engineering handoff instructions

**Inputs:** this contract; the PRD (document revision 1.1); latest Codex audit (the 2026-11-15 P0 Readiness Audit is a historical snapshot, so re-verify against current code); latest local CARVIS repository; existing Figma design exploration. Do not access, copy, transfer or reuse third-party proprietary source code, data, credentials or confidential information (including unreleased product details) without explicit written authorization from its owner; use only authorized architecture patterns.

**First deliverables, before code changes (milestone M1 — Production Architecture):**

1. Proposed entity-relationship diagram covering V1 and planned post-V1 extensions, field dictionary, ownership and tenant-scoping rules.
2. Transactional DB and auth options compared against CARVIS's real operational constraints; explicit single-store decision recommendation.
3. Incremental migrations and compatibility map from current in-memory/local-JSON state.
4. Versioned API contracts for identity, Garage, conversations, citations, history, feedback and internal Brain coverage.
5. Exact P0 feature-to-screen-to-entity-to-endpoint-to-test traceability matrix.
6. Threat model: tenant spoofing, IDOR, webhook replay, unauthorized ingestion, source rights leakage, privacy retention.
7. Phased implementation plan with separate acceptance gates; no big-bang rewrite of voice/retrieval.

**Engineering constraints:** Preserve the validated Vapi → FastAPI → Qdrant verifier, sources/refusal behavior and optional Meta modules. Every change is staged, tested, reversible and measured. No production alias, provider config, credentials or cloud service mutations without separate explicit approval. Do not assume existing screenshots mean backend functionality exists. Do not solve speculative post-V1 needs by expanding the V1 pilot.

## 12. Questions to close before implementation (not blockers to drafting)

| Open point | Recommended default for decision |
|---|---|
| Pilot technician's supported cars/categories | Select with the pilot technician from actual shop work; start small, rights-cleared |
| Identity provider and transactional store | Conventional secure OIDC/JWT plus transactional relational DB preferred; compare SpacetimeDB fairly. **Resolved** by accepted ADR-0001 (PostgreSQL) and ADR-0002 (Supabase Auth as OIDC issuer) |
| Owner access in V1 | No owner login; show observed pilot report |
| Internal Brain dashboard | Minimal read-only optional; CLI/report sufficient if time-critical |
| Transcript/audio retention | Store only approved minimal history; no CARVIS raw audio by default |
| Operator-provisioned shop association | Yes, for initial test; manager invitations later |
| Phone camera photo input | Defer unless it materially improves supported pilot tasks |
| AirPods custom wake | Exclude from TestFlight V1; ordinary headset during call supported where tested |

## 13. Definition of done

**V1 product completeness does not mean every mockup is implemented.** It means the pilot technician can independently install and use the product for specific real repair information tasks, receive sourced answers or safe refusals, change vehicles without leakage, return to their history, provide feedback, and use the app reliably with account/security/privacy protections—without wearing Meta glasses or administering the Brain.

**Pilot success** means observations demonstrate reduced disruption or useful repeat adoption, and the shop owner provides concrete interest or feedback about what would make CARVIS a normal part of the workday. A technically successful scripted demonstration alone is insufficient.

---

## Source basis and precedence

1. **CARVIS PRD (document revision 1.1; first drafted Nov 14, 2026)** — primary product scope, P0 functional requirements, five-tab UX, knowledge licensing, pilot objectives and release gates.
2. **CARVIS P0 Readiness Audit (Nov 15, 2026)** — current local repository state at time of Codex audit, 24-record WRX corpus observation, missing persistence/security/UI functionality, and successful reported physical-iPhone pipeline.
3. **Repository architecture inventories, technical-debt and target-architecture documents (Nov 14, 2026)** — historical engineering constraints and preservation guidance, subordinate to more recent audit and PRD.
4. **Owner's current direction (Nov 15, 2026)** — strictly utility-first pilot, operator-preconfigured Brain, Meta as Coming Soon, post-V1 priorities driven by mechanic and buyer evidence.

**Conflict rule:** PRD and current owner-approved product decisions define desired behavior. Fresh repository tests/audits define implementation truth. An earlier audit or visual prototype never overrides newer verified implementation evidence.

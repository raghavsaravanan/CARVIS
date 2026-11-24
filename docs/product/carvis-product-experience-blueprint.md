# CARVIS Product Experience Blueprint

**Document revision:** 1.0 · 2026-11-24

**Status:** Non-authoritative long-term product vision and evaluation plan. It is not an approved release contract and creates no requirement, scope item, schedule or commitment.

**Repository baseline:** `main` at `e807df7` (PR #27 merged); PRD revision 1.3 and V1 Product Experience Contract revision 1.4

**Owner:** Product/repository owner; acceptance pending

## 1. How to use this blueprint

CARVIS should make authorized automotive information accessible where a technician works. The technician selects and confirms the vehicle, asks naturally, and receives an applicable, source-backed answer or a clear reason CARVIS cannot answer. The technician retains professional judgment. The first commercial validation is one pilot technician and one pilot shop; this public document deliberately does not identify them.

This document is a product strategy and evaluation plan. It does not add to V1 scope, alter an API, accept an ADR, authorize a provider, approve a budget, assign a date or declare a release ready. It exists so current and future collaborators can understand what CARVIS is becoming and why.

### Precedence

This blueprint is subordinate to the following documents, in the order given by the [documentation map](../README.md#authority-and-precedence). Where it disagrees with any of them, they win and this document is corrected:

1. [`AGENTS.md`](../../AGENTS.md) for engineering behavior, safety and trust rules.
2. The [PRD](../PRD.md) (requirements, priorities, release strategy §6, validation stages §14.0, release gates §15) and the [V1 Product Experience Contract](v1-product-experience-contract.md) (approved V1 scope and decision register).
3. Accepted [decision records](../decisions/README.md) (ADR-0001 to ADR-0004 at this baseline) and the owner-accepted [operational decisions](../decisions/operational-decisions.md).
4. The [V1 architecture](../architecture/README.md), the [M2 roadmap](../architecture/12-m2-roadmap.md) and the [traceability matrix](../architecture/11-traceability-matrix.md), which record engineering sequence, open owner decisions and merged status.
5. The code and its tests, for what is implemented.

Task status, schedules and named assignments belong in the separate operating tracker, not here and not in the repository. Do not treat this blueprint as a status ledger. Every status statement below is dated to the baseline above and must be re-verified against current `main`.

### Evidence and change labels

| Label | Meaning in this document |
| --- | --- |
| **Merged requirement** | On `main` in the PRD, the V1 contract, the architecture documents or an accepted ADR. A requirement is not necessarily implemented. |
| **Merged implementation** | Present in `main` code and tests. A prototype does not imply pilot readiness. |
| **Proposal** | Product choice, release theme, target or economic assumption awaiting owner or customer evidence. |
| **Blocked** | An explicit decision, rights, technical, safety, privacy or release gate must be resolved before the named activity. |

At this baseline the PRD is revision 1.3 and the V1 contract is revision 1.4. Main defines V1, milestones M1 to M5 and post-V1 priorities P1 to P3. It does **not** approve post-V1 product versions, names, contents or dates; the future product directions in §6 are planning proposals only. [PR #27](https://github.com/raghavsaravanan/CARVIS/pull/27) is merged: it added principle P-09, the Stage S/R/C validation labels (PRD §14.0), the conditional CAR-019 note, and the vehicle-context design rules for B3 to B5 ([03](../architecture/03-data-model.md), [06](../architecture/06-vapi-ingress.md), [07](../architecture/07-brain.md)). Main's [traceability matrix](../architecture/11-traceability-matrix.md) records B1, B2a, B2b-1, B2b-2 and B2c as merged and B3 onward and the full iOS V1 as not started on `main` at this baseline. Recheck every status claim here after later engineering merges.

## 2. Product promise, users, and boundaries

**Primary user:** professional automotive technician in a noisy, hands-busy shop. **Buyer:** shop owner/manager. **Operator:** CARVIS team member who obtains permitted sources, manages coverage and reviews, investigates safety issues, and prepares the pilot report. V1 does not require an owner account or a technician-facing document upload/admin tool.

The V1 pilot is a native iPhone application with Home, Garage, CARVIS, History, and Profile. The mandatory identification path is saved Garage vehicle, VIN entry/decode, or manual configuration followed by explicit in-app confirmation. A VIN does not settle every service variant. The voice call is explicitly started and can use an ordinary connected headset as its audio route. The Brain is operator configured. V1 needs reviewed, rights-cleared evidence for actual technical answers, complete selected procedures, durable authorized history, feedback, privacy controls, and the PRD §15 release gates. Meta, custom wake listening, repair-order integration, diagnostic autonomy, and shop management are outside mandatory V1.

**Merged requirement (PRD 1.3, contract 1.4, roadmap D-19/D-20):** conversational vehicle identification is only a conditional proposal inside an already confirmed conversation; it cannot create a snapshot or replace in-app confirmation, and its inclusion in V1 remains open under roadmap D-19. The Stage S requirement (controlled evaluation through the real application with isolated, explicitly labeled synthetic evidence) is approved by owner direction, but its serving mechanism remains open under roadmap D-20. The design assumes that no technical answer is released from a prior vehicle context after a switch, and that no synthetic evidence can authorize real repair guidance (principle P-09).

## 3. Experience inventory and journeys

The nine domains describe the intended experience across releases, not nine V1 workstreams. For each row, the journey is the minimum observable interaction to design and test. A capability labeled future is a proposal, not a promise. All technical answers use the common evidence gate in §4.

### E01 — Vehicle Intelligence: know the exact car

| Variant and stage | Concrete technician journey and safe outcome |
| --- | --- |
| Saved vehicle, **V1 required** | Open Garage, choose a saved car, inspect identifying configuration, tap Use this vehicle. Home displays the confirmed car. A stale or archived entry asks for reconfirmation before lookup. |
| VIN typed/decode, **V1 required** | Enter VIN; CARVIS validates format, decodes available attributes, displays any unknown engine/trim/production detail, and asks the technician to complete them before in-app confirmation. An invalid VIN stays editable; decoder outage offers manual entry. |
| Manual selection, **V1 required** | Choose year, make, model and service-relevant variants, see a review screen, confirm. If the needed variant is unknown, a technical request produces a targeted question rather than a guessed value. |
| Vehicle switch, **V1 required** | During a call, select another vehicle. CARVIS ends the old vehicle-scoped conversation/call, requires confirmation for the new car, and starts a new context. A delayed old answer is suppressed; the old history remains attached to its original snapshot. The backend rules are in [03 "Vehicle context rules"](../architecture/03-data-model.md) and [06](../architecture/06-vapi-ingress.md) and are implemented by B3 to B5. |
| Conversational proposal, **conditional CAR-019 / D-19** | In an already confirmed call, say “I am moving to the other car.” CARVIS may show a candidate on the confirmation screen; no spoken claim or model tool changes authority. Without inclusion approval, the user uses Garage. |
| VIN camera recognition, **post-V1 P1 proposal** | Point phone at VIN, review OCR result character by character, correct errors, then confirm. OCR never becomes vehicle authority by itself. |
| License plate lookup, **post-V1 proposal** | With a lawful, authorized provider and shop consent, enter/scan plate, review possible matches, then confirm the actual car. If access/region is unsupported, use VIN/manual entry. |
| Repair-order identification, **post-V1 P1 proposal** | Open an assigned repair order, inspect vehicle and assignment, confirm before technical work. If the RO and physical VIN differ, halt the auto association and ask for correction. |

### E02 — Technical Intelligence: obtain exact facts

| Variant and stage | Concrete technician journey and safe outcome |
| --- | --- |
| Torque and tightening conditions, **V1 supported scope** | Ask for a specific operation on the confirmed vehicle. CARVIS resolves position/component and units, speaks only the reviewed value and conditions, and displays the exact source. An absent condition or conflicting source causes clarification/refusal. |
| Brake service limits and tolerances, **V1 supported scope** | Ask “minimum rear rotor thickness”; CARVIS distinguishes rotor from pad, axle and measurement type, then returns the source-backed limit. “Minimum brake thickness” without enough detail prompts a specific question. |
| Fluid type/capacity, **V1 only where reviewed** | Ask for fluid and quantity; CARVIS confirms system, fill/drain state, and applicable configuration. It refuses a generic capacity when the source describes a different condition. |
| Tools and service specifications, **V1 only where reviewed** | Ask what tool or setting a supported procedure requires. CARVIS shows required tool identity and provenance, without inventing part numbers or substituting “common practice.” |
| Maintenance intervals and references, **future coverage proposal** | Ask when service is due; CARVIS checks duty cycle, mileage/time basis, revision and applicable market. If those are unknown, it asks or reports that coverage is unavailable. |
| Broader licensed catalog, **post-V1 P1 proposal** | Technician asks an ordinary question outside pilot coverage; a rights-cleared adapter may retrieve it only after source review and entitlement checks. Until then, the app says it lacks reviewed coverage. |

### E03 — Procedural Intelligence: support a whole service method

| Variant and stage | Concrete technician journey and safe outcome |
| --- | --- |
| Selected complete procedure, **V1 CAR-043** | Ask for a supported EPB service method. CARVIS checks vehicle applicability, prerequisites, tools, warnings, ordered steps and restoration/verification stages before showing or speaking the whole reviewed method. Missing stages mean refusal, never a partial method presented as complete. |
| Procedure prerequisites/warnings, **V1 within selected coverage** | Before a step is read, CARVIS presents source-backed prerequisites and safety conditions; the technician acknowledges what they need to inspect. CARVIS does not certify the work. |
| Interactive step-by-step, **post-V1 P1 proposal** | Start a reviewed procedure; the technician advances, pauses or repeats steps, and can resume at a confirmed step. A source revision or vehicle change invalidates the in-progress guide and requires revalidation. |
| Procedure continuity and handoff, **post-V1 proposal** | Leave a job mid-procedure; later resume with prior step state clearly labeled as technician-entered. A second technician sees only authorized context and must confirm the current physical state before following guidance. |
| Unsupported “how-to” request, **all stages** | If the Brain has only a fragment or routine tutorial, CARVIS says it cannot provide a complete applicable procedure and points to the normal authorized service source. |

### E04 — Diagnostic Intelligence: investigate without declaring a repair

| Variant and stage | Concrete technician journey and safe outcome |
| --- | --- |
| Known issue, TSB, recall discovery, **conditional CAR-042 or later** | Ask whether a symptom has published communications. CARVIS presents attributed documents and applicability with publication/revision dates. It distinguishes TSB from recall, model-level match from VIN-specific open-campaign status, and a possible issue from a confirmed fault. Without authorized source coverage, it refuses. |
| DTC interpretation, **post-V1 P1 proposal** | Technician enters a code and vehicle; CARVIS explains source-backed definitions and possible tests, states what data is still needed, and does not turn a code into a diagnosis. |
| Symptom investigation, **post-V1 P1 proposal** | Describe a symptom; CARVIS asks discriminating questions, offers reviewed diagnostic branches, and records technician observations separately from verified facts. It stops when evidence is insufficient. |
| Diagnostic decision tree, **post-V1 proposal** | With an approved procedure, CARVIS leads through a conditional test: request measurement, record the technician's value with units/source of measurement, then show the corresponding branch. It never claims it performed the test. |
| Scan-tool integration, **post-V1 P1 proposal** | Import authorized read-only DTC/live data with timestamp and vehicle binding. If the tool disconnects or data is stale, it labels the reading and asks the technician to verify; no autonomous control or clearing of codes. |

### E05 — Historical Intelligence: remember the right history

| Variant and stage | Concrete technician journey and safe outcome |
| --- | --- |
| Conversation and answer history, **V1 required** | Open History, find a prior session by date/vehicle, read the final answer or refusal and the evidence revision captured then. A historical answer is labeled historical and is not automatically reused as current evidence. |
| Previous shop repairs, **post-V1 P1 proposal** | With customer/shop authorization, ask “was this brake job done before?” CARVIS reads the relevant shop record, cites date and recorded work, and distinguishes documentation from physical proof. If no permitted record exists, it says so. |
| Mileage and recurring issues, **post-V1 proposal** | Ask for prior mileage/recurrence; CARVIS shows dated records and inconsistencies, avoids calculating a diagnosis from sparse entries, and lets the technician correct source-system data there. |
| Prior technician observations, **post-V1 proposal** | Read a prior note labeled with author/time and uncertainty. It is never promoted to a verified specification. Access follows shop role and job policy. |

### E06 — Job Intelligence: connect the current repair to records

| Variant and stage | Concrete technician journey and safe outcome |
| --- | --- |
| Assigned repair orders, **post-V1 P1 proposal** | Technician opens assigned jobs from a permitted shop system; CARVIS displays RO identifier, customer-minimized vehicle context and task. A mismatch with the physical car blocks technical lookup until confirmed. |
| Job progress, **post-V1 proposal** | Technician marks inspection, work and verification stages. CARVIS records who asserted each event and time; an answer retrieval is never counted as completed work. |
| Voice notes and measurements, **post-V1 P1 proposal** | Dictate an observation or speak a measurement; CARVIS transcribes it as a draft, shows units and uncertainty, and asks for technician confirmation before saving. It does not claim sensor origin. |
| Job summary, **post-V1 proposal** | At completion, CARVIS drafts a summary of confirmed notes and source-linked answers, visually separates performed work from suggestions, and requires review/edit. |
| Authorized write-back, **post-V1 P1 proposal** | Technician explicitly approves the final summary and destination RO. CARVIS writes through a scoped API, shows success or a retryable failure with duplicate protection, and keeps the shop system as the record of truth. |

### E07 — Visual Intelligence: interpret physical context cautiously

| Variant and stage | Concrete technician journey and safe outcome |
| --- | --- |
| VIN image, **post-V1 P1 proposal** | Capture a still image, review OCR and confirm the vehicle in app; the image is not technical evidence or authority. |
| Component recognition, **post-V1 P2 proposal** | Photograph a component; CARVIS proposes possible identities, asks for context/angle when uncertain, and offers only reviewed information for the confirmed vehicle. An image or model confidence never proves a service fact. |
| Visual inspection and camera question, **post-V1 P2 proposal** | Ask “what am I looking at?” with a still photo; CARVIS describes observed visual features, labels them as visual hypotheses, and cites separate sources for any repair information. It refuses quantitative claims absent reviewed evidence or a validated measurement method. |
| Smart glasses camera, **post-V1 P2 proposal** | Start an explicit capture on supported hardware, review the same evidence/refusal on phone/audio, and stop capture visibly. Test battery, noise, latency and privacy with real devices before a pilot. |
| Reassembly memory / overlays, **P3 research** | Capture opt-in reference images for one task and later retrieve them as user-created memory, with deletion controls. Spatial overlays require display-capable hardware and separate safety validation; camera-only glasses cannot display overlays. |

### E08 — Ambient Intelligence: reach help without adding friction

| Variant and stage | Concrete technician journey and safe outcome |
| --- | --- |
| Explicit iPhone voice call, **V1 required** | From Home/CARVIS, tap Talk, see connecting/listening/processing/speaking states, ask and interrupt, and tap End. A failure shows retry/end, never false “connected.” |
| Ordinary wired/Bluetooth headset route, **V1 when device-tested** | Connect headset before an active call; CARVIS shows the selected audio route. If it disconnects, speech pauses/revalidates or the call ends safely, with no hidden listening. |
| Active-session wake or earbuds shortcut, **post-V1 proposal** | With OS-permitted behavior, invoke CARVIS within an active, consented session; a missed wake or locked phone falls back to explicit tap. No promise of always-listening cold start. |
| Background availability, **post-V1 proposal** | The user explicitly opts in to a supported background session with a visible state and easy stop. OS interruption, battery constraints, and privacy controls are tested before claims. |
| Glasses audio, **P2 proposal** | Pair supported glasses; confirm vehicle and active route on phone, then converse through glasses. Route handoff cannot carry a stale answer to a new car. |
| CARVIS Hub / room presence, **P3 research** | A shop device is proposed only after user demand, privacy design, hardware economics and identity binding. An unauthenticated ambient utterance cannot open a vehicle-scoped technical session. |

### E09 — Shop Intelligence: create organizational value without taking over the shop

| Variant and stage | Concrete technician/owner journey and safe outcome |
| --- | --- |
| Isolated workspace and owner pilot report, **V1** | The operator provisions the permitted context; the technician sees only own authorized vehicles/history. The owner receives a concise measured pilot report outside the app, with limitations and costs. |
| Shared knowledge and collaboration, **post-V1 P1 proposal** | Technician shares a confirmed note or reviewed source with an authorized coworker for a job; recipients see author, date and rights scope. A personal or other-shop record is never silently shared. |
| Shop administration, **post-V1 P1 proposal** | Authorized admin invites/removes a member and manages roles; removal revokes access promptly. The audit records actor/action without transcripts. |
| Integration management, **post-V1 proposal** | Admin connects a permitted shop system, views scopes and last sync, tests read-only access, and can disconnect/delete tokens. A failed sync does not silently erase local history. |
| Operational insight, **post-V1 proposal** | Owner sees aggregate supported usage, time comparisons, refusal categories and spend with small-sample caveats. No raw technician audio or private notes by default. |

## 4. Cross-experience UX, trust, and privacy rules

These rules restate the direction of the PRD (§5, §12) and `AGENTS.md` for design use; those documents govern.

1. **One visible vehicle context.** Show the confirmed car and material variants anywhere technical content appears. Treat each conversation/answer/history record as bound to its original immutable snapshot. A switch ends the old vehicle-scoped call and suppresses in-flight output; the rules are in [03](../architecture/03-data-model.md), [06](../architecture/06-vapi-ingress.md) and [07](../architecture/07-brain.md).
2. **Evidence has a visible shape.** A verified card contains value/steps, units, conditions, vehicle applicability, source title, page/section/table or inspectable locator, revision, and review state. Spoken and displayed technical text must derive from one server-approved outcome. Never use a generic confidence score as proof.
3. **Clarify precisely; refuse plainly.** Ask one actionable question when missing configuration, position, operation or measurement condition can resolve the request. Distinguish unsupported coverage, inapplicability, conflict, revoked source, and service outage. Do not make up a numeric value, procedure, warning, part number or diagnosis.
4. **Voice is central but controllable.** The phone is the default. Expose ready, connecting, listening, processing, speaking, reconnecting, failed and ended states; keep End Call available. Let users read citations and history even when microphone permission is denied, subject to implemented fallback.
5. **Separate fact, observation, hypothesis, simulation, and action.** A technician-entered measurement is a dated observation; a camera model output is a visual hypothesis; a source-backed fact is reviewed evidence. A repair is completed only when a technician confirms it. Every simulation is unmistakably labeled and cannot look like a verified real repair answer.
6. **Preserve professional workflow.** Large, glove-friendly controls; simple navigation; readable text, Dynamic Type, VoiceOver, low-distraction motion, and real workshop noise tests. Do not require a mechanic to administer documents or understand AI infrastructure.
7. **Minimize and isolate data.** Authenticate and authorize every protected read/write from server-derived identity and membership. Collect only task-relevant customer and vehicle fields; no raw audio or continuous image capture by default. Disclose provider handling, consent, retention, export/deletion, and incident paths before field use. Contract D-12 and proposed ADR-0009 retention are unresolved.
8. **Keep systems of record authoritative.** CARVIS may read authorized shop data and draft updates; write-back needs explicit user approval, proper scope, idempotency and audit. Avoid claiming shop records prove actual physical work.
9. **Graceful recovery is part of quality.** On network/provider loss, expired login, denied permission, source withdrawal, or interrupted audio, preserve safe state, explain what happened, and offer an honest retry or exit. Do not replay an answer from an ended call or a different vehicle.

## 5. Implementation and dependency map

The columns below separate code that exists from a product path that can be validated. “Simulated” is only a controlled demonstration or engineering input, never a license to serve real repair guidance.

| Experience/data | Merged main today | V1 path or authorized real dependency | Isolated simulation path | Later integration gate |
| --- | --- | --- | --- | --- |
| Identity and shop scope | B2a JWT verifier; B2b users/workspaces/memberships and forced RLS; B2c GET /v1/me and /v1/workspaces. The iOS app has only the legacy local sign-up and device-token flow; the V1 identity-provider sign-in (CAR-001) is not started. | Supabase Auth/host planned by accepted ADR-0002, plus secure iOS token flow, production provisioning and tenant tests. | Fake JWKS/test principals in local tests only. | Multi-shop roles/invitations require policy and demand. |
| Garage / vehicle | Legacy iOS free-text/single-car demonstration; no durable V1 Garage API. | B3 saved vehicles, VIN validation/decode, manual variants, confirm snapshot; M4 UI. Decoder rights/terms and outage behavior verified. | Synthetic vehicle identities in isolated tests and labeled Stage S only. | VIN camera, plate or RO lookup require permission, accuracy and confirmation. |
| Voice / calls | Existing Vapi → FastAPI legacy conversation state machine and iOS voice controller; Track A hardening (A1 to A6) merged. | B4 durable conversations; B5 authenticated/bound ingress; M4 UI; M5 real-device and spoken-output integrity. Provider gates G-V1 to G-V6 and D-14 apply. | Mock transport and speech tests; Stage S may exercise the actual app only after the D-20 mechanism and isolation. | Wake, background and wearables need OS/device/privacy evidence. |
| Technical evidence / procedures | Legacy reviewed Qdrant v2 verification/refusal tests; no complete new Brain lifecycle in production. | B7a to B7f, M3 rights-cleared corpus, qualified reviewer/publisher, exact scope and safe activation. B7f is the only new serve-path switch. | Synthetic fixtures for engineering; Stage S separate synthetic workspace, permanently simulated labels and no real guidance (D-20; B7a/B7c partition rules). | Licensed broad content needs contractual rights, cost and quality gates. |
| History / feedback | Legacy in-memory/local demonstration; no V1 durable history or feedback UI. | B4 durable state, B6 evidence/history/feedback endpoints, M4 screens, B8 deletion/retention. | Test data in isolated workspace. | Shop repair history needs source-system authority and consent. |
| Diagnostics / shop records | No approved live repair-order, scan-tool or Tekmetric integration. | CAR-042 only if conditional V1 decision (D-18), rights, quality and cost pass; otherwise out of V1. | Labeled synthetic RO/DTC/TSB fixtures in a demo that cannot be mistaken for real advice. | Read-only connector first, tenant/VIN match, rights, security and technical validation; write-back later. |
| Camera / glasses | Preserved prototype vision and optional Meta adapters; V1 functionality is not accepted. | V1 presents Meta as unavailable; B9 secures legacy vision route without adding camera guidance. | Images created/authorized for testing, labeled; no image-derived repair fact. | P2 physical-device, consent and source validation. |
| Operations | B1 health/readiness and baseline migrations; B2 identity foundation. | B10 staging/production, backup/restore, monitoring; M5 TestFlight/device and incident gates. | Local, simulator and staging checks recorded separately from live/production. | Scale only after measured use. |

**Source access ladder:** (1) register permission and intended uses; (2) acquire only permitted content; (3) stage extraction as pending; (4) qualified technical review and separate publication; (5) publish exact coverage; (6) test supported and adversarial cases; (7) activate only after safety/release gates; (8) monitor revision, withdrawal and complaints. An ALLDATA or other shop subscription by itself is not permission to copy, index, cache, display or speak its content. Public web availability is not a reuse license. If rights or review are missing, narrow the real pilot scope or delay independent technical lookup.

**Validation stages (PRD §14.0, merged):** Stage S is a controlled experience evaluation through the real application using explicitly labeled synthetic evidence in a dedicated isolated scope; it proves flow and UX, not real repair utility. Stage R uses authorized, independently reviewed real technical information for the controlled field test. Stage C tests repeat use, buyer willingness, costs and operating fit. These provenance labels do not replace ordinary engineering tests or PRD §15 physical-device, privacy and spoken-output gates, and a Stage S result never satisfies a Stage R or C measure or a §15 gate that needs real evidence. Stage S serving is blocked until D-20 is resolved and the B7a/B7c partition rules are accepted.

## 6. Product directions and decisions

The existing [PRD §6](../PRD.md#6-release-strategy) is the release authority: V1 is defined; P1 is connected shop priority, P2 wearables, P3 research, and no product version number, release name or date is assigned to any post-V1 priority. The four directions below are **future product directions** that group candidate capabilities for discussion. They are descriptive names only: not numbered versions, release names, committed releases, scope or dates, and they cannot become approved merely by appearing in this document or the tracker. Naming or sequencing any release would need an explicit owner decision and a matching amendment of the PRD and [documentation terminology](../README.md#terminology-and-milestones).

| Direction | Candidate user outcome | Candidate domains | Entry evidence and exit gate |
| --- | --- | --- | --- |
| **Technical copilot** (V1, the defined release; shown for reference) | Select and confirm a car, ask by phone, receive verified answer or refusal, review history. | E01–E03 core, E05 conversation history, E08 active phone voice, E09 isolation/pilot report. E04 CAR-042 is conditional. | PRD §15 and contract §10 gates; rights-cleared coverage; real device; pilot consent. No post-V1 feature needed. |
| **Connected repair copilot** (future direction; overlaps P1) | Use authorized service/shop context and broader evidence to reduce repeat entry. | E01 RO identification, E02 catalog breadth, E04 attributed diagnostics, E05 repair history, E09 read-only integration. | V1 pilot shows repeat utility; data/API rights; read-only connector and scope audit; at least one customer validates incremental value and cost. |
| **Repair lifecycle copilot** (future direction; overlaps P1) | Carry confirmed job context and approved notes to the shop record. | E03 guided continuity, E06 jobs/notes/summary/write-back, E09 collaboration/admin. | Connected-repair source-system match reliable; technician review and owner permission; audit, duplicate/retry and rollback tests; paid or concrete purchasing signal. |
| **Multimodal copilot** (future direction; overlaps P2) | Add phone camera and supported glasses without changing evidence authority. | E07 visual, E08 glasses audio, E01 camera VIN. | Physical-device performance, opt-in capture/deletion, no image-as-proof failures, clear device-specific claims. |
| **Ambient intelligence** (research direction; overlaps P3) | Assistance available through validated background/hub patterns where worth the complexity. | E08 ambient/hub, E09 advanced shop insight, E07 memory/possible overlays. | Demonstrated demand, privacy/OS feasibility, hardware economics, safety and support model. |

Before committing any post-V1 capability to a release, the owner should record: problem evidence, customer count and task frequency, rights/access, safety tier, incremental cost, alternative manual workflow, technical owner and an acceptance test. The directions can be reordered or dropped after the V1 evidence review. Nothing here authorizes implementation of a post-V1 capability or changes V1 scope; a post-V1 priority is reopened only by demand, data rights, validation or a concrete V1 blocker (PRD §16).

## 7. Release acceptance and measurement

### V1 gates, inherited rather than redefined

The authoritative release decision is [PRD §15](../PRD.md#15-testflight-release-criteria) and [contract §10](v1-product-experience-contract.md#10-pilot-release-gates-no-false-completion). The launch packet must show: complete five-destination iOS flow; real sign-in/Garage/confirm/voice/citation/history/feedback/privacy; protected routes and tenant tests; rights and reviewer records for every active source; source revision/withdrawal behavior; zero unsupported numerical or wrong-vehicle release in the required safety suite; 100% traceability for verified answers; actual spoken-output integrity; physical iPhone audio/interruption/network checks; stable host, monitoring, rollback, account deletion policy, shop/technician consent, and a documented baseline. A green unit test or Stage S demo cannot stand in for a real device or real evidence gate.

### Evaluation protocol

For each task, record the vehicle/configuration, request category, source rights/revision, supported-scope decision, start-to-usable-answer time for the existing workflow and CARVIS, interruptions, verified/clarified/refused outcome, safety failure, voice completion, technician feedback, and permissible cost metadata. Collect minimal data; do not store unnecessary audio/transcripts. Pre-register supported tasks and independent expected evidence before scoring. Report scripted versus spontaneous tasks, sample sizes, confidence/limitations and excluded tasks. Refusals are safe outcomes but are not successful lookup time savings.

| Measure | Existing PRD working target (§14.3) | Measurement / decision use |
| --- | --- | --- |
| Verified response correctness | At least 95% on curated supported questions | Qualified reviewer independently checks exact value, units, conditions and applicability; report numerator/denominator. |
| Unsupported numerical answers | Zero in required negative/adversarial tests | Hard stop on any unsupported, wrong-vehicle, conflicting or incomplete-as-complete answer; root cause and renewed test before field release. |
| Source traceability | 100% of verified answers | Inspect original rights-cleared source and revision for every scored verified outcome. |
| Lookup time | At least 30% median reduction on matched supported tasks | Same task/vehicle/source availability; record both distributions and sample size, not only a demo median. |
| Voice task completion | At least 90% of supported test interactions | End-to-end device interaction without blocking failure; track noise, route and interruption separately. |
| Repeat use | Voluntary use across multiple work sessions | Count self-initiated task sessions, not only prompted demo usage. |
| Buyer signal | Extended pilot agreement or concrete purchasing assessment | Record buyer's price, purchasing process and conditions; do not call polite interest a sale. |

The coverage thresholds below are the **unconfirmed** D-16 targets already proposed in [contract §6.5](v1-product-experience-contract.md#65-pilot-technician-workflow-proposed-pilot-coverage-and-acquisition-gates-document-revision-12-2026-11-22): at least 25 representative pilot lookup tasks and 3 to 5 exact configurations, with at least 60% coverage of agreed tasks, 200 to 500 reviewed facts and 5 to 10 complete procedures. No denominator may be changed after observing failures to create a pass. A **proposed** Stage S usability criterion: at least 8 of 10 representative task runs can locate confirmed context, distinguish a simulated answer from a verified answer, and reach End Call without help; any simulation misread as real guidance is a stop and redesign. It remains a proposal: it is not in the PRD or the contract, is not an approved acceptance criterion, and would need owner adoption (for example through D-20 or a contract revision) before anyone uses it as a pass criterion. Stage R readiness remains governed by PRD §15, not by it.

For any future direction, use a release-specific scorecard before work begins: task frequency, incremental time saved, verified safety, connector coverage, consent/privacy, weekly active technicians, paid conversion/renewal, support burden, and contribution margin. Do not set universal targets before observing V1 and partner access.

### Failure and privacy acceptance matrix

| Situation | Required observable behavior / test |
| --- | --- |
| No vehicle, ambiguous VIN, or unknown service variant | Ask for explicit in-app confirmation or missing detail; never answer a vehicle-specific value from an assumption. |
| Wrong vehicle, switch during retrieval or playback, call replay | End old context; suppress old content; historical record stays on old snapshot. Test before and after provider retries and backend restart. |
| Missing/unlicensed, conflicting, incomplete, revoked or stale source | Refuse with a distinct reason; no fallback to another vehicle, generic model knowledge, web search or synthetic data. |
| Audio route loss, mic denial, provider/backend outage | Display accurate state; pause/revalidate or end safely; user can retry or read available history. No hidden recording or duplicate call. |
| Cross-tenant ID, revoked membership, expired token | Deny without leaking existence/content; terminate access and protect local caches. Test with manipulated resource IDs. |
| Uploaded/photographed/scan data | Require consent, source rights and minimal retention; image/DTC hypothesis cannot authorize a repair fact. |
| Simulation mode | Durable simulated label on every relevant screen/output and export; isolated synthetic scope; impossible to cite as verified real repair evidence. Test cross-scope negative paths. |
| Account deletion or source withdrawal | Stop access, apply approved retention/export/deletion policy, propagate to relevant processors, and invalidate affected answers/citations. |

## 8. Business model hypotheses and economic controls

A business model **hypothesis** is needed now to decide what to measure; final pricing and channel strategy wait for real utility, rights and cost evidence. The first commercial check is the pilot shop owner after a real-task field test, with the participant's and shop's names kept outside public repository material.

| Assumption to test | Initial hypothesis (not a fact) | Evidence to collect / decision |
| --- | --- | --- |
| Customer, user, buyer | Independent repair shops; technician uses, owner pays. | Observe buyer decision process, budget authority and whether technician value translates to owner value. |
| Core value | Less lookup interruption and elapsed time on exact vehicle-specific facts/procedures. | Matched supported task timing, refusal mix, repeat voluntary use, trust interviews. |
| Revenue | Recurring B2B subscription; compare per-technician seat and per-shop tier. | Ask for a concrete paid pilot/quote after observed use; test usage limits and seats without promising unlimited licensed data. |
| Distribution | Founder-led pilot and referrals before channel partnerships. | Track lead source, demo-to-trial, trial-to-paid, sales cycle and onboarding hours across additional shops. |
| Major variable costs | Licensed content, voice minutes, model calls, transcription, hosting, support and technical review. | Instrument cost per supported/verified answer and per active shop. Proposed ADR-0008 estimates $70 to $150/month platform cost before provider usage, but that ADR is unaccepted and prices require fresh verification. |
| Gross economics | Price must cover direct data/voice/cloud/support cost plus review amortization at actual usage. | Compute monthly contribution margin = recognized subscription revenue − direct variable serving/licensing/support costs; report one-time onboarding/review separately and show sensitivity to low/high usage. |
| Retention | Continued use requires useful coverage and trust, not a polished demo alone. | Cohort weekly active technicians, repeated tasks, renewal intent and reasons for nonuse. |

Do not contact paid providers, buy licenses, configure live accounts or claim access without owner authorization. Commercial readiness additionally needs written data rights, terms for speaking/displaying source content, support/incident ownership, privacy agreements, pricing approved by the owner, and evidence from more than a single curated demonstration.

## 9. Dependency order and open decisions

This section describes dependency logic only. It carries no dates or deadlines; scheduling, capacity and named assignments live in the operating tracker, and a slipped dependency is reforecast there. The engineering sequence of record is the [M2 roadmap](../architecture/12-m2-roadmap.md) and PRD §6.5; its serial-assignment rule for M2 packages still governs.

**Dependency order for V1:** B3 (Garage and snapshots) → B4 (durable conversations) → B5 (bound voice ingress) and B6 (history/feedback) → B7a to B7f (Brain authority and serving gate) together with M3 rights, review and coverage → M4 integrated iOS → M5 release gates → V1 Stage R field test → Stage C commercial assessment → a post-V1 decision from the evidence. M3 rights acquisition and B10 operations may run in parallel where the roadmap allows. R3 retrieval comparison is off the critical path unless a new discovery adapter is chosen. B9 legacy-route migration and SpacetimeDB retirement require their own accepted decisions and are not folded into B3 to B5.

**Contingency principles (from contract §6.5 and the roadmap):**

- If rights or qualified review are missing, narrow the agreed real coverage with the pilot technician's consent or delay independent technical lookup; engineering continues on isolated synthetic fixtures, which never clear a real-evidence gate.
- Stage S results cannot satisfy B7, M5 or the independent pilot gates; if Stage S isolation or labeling fails, stop Stage S and fix it before any further run.
- A mocked route can support design iteration but cannot count as an integrated iOS exit.
- A failed M5 gate extends M5; no independent technical pilot proceeds on it.
- If post-V1 evidence is weak, invest in V1 coverage and reliability rather than naming a release; if an integration is not accessible, keep a manual or narrower path explicitly labeled.

### Decision queue and exact blockers

| Decision or evidence | Needed for | State at baseline |
| --- | --- | --- |
| D-19 inclusion of the conditional conversational proposal (CAR-019) | Any CAR-019 implementation | Owner direction recorded 2026-11-24: manual Garage/VIN plus in-app confirmation is the mandatory baseline; inclusion of the proposal form remains open. |
| D-20 synthetic serving mechanism and partition gate | B7a/B7c design acceptance and Stage S serving | Requirement approved by the owner on 2026-11-24; mechanism open; no synthetic real repair advice. |
| D-4 / contract D-12 / ADR-0009 retention | B8, privacy disclosures, V1 release | Open/proposed. |
| D-8 and D-13 Brain protocol, rights owner and qualified reviewer/publisher (D-17) | B7 and real corpus publication | Proposed or partly owner-directed; no real-scope publication without approval and records. |
| D-9 Vapi provider validation, G-V1 to G-V6, D-14 spoken-output integrity | B5 and M5 technical voice | Direction recorded; live provider call and release validation still require their gates. |
| D-16 confirmed tasks/configurations and pilot/shop consent | M3 coverage plan and real V1 field test | Proposed targets, not confirmed. |
| D-18 conditional TSB/recall inclusion | CAR-042 | Open; not a V1 release gate. |
| Apple account, hosting/backups/ops decisions D-5/D-7, naming clearance, incident owner | M5/TestFlight | Outstanding or proposed. |
| Real connector agreements and buyer evidence | Post-V1 themes | Unverified; no approved post-V1 version plan. |

Roadmap D-numbers and contract D-numbers are separate series; verify the current state of each in the roadmap and contract before relying on this table.

## 10. Collaborator handoff and checklist

**For product/design:** turn each E01–E09 row into a screen/state prototype or research question, prioritizing V1 journeys J-01 to J-08 and failure cases. Do not add deferred functionality to the V1 acceptance list. Record assumptions and customer observations beside each proposal.

**For engineering:** use the PRD, contract, accepted ADRs and M2 roadmap for implementation, and preserve the protected voice/verification/vision boundaries in `AGENTS.md`. This blueprint does not authorize a branch, commit, provider action, production edit or scope change.

**For data/technical review:** build the rights register and coverage manifest; keep source origin, allowed uses, reviewer, publisher, revision, applicability and withdrawal path auditable. Do not publish a real scope from synthetic or unreviewed material.

**For the tracker owner:** keep dates, status and named assignments in the tracker. Link its items to the E01–E09 domains by identifier only, and update it from accepted decisions rather than from this document.

| Checklist item | Status | Remaining action |
| --- | --- | --- |
| E01–E09 inventory and meaningful variants | Drafted | Product owner review of taxonomy and priorities. |
| Concrete journeys, failures and recovery | Drafted | Technician observation and design prototype validation. |
| Cross-experience UX/safety/privacy rules | Drafted against merged V1 contract | Revisit after the retention decision (D-4/D-12). |
| Real/simulated dependency map | Drafted | D-20 mechanism and rights/access evidence. |
| V1 release acceptance/measurable validation | Mapped to authoritative gates | Execute gates; do not mark targets achieved before data. |
| Future product directions | Proposed only | Owner prioritization after V1 evidence; no committed releases, versions or dates. |
| Business model/economics | Hypotheses recorded | Gather real usage cost and buyer purchasing assessment. |

## Source basis (verify before accepting)

- [Documentation map](../README.md): precedence, terminology, M1–M5 and P0–P3 definitions.
- [PRD](../PRD.md): vision, requirement IDs, release strategy, validation stages (§14.0), pilot targets (§14.3), §15 gates and non-goals (§16).
- [V1 Product Experience Contract](v1-product-experience-contract.md): J-01 to J-08, decision register, pilot coverage proposals (§6.5), V1/post-V1 boundaries (§8) and safety/privacy matrix (§9).
- [M2 roadmap](../architecture/12-m2-roadmap.md) and [traceability matrix](../architecture/11-traceability-matrix.md): implementation order, open owner decisions and merged status as of the baseline.
- [Decision records](../decisions/README.md): ADR-0001 to ADR-0004 accepted; ADR-0005 to ADR-0010 proposed at this baseline.
- [Current backend API](../../backend/api_v1/routes.py) and [legacy voice/verification code](../../backend/main.py): current code reality; the `/v1` surface presently exposes only `me` and `workspaces`.
- [PR #27](https://github.com/raghavsaravanan/CARVIS/pull/27) (merged): the 2026-11-24 product reconciliation and bounded B3 to B5 design review; its content now lives in the PRD, contract and architecture documents above.

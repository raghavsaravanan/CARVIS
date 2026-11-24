# CARVIS
## Product Requirements Document
**Conversational Automotive Repair & Visual Intelligence System**

**Document revision:** 1.3 — Draft for Review (revision 1.0: November 14, 2026)
**Date:** November 14, 2026 · terminology revised November 15, 2026
**Product stage:** Hackathon prototype → Field-testable product
**V1:** The first complete field-testable CARVIS release — iOS / Audio-First / TestFlight
**Primary pilot:** Independent automotive repair shop (V1 technician field test)
**Status:** Product requirements proposed; the repository audit was completed on November 15, 2026 (a historical snapshot, see `docs/audits/`); technical design is recorded in `docs/architecture/` and `docs/decisions/`; the open decisions in §18 not marked resolved remain pending

**Revision 1.1** changes terminology only. It adopts the V1 / M1–M5 / P0–P3 conventions below and removes statements that the repository audit had not yet happened. All requirement IDs, priorities, and acceptance criteria are unchanged.

**Revision 1.2** (November 23, 2026) refers to the pilot participant by role ("the pilot technician") instead of by name, and marks the two §18 decisions that accepted decision records have resolved. All requirement IDs, priorities, acceptance criteria, and scope are unchanged.

**Revision 1.3** (November 24, 2026) records the owner's product direction of that date: CARVIS's positioning as a conversational intelligence layer (§2.2), development principle P-09 (§5), validation stages S, R and C as provenance labels (§14.0), and conversational vehicle identification as a conditional V1 enhancement (CAR-019, §7.2, §8.2). V1 scope, existing requirement IDs, priorities, acceptance criteria and §14.3 targets are unchanged.

---

## Terminology

- **V1** is the first complete field-testable CARVIS release, deployed through TestFlight for the pilot technician. "V1" always means this product release. It is a product version, never a document revision.
- **M1–M5** are the engineering milestones that lead to V1. They organize work; they are not product versions. The sequence ends with **V1 — Technician Field Test**. See §6.5.
- **P0** is the priority for requirements that are mandatory in V1. **P1, P2, and P3** are post-V1 priorities. They rank importance only: no product version number, release name, or date is assigned to any of them.
- **Document revision** (for example "1.1" above) numbers edits of this PRD and is unrelated to V1. "v2" in Qdrant and schema documents (`carvis_specs_v2`, specification schema version 2) names a data-schema generation, not a product version.

---

# 1. Executive Summary

CARVIS is an AI-powered automotive copilot designed to give professional technicians immediate access to reliable, vehicle-specific repair information without interrupting their work.

Modern repair shops already possess substantial technical knowledge through service-information platforms, diagnostic tools, and manufacturer documentation. Yet accessing that knowledge often requires a technician to stop working, remove or clean their gloves, locate a computer, navigate service documentation, and manually interpret the results.

CARVIS addresses the gap between **having information and being able to use it at the moment it is needed**.

The long-term product combines natural voice interaction, visual understanding, contextual vehicle intelligence, verified technical information, and wearable computing.

V1 focuses on a smaller, testable proposition:

**A technician identifies a vehicle once, asks CARVIS a technical question through an iPhone, and receives a spoken answer supported by verified, applicable repair information—or an explicit refusal when sufficient evidence is unavailable.**

V1 will validate the intelligence platform, establish a usable application, and generate real mechanic feedback before expanding to smart-glasses workflows.

CARVIS is intended to augment technician expertise, not replace professional judgment.

# 2. Product Vision

## 2.1 Long-Term Vision

Create a context-aware automotive intelligence platform that accompanies technicians throughout the repair process.

A mature CARVIS experience should allow a mechanic to:

- Identify a vehicle automatically through its VIN or connected repair order.
- Ask technical questions naturally without navigating a computer.
- Retrieve exact specifications, procedures, diagrams, and approved technical documentation.
- Show CARVIS a component and ask for identification or relevant service guidance.
- View diagnostic data, procedural steps, and diagrams through supported display-equipped wearables.
- Preserve relevant repair context across conversations.
- Document observations and technician-confirmed work.
- Share appropriate job information with the shop's existing systems.

The mechanic should not need to manage AI models, upload documents, or understand CARVIS's internal architecture.

The product should integrate into established repair workflows rather than create new administrative burdens.

## 2.2 Core Product Proposition

**CARVIS brings verified automotive intelligence to the technician, in the context of the vehicle and task already being worked on.**

CARVIS is a conversational intelligence layer over the repair-information and shop systems technicians already use. The product is designed around the technician experience it should ultimately deliver, not around today's data availability or integration limits; V1 delivers the part of that experience defined in §6.1.

## 2.3 V1 Proposition

For V1, the technician field test deployed through TestFlight:

**Voice-first access to verified, vehicle-specific automotive information through a polished native iOS application.**

V1 must be genuinely useful on an iPhone without requiring Meta glasses, a dedicated shop computer, or a custom hardware appliance.

# 3. Problem Definition

## 3.1 Primary Problem

Automotive technicians frequently interrupt physical repair work to retrieve information already available through existing service-information systems.

These interruptions create:

- Time spent navigating documentation instead of repairing vehicles.
- Repeated switching between physical work and digital systems.
- Difficulty accessing information while hands are occupied or dirty.
- Increased cognitive load when remembering procedures or specifications.
- Potential mistakes when specifications are applied to the wrong vehicle configuration.
- Limited continuity between questions about the same vehicle or repair.

The problem is not simply a lack of information.

It is the difficulty of retrieving **the right information, for the right vehicle, at the right moment**, without breaking the technician's workflow.

## 3.2 Secondary Problem

General-purpose AI assistants can produce plausible technical responses even when they lack valid source evidence.

In automotive repair, incorrect torque specifications, fluid capacities, tightening procedures, or diagnostic instructions may create safety and financial risks.

CARVIS must distinguish between:

1. Understanding a technical question.
2. Retrieving information relevant to that question.
3. Establishing whether the information actually applies to the vehicle.
4. Presenting an answer with appropriate evidence.

Language-model confidence must never be treated as proof of technical correctness.

## 3.3 Opportunity

The initial hypothesis is that a conversational, source-grounded interface can reduce the time and friction required to access repair information.

The pilot must test that hypothesis rather than assume it is true.

# 4. Users and Stakeholders

| User | Primary needs | Priority |
|---|---|---|
| Automotive technician | Fast, reliable answers while performing repairs | Primary |
| Shop owner / manager | Productivity, trust, accountability, reasonable cost | Primary buyer |
| Service advisor | Vehicle context, repair-order coordination | Future |
| Shop administrator | User management, access control, organization settings | Limited in V1 |
| CARVIS operator | Troubleshooting, support, reliability monitoring | Internal |

## 4.1 Primary User: Technician

The technician may be working in a noisy environment, wearing gloves, handling tools, or moving between vehicles.

The application must minimize typing and unnecessary navigation after the initial setup.

The technician should be able to use the product without technical knowledge of AI, embeddings, vector databases, or document ingestion.

## 4.2 Primary Buyer: Shop Owner

The shop owner evaluates CARVIS on outcomes:

- Does it reduce interruptions?
- Does it save measurable time?
- Can technicians trust its answers?
- Is it easy to adopt?
- Does it integrate with existing shop operations?
- Is its cost justified by the value delivered?

The pilot demonstration should answer these questions through observable results rather than technical claims alone.

# 5. Product Principles

**P-01 — Evidence before confidence**

CARVIS must never present an unsupported technical specification as verified. A fluent model response does not constitute evidence.

**P-02 — Vehicle context is mandatory**

Technical answers must be scoped to the applicable vehicle configuration and relevant service conditions.

**P-03 — Minimal technician friction**

After onboarding, common interactions should require as few manual steps as possible.

**P-04 — Voice is an interface, not the intelligence platform**

The knowledge, verification, and context systems must remain usable across phone, glasses, and future interfaces.

**P-05 — Professionals retain control**

CARVIS provides information and guidance. It does not certify repairs, automatically authorize dangerous procedures, or replace technician judgment.

**P-06 — Failure must be explicit**

Missing documents, conflicting data, unsupported vehicles, interrupted connections, and uncertain interpretations must produce clear behavior rather than fabricated answers.

**P-07 — Shop data stays isolated**

Every user, shop, vehicle, and conversation must be protected by appropriate access controls.

**P-08 — Build for extensibility without delaying V1**

Support future vision, wearables, and external data integrations through clear boundaries. Do not build unnecessary infrastructure before it delivers value.

**P-09 — Design the experience. Integrate what we can. Simulate what we cannot. Validate incrementally. Replace simulations with authorized integrations when available.**

Build real application and backend infrastructure, and integrate authorized real data wherever it is available. Where an external integration is unavailable, isolated and explicitly labeled synthetic data may exercise the real application, retrieval and verification pipeline to validate the experience (Stage S, §14.0). Simulated and real technical information stay separated, and synthetic evidence never authorizes repair guidance. Integration boundaries are designed so authorized sources can replace simulations without redesigning the product. Unavailable commercial integrations are not prerequisites for controlled experience validation; real technical use still requires authorized data, qualified review and the §15 gates. This principle does not authorize any deferred capability (§16).

# 6. Release Strategy

## 6.1 V1 — Technician Field Test (P0)

V1 is the first complete field-testable CARVIS release: an audio-first iOS build deployed through TestFlight for the pilot technician. Engineering work toward V1 is organized as milestones M1–M5 (§6.5). The first CARVIS TestFlight build must support:

- Account creation and sign-in.
- Individual mechanic profile.
- Basic shop affiliation where applicable.
- Vehicle identification and confirmation.
- Natural voice conversations through iPhone.
- Vehicle-scoped technical information retrieval.
- Deterministic verification and source provenance.
- Clear clarification and refusal behavior.
- Persistent conversation state.
- Conversation and answer history.
- Basic settings, privacy, and support.
- Operational telemetry and feedback collection.

The pilot may support a limited set of vehicles and specification categories, provided the scope is explicitly disclosed.

**Pilot technician's workflow priorities (discussion of November 20, 2026).** Highest value: exact
specifications that vary by vehicle (for example lug-nut torque and minimum brake service limits,
with rotor versus pad resolved), vehicle-specific electronic parking brake retraction and service
methods, and selected fluids, capacities and tools. Manufacturer communications about known issues
are a conditional V1 enhancement (CAR-042). Previous shop repair history in Tekmetric is deferred
(§16). Routine repair tutorials are lower value. The discussion does not establish data licensing,
a diagnosis, API access or demand at other shops.

## 6.2 Connected Shop Experience (P1, post-V1)

P1 is a post-V1 priority. No product version number, release name, or date is assigned to it. After V1, P1 work may add:

- Authorized repair-order integration.
- Automatic vehicle and technician assignment.
- Expanded licensed technical-information coverage.
- Multiple technicians within a managed shop workspace.
- Shared repair context and authorized shop activity feeds.
- Diagnostic scanner data integration.
- Technician-confirmed repair notes and reports.

## 6.3 Wearable Intelligence (P2, post-V1)

P2 is a post-V1 priority with no assigned product version number, release name, or date. Wearable work targets:

- Supported Meta smart-glasses integration.
- Reliable camera-assisted visual reasoning.
- Glasses-based audio interaction.
- Consistent voice and vehicle session handoff.
- Wearable-specific battery, noise, connectivity, and ergonomics testing.

Camera/audio glasses and display-equipped AR glasses are distinct device classes. Visual overlays must not be promised for hardware that lacks a display.

## 6.4 Future Research (P3, post-V1)

Long-term opportunities include CARVIS Hub, authorized offline knowledge availability, visual disassembly memory, reassembly assistance, live diagnostic overlays, and spatially anchored AR guidance.

These are not prerequisites for V1.

## 6.5 Engineering Milestones to V1

Work leading to V1 is organized as five milestones. They are execution stages, not product versions, and they carry the P0 requirements in §8 to the V1 release gates in §15. The ordering below is the intended sequence; M3 may proceed in parallel with M2 once M1 has settled the contracts both depend on, and M4 builds on the real data models and APIs that M2 delivers rather than on the current local-only demonstration state.

| Milestone | Purpose | Principal scope | Completion is judged against |
|---|---|---|---|
| **M1 — Production Architecture** | Decide and document how V1 will be built before application code changes | Canonical domain model; identity and transactional-database selection; tenant-authorization design; versioned API contracts; migration plan; threat model; requirement-to-screen-to-entity-to-endpoint-to-test traceability; architecture decision records. Open decisions in §18 are recorded here and are approved by the repository owner | Owner-accepted decision records and the deliverables listed in the Product Experience Contract (§11) |
| **M2 — Backend and Database** | Make identity, tenancy, and state durable and authorized | Authenticated principal on protected APIs; durable users, workspaces, memberships, vehicles, conversations, answer outcomes, and feedback; server-derived tenant authority; internal-only ingestion and review; existing voice, verification, and refusal contracts preserved | Identity and workspace requirements (§8.1), conversation persistence and history requirements (CAR-027 in §8.3; §8.5), and the authentication and tenant-isolation items in §15.2 |
| **M3 — CARVIS Brain Pilot Configuration** | Prepare the operator-managed knowledge corpus for the pilot technician's supported scope | Documented usage rights for every source; reviewed, source-bound evidence; explicit supported-coverage definition; positive and adversarial evaluation sets; revision and conflict behavior | Knowledge requirements (§8.4), the knowledge strategy in §10, and knowledge readiness (§15.3) |
| **M4 — Native iOS V1** | Deliver the V1 application experience on real data | Five principal destinations (§9.1); real sign-in; Garage with VIN and manual selection and vehicle confirmation; voice-conversation states; visible source evidence; History; feedback; settings, privacy, and account deletion; Meta glasses shown only as unavailable | Vehicle, voice, and history requirements as presented in the app (§8.2, §8.3, §8.5), UX specification (§9), and product readiness (§15.1) |
| **M5 — Deployment and TestFlight Validation** | Make the build safe to hand to the pilot technician | Stable HTTPS backend; secret management; monitoring and crash reporting; privacy disclosures; physical-device audio, interruption, and network testing; TestFlight archive and install; incident and rollback procedures | Engineering readiness (§15.2) and pilot readiness (§15.4) |
| **V1 — Technician Field Test** | Learn whether CARVIS is useful to a working technician | The pilot technician uses the TestFlight build on real, supported repair-information tasks; results are recorded under §14 | Pilot evaluation and success metrics (§14) |

Scope boundaries and unresolved decisions are not changed by this sequencing. The requirement areas named above are indicative; the M1 traceability matrix records the authoritative milestone for each P0 requirement ID. A milestone that finishes does not mean V1 is ready: only the gates in §15 establish readiness for the pilot technician.

# 7. Core User Experience

## 7.1 Journey A — First-Time Onboarding

**Trigger:** A technician installs CARVIS.

1. The user opens CARVIS and sees a concise introduction to its purpose.
2. The user creates an account or signs in.
3. The application collects only necessary profile information.
4. The user optionally associates with a shop or selects an individual workspace.
5. CARVIS explains its information-coverage limits and evidence-based answer behavior.
6. The user grants microphone access when required.
7. The user reaches the main application.

**Successful outcome:** The user can reach the vehicle-selection and conversation experience without unnecessary setup.

**Failure handling:** Authentication failures, declined microphone permissions, and unavailable services must have recoverable states.

## 7.2 Journey B — Vehicle Identification

**Trigger:** The technician begins work on a vehicle.

The user can identify a vehicle through:

- VIN entry.
- Camera-assisted VIN recognition where supported.
- Manual year/make/model/engine selection.
- A previously saved vehicle.
- *Conditional V1 enhancement (CAR-019):* a vehicle described in conversation, proposed as a candidate that the technician confirms in the app like any other identification.

CARVIS decodes or resolves the available vehicle information and shows a confirmation screen.

The user confirms the vehicle before receiving vehicle-specific technical answers.

Where the VIN does not establish a required engine, drivetrain, trim, production date, or service configuration, CARVIS must ask for clarification.

**Successful outcome:** CARVIS establishes an active, explicit vehicle context.

**Failure handling:** Invalid, incomplete, or ambiguous vehicle identities must not silently resolve to an assumed configuration.

## 7.3 Journey C — Technical Voice Question

**Trigger:** The technician starts a conversation and asks a question.

Example:

*"What's the minimum brake rotor thickness on this vehicle?"*

CARVIS:

1. Captures and interprets the request.
2. Determines the requested component, operation, and specification type.
3. Associates the request with the active vehicle.
4. Requests clarification if required.
5. Retrieves candidate information from authorized sources.
6. Checks source validity, applicability, completeness, and conflicts.
7. Constructs a response using verified information.
8. Speaks the response.
9. Displays the supporting source and relevant conditions.

**Successful outcome:** The mechanic receives a correct, applicable, evidence-backed answer without navigating service documentation.

## 7.4 Journey D — Insufficient Evidence

**Trigger:** CARVIS cannot establish a valid answer.

Possible reasons include:

- No authorized document is available.
- The requested specification is absent.
- Vehicle configuration is insufficient.
- Retrieved values conflict.
- Required service conditions are unknown.
- The technical information source is unavailable.

CARVIS must explain the limitation concisely.

Example:

*"I don't have a verified torque specification for that component on this vehicle. Check the applicable service procedure before proceeding."*

The system must not fill missing values with general automotive knowledge or plausible estimates.

## 7.5 Journey E — Follow-Up Conversation

The technician asks:

*"What about the rear rotors?"*

CARVIS preserves the confirmed vehicle context and interprets the new component reference using the existing conversation.

Vehicle context remains active until explicitly changed or the session is ended according to defined session rules.

## 7.6 Journey F — Switching Vehicles

The technician opens another vehicle or scans a different VIN.

CARVIS must:

- Establish the new vehicle identity.
- Invalidate vehicle-specific assumptions from the previous context.
- Prevent stale answers and pending operations from being attributed to the new vehicle.
- Preserve prior history without mixing contexts.

## 7.7 Journey G — Returning to a Previous Session

A signed-in technician can access permitted conversation history and previously retrieved answers.

Previously displayed specifications must retain their source context and must not silently become authoritative for a different vehicle or revised document version.

# 8. Functional Requirements

Priorities:

- **P0:** Mandatory in V1, the technician field-test release.
- **P1:** Important after V1.
- **P2:** Wearable and advanced capabilities, after V1.
- **P3:** Long-term research, after V1.

P1–P3 rank priority only. No product version number, release name, or date is assigned to them.

## 8.1 Identity and Workspace

| ID | Requirement | Priority |
|---|---|---|
| CAR-001 | Secure account registration and sign-in | P0 |
| CAR-002 | Persistent user profile and preferences | P0 |
| CAR-003 | Individual workspace with optional shop affiliation | P0 |
| CAR-004 | Strict user and tenant authorization on backend resources | P0 |
| CAR-005 | Account deletion and personal-data management | P0 |
| CAR-006 | Shop invitations and administrator-managed membership | P1 |
| CAR-007 | Multiple shop memberships and advanced roles | P1 |

**Acceptance conditions:**

A user can sign in again without repeating onboarding. Unauthorized users cannot access another user's vehicles or sessions. Shop membership never grants access outside its authorized scope.

## 8.2 Vehicle Management

| ID | Requirement | Priority |
|---|---|---|
| CAR-010 | VIN entry and format validation | P0 |
| CAR-011 | VIN decoding through a supported service | P0 |
| CAR-012 | Manual vehicle configuration selection | P0 |
| CAR-013 | Vehicle confirmation before technical lookup | P0 |
| CAR-014 | Saved vehicle garage | P0 |
| CAR-015 | Active vehicle selection and safe context switching | P0 |
| CAR-016 | Ask for unresolved configuration details | P0 |
| CAR-017 | VIN camera recognition | P1 |
| CAR-018 | Repair-order-based automatic vehicle identification | P1 |
| CAR-019 | Conversational vehicle identification: a vehicle described in conversation becomes an unconfirmed candidate; only the technician's in-app confirmation (CAR-013) establishes vehicle context | Conditional V1 enhancement (roadmap D-19) |

**Acceptance conditions:**

The system must not assume that decoding a VIN establishes every configuration detail required for a service specification.

A vehicle mismatch or change must prevent stale technical information from reaching the user.

## 8.3 Voice and Conversation

| ID | Requirement | Priority |
|---|---|---|
| CAR-020 | Explicitly initiated iPhone voice conversation | P0 |
| CAR-021 | Speech-to-text and spoken responses | P0 |
| CAR-022 | Contextual follow-up questions | P0 |
| CAR-023 | Clarification for ambiguous requests | P0 |
| CAR-024 | Interrupt, stop, and restart controls | P0 |
| CAR-025 | Microphone and network failure recovery | P0 |
| CAR-026 | Clear listening, processing, and speaking states | P0 |
| CAR-027 | Persistent conversation state | P0 |
| CAR-028 | Optional voice and response preferences | P1 |
| CAR-029 | Glasses-specific voice invocation | P2 |

**Acceptance conditions:**

The primary workflow must function without Meta glasses.

The application must not promise continuous background listening or locked-phone wake-word support unless those behaviors are independently implemented and validated.

## 8.4 Knowledge Retrieval and Verification

| ID | Requirement | Priority |
|---|---|---|
| CAR-030 | Search authorized repair-information sources | P0 |
| CAR-031 | Apply vehicle configuration filters | P0 |
| CAR-032 | Match requested component, operation, and specification | P0 |
| CAR-033 | Preserve source identity, location, revision, and conditions | P0 |
| CAR-034 | Validate numeric specifications before spoken output | P0 |
| CAR-035 | Detect incompatible or conflicting candidate evidence | P0 |
| CAR-036 | Refuse unsupported answers | P0 |
| CAR-037 | Display source details alongside responses | P0 |
| CAR-038 | Track supported and unsupported information coverage | P0 |
| CAR-039 | Provider-specific retrieval adapters | P1 |
| CAR-040 | Expanded procedures and diagnostic workflows | P1 |
| CAR-041 | Spoken output preserves server-approved facts, units, qualifications and refusals | P0 (release gate) |
| CAR-042 | Known-issue, TSB and recall discovery with attribution | Conditional V1 enhancement |
| CAR-043 | Selected complete, reviewed procedures for supported tasks (for example EPB service), refused rather than given partially | P0 |

**Acceptance conditions:**

No numerical technical specification may be presented as verified without evidence accepted by the verification layer.

The user must be able to identify the source of each verified answer.

Conflicting or incomplete sources must trigger clarification or refusal rather than arbitrary selection.

CAR-042 may ship in V1 only if authorized sources, applicable coverage, validated quality and
implementation cost justify it; it is neither a V1 release gate nor a committed post-V1 item. A TSB
is not a recall, and neither proves a fault or an open campaign on an individual vehicle; a
model-level recall match is not VIN-level open status.

## 8.5 Conversation History and Feedback

| ID | Requirement | Priority |
|---|---|---|
| CAR-050 | Store conversation metadata and approved response history | P0 |
| CAR-051 | Retrieve past sessions within authorized scope | P0 |
| CAR-052 | Associate sessions with vehicles | P0 |
| CAR-053 | Allow technicians to report incorrect or unhelpful responses | P0 |
| CAR-054 | Track response outcomes for internal evaluation | P0 |
| CAR-055 | Technician-confirmed repair observations | P1 |
| CAR-056 | Authorized repair-order documentation export | P1 |

A retrieved torque specification must never automatically be recorded as proof that a technician performed the torque operation.

## 8.6 Visual and Wearable Capabilities

| ID | Requirement | Priority |
|---|---|---|
| CAR-060 | Preserve existing vision integration behind an interface boundary | P0 architectural constraint |
| CAR-061 | Preserve existing glasses development work | P0 architectural constraint |
| CAR-062 | Camera-assisted component analysis | P2 |
| CAR-063 | Glasses audio conversation | P2 |
| CAR-064 | Reliable voice and camera coordination on supported glasses | P2 |
| CAR-065 | Live diagnostic visualization | P2 |
| CAR-066 | Display-equipped wearable guidance | P3 |
| CAR-067 | Disassembly and reassembly visual memory | P3 |

V1 must not expose unfinished wearable controls as functioning product capabilities.

# 9. Application UX Specification

## 9.1 Primary Navigation

CARVIS V1 should contain five principal destinations.

| Screen | Purpose |
|---|---|
| Home | Active vehicle, resume conversation, primary call to action |
| Garage | Saved vehicles, add vehicle, vehicle details |
| CARVIS | Voice interface, response display, supporting evidence |
| History | Previous conversations and retrieved answers |
| Profile | Account, shop information, privacy, settings, support |

The CARVIS voice experience should remain the central interaction—not a feature buried inside administrative navigation.

## 9.2 Home

The Home screen should answer three questions immediately:

1. Which vehicle am I working on?
2. Am I ready to ask CARVIS something?
3. How do I begin?

Avoid large dashboards, unnecessary statistics, and complex management features in V1.

## 9.3 CARVIS Voice Screen

Required states:

- **Ready:** A vehicle is selected; the user may start.
- **Listening:** Audio capture is active.
- **Processing:** The system is interpreting or retrieving information.
- **Clarification needed:** Additional input is required.
- **Speaking:** A response is being delivered.
- **Verified answer:** Supporting evidence is available.
- **Unsupported:** CARVIS cannot substantiate the requested information.
- **Connection error:** The interaction can be retried or safely ended.

The voice screen must clearly distinguish an answer that has been verified from an explanatory response or a refusal.

## 9.4 Answer Presentation

A verified answer should display:

- Requested specification or technical instruction.
- Applicable vehicle and configuration.
- Units, conditions, and relevant qualifiers.
- Source name and reference.
- Verification status.
- Feedback control.

The interface must not use a generic confidence percentage as a substitute for source applicability.

## 9.5 UX Accessibility

The application must support readable text, adequate touch targets, VoiceOver accessibility where applicable, clear audio states, and use in a noisy workshop environment.

Controls must remain usable when the user cannot comfortably type.

# 10. Automotive Knowledge Strategy

This is the most consequential external dependency for CARVIS.

## 10.1 Required Capability

CARVIS must retrieve applicable repair information from sources that it is authorized to access, process, and present.

For commercially restricted sources, permissions may need to cover:

- API retrieval.
- AI-assisted processing.
- Storage and caching.
- Indexing for search.
- Display and spoken presentation.
- Data retention and deletion.
- Use by multiple shops or technicians.

These rights must be established before the corresponding integration is used in a real pilot or commercial product.

## 10.2 ALLDATA

The initial shop uses ALLDATA.

That establishes a desirable integration target, **not automatic permission to extract or store its content**.

The PRD does not assume that ALLDATA provides a public API or grants CARVIS data-reuse rights.

A Chrome extension must not become a substitute for obtaining the required authorization to copy, crawl, or index proprietary service information.

## 10.3 Initial Pilot Knowledge

Until broader provider access is available, CARVIS may use a limited, rights-cleared collection of reviewed technical information.

Every supported source must carry sufficient metadata to establish:

- Vehicle applicability.
- Component and operation.
- Specification or procedure type.
- Numerical value and units, where relevant.
- Applicable conditions and exceptions.
- Document title and location.
- Revision or publication information, where available.
- Origin and applicable usage rights.
- Review status and time of validation.

Coverage must be explicitly communicated to pilot users.

CARVIS must not present limited test coverage as universal automotive knowledge.

## 10.4 Retrieval Is Not Verification

Semantic retrieval is permitted to identify potentially relevant information.

Retrieval ranking alone must not determine whether a specification is valid.

Verification must independently check the structured source evidence against the requested vehicle, component, operation, and service conditions.

If the required evidence is absent, ambiguous, stale, or conflicting, CARVIS must not generate a definitive numerical answer.

## 10.5 Knowledge Lifecycle

Future commercial operation must support source updates, revisions, invalidation of outdated specifications, controlled re-indexing, and traceability from a displayed answer to the underlying authorized record.

# 11. System Behavior and Logical Boundaries

The PRD defines responsibilities, not mandatory deployment technologies.

**Logical request flow:**

iOS interface → authenticated conversation request → vehicle and session context → intent interpretation → authorized knowledge retrieval → deterministic validation → response construction → speech and evidence display.

## 11.1 Conversation Responsibility

The conversation subsystem manages the active exchange, follow-up references, clarifications, and interruptions.

It must not independently manufacture authoritative specifications.

## 11.2 Vehicle Responsibility

The vehicle subsystem owns confirmed vehicle identity and unresolved configuration attributes.

No conversational agent may silently override a confirmed vehicle configuration.

## 11.3 Knowledge Responsibility

The knowledge subsystem retrieves source evidence from authorized collections or provider integrations.

It must preserve the data required for downstream verification.

## 11.4 Verification Responsibility

The verification subsystem independently evaluates applicability, numerical values, conditions, conflicts, and evidence sufficiency.

A failed verification must prevent an unsupported value from being spoken as verified.

## 11.5 Persistence Responsibility

User accounts, shop membership, vehicles, conversations, and source records require durable storage appropriate to their role.

The final database technologies will be selected in the technical design (milestone M1), informed by the repository audit completed on November 15, 2026. That audit is a historical snapshot; verify its findings against the current code.

## 11.6 Interface Responsibility

Phone, smart glasses, and future wearables are clients of the same core intelligence services.

The initial iPhone application must not depend on wearable-device availability.

# 12. Safety, Privacy, and Security

## 12.1 Technical Safety

CARVIS must:

- Refuse unsupported critical specifications.
- Preserve units and service conditions.
- Avoid cross-vehicle contamination.
- Surface ambiguity rather than guessing.
- Distinguish retrieved facts from general explanatory guidance.
- Warn when procedures require professional verification or specialized tools.
- Avoid claiming a repair or inspection was completed without technician confirmation.

## 12.2 Identity and Access

The backend must enforce authentication and authorization for all protected records.

Users must not be able to access other shops' conversations, vehicle records, or private operational data through manipulated identifiers or client-side state.

## 12.3 Data Protection

Personal and shop data must be protected in transit and at rest using appropriate security controls.

Secrets must not be embedded in distributed mobile applications.

Service credentials, licensed provider access, and verification-sensitive operations must remain controlled by trusted backend systems.

## 12.4 Audio and User Consent

The product must clearly disclose microphone use.

Audio retention should be minimized. Persistent raw audio recording must not be enabled by default without a defined purpose, appropriate consent, retention period, and deletion mechanism.

Transcript and diagnostic logging must also follow explicit retention and access policies.

## 12.5 Provider and Platform Compliance

Before V1 is released to the pilot technician, CARVIS must satisfy applicable Apple App Store requirements, privacy disclosures, third-party service agreements, and automotive information licensing terms.

# 13. Nonfunctional Requirements

The following are **proposed pilot targets**, to be tested and adjusted against real hardware, network conditions, and knowledge-provider behavior.

| Category | Proposed requirement |
|---|---|
| Perceived responsiveness | Voice acknowledgment or state feedback begins within 2 seconds at p95 under defined test conditions |
| Verified-answer latency | Target p95 of 8 seconds or less for supported, warm-path queries; report actual distribution |
| Answer validity | Zero unsupported numerical specifications in the curated pre-release safety evaluation |
| Source traceability | 100% of responses labeled as verified have inspectable supporting evidence |
| Context isolation | No cross-vehicle or cross-tenant information leakage in required tests |
| Session resilience | Recover gracefully from interruptions, reconnects, and failed provider calls |
| Availability | Pilot infrastructure monitored with explicit incident reporting and recovery procedures |
| Maintainability | CI, automated tests, typed interfaces where practical, documented boundaries |
| Security | No known unresolved critical authentication or authorization vulnerabilities at release |
| Observability | Request tracing, stage-level latency, retrieval outcomes, refusal reasons, error rates |

The latency figures are targets, not measured current capabilities or guarantees.

An incorrect technical answer delivered quickly is a more serious failure than a justified refusal delivered more slowly.

# 14. Pilot Evaluation and Success Metrics

## 14.0 Validation Stages

Every validation method and result is labeled with the stage it belongs to. The stages are provenance labels: they do not replace or reclassify the targets in §14.3 or the gates in §15.

| Stage | Purpose | Evidence allowed |
| --- | --- | --- |
| **S — Experience validation** | Interaction quality, reliability, usability, context management and workflow friction, in controlled sessions on the real application | Isolated, explicitly labeled synthetic evidence where authorized data is unavailable (P-09), served only in a dedicated synthetic workspace and always presented as simulated |
| **R — Real technical validation** | Correctness, applicability, safety, reliability and measurable utility on genuine supported repair-information tasks | Authorized, independently reviewed evidence only |
| **C — Commercial validation** | Continued technician use, shop-owner evaluation and a concrete purchasing assessment | Real use under Stage R conditions |

A Stage S result never satisfies a §14.3 target, a Stage R or C measure, or a §15 gate, and is never reported as real technical coverage or commercial utility. The pilot technician remains the primary V1 participant, and the pilot shop is the first commercial validation target.

## 14.1 Primary Product Hypothesis

Technicians using CARVIS can retrieve supported, verified repair information with less interruption and less elapsed effort than their existing lookup workflow.

## 14.2 Evaluation Method

The pilot should compare representative information lookup tasks performed through the shop's existing workflow against equivalent supported CARVIS tasks.

The evaluation must include:

- Successful verified answers.
- Appropriate refusals.
- Wrong-vehicle and ambiguous requests.
- Actual elapsed lookup time.
- User-perceived convenience.
- Repeated use over multiple repair sessions.

## 14.3 Proposed Success Targets

| Metric | Initial pilot target |
|---|---|
| Verified response correctness | At least 95% on a curated supported-question evaluation set |
| Unsupported numerical answers | Zero in required negative and adversarial tests |
| Source traceability | 100% of verified answers |
| Time savings | Demonstrate a 30% median reduction on matched, supported lookup tasks |
| Voice completion | At least 90% of supported test interactions completed without a blocking failure |
| Technician adoption | The pilot technician voluntarily uses CARVIS again across multiple work sessions |
| Commercial signal | Shop owner agrees to an extended pilot or provides a concrete purchasing assessment |

These targets are working hypotheses. We should retain actual observed results, sample sizes, and limitations rather than treating targets as achieved outcomes.

## 14.4 Metrics to Record

For each evaluated interaction, capture permissible metadata about:

- Request category.
- Vehicle context completeness.
- Whether the question was supported.
- Verification result.
- Clarification or refusal reason.
- Time to response.
- Error or interruption.
- Technician feedback.

Sensitive content should be minimized and access controlled.

# 15. TestFlight Release Criteria

V1 is ready for the technician field test only when all required criteria are satisfied. These gates are the completion test for milestones M1–M5 (§6.5).

## 15.1 Product Readiness

- [ ] New users can install the app, onboard, and sign in.
- [ ] Users can identify and confirm a supported vehicle.
- [ ] Users can initiate and complete voice conversations through iPhone.
- [ ] The application provides visible, understandable conversation states.
- [ ] Verified answers include applicable evidence.
- [ ] Unsupported answers are refused appropriately.
- [ ] Users can switch vehicles without leaking prior context.
- [ ] Conversations and account state persist as designed.
- [ ] Users can report problems and request support.

## 15.2 Engineering Readiness

- [ ] Existing verified behavior is protected by automated regression tests.
- [ ] Critical API contracts and failure paths are tested.
- [ ] Authentication and tenant isolation are validated.
- [ ] Real-device audio and interruption testing is completed.
- [ ] Actual spoken technical output preserves server-approved facts, units, qualifications and refusals, including after interruption, retry and vehicle switch (CAR-041); otherwise a controlled delivery path is added or technical voice release is blocked.
- [ ] Service failures are observable and recoverable.
- [ ] Release configuration and secrets are appropriately secured.
- [ ] Crash reporting and operational monitoring are available.
- [ ] Privacy disclosures and account-deletion behavior are implemented.

## 15.3 Knowledge Readiness

- [ ] Pilot knowledge sources are documented and authorized for intended use.
- [ ] Supported vehicle and question coverage is explicitly defined.
- [ ] Numerical verification and conflict behavior pass curated evaluations.
- [ ] No unsupported technical specification is presented as verified.
- [ ] The user can distinguish verified answers from unsupported guidance.

## 15.4 Pilot Readiness

- [ ] The pilot technician understands the supported scope and limitations.
- [ ] The shop permits the intended test activities.
- [ ] A baseline lookup workflow has been documented.
- [ ] Feedback, incident reporting, and rollback procedures exist.
- [ ] Initial testing does not depend on unfinished glasses functionality.

Passing these gates permits a controlled pilot. It does not establish broad commercial readiness.

# 16. Non-Goals for V1

V1 will not attempt to deliver:

- Universal OEM repair-information coverage.
- Unauthorized ALLDATA scraping or mass document extraction.
- Fully autonomous diagnostic decisions.
- Automatic certification of completed repairs.
- Production-ready AR overlays.
- Continuous visual recording of technician work.
- Local offline AI inference hardware.
- CARVIS Hub installation.
- Custom-manufactured glasses.
- Broad fleet, heavy-duty, or industrial equipment support.
- Fully automated invoicing or repair-order synchronization.
- A comprehensive multi-location shop-management platform.

These features may be evaluated later if they support demonstrated customer value.

**Intentional deferrals and extension paths.** Nothing below gets speculative schemas or services
now; each is reopened only by demand, data rights, validation or a concrete V1 blocker.

| Deferred | Why | Later path / trigger |
|---|---|---|
| Broad ALLDATA/MOTOR integrations | Rights, cost, unvalidated demand | Limited licensed pilot data if needed; later an authorized source adapter (CAR-039) |
| Tekmetric and plate-based lookup | Shop authorization, privacy, external API dependency | Read-only, tenant-scoped records and confirmed external vehicle IDs after demand and access |
| Universal coverage | Acquisition and review scale | Incremental coverage manifest driven by missed real tasks |
| Automated evidence approval | Safety and extraction uncertainty | Reviewer assistance, independently validated before any policy change |
| Statistical associations | Benefit unproven | Optional discovery index; never trust promotion |
| Full ontology or graph database | Modeling and operations overhead | Reviewed relations as needed; a graph only on measured benefit |
| ColBERT, SPLADE, custom neural retrieval | No demonstrated V1 requirement | Replace the discovery adapter only after a benchmark improvement (R3 method) |
| Autonomous diagnosis, OBD-II | Requires real observations and stronger evidence and safety | Structured observation and diagnostic-evidence interfaces (CAR-040) |
| Automated shop documentation or management | Not core pilot utility | Technician-confirmed notes and authorized repair export |
| Advanced visual reasoning | Model, dataset, physical and evidence validation | Preserved vision boundary; reviewed component evidence |
| Glasses and background wake | Hardware, OS privacy and reliability | Existing adapters retained; independently tested active-session invocation |
| CARVIS Hub, offline, consumer product | Hardware economics; different users and safety | Shared versioned Brain interface; validate deployment and use case later |
| Mechanic upload and admin dashboard | Review and publication risk; no pilot need | Operator CLI and report now; permission-controlled workspace later |

# 17. Dependencies and Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Authorized repair-data access unavailable | Critical | Seek provider agreements; use narrowly scoped rights-cleared pilot data |
| Incorrect or inapplicable specification | Critical | Structured verification, conflict detection, curated safety evaluation, refusal |
| Vehicle identity ambiguity | High | Confirmation, configuration clarification, safe context invalidation |
| Audio performance in noisy workshops | High | Real-device testing, interruption handling, microphone strategy |
| Unstable voice-provider behavior | High | Defined provider boundaries, retries, fallback/error states |
| Incomplete authentication or tenant isolation | Critical | Backend access controls and negative security tests |
| Hackathon code regressions during cleanup | High | Repository audit completed (November 15, 2026); characterize existing behavior, incremental refactoring |
| Weak mechanic adoption | High | Observe real tasks and measure time saved |
| Excessive third-party costs | Medium | Instrument per-session costs and optimize from actual usage |
| Apple review or policy issues | High | Validate compliance and privacy requirements before release |
| Insufficient pilot coverage | High | Choose supported vehicles and questions with the pilot technician before launch |

**Critical dependency:** CARVIS cannot responsibly offer broad, proprietary OEM specification coverage until appropriate data rights and technically viable access have been established.

# 18. Open Decisions

The following decisions, except those marked resolved, remain unresolved and should be closed during the technical design or pilot preparation.

| Decision | Proposed direction | Owner / timing |
|---|---|---|
| Voice orchestration provider | Evaluate existing Vapi implementation before replacing it | Technical design |
| Canonical transactional database | **Resolved:** PostgreSQL ([ADR-0001](decisions/0001-single-store-postgresql.md), accepted) | Technical design |
| Initial authentication method | **Resolved:** Supabase Auth as the OIDC issuer, with email and Sign in with Apple planned ([ADR-0002](decisions/0002-identity-provider-and-token-model.md), accepted) | UX + technical design |
| Initial vehicle data coverage | Select specific supported configurations based on the pilot technician's work | Pilot preparation |
| Repair-information licensing | Contact ALLDATA and alternative authorized providers | Business / external |
| First shop integration | Defer until a supported authorization route exists | Post-V1 or earlier if available |
| Audio/transcript retention | Minimal retention with clear consent and deletion rules | Security / legal review |
| Team ownership and contributions | Confirm responsibilities and IP arrangements | Before major development |
| Public App Store release | Decide after TestFlight evidence and compliance review | Post-V1 |
| Pricing and commercial packaging | Base on measured value, provider costs, and customer willingness to pay | Post-V1 |

# 19. Engineering Handoff

The PRD establishes the intended product behavior.

It does **not** establish that the corresponding features already exist in the current repository.

The engineering deliverables, in order, are:

**1. Repository Audit & Capability Inventory**

*Status: completed on November 15, 2026 as the P0 Readiness Audit (`docs/audits/2026-11-15-p0-readiness-audit.md`). It is a historical snapshot; re-verify its findings against the current code and tests before relying on them.*

Examine the actual current implementation, SwiftUI screens, backend components, service integrations, tests, security model, and deployment configuration.

Classify every PRD requirement as:

- Implemented and validated.
- Implemented but insufficiently validated.
- Partially implemented.
- Missing.
- Deferred or unnecessary.

**2. Gap Analysis**

*Status: the audit's P0 gap matrix provides the initial analysis. The refreshed, authoritative traceability matrix is a milestone M1 deliverable.*

Map each P0 requirement to existing code, missing capabilities, technical risks, dependencies, and estimated engineering work.

**3. Technical Design Document**

*Status: pending; this is milestone M1 — Production Architecture.*

Select and document architecture boundaries, database design, API contracts, conversation state transitions, identity/security model, knowledge-provider interfaces, deployment, and observability.

**4. Engineering Execution Plan**

Refine milestones M1–M5 (§6.5) into GitHub issues, acceptance tests, release gates, and bounded refactoring tasks.

Refactoring must preserve validated functionality and must not replace a working system solely for architectural aesthetics.

# 20. Definition of Product Success

The initial success condition is not a particular model, framework, repository structure, or number of features.

It is an observable workflow.

The pilot technician opens CARVIS, identifies a supported vehicle, and asks for a technical specification while performing a repair.

CARVIS understands the question, retrieves applicable evidence, verifies the information, and delivers a useful spoken answer.

When it cannot establish the answer, it refuses to guess.

The pilot technician can repeat this process reliably, with less effort than their existing information-retrieval workflow.

They can then demonstrate the product to their shop owner, supported by measured results and a clear explanation of its limitations.

**That is what V1 must earn.**

The longer-term objective is to expand from a useful voice application into a trusted, multimodal automotive intelligence platform that integrates directly into professional repair workflows.

**End of CARVIS PRD, document revision 1.1 — Draft for Review**
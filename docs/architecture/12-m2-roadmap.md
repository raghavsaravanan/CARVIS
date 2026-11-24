# 12 — M2 roadmap and owner decisions

Process: small, independently reviewable PRs; tests first; each PR states scope, security and
migration/rollback notes, and passes `scripts/verify.sh` and CI. **The implementer never merges its
own PR.** Nothing here authorizes provider, production or infrastructure changes.

## Track A — immediately safe security fixes

Independent of identity, database and issuer choices; no new infrastructure; no iOS contract change;
each reversible by revert. Owner approved Track A as the first implementation phase, starting with
A1, **after this documentation PR is reviewed and merged**.

| PR | Change | Why safe now |
| --- | --- | --- |
| **A1 (first)** | `/vapi-tool` fails closed: refuse to boot outside local if `VAPI_WEBHOOK_SECRET` is empty; `hmac.compare_digest`; tests for unset, empty, wrong, correct secret | Render already sets the secret; behavior with a secret is unchanged |
| A2 | `/upload` operator-gated by a required `CARVIS_OPERATOR_TOKEN`; 50 MiB streaming cap; `%PDF-` magic check; reject before any LlamaParse call | `/upload` is not used by the iOS app [V] |
| A3 | `bind_call` refuses re-binding a `vapi_call_id` mapped to a different session (idempotent re-bind allowed); prune `_calls`; cap and throttle unauthenticated `POST /conversation/sessions` | Shapes unchanged; interim until B5 |
| A4 | Remove silent `shop_demo`, `hackutd`, `george_specs` defaults outside local | Startup error only in misconfigured environments |
| A5 | Pin dependencies with a lockfile; move pytest out of runtime; stop sourcing `.env` as shell; Render plan off Free (owner action) | No behavior change |
| A6 | Request-size caps; generic 503 messages (no `str(exc)`); structured logging scaffold without transcripts | No contract change |

Not in Track A: authenticating `/vision-query` or `/conversation/sessions`, removing caller-supplied
`shop_id`, the sessionless legacy lookup, Vapi binding redesign, identity, RLS, evidence activation.

## Track B — architecture-dependent

| PR | Scope | Depends on |
| --- | --- | --- |
| B1 | `Settings`, `/healthz`, `/readyz`, request IDs, PostgreSQL in CI, Alembic baseline with upgrade/downgrade/linear-history jobs, provider-neutral role-creation migration; vendor-independent (no provider provisioning, no issuer- or host-specific roles, grants or connection assumptions; those move to B2) | D-1 (accepted 2026-11-22) |
| B2a | Connection and role hardening, token verifier: B1 deferred N2 (host/port arity) and N3 (service files); request-path engine; `carvis_bootstrap`/`carvis_provisioner` roles, default-function-privilege revokes, issuer-role revokes and adopted-role preflight; owner-run runtime-login check/grant command; readiness role switch and login self-check; JWT verifier with fake JWKS tests, not wired to routes. T3, 90 min | B1; D-2 (ADR-0002), ADR-0003 |
| B2b-1 | Users, workspaces, memberships with forced RLS; `ensure_principal` provisioning; reusable catalog check; database-level isolation tests ([04](04-identity-tenancy-rls.md) "Validation" 1, 2, 6, 7, 8, 10, 12–15). T3 (owner split of B2b's 150 min, 2026-11-24), 90 min | B2a |
| B2b-2 | Two-phase `after_begin` session context (`db/context.py`); app-level harness: pool leak, interleaving, rollback, fail-closed layers ([04](04-identity-tenancy-rls.md) "Validation" 3, 4, 5, 16). T3, 60 min | B2b-1 |
| B2c | `/v1` auth dependency, `GET /v1/me`, `GET /v1/workspaces`, `/v1`-scoped error envelope, OpenAPI snapshot; **API contract freeze** (frozen/provisional, iOS agreement required, ADR-0004). T4, 120 min | B2b-2; ADR-0004 |
| B3 | Garage: vehicles, snapshots with immutability triggers, VIN validation, `/v1/vehicles*`; the confirm transaction as the only snapshot-creation path (vehicle version bound, archived refused, `workspace_id` and composite FKs, unknown versus not-applicable attributes); `Idempotency-Key` on create and confirm; `X-Workspace-Id` validation (first workspace-scoped route). `POST /v1/vehicles/decode` stays provisional | B2c |
| B4 | Durable conversations, calls, turns, `webhook_events`; PostgreSQL-backed `ConversationStore` behind the existing interface; restart-durability tests; conversation bound to one snapshot of a non-archived vehicle at creation, a switch ends conversation and call, per-conversation derived state (including any visual hypothesis), `turns.vehicle_snapshot_id` NOT NULL with workspace-scoped composite links; carry-forward (design-review N3): the server ends the user's other open conversations and their calls in the same transaction that creates a new conversation, before the new context is usable; acceptance: switch between a request and its release releases nothing for the old vehicle | B3 |
| B5 | Vapi ingress v2 ([06](06-vapi-ingress.md)): credential, bind proof, `resolve_call`, dedupe, `call_not_ready`; flagged removal of payload-trusting bind and sessionless path; `confirm_vehicle` without authority; replay only on the current call; acceptance: replay after a switch and a model claiming spoken confirmation change nothing. carry-forward: validate that ending a call cuts in-flight audio (G-V6 covers only tool-call retries; add the check to the gate set or the D-14 spoken-output tests); CAR-019 proposal tool only under D-19, with its confirmation on P06 | B4; gates G-V1…G-V6 (D-9) |
| B6 | Evidence references, history, feedback endpoints | B4 |
| B7a–f | Brain in PostgreSQL ([07](07-brain.md)), split below | B2c, D-8 |
| B8 | Account deletion/export and retention jobs | B2c–B6, D-4 |
| B9 | Authenticate `/vision-query`, `/upload`→internal, `/conversation/sessions`; SpacetimeDB retirement ([08](08-migration-and-spacetimedb.md)) | B5, iOS ready, D-3, D-6 |
| B10 | Staging and production pipeline, nightly dump, restore drill, alerts, runbooks | B1 |

Parallel: M3 corpus work after the B7 contract; iOS M4 consumes the contracts frozen at B2c.

**Bounded B3–B5 design review (2026-11-24, T4; owner direction of that date).** Vehicle context is
backend-authoritative end to end: one snapshot-creation path (B3), a conversation bound to one snapshot with a
switch ending it (B4), voice tools without vehicle authority (B5), and evaluation and release against the snapshot
and call generation captured when a request begins (B7d, B7e). The rules are in
[03-data-model.md](03-data-model.md) "Vehicle context rules", [06-vapi-ingress.md](06-vapi-ingress.md) steps 6 and 7
and [07-brain.md](07-brain.md) "Outcomes and response compiler". Conversational vehicle identification (CAR-019)
is a conditional enhancement limited to proposals inside a confirmed conversation (D-19) and needs no B3 or B4
change; the Stage S requirement is approved and its serving mechanism stays open for B7a (D-20). B4 now depends on B3,
whose snapshot table its foreign keys reference.

B2 is split into serial rows B2a, B2b and B2c (owner, 2026-11-22), and B2b further into B2b-1 and
B2b-2 (table above), each its own draft PR titled `(M2 B2a)` and so on, each starting only after the
previous one merges. All rely on ADR-0002, ADR-0003 and ADR-0004, which the owner accepted on
2026-11-23. No row provisions Supabase, configures a provider or creates credentials.

## B7 Brain packages (approved split, subject to review)

Owner-approved decomposition on 2026-11-22 (D-12), subject to dependency and acceptance-criteria
review. **Non-serving boundary:** no package before B7f changes what is served; the existing
verified path keeps serving, and new tables, projections and gates run only in tests and staging
until B7f passes. Each package is its own PR at T4 (`docs/architecture/07-brain.md` and the evidence
code paths floor at T4). Migration order is linear (B7a, then B7b and B7c, then B7e); B7b and B7c
may run concurrently only with disjoint files and an agreed migration order (Concurrency rules in
[`../development-workflow.md`](../development-workflow.md)). Route changes in `backend/main.py` land
only in B7e and B7f (B6 owns its own history and feedback routes). B6 and B7a are coupled only
through `evidence_references`: B6 stores `evidence_id`, `state_version` and digest without a foreign
key, and whichever of B6 and B7a merges second adds the constraint in its migration. B7f requires
B5 and B6 merged; its activation switch is the only barrier that changes serving, and it needs
owner approval.

| Package | Scope | Depends on | Acceptance criteria |
| --- | --- | --- | --- |
| B7a | Canonical knowledge and evidence schema (source documents and revisions with rights basis, fragments, entities and aliases, applicability, specifications, procedures and steps, review decisions, evidence versions, coverage), versioned internal contracts, additive migration with downgrade | B2, D-8; D-20 for any synthetic-partition element | Migration up/down on a scratch store; constraints reject activation without rights basis; append-only review decisions enforced; RLS and scope tests; nothing served |
| B7b | Operator ingestion: source registration before transmission, parser adapter (LlamaParse baseline), technical normalization, typed `pending` extraction, terminology resolution | B7a | Normalization golden tests for every form listed in 07 "Knowledge construction"; no external call without a registered permission; extractions are `pending` only; synthetic fixtures cannot reach a real scope |
| B7c | Review and publication roles, projection loop, tombstones, control collection, reconciliation, quarantine and restore | B7a (coordinate with the B7b importer); accepted protocol (07 "Protocol gate") | Acceptance cases 1–12 in 07 "Tests", F3 and the restore tests pass on real PostgreSQL and a Qdrant test instance; reviewer ≠ publisher enforced; reconciliation never raises trust |
| B7d | Query mapping (subject, operation, property, position, conditions, follow-up), authoritative scope enumeration with dependency closure, discovery adapter that only proposes mappings re-entering the exact path | B7a, B7c trust contract, accepted protocol (07 "Protocol gate"); R3 only if a discovery layer beyond the baseline is adopted | 07 authoritative-scope acceptance requirements, including F1–F3, and the accepted protocol's cases; structured exact retrieval works without any discovery layer; scope limit refuses with `clarification` |
| B7e | Unified evidence gate, conflict and completeness evaluation, deterministic response compiler, outcomes, coverage manifest | B7c, B7d, accepted protocol | 07 serve-time requirements and F1–F3 as acceptance cases; existing `test_specs_v2.py`/`test_ride_height.py` unchanged and passing; every outcome produced by a test; spoken and displayed text derive from one versioned answer |
| B7f | Full real-store lifecycle, regression and adversarial acceptance, integration with B5 and B6, activation behind a reviewed switch | B7e, B5, B6 | Mandatory safety suite (zero unsupported numerical, wrong-vehicle, conflicting or incomplete-as-complete answers; 100% traceability); owner approval before switching serving to the new gate |

**B7 carry-forwards (owner, 2026-11-24).** Recorded here so the packages pick them up; none changes scope or authorizes
work before its package.

- **WRX regression tests and fixtures (B7a, B7e, B7f).** `test_specs_v2.py`, `test_ride_height.py` and
  `backend/tests/fixtures/wrx-acceptance.json` are preserved unchanged for now (B7e's "unchanged and passing" criterion
  stands). Provenance concerns: their values and source hashes derive from documents whose usage rights are not
  established, and the corresponding live records were reviewed by AI agents, not a qualified human reviewer (D-17). Before
  any of them is treated as acceptance evidence for a real scope, or kept long term, the owner decides whether to keep,
  replace with synthetic equivalents, or re-source them from rights-cleared material. Nothing is changed until then.
- **CAR-043 procedure extraction gap (B7b, B7d, B7e).** The existing extractor emits ordered prose steps without component,
  operation or applicability, so no procedure can reach a reviewable state on the legacy path (the incomplete case is
  detected only because `step_count` is unset). B7b must produce typed `pending` procedure records (prerequisites, tools,
  warnings, ordered steps, applicability); B7d and B7e own the group completeness check and the `incomplete` refusal.

## R3 — bounded retrieval comparison (off the critical path)

R3 decides only whether a discovery layer beyond structured exact retrieval is adopted. It blocks
B7d's discovery adapter if one is chosen, and nothing else; B1–B6, B7a–c and B8–B10 never wait for
it. Budget: 2 hours, escalation at 4 hours, review per the bounded workflow. Systems compared, with
the same authorization, corpus, evidence gate and query sets: **A** the current baseline, **B**
structured plus reviewed aliases and lexical matching, **C** B plus dense discovery.

- **Benchmark (proposed):** about 120 labeled cases: 30 exact specifications, 20 terminology and
  paraphrase, 15 complete procedures, 15 applicability, 10 conditional known-issue citations, 15
  conflicts or missing data, 15 follow-ups and multipart questions; held-out source families;
  independently labeled expected evidence IDs, values, units, conditions, steps and refusal
  reasons. Cases without rights-cleared real coverage are synthetic and labeled so.
- **Metrics:** recall@k and ranking by category; exact value and unit correctness; applicability;
  procedure completeness; citation accuracy; correct abstention; p50/p95 latency; resource cost.
- **Proposed adoption thresholds (D-15; set before scoring, not results):** B or C is adopted only
  if, on held-out cases, it raises recall@5 for the terminology and paraphrase category by at least
  10 percentage points over A, lowers no other category's correctness, keeps the mandatory safety
  suite at zero failures, and keeps warm Brain-only p95 for supported specification lookups under
  1 s. Otherwise A is retained. These thresholds are proposals until the owner accepts them.

## M3 — pilot knowledge acquisition (parallel, external gate)

Acquisition and the pilot technician's task confirmation start now, in parallel with Track B; ingestion,
technical review, evaluation, coverage publication and correction follow the relevant B7 gates. An
internal CLI and report are required; a dashboard is optional; there is no mechanic ingestion UI.
No purchase, account change, licensing outreach or scraping without owner approval. Proposed pilot
targets and the acquisition gates are in the
[V1 contract §6.5](../product/v1-product-experience-contract.md).

**Preparation status (owner direction, 2026-11-24).** The owner holds source rights initially (D-8) and may act as
publisher (D-17); a separate qualified reviewer is not yet named. Real coverage targets stay open until the pilot
technician's tasks are confirmed (D-16), and simulation carries no vehicle quota. Evidence classes: authorized public
data (context only), rights-cleared technical evidence where it exists, and independently fabricated synthetic evidence
for unavailable integrations (Stage S, never coverage). The existing 2022 WRX corpus is **quarantined** until its rights
are established: it is not classified as synthetic, not used for demonstrations, and no new ingestion or parsing of it
runs. The live collections were not modified; a read-only live inventory and offline backup were taken on 2026-11-24 (the
live counts match the 2026-11-15 audit; its verified records were reviewed by AI agents, not a qualified human
reviewer, and none has a recorded rights basis). Legacy exports were preserved offline. The source register, synthetic fixtures, evaluation cases,
coverage manifest and public-data notes are prepared outside Git because they hold source-rights and private data; they
enter the repository only through B7 or a later owner-approved change. Public-data findings (NHTSA vPIC for B3b, recalls
and manufacturer communications for conditional D-18): the NHTSA pages read state no licence, attribution or
caching terms, so caching and storage of responses stay unconfirmed until the owner reads NHTSA's current terms.
Nothing here is integrated, ingested or activated, and it adds no V1 scope.

## B1 task contract (implementation-ready once authorized)

Recorded here so B1 can start without re-planning; the owner's `/carvis-continue` invocation (or
an Orca contract recording it) is still required ([`../development-workflow.md`](../development-workflow.md),
"Task contract").

```text
Task:            M2 B1 — backend foundation: settings, health/readiness, request IDs, PostgreSQL CI,
                 Alembic baseline and roles
Tier:            T4 (scripts/review-scope.sh floors backend/main.py at T4; backend/requirements*,
                 .github/ and backend/tests/ are T3; confirmed by the owner, 2026-11-22) — design
                 review by both reviewer classes, at most 2 implementation rounds
Authorization:   <owner, date: commit / push to origin / draft PR; invocation of /carvis-continue B1>
Depends on:      ADR-0001 accepted (D-1, 2026-11-22); D-2 not required (owner, 2026-11-22)
Base:            <origin/main SHA at assignment>
Branch:          feat/b1-backend-foundation
Worktree:        <Orca worktree path and id>
Scope:           backend/settings.py (new, typed settings; no provider-specific fields),
                 backend/main.py (only /healthz, /readyz, request-ID middleware, settings wiring),
                 backend/db/ (new: engine/session factory), backend/migrations/ (new Alembic env,
                 baseline revision, provider-neutral role-creation revision: CARVIS application,
                 migrator and worker roles with grants on CARVIS-owned schemas only),
                 backend/requirements.in,
                 backend/requirements.txt, backend/requirements-dev.in, backend/requirements-dev.txt,
                 backend/tests/test_b1_*.py, .github/workflows/ci.yml (PostgreSQL service and
                 migration jobs), README.md and docs/backend/architecture.md (configuration)
                 excluded: existing route behavior and status codes, Qdrant and Brain code,
                 render.yaml, any provider or production configuration, iOS; grants or revokes on
                 issuer- or host-specific roles (for example Supabase anon, authenticated,
                 service_role), pooler or connection-string assumptions (B2, D-2)
Acceptance:      /healthz returns 200 without dependencies; /readyz returns 503 until PostgreSQL is
                 reachable and migrations are at head, 200 afterwards; every response carries a
                 request ID (accepted only if well formed, otherwise generated) and logs never
                 include transcripts or secrets; Alembic upgrade and downgrade of the baseline and
                 role revisions run clean; CI fails on more than one Alembic head; settings fail
                 closed outside local when required values are missing; no Supabase, Render or
                 issuer-specific assumption; all existing tests unchanged and passing
Verification:    narrowest new tests first; scripts/verify.sh; scripts/check-runtime-lock.sh (new
                 dependencies); migrations up/down on a scratch PostgreSQL; mutation check for each
                 new guard (readiness, request-ID validation, settings fail-closed, single head);
                 /carvis-regression sections 3 and 4 (pipeline preservation, adversarial
                 refusals); provider and production boundary statement in the PR;
                 labels: mocked/unit, local; no live provider
Completion:      committed candidate SHA, review-scope exit 0, checks with labels, handoff record
Stop if:         a stopping condition (development-workflow, "Review budget, findings and stopping");
                 a vendor or issuer decision is needed; any existing route contract would change;
                 a production or provider action is needed; time budget <owner estimate> exceeded twice
Budget:          T4 review budget; time budget <owner estimate>
```

## Owner decisions

Architecture direction, technology choices, Track A/B and the V1 simplification of Brain restore
safety were **approved in principle by the owner on 2026-11-15**. Remaining items to resolve before
the decision records are marked `accepted` or the dependent PR starts:

| ID | Decision | Recommendation | Blocks |
| --- | --- | --- | --- |
| D-1 | PostgreSQL as the single store | **Accepted** by the owner on 2026-11-22 (ADR-0001) | B1 (cleared) |
| D-2 | Issuer and host: Supabase Auth and Supabase PostgreSQL for V1; FastAPI the only application API | **Accepted** by the owner on 2026-11-23 (ADR-0002); Apple Developer account, custom SMTP, paid plan and other provisioning choices remain deferred to provisioning | ADR-0002, B2a–B2c (cleared; not B1: owner, 2026-11-22) |
| D-3 | Break legacy unauthenticated routes on a date agreed with the iOS worktree | Approve after B2 contract | B9 |
| D-4 | Retention: transcript text 90 days then metadata, no raw audio, audit 1 year, deletion grace 30 days | Approve | ADR-0009, B8 |
| D-5 | Backups: provider daily plus nightly external dump; PITR add-on yes or no | No PITR for pilot | ADR-0008 |
| D-6 | Export `hackutd` table counts read-only; approve retirement; owner decides on live database | Retire after export | ADR-0007, B9 |
| D-7 | Hosting: Render paid production instance and a staging instance; error-tracker vendor; budget (~$70–150/month) | Approve | ADR-0008, B10 |
| D-8 | Brain: serve-time PostgreSQL gate, tombstone-first withdrawal, quarantine and reapproval rule; pilot corpus and rights owner; knowledge model and benchmark-gated retrieval | Approve ADR-0006 as amended by ADR-0010; name the pilot corpus and rights owner. **Partly resolved (owner, 2026-11-24):** the owner is the initial rights owner; the pilot corpus is not yet named and no real source has a recorded rights basis; the ADR-0006 and ADR-0010 acceptance stays open | B7a–f |
| D-9 | One staging Vapi assistant and one live call to validate G-V1…G-V6 and spoken-output integrity | Direction approved by the owner on 2026-11-22; no live call or provider change authorized yet | ADR-0005 final, B5 |
| D-10 | Contract defaults D-06, D-07, D-09 | Approve | scope |
| D-11 | Track A may start after this PR merges; A1 first | Approved | — |
| D-12 | B7 split into B7a–f | Approved by the owner on 2026-11-22, subject to dependency and acceptance review | B7 planning |
| D-13 | PostgreSQL-first authoritative evidence scope (07 "Serve-time rule"): mandatory requirements, the delivery-window residual (07 requirement 6) and the detailed evidence protocol | Requirements and the residual (for V1) approved by the owner on 2026-11-22; the detailed protocol stays proposed until it resolves F1–F3, passes T4 design review and receives final owner sign-off | ADR-0010; design acceptance of B7c–e; B7a schema elements for publication status or decision counters; B7f activation |
| D-14 | Spoken-output integrity as a mandatory V1 release gate | Approved by the owner on 2026-11-22 | B5, technical voice release, M5 |
| D-15 | R3 adoption thresholds and latency target | Accept before R3 scoring | R3, B7d discovery adapter |
| D-16 | Pilot targets with the pilot technician (V1 contract §6.5) | Confirm with the pilot technician. **Open (owner, 2026-11-24):** real targets stay open until the technician's tasks are confirmed; no vehicle quota applies to synthetic evidence | M3 evaluation, V1 field test |
| D-17 | Named qualified technical reviewer and publisher | Name before any real-scope publication. **Partly resolved (owner, 2026-11-24):** the owner may serve as authorized publisher, subject to the role requirements; the separate qualified technical reviewer is still outstanding | M3 publication |
| D-18 | Include conditional TSB/recall discovery in V1 | Decide per rights, coverage, quality and cost; not a release gate. **Open (owner, 2026-11-24):** stays conditional and outside mandatory V1 scope; public-data research is prepared for the decision (caching and storage rights unconfirmed) | CAR-042 |
| D-19 | Include conversational vehicle identification in V1 (CAR-019) | **Direction set by the owner on 2026-11-24:** manual Garage and VIN identification with explicit in-app confirmation is the mandatory V1 baseline; voice proposals inside a confirmed conversation may remain a conditional enhancement; pre-vehicle conversations and spoken confirmation are not in V1, and any expansion needs explicit owner approval and reconciliation of the affected contracts (spoken confirmation would also need a speech-input validation and acknowledgment gate; D-14 covers output only). Inclusion of the proposal form stays open | CAR-019 proposal tool (B5 or later); not B3, B4 or base B5 |
| D-20 | Stage S synthetic-evidence serving mechanism (07 "Stage S synthetic evidence") | **Requirement approved by the owner on 2026-11-24** (controlled Stage S validation through the real application with isolated, explicitly labeled synthetic evidence that can never authorize real repair guidance); the implementation decision stays open for B7a. Recommendation: a server-issued Stage S mode bound to a dedicated synthetic workspace, excluded from real and global scope resolution, durably labeled simulated, never verified, separate metrics. **Owner, 2026-11-24:** the serving mechanism is left to B7a design | Stage S serving runs; B7a design acceptance and B7c publication decisions that encode the synthetic partition; not B3–B6 |

Decision IDs D-12 onward continue this roadmap's numbering; they are separate from the V1
contract's D-01–D-12.

Standing constraints: the external reference checkout is never modified; no production
infrastructure change; no live database deletion.

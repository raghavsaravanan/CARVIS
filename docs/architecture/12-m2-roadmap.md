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
| B2 | Users, workspaces, memberships; JWT dependency (fake JWKS in tests); RLS scaffolding and `after_begin` context; full RLS test harness; **API contract freeze** | B1; D-2 |
| B3 | Garage: vehicles, snapshots with immutability triggers, VIN validation, `/v1/vehicles*` | B2 |
| B4 | Durable conversations, calls, turns, `webhook_events`; PostgreSQL-backed `ConversationStore` behind the existing interface; restart-durability tests | B2 |
| B5 | Vapi ingress v2 ([06](06-vapi-ingress.md)): credential, bind proof, `resolve_call`, dedupe, `call_not_ready`; flagged removal of payload-trusting bind and sessionless path | B4; gates G-V1…G-V6 (D-9) |
| B6 | Evidence references, history, feedback endpoints | B4 |
| B7a–f | Brain in PostgreSQL ([07](07-brain.md)), split below | B2, D-8 |
| B8 | Account deletion/export and retention jobs | B2–B6, D-4 |
| B9 | Authenticate `/vision-query`, `/upload`→internal, `/conversation/sessions`; SpacetimeDB retirement ([08](08-migration-and-spacetimedb.md)) | B5, iOS ready, D-3, D-6 |
| B10 | Staging and production pipeline, nightly dump, restore drill, alerts, runbooks | B1 |

Parallel: M3 corpus work after the B7 contract; iOS M4 consumes the contracts frozen at B2.

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
| B7a | Canonical knowledge and evidence schema (source documents and revisions with rights basis, fragments, entities and aliases, applicability, specifications, procedures and steps, review decisions, evidence versions, coverage), versioned internal contracts, additive migration with downgrade | B2, D-8 | Migration up/down on a scratch store; constraints reject activation without rights basis; append-only review decisions enforced; RLS and scope tests; nothing served |
| B7b | Operator ingestion: source registration before transmission, parser adapter (LlamaParse baseline), technical normalization, typed `pending` extraction, terminology resolution | B7a | Normalization golden tests for every form listed in 07 "Knowledge construction"; no external call without a registered permission; extractions are `pending` only; synthetic fixtures cannot reach a real scope |
| B7c | Review and publication roles, projection loop, tombstones, control collection, reconciliation, quarantine and restore | B7a (coordinate with the B7b importer) | Acceptance cases 1–12 in 07 "Tests" and the restore tests pass on real PostgreSQL and a Qdrant test instance; reviewer ≠ publisher enforced; reconciliation never raises trust |
| B7d | Query mapping (subject, operation, property, position, conditions, follow-up), authoritative scope enumeration with dependency closure, discovery adapter that only proposes mappings re-entering the exact path | B7a, B7c trust contract; R3 only if a discovery layer beyond the baseline is adopted | Authoritative-scope cases 13–30; structured exact retrieval works without any discovery layer; scope limit refuses with `clarification` |
| B7e | Unified evidence gate, conflict and completeness evaluation, deterministic response compiler, outcomes, coverage manifest | B7c, B7d | Existing `test_specs_v2.py`/`test_ride_height.py` unchanged and passing; every outcome produced by a test; spoken and displayed text derive from one versioned answer |
| B7f | Full real-store lifecycle, regression and adversarial acceptance, integration with B5 and B6, activation behind a reviewed switch | B7e, B5, B6 | Mandatory safety suite (zero unsupported numerical, wrong-vehicle, conflicting or incomplete-as-complete answers; 100% traceability); owner approval before switching serving to the new gate |

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

Acquisition and Tyler's task confirmation start now, in parallel with Track B; ingestion,
technical review, evaluation, coverage publication and correction follow the relevant B7 gates. An
internal CLI and report are required; a dashboard is optional; there is no mechanic ingestion UI.
No purchase, account change, licensing outreach or scraping without owner approval. Proposed pilot
targets and the acquisition gates are in the
[V1 contract §6.5](../product/v1-product-experience-contract.md).

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
| D-2 | Issuer and host: Supabase (Pro for production); confirm Apple Developer account and custom SMTP | Supabase | ADR-0002, B2 (not B1: owner, 2026-11-22) |
| D-3 | Break legacy unauthenticated routes on a date agreed with the iOS worktree | Approve after B2 contract | B9 |
| D-4 | Retention: transcript text 90 days then metadata, no raw audio, audit 1 year, deletion grace 30 days | Approve | ADR-0009, B8 |
| D-5 | Backups: provider daily plus nightly external dump; PITR add-on yes or no | No PITR for pilot | ADR-0008 |
| D-6 | Export `hackutd` table counts read-only; approve retirement; owner decides on live database | Retire after export | ADR-0007, B9 |
| D-7 | Hosting: Render paid production instance and a staging instance; error-tracker vendor; budget (~$70–150/month) | Approve | ADR-0008, B10 |
| D-8 | Brain: serve-time PostgreSQL gate, tombstone-first withdrawal, quarantine and reapproval rule; pilot corpus and rights owner; knowledge model and benchmark-gated retrieval | Approve ADR-0006 as amended by ADR-0010; name the pilot corpus and rights owner | B7a–f |
| D-9 | One staging Vapi assistant and one live call to validate G-V1…G-V6 and spoken-output integrity | Direction approved by the owner on 2026-11-22; no live call or provider change authorized yet | ADR-0005 final, B5 |
| D-10 | Contract defaults D-06, D-07, D-09 | Approve | scope |
| D-11 | Track A may start after this PR merges; A1 first | Approved | — |
| D-12 | B7 split into B7a–f | Approved by the owner on 2026-11-22, subject to dependency and acceptance review | B7 planning |
| D-13 | PostgreSQL-first authoritative evidence scope (07 "Serve-time rule"), including acceptance of the stated delivery-window residual (07 step 5) | Approved in principle on 2026-11-22; the evidence decision table, evaluation stages and delivery-window residual (for V1) accepted by the owner on 2026-11-22; final T4 sign-off on the reviewed candidate pending | ADR-0010, B7c–e |
| D-14 | Spoken-output integrity as a mandatory V1 release gate | Approved by the owner on 2026-11-22 | B5, technical voice release, M5 |
| D-15 | R3 adoption thresholds and latency target | Accept before R3 scoring | R3, B7d discovery adapter |
| D-16 | Pilot targets with Tyler (V1 contract §6.5) | Confirm with Tyler | M3 evaluation, V1 field test |
| D-17 | Named qualified technical reviewer and publisher | Name before any real-scope publication | M3 publication |
| D-18 | Include conditional TSB/recall discovery in V1 | Decide per rights, coverage, quality and cost; not a release gate | CAR-042 |

Decision IDs D-12 onward continue this roadmap's numbering; they are separate from the V1
contract's D-01–D-12.

Standing constraints: the external reference checkout is never modified; no production
infrastructure change; no live database deletion.

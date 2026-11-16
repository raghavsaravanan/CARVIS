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
| B1 | `Settings`, `/healthz`, `/readyz`, request IDs, PostgreSQL in CI, Alembic baseline with upgrade/downgrade/linear-history jobs, role-creation migration | D-1, D-2 |
| B2 | Users, workspaces, memberships; JWT dependency (fake JWKS in tests); RLS scaffolding and `after_begin` context; full RLS test harness; **API contract freeze** | B1 |
| B3 | Garage: vehicles, snapshots with immutability triggers, VIN validation, `/v1/vehicles*` | B2 |
| B4 | Durable conversations, calls, turns, `webhook_events`; PostgreSQL-backed `ConversationStore` behind the existing interface; restart-durability tests | B2 |
| B5 | Vapi ingress v2 ([06](06-vapi-ingress.md)): credential, bind proof, `resolve_call`, dedupe, `call_not_ready`; flagged removal of payload-trusting bind and sessionless path | B4; gates G-V1…G-V6 (D-9) |
| B6 | Evidence references, history, feedback endpoints | B4 |
| B7 | Brain in PostgreSQL ([07](07-brain.md)): schema, importer, review/publish roles, projection loop, serve-time gate, tombstones, reconcile, quarantine, scope generation | B2, D-8 |
| B8 | Account deletion/export and retention jobs | B2–B6, D-4 |
| B9 | Authenticate `/vision-query`, `/upload`→internal, `/conversation/sessions`; SpacetimeDB retirement ([08](08-migration-and-spacetimedb.md)) | B5, iOS ready, D-3, D-6 |
| B10 | Staging and production pipeline, nightly dump, restore drill, alerts, runbooks | B1 |

Parallel: M3 corpus work after the B7 contract; iOS M4 consumes the contracts frozen at B2.

## Owner decisions

Architecture direction, technology choices, Track A/B and the V1 simplification of Brain restore
safety were **approved in principle by the owner on 2026-11-15**. Remaining items to resolve before
the decision records are marked `accepted` or the dependent PR starts:

| ID | Decision | Recommendation | Blocks |
| --- | --- | --- | --- |
| D-1 | PostgreSQL as the single store | Approve | ADR-0001, B1 |
| D-2 | Issuer and host: Supabase (Pro for production); confirm Apple Developer account and custom SMTP | Supabase | ADR-0002, B1–B2 |
| D-3 | Break legacy unauthenticated routes on a date agreed with the iOS worktree | Approve after B2 contract | B9 |
| D-4 | Retention: transcript text 90 days then metadata, no raw audio, audit 1 year, deletion grace 30 days | Approve | ADR-0009, B8 |
| D-5 | Backups: provider daily plus nightly external dump; PITR add-on yes or no | No PITR for pilot | ADR-0008 |
| D-6 | Export `hackutd` table counts read-only; approve retirement; owner decides on live database | Retire after export | ADR-0007, B9 |
| D-7 | Hosting: Render paid production instance and a staging instance; error-tracker vendor; budget (~$70–150/month) | Approve | ADR-0008, B10 |
| D-8 | Brain: serve-time PostgreSQL gate, tombstone-first withdrawal, quarantine and reapproval rule; pilot corpus and rights owner | Approve | ADR-0006, B7 |
| D-9 | One staging Vapi assistant and one live call to validate G-V1…G-V6 | Approve | ADR-0005 final, B5 |
| D-10 | Contract defaults D-06, D-07, D-09 | Approve | scope |
| D-11 | Track A may start after this PR merges; A1 first | Approved | — |

Standing constraints: the external reference checkout is never modified; no production
infrastructure change; no live database deletion.

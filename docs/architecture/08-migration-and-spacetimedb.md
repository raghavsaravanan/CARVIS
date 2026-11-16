# 08 — Migration invariants and SpacetimeDB retirement

## Is there SpacetimeDB data to preserve?

Code facts [V]: Python writes only the reducers `start_shop_query` and `record_shop_query_result`
from `/vision-query` (`backend/main.py:1345`), through one service identity that requires a
pre-existing `user_profile` with a shop. No Python or iOS code calls `registerOrUpdateProfile`,
invites or join reducers, and no iOS bindings exist.

The live `hackutd` database is **not** accessed by this work. Possibly valuable rows are limited to
(a) `user_profile`, `shop`, `shop_invite` created through some earlier client and (b) any
`vision_query` or `query_result` telemetry. **Owner action** (decision D-6): export the tables
read-only, store the export outside the repository, and report row counts per table.

Decision rule: demo/test rows only ⇒ archive the module at a git tag and the export, then retire.
Real people or shops present ⇒ a one-off reviewed import into `users`, `workspaces`, `memberships`
(people re-register through the identity provider; match on email only with consent). Deleting the
live database is the owner's action, never part of a PR.

## Invariants every migration PR must assert

1. No authoritative read path depends on SpacetimeDB at any step (test: run the suite with all
   `SPACETIMEDB_*` variables unset).
2. `/vision-query` status codes and response bytes are unchanged by telemetry removal (contract test).
3. Schema changes are expand → backfill → contract; no revision both adds and drops; no
   data-destroying DDL without a preflight query and a verified backup.
4. Every expand revision has a tested `downgrade()`; contract revisions are forward-only and require a
   pre-contract backup and explicit owner approval.
5. `vehicle_snapshots`, `document_revisions`, `review_decisions`, `audit_events` reject UPDATE/DELETE
   through the application role.
6. Every table with `workspace_id` has RLS enabled and forced (catalog check).
7. The Alembic history is linear (CI check).

## Rollback tests (CI, real PostgreSQL, no mocks)

1. `upgrade head → downgrade base → upgrade head` yields an identical schema (`pg_dump --schema-only` diff).
2. Revision N is applied to a seeded database with representative rows, then downgraded; version N-1
   application tests pass (old code runs on the new schema).
3. The previous application image boots against schema N and passes smoke and contract tests.
4. A backup is restored into staging and timed (release gate G4).
5. Feature-flag-off paths for telemetry removal and legacy routes are exercised.

## Retirement steps (separate PRs, reversible until the last)

1. Flag SpacetimeDB telemetry off (default off); suite green.
2. Remove the reducer calls and the helper in `backend/main.py`.
3. Remove the `SpacetimeDB typecheck` CI job and update the required-checks list in
   [`../development-workflow.md`](../development-workflow.md) (owner admin action on branch protection).
4. Tag the archive, then delete `backend/spacetimedb/` and update `AGENTS.md`,
   `backend/spacetimedb/AGENTS.md` references and `docs/backend/architecture.md`.
5. The owner decides what to do with the live `hackutd` database.

No dual write is needed; nothing authoritative lives in SpacetimeDB.

## Current-state mapping (expand/contract)

| Today | Target | Step |
| --- | --- | --- |
| In-memory `ConversationStore`, `_calls` | `conversations`, `calls`, `turns`, `webhook_events` behind the same store interface | Track B4 then B5 |
| iOS `account.json`, car, history, job JSON | Identity provider, `/v1/me`, `/v1/vehicles`, `/v1/conversations` | iOS M4 against B2–B6 contracts |
| Qdrant-only review state | PostgreSQL decisions plus Qdrant projection | Track B7 |
| SpacetimeDB telemetry | `turns`, `audit_events` | Track B9 |

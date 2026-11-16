# 0007. Retire SpacetimeDB

- **Status:** proposed
- **Date:** 2026-11-15
- **Resolves:** PRD open decision on realtime store; contract D-08
- **Supersedes:** none

## Context

SpacetimeDB is described as the retained realtime module in [`../../AGENTS.md`](../../AGENTS.md) but
holds only best-effort telemetry from `/vision-query` through one service identity, with no iOS
bindings or approved deployment, a reducer-name mismatch of unconfirmed effect, and no authorization
tests (typecheck only). See [`../architecture/08-migration-and-spacetimedb.md`](../architecture/08-migration-and-spacetimedb.md).

## Options considered

Retain and integrate (second identity system beside FastAPI; no relational constraints/migrations
story); retain as telemetry only (carries risk, no value); retire.

## Decision

Retire it in staged, reversible PRs after the owner exports the live database counts read-only
(D-6): telemetry flag off, remove calls, remove the CI job, archive at a git tag and delete the
module, update documents. The live `hackutd` database is never deleted by a PR.

## Consequences

Removes a required CI check (owner updates branch protection) and a dependency. Rollback: revert the
PRs; no data is lost because nothing authoritative is stored.

## Verification

Suite green with `SPACETIMEDB_*` unset; `/vision-query` contract test unchanged; gate G12.

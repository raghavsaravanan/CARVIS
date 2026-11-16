# 0006. CARVIS Brain: PostgreSQL authority, Qdrant projection, fail-safe restore

- **Status:** proposed
- **Date:** 2026-11-15
- **Resolves:** PRD CAR-030–038; contract D-10
- **Supersedes:** none

## Context

Review decisions currently live only in Qdrant payloads and a free-text reviewer string. A
PostgreSQL restore to before an evidence withdrawal could leave both stores agreeing on an obsolete
verified state. The deterministic verifier must be preserved.

## Options considered

| Option | Assessment |
| --- | --- |
| Qdrant as source of truth | No transactions, no audit joins |
| PostgreSQL authority, Qdrant projection, serve-time gate | Chosen |
| Add an external append-only hash-chained ledger | Stronger but adds infrastructure; deferred as an additive option |
| Reapproval and quarantine on any restore, with Qdrant tombstones as a second witness | Chosen for V1 |

## Decision

PostgreSQL holds documents, revisions, evidence state and append-only decisions. Evidence is spoken
only if Qdrant returns it **and** PostgreSQL says verified with a matching digest. Withdrawals write a
Qdrant tombstone first (never deleted) and bump a `brain_control` decision counter, then commit
PostgreSQL. Detected or announced restore ⇒ quarantine (`brain_unavailable`), trust-reducing-only
reconciliation, mandatory reapproval where continuity cannot be proven, exit by explicit publisher
action. Withdraw reasons distinguish non-blocking removals from `suspect_conflict` blockers so removal
never turns a conflict into a confident answer. Full design:
[`../architecture/07-brain.md`](../architecture/07-brain.md). Not chosen for V1: an external ledger.
Accepted residual risk: a silent double rollback with no operator action.

## Consequences

Adds a PostgreSQL query on the serve path (indexed, one round trip) and a small projection loop.
Rollback: the serve-time gate can be disabled by flag only with owner approval; the unchanged Python
verification remains authoritative either way.

## Verification

Restore drill (G14), tamper, outage, conflict and procedure-completeness tests listed in the
architecture document, plus the existing verification suites unchanged (G2).

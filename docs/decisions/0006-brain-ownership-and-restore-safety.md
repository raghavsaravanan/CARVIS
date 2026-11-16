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

PostgreSQL holds documents, revisions, evidence state and append-only decisions.

**Serve-time invariant.** An evidence record is spoken only if, in **both** stores, (1) status is
active/verified, (2) the payload digest matches, (3) `state_version` is equal, and (4) no tombstone
with `state_version` at least PostgreSQL's exists. A tombstone blocks the answer by itself, even if the
PostgreSQL withdrawal transaction failed. Reading either store failing yields `brain_unavailable`.

**Tombstones and counter.** Withdrawal writes the tombstone and `intent_seq` first, commits PostgreSQL
(`decision_seq`), then writes `committed_seq`. Tombstones and the counter live in an alias-independent
control collection (`carvis_brain_control`) that alias swaps, rebuilds and `assert_staging` never touch;
nothing deletes from it. Generation activation is aborted if the candidate generation contradicts a
tombstone, PostgreSQL `state_version`, or the counter. Mismatches fail closed: per-evidence block for
version, digest or tombstone mismatches; global quarantine when PostgreSQL is older than `committed_seq`,
the control collection is older, missing or unreadable, or either store is unreachable.

**Restore.** Announced or detected restore ⇒ quarantine (`brain_unavailable`), trust-reducing-only
reconciliation, mandatory reapproval where continuity cannot be proven, exit by explicit publisher
action. Withdraw reasons distinguish non-blocking removals from `suspect_conflict` blockers so removal
never turns a conflict into a confident answer. Full design:
[`../architecture/07-brain.md`](../architecture/07-brain.md). Not chosen for V1: an external ledger.
Accepted residual risk: a silent double rollback of PostgreSQL and the control collection with no
operator action.

## Consequences

Adds one indexed PostgreSQL query and one batched control-collection read on the serve path, and a small projection loop.
Rollback: the serve-time gate can be disabled by flag only with owner approval; the unchanged Python
verification remains authoritative either way.

## Verification

Restore drill (G14); the 12 serve-time, tombstone and alias-swap acceptance cases, and the tamper,
outage, conflict and procedure-completeness tests, listed in the architecture document; plus the existing verification suites unchanged (G2).


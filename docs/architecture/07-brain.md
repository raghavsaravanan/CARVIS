# 07 — CARVIS Brain: ownership, evidence lifecycle, restore safety

## Ownership

PostgreSQL is the only source of truth for source documents, revisions, evidence state, review
decisions and coverage. Qdrant is a rebuildable projection (payload: `evidence_id`, `state_version`,
`payload_digest`, `scope`, applicability fields) and never holds identity, decisions or transactions.
Global versus shop-specific access is explicit: `source_documents.scope` (global or workspace) with a
server-derived `brain_scopes` filter. `rights_basis` is mandatory before activation (contract D-10: a
subscription is not permission to process or present content). Operator workflows stay CLI plus
internal API; no mechanic-facing administration.

The existing ingestion and review tooling (`backend/ingest.py`, `backend/migrate_v2.py`) is kept; it
gains Postgres-backed decisions and an authenticated reviewer identity.

## Serve-time rule (intersection)

An evidence record may be spoken only if **both** hold:

- (a) Qdrant returns it from the exact-filter set with a valid `verification_digest` (existing code,
  unchanged), and
- (b) PostgreSQL says `state = 'verified'` and `payload_digest` equals the point's digest.

After the existing exact-filter `scroll`, candidate point IDs are checked with one indexed
PostgreSQL query:

| Candidate status in PostgreSQL | Outcome |
| --- | --- |
| verified, digest matches | continues to the unchanged `evaluate_candidates` |
| withdrawn with reason `incorrect_extraction`, `superseded` or `rights` | removed **before** conflict evaluation |
| withdrawn with reason `suspect_conflict`, `quarantined`, unknown, or digest mismatch | **blocker**: the scope refuses (`conflict` or `unverified`) |
| PostgreSQL unreachable | `unverified` refusal; never a guess |

Python verification stays authoritative; this gate adds a check and never relaxes one. Removal
happens before the unchanged conflict, applicability and procedure-completeness logic, so removing
one step makes a procedure `incomplete`, and removing one of two conflicting records still refuses
unless the withdrawal reason is non-blocking.

## Activation (two-phase, idempotent)

1. Reviewer decision `verify` (append-only, digest-bound to the source PDF as today, source
   confirmed, rights basis present) increments `state_version` and enqueues a `projection_jobs` row in
   one transaction.
2. The projection loop writes the point to the staging collection with a deterministic point ID and
   marks the job done only after a read-back.
3. The publisher (a different role from the reviewer) runs the existing validate and atomic alias
   activation. Until the alias targets the validated generation, nothing new is served.

## Withdrawal (Qdrant tombstone first, never deleted)

Order: (a) set the Qdrant payload `status=withdrawn`, `state_version=n` and increment the
`brain_control` decision counter (synchronous; failure aborts and is shown to the operator),
(b) commit PostgreSQL (`state`, `withdraw_reason`, append-only decision, `system_meta.decision_seq`),
(c) audit event. Withdrawn points are **kept** in Qdrant as tombstones. Because Qdrant always holds a
withdrawal at least as new as PostgreSQL, a PostgreSQL restore to before the withdrawal is detectable.
Historical `evidence_references` remain and render "source withdrawn".

## Reconciliation

`brain reconcile` (CLI, plus a scheduled tick in the worker loop, and after each publish) compares
PostgreSQL and Qdrant per `(point_id, state_version, digest, status)`:

- missing in Qdrant: alert; not served (safe)
- present in Qdrant but not verified in PostgreSQL: not served (gate); the job removes or tombstones
- digest or version mismatch: evidence set to `quarantined`; operator alert
- auto-repair only moves toward **less** trust (apply tombstones into PostgreSQL as
  `restored_from_qdrant` withdrawals; quarantine mismatches). Moving toward more trust is never
  automatic.

## Restore safety (V1, intentionally minimal)

Hazard: a PostgreSQL restore to a point before a withdrawal, with Qdrant also still showing the record
as verified, would make both stores agree on an obsolete state. The intersection rule alone does not
prevent this, so V1 adds a second witness without new infrastructure:

1. **PostgreSQL is authoritative**, protected by provider backups plus the nightly independent dump
   ([09-deployment-operations.md](09-deployment-operations.md)).
2. **Qdrant tombstones plus a control record.** A single point `brain_control` holds
   `{decision_seq, updated_at}`, incremented on every Brain decision together with the tombstone or
   verify write; PostgreSQL keeps `system_meta.decision_seq`, updated in the same transaction.
   `pg.decision_seq < qdrant.decision_seq`, or any `qdrant.status=withdrawn` while PostgreSQL says
   `verified`, or a higher Qdrant `state_version`, proves PostgreSQL is older than a decision.
3. **Quarantine mode.** Set by the deploy flag `CARVIS_BRAIN_MODE=quarantine` (outside both stores) or
   automatically on the mismatch above, checked at boot and on every reconciliation tick. Technical
   lookups return `brain_unavailable`; sign-in, Garage, history and feedback keep working.
   **Runbook rule: set quarantine before ANY PostgreSQL restore, PITR or failover, or Qdrant snapshot
   restore.**
4. **Reapproval where history cannot be trusted.** After a restore, every verified record whose
   withdrawal history cannot be established, meaning continuity of `decision_seq` and `state_version`
   between the two stores is not proven, becomes `quarantined` and needs a fresh reviewer decision
   (digest re-bound to the source PDF through the existing CLI). The V1 corpus is small, so full
   re-review is the accepted worst case.
5. **Exit quarantine** only when reconciliation shows zero discrepancies, `decision_seq` is equal in
   both stores, the acceptance suite passes on a collection rebuilt from reconciled PostgreSQL, and
   the publisher records an exit audit event.
6. **Residual risk (stated):** a silent, simultaneous rollback of both stores to an older consistent
   state with no operator action is undetectable by software. It is mitigated by the mandatory
   quarantine-on-restore rule and by recording the latest `decision_seq` in the ops log after each
   publish. If scale or risk later warrants it, an external append-only record can be added without
   changing this design (additive).

## Scope schema generation

An explicit `scope` payload field (`global` or workspace ID) is added alongside the existing `shop_id`
as an additive schema generation, activated only through the full acceptance suite
(`backend/tests/fixtures/wrx-acceptance.json` plus new global/shop cases). The existing
"no cross-vehicle or shop fallback" tests are extended to global-versus-shop.

## Tests

- Crash between activation steps 1 and 2 ⇒ not served; reconciliation re-queues.
- Withdraw with Qdrant unreachable ⇒ withdrawal aborts, nothing half-applied.
- Tamper with a Qdrant payload ⇒ refusal. PostgreSQL down ⇒ refusal, not a guess.
- PITR-simulated restore to before withdrawal W with Qdrant intact ⇒ automatic quarantine; W's scope
  refuses; reconcile re-applies W; refusal persists until exit.
- Qdrant restored from an older snapshot (restore flag set) ⇒ quarantine.
- Both stores restored to the same older point with the flag set ⇒ all verified evidence quarantined
  until reapproved.
- Reconciliation never promotes trust; `decision_seq` mismatch detected at boot; quarantine flag works
  with both stores healthy.
- Conflict handling: A and conflicting B verified ⇒ refuse; B withdrawn `superseded` ⇒ answers from A;
  B withdrawn `suspect_conflict` ⇒ still refuse; one procedure step withdrawn ⇒ `incomplete`;
  withdrawn plus quarantined mix ⇒ refuse; all candidates withdrawn ⇒ `unavailable`.
- Missing `rights_basis` ⇒ activation blocked; global versus shop scope isolation.

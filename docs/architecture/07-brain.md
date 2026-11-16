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

An evidence record may be spoken only if **all** of the following hold, evaluated per record, in
**both** stores:

1. **Active/verified status:** PostgreSQL `state = 'verified'` **and** the Qdrant point payload has
   `status = 'verified'` (existing `verification_status` check, unchanged).
2. **Digest:** PostgreSQL `payload_digest` equals the Qdrant payload digest, and the existing
   `verification_digest == evidence_digest()` check passes.
3. **Compatible state version:** PostgreSQL `state_version` **equals** the Qdrant payload
   `state_version`. Any inequality, in either direction, is a mismatch (see the fail-closed table).
4. **No blocking tombstone:** the alias-independent control collection (see "Tombstones and the
   decision counter") holds no tombstone for this `evidence_id` whose `state_version` is **greater than
   or equal to** the PostgreSQL `state_version`. A tombstone **blocks the answer by itself**, even if
   the PostgreSQL withdrawal transaction failed or PostgreSQL still says `verified`.

After the existing exact-filter `scroll`, the candidate IDs are checked with one indexed PostgreSQL
query and one batched read of the control collection (two reads, no per-record round trips).

| Candidate status | Outcome |
| --- | --- |
| All four conditions hold | continues to the unchanged `evaluate_candidates` |
| Withdrawn in PostgreSQL with reason `incorrect_extraction`, `superseded` or `rights`, and a matching tombstone | removed **before** conflict evaluation |
| Withdrawn with reason `suspect_conflict`, or `quarantined`, or unknown to PostgreSQL | **blocker**: the scope refuses (`conflict` or `unverified`) |
| Any condition above fails (digest, status, version mismatch, tombstone with no matching PostgreSQL withdrawal) | **blocker** for the evidence's scope: `unverified` refusal; evidence flagged for reconciliation |
| PostgreSQL unreadable, control collection unreadable or missing | `brain_unavailable` refusal (global fail closed); never a guess |

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

Order, for a withdrawal that moves evidence from `state_version = n` to `n+1`:

1. **Tombstone and intent (synchronous; failure aborts the withdrawal):** write the tombstone for the
   evidence (`state_version = n+1`, `reason`) and set control `intent_seq = S+1` in the control
   collection.
2. **PostgreSQL commit:** `state`, `withdraw_reason`, the append-only decision, `state_version = n+1`
   and `system_meta.decision_seq = S+1`, in one transaction.
3. **Commit marker:** set control `committed_seq = S+1` (retried by reconciliation if it fails), then
   write the audit event.

If step 2 fails or the process dies after step 1, the tombstone remains. The evidence is **blocked**
(serve-time condition 4) while PostgreSQL still says `verified`, and reconciliation reports an
unresolved intent (`intent_seq > committed_seq`). The operator either retries the withdrawal (completes
step 2) or explicitly cancels it with a new reviewer decision that raises `state_version` above the
tombstone's (`reapprove`); nothing resumes automatically. A failed PostgreSQL transaction therefore
never un-blocks anything. Withdrawn points and tombstones are **never deleted**. Historical
`evidence_references` remain and render "source withdrawn".

## Tombstones and the decision counter survive collection alias swaps

The serving collection is replaced by alias swaps (`carvis_specs_active`, existing
`migrate_v2.py activate`), so tombstones and the counter must not live there. They live in a dedicated
**control collection** `carvis_brain_control`:

- **Not aliased, not swapped, not rebuilt.** Alias activation, `assert_staging` and the rebuild tooling
  never target it; only the Brain decision commands write to it, and nothing deletes from it.
- **Contents:** one tombstone point per withdrawn evidence (point ID = deterministic UUID of the
  `evidence_id`; payload `state_version`, `reason`, `digest`, `ts`) and one singleton control point
  `{intent_seq, committed_seq, generation_epoch}` (`committed_seq` mirrors PostgreSQL `decision_seq`).
- **Serve-time reads it directly** (batched by evidence ID), independent of whichever generation the
  alias currently targets. A swap therefore cannot drop a tombstone or reset the counter.
- **Generation build and activation guards:** a new generation is built from PostgreSQL and also copies
  every tombstone into the point payload (`status=withdrawn`) as defense in depth. `validate` and
  `activate` additionally require that (i) every tombstoned `evidence_id` is absent or `withdrawn` in
  the candidate generation, (ii) every candidate-generation point has `state_version` equal to
  PostgreSQL's, and (iii) the control singleton is readable with `committed_seq` equal to
  PostgreSQL's `decision_seq` (or `intent_seq` still pending and explicitly acknowledged). Any failure
  aborts activation; the alias is unchanged.
- **Restore of the control collection itself** (snapshot restore, recreation, emptied) is a restore
  event: quarantine, with the same procedure as below. A missing or empty control collection with a
  non-zero PostgreSQL `decision_seq` is a mismatch, never a "no tombstones" state.

## Mismatches fail closed

| Observation | Meaning | Result |
| --- | --- | --- |
| Tombstone `state_version` ≥ PostgreSQL's for that evidence | Withdrawal in flight, PostgreSQL failed, or PostgreSQL restored older | That evidence blocked; scope refuses; reconcile |
| Qdrant payload `state_version` ≠ PostgreSQL's | Stale projection or restored store | That evidence blocked (`quarantined` by reconciliation) |
| Payload digest ≠ PostgreSQL digest | Tampering or partial write | That evidence blocked and `quarantined` |
| `pg.decision_seq` < control `committed_seq` | PostgreSQL is older than a committed decision | **Global quarantine** (`brain_unavailable`) |
| Control `committed_seq` < `pg.decision_seq` and `intent_seq` < `pg.decision_seq` | Control collection older than PostgreSQL (restored or lost) | **Global quarantine** |
| Control `intent_seq` > `committed_seq` with `pg.decision_seq` = `committed_seq` | A decision started but not committed | Per-evidence block only (no global quarantine); operator action |
| Control collection or PostgreSQL unreachable, or control point missing | Cannot prove state | **Global quarantine** |
| Candidate generation fails any activation guard | Unsafe swap | Activation aborted; alias unchanged |

Only reconciliation that moves toward **less** trust runs automatically; clearing a block requires a
reviewer decision that raises `state_version` above any tombstone.

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
2. **Qdrant tombstones plus a control record**, both in the alias-independent control collection
   `carvis_brain_control` (see above), with the intent/commit protocol: `pg.decision_seq <
   control.committed_seq`, or a tombstone whose `state_version` is at least PostgreSQL's while
   PostgreSQL says `verified`, proves PostgreSQL is older than a decision (or a withdrawal is in
   flight). Both cases fail closed per the mismatch table.
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

### Serve-time invariant, tombstone and alias-swap acceptance cases

Each case runs against real PostgreSQL and a Qdrant test instance, asserts the user-visible outcome
(refusal reason or answer) and that no unverified value is ever spoken.

1. **Status:** PostgreSQL `verified`, Qdrant payload not verified ⇒ refuse; reverse ⇒ refuse.
2. **Digest:** payload digest differs from PostgreSQL's (tampered or partial write) ⇒ refuse; evidence
   `quarantined` by reconciliation.
3. **State version:** Qdrant `state_version` lower than PostgreSQL's ⇒ refuse; higher ⇒ refuse; equal ⇒
   answers.
4. **Tombstone blocks despite PostgreSQL failure:** withdrawal step 1 succeeds, step 2 (PostgreSQL
   commit) fails or the process is killed ⇒ evidence still `verified` in PostgreSQL yet the answer
   refuses; reconciliation reports the pending intent; retrying the withdrawal completes it;
   cancelling requires a `reapprove` decision with a higher `state_version`.
5. **Tombstone, PostgreSQL restored older:** tombstone `state_version` ≥ PostgreSQL's ⇒ evidence
   blocked; with `pg.decision_seq` < `committed_seq` ⇒ global quarantine (`brain_unavailable`).
6. **Alias swap preserves tombstones and counter:** withdraw evidence W, then run validate/activate to a
   new generation ⇒ W still refuses, control collection untouched, counters unchanged; a generation
   built from PostgreSQL carries W as withdrawn.
7. **Unsafe swap aborted:** candidate generation containing a tombstoned evidence as verified, a point
   with `state_version` ≠ PostgreSQL's, or a control singleton whose `committed_seq` ≠ PostgreSQL's
   `decision_seq` ⇒ `activate` fails and the alias is unchanged.
8. **Control collection lost/emptied/restored older:** missing, empty (with non-zero `decision_seq`),
   unreadable, or older than PostgreSQL beyond `intent_seq` ⇒ global quarantine; nothing is served
   until the exit procedure completes.
9. **Failure to read either store:** PostgreSQL down, control collection down, or control point missing
   ⇒ `brain_unavailable`, never an answer from one store alone.
10. **No auto-promotion:** reconciliation never clears a tombstone or raises trust; only a reviewer
    decision raising `state_version` above the tombstone re-enables the evidence.
11. **Commit marker failure:** step 3 (`committed_seq`) fails after PostgreSQL commit ⇒ evidence stays
    withdrawn, no global quarantine (`pg.decision_seq` ≤ `intent_seq`); reconciliation repairs the marker.
12. **Conflict preserved:** a tombstone-blocked record in the applicable scope is a blocker (not silently
    removed) unless its withdrawal is committed in PostgreSQL with a non-blocking reason.

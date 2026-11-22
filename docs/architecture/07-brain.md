# 07 — CARVIS Brain: ownership, evidence lifecycle, knowledge model, restore safety

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

## Serve-time rule (authoritative scope, then intersection)

Status: ADR-0006 and ADR-0010 are `proposed` (roadmap D-8 open). The PostgreSQL-first scope below
was approved in principle by the owner on 2026-11-22 (roadmap D-13); final evidence-policy sign-off
is pending. It replaces the earlier candidate-first description, in which the Qdrant exact-filter
`scroll` produced the candidates and only those were checked in PostgreSQL. That description no
longer applies: a record missing from the projection must never hide a conflict, a withdrawal or a
missing procedure step.

Evaluation order for one resolved query (confirmed vehicle snapshot, server-derived `brain_scopes`,
resolved subject, operation, property and position):

1. **Authoritative scope (PostgreSQL first, read first).** One read-only transaction at
   `REPEATABLE READ` enumerates the applicable scope conservatively: every evidence record for the
   resolved subject (through reviewed aliases and across all revisions of the same source) whose
   applicability matches the confirmed snapshot, **plus its dependency closure** (procedure steps,
   prerequisite specifications, linked warnings), in any state, with `state_version`,
   `payload_digest`, withdrawal reason and publication status (whether its decision is in the
   generation the serving alias activated, as recorded in PostgreSQL), plus
   `system_meta.decision_seq`. Applicability is exact: an attribute the record requires that the
   snapshot lacks is unknown, not a wildcard, and yields `clarification`. More than **256** records
   in the scope, dependency closure included, refuses with today's `clarification` ("narrow the
   component and operation"); the set is never truncated.
2. **Projection completeness, both directions.** (a) Every *verified and published* authoritative
   record must have a matching serving point (conditions 1 to 3 below); missing or stale is a
   **blocker** for its scope (`unverified`) and is flagged for reconciliation. (b) The same exact
   filter is enumerated in the serving collection (at most 256 points, as today); any point that is
   not a verified and published authoritative record is a **blocker** (`unverified`): it means the
   projection is ahead of PostgreSQL or PostgreSQL was restored older, and reconciliation runs.
3. **Control witness, after the snapshot.** The read order is fixed: PostgreSQL snapshot, then the
   serving-collection read, then one batched control-collection read for every authoritative
   evidence ID, compared against the captured `state_version` (condition 4 below) and the snapshot
   `decision_seq` (mismatch table). A withdrawal writes its tombstone before its PostgreSQL commit,
   so one that started before the control read is caught by the snapshot or by the tombstone.
4. **Evaluation over the authoritative set, not the top results.** Conflict, applicability,
   procedure-completeness and dependency checks run over every authoritative record not removed by
   the table below. A missing required step or dependency is `incomplete`; an unresolved conflict is
   `conflict`.
5. **Final witness before release.** Immediately before the compiled answer is released for
   delivery, the control singleton is read again. If `intent_seq` or `committed_seq` changed since
   step 3, the evaluation reruns once; a second change refuses (`unverified`). Residual (stated): a
   withdrawal that starts after the final witness, while speech is already playing, is not recalled
   from audio; the answer's evidence reference then renders "source withdrawn" in history.
6. **Discovery and ranking.** Lexical or dense discovery may only propose a subject or operation
   mapping, which re-enters step 1, or order equivalent citations inside the evaluated set. It never
   adds a record, removes one, or chooses the scope (see "Retrieval layers").

The gate has no bypass for technical answers: if it cannot run, the outcome is `brain_unavailable`
(quarantine). This replaces the "disable the gate by flag" rollback in proposed
[ADR-0006](../decisions/0006-brain-ownership-and-restore-safety.md) for the serve path
([ADR-0010](../decisions/0010-brain-knowledge-model-and-retrieval.md)).

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

The reads are one PostgreSQL snapshot query, one serving-collection read, one batched control read
and the final control-singleton read (no per-record round trips).

| Authoritative record status | Outcome |
| --- | --- |
| All four conditions hold | continues to the unchanged `evaluate_candidates` |
| `verified` and published, but missing or stale in the projection | **blocker** for its scope: `unverified`; flagged for reconciliation |
| `verified` but not yet published (activation pending) | does not authorize; **blocks** only if it conflicts with the answer or is a required step or dependency of it |
| `pending` or `rejected` | not evidence: neither authorizes nor blocks (review only) |
| Serving point in scope that is not a verified and published authoritative record | **blocker**: `unverified`; reconciliation |
| Withdrawn in PostgreSQL with reason `incorrect_extraction`, `superseded` or `rights`, and a matching tombstone | removed **before** conflict evaluation |
| Withdrawn with reason `suspect_conflict`, or `quarantined`, or unknown to PostgreSQL | **blocker**: the scope refuses (`conflict` or `unverified`) |
| Any condition above fails (digest, status, version mismatch, tombstone with no matching PostgreSQL withdrawal) | **blocker** for the evidence's scope: `unverified` refusal; evidence flagged for reconciliation |
| Scope larger than 256 records, dependency closure included | `clarification` (narrow the component and operation), as today; never truncated |
| Control singleton changed between step 3 and the final witness, twice | `unverified` refusal |
| PostgreSQL unreadable, control collection unreadable or missing, projection unreadable | `brain_unavailable` refusal (global fail closed); never a guess |

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

## Knowledge model (logical)

Physical tables, indexes and API payloads are designed in roadmap B7a under bounded review; this is
the logical contract they must satisfy ([ADR-0010](../decisions/0010-brain-knowledge-model-and-retrieval.md)).

- **Source document and revision:** origin, rights basis and permitted processing and presentation,
  `global` or workspace scope, source hash, revision, integrity.
- **Source fragment:** original text, table, row, page, section, warning or figure locator, parser
  and extraction version, exact link to the source revision.
- **Entity and terminology:** canonical component, system, tool or identifier; scoped, reviewed
  aliases; typed relationships. An actuator is not an alias for its whole system.
- **Applicability:** explicit configuration (market, engine, transmission, trim, equipment, build or
  VIN constraints where required). Unknown is never a wildcard; a VIN decode is not sufficient for
  every variant.
- **Specification:** subject, operation, property, position, raw and decimal value, unit, range,
  limit, tolerance or ordered torque-angle sequence, conditions and warnings, at source precision.
  Only deterministic, explicitly supported unit conversions.
- **Procedure:** prerequisites, tools, warnings, ordered steps, conditional branches, dependencies
  and linked specifications; completeness is checked as a group.
- **Manufacturer communication (conditional V1 enhancement):** type, attribution, applicability,
  date or revision, documented conditions and limits. A TSB is not a recall; neither proves a fault
  or an open campaign on an individual vehicle; no automatic diagnosis.
- **Reviewed relationships**, only as needed: `part_of`, `alias_of`, `applies_to`, `requires`,
  `precedes`, `references`, `supersedes`. A statistical association is discovery only, never proof.
- Review decisions, evidence versions, immutable answer evidence references and coverage entries
  (existing entities; [03-data-model.md](03-data-model.md)).

Only accepted evidence authorizes a technical claim. Verified facts, attributed manufacturer
communications, technician observations, shop records, visual hypotheses, statistical associations,
AI inference and pending extractions stay distinguishable; observation or assistant history is never
proof that a repair was performed.

## Knowledge construction (operator only)

Register the source and its permitted processing **before** upload or any third-party transmission;
parse into page-, section- and table-aware fragments; normalize without losing the original
representation; extract typed `pending` records; resolve reviewed terminology and dependencies;
validate layout, values, applicability, revisions, conflicts and completeness; a qualified reviewer
compares against the original; digest-bound review decision; build and validate the projection;
the publisher activates; publish the coverage manifest; monitor gaps and supersede, withdraw or
reconcile.

- Structured JSON or CSV maps directly through the validated schema. Digital PDFs use the existing
  LlamaParse adapter; complex or scanned tables use review and exact source transcription. Diagrams
  keep their location and references, never an automatic mechanical interpretation.
- No cloud parser and no external model receives a source, shop data or restricted content without
  source-specific permission. Docling is a conditional alternative, adopted only if measured
  extraction quality or cost warrants it.
- Normalization preserves technical forms (`3.5 L`, `P0302`, `10.5 Ω`, `M12 × 1.5`, `90° + 45°`),
  left/right and front/rear, sign, decimal, range and tolerance, units, row and column association,
  warning scope and heading context; ingestion and query normalization use the same rules.
- The original source is the evidence, not the generated extraction. Synthetic fixtures are never
  published to a real pilot scope.

## Retrieval layers

1. **Structured exact retrieval** over the authoritative scope (above). Always on.
2. **Reviewed aliases and technical lexical matching** for discovery of the subject and operation.
3. **Dense semantic discovery** (existing `BAAI/bge-small-en-v1.5` embeddings) as an optional,
   measured enhancement.

Layers 2 and 3 only help find the scope or choose a citation; they never authorize, add or remove
evidence. Adopting layer 2, layer 3 or any rank fusion requires the bounded R3 comparison
([12-m2-roadmap.md](12-m2-roadmap.md), "R3"); until then the existing baseline is retained.

## Outcomes and response compiler

Outcomes: `verified`, `clarification`, `unsupported`, `incomplete`, `conflict`, `unverified`,
`brain_unavailable`. A partial answer is allowed only when it is independently verified and
explicitly scoped; a safety-critical procedure is never partial while presented as complete.
Ambiguity is never resolved by guessing. A vehicle switch invalidates derived facts and pending
responses.

A deterministic compiler builds each answer from approved facts, units, conditions and citations
into one versioned answer from which both the spoken and the displayed output derive. An LLM may
interpret the question or phrase the delivery; it cannot override the gate or supply a critical
value, unit, condition, step or refusal. Each answer records the exact source and record versions;
withdrawn evidence remains in history marked withdrawn and is never reused as active guidance.
Source deletion and retention rights are respected; revocation metadata is kept without retaining
restricted content.

## Spoken-output integrity (V1 release gate)

Approved by the owner on 2026-11-22 as a mandatory V1 release gate (roadmap D-14). Actual technical
speech must preserve the server-approved facts, units, qualifications and refusal outcomes,
including after interruption, retry and vehicle switch. A prompt instruction is not assurance: the
gate is validated against real spoken output on staging (B5, D-9; a live staging call still needs
its own owner approval) and on physical devices (M5). If the voice provider cannot deliver
controlled critical content reliably, CARVIS adds a controlled speech-delivery path or blocks
technical voice release; verification is never relaxed.

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

### Authoritative-scope acceptance cases

13. **Missing projection hides nothing:** record B is `verified` in PostgreSQL and conflicts with A,
    but B has no projection point ⇒ the scope refuses (`unverified`); B is flagged for
    reconciliation.
14. **Conflict outside the ranked results:** a conflicting verified record ranked below any top-k
    cut-off still blocks (`conflict`); ranking cannot remove it.
15. **Missing step projection:** a required procedure step is verified in PostgreSQL but absent
    from the projection ⇒ no complete procedure is spoken (`unverified` or `incomplete`).
16. **Scope limit:** 257 applicable records, dependency closure included ⇒ `clarification`; no
    truncated answer.
17. **Withdrawal race:** a withdrawal's tombstone is written after the PostgreSQL snapshot but
    before the control read ⇒ the record is blocked; a decision committed between the control read
    and the final witness ⇒ rerun, and a second change ⇒ `unverified`.
18. **Pending is inert:** a `pending` record neither authorizes an answer nor blocks a verified one;
    a verified but unpublished record blocks only when it conflicts or is a required step.
19. **Unknown applicability:** a record requiring an attribute the snapshot lacks ⇒
    `clarification`, never a wildcard match.
20. **Ranking boundary:** lexical or dense discovery that surfaces a record outside the
    authoritative set ⇒ never served; a proposed mapping re-enters scope enumeration.
21. **Reverse direction:** a serving point in scope with no verified and published PostgreSQL record
    (PostgreSQL restored older) ⇒ `unverified`; reconciliation runs.
22. **Dependency closure:** a prerequisite specification linked from a procedure is withdrawn with a
    blocking reason ⇒ the procedure refuses.

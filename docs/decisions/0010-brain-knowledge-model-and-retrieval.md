# 0010. Brain knowledge model, authoritative scope and benchmark-gated retrieval

- **Status:** proposed
- **Date:** 2026-11-22
- **Resolves:** nothing alone. Contributes to roadmap D-8 with
  [ADR-0006](0006-brain-ownership-and-restore-safety.md); D-8 stays open (it also covers the pilot
  corpus and rights owner). Covers PRD CAR-030–038, CAR-041, CAR-043.
- **Supersedes:** none. **Amends** proposed ADR-0006: its serve-path entry point (candidate-first
  query) and its "gate disabled by flag" rollback for the serve path.

## Context

ADR-0006 makes PostgreSQL authoritative for Brain state, but the serve-time rule in
[`07-brain.md`](../architecture/07-brain.md) took its candidates from the Qdrant exact-filter scroll,
so a verified, withdrawn or conflicting record missing from the projection was invisible. V1 also
needs a typed knowledge model, an operator ingestion pipeline and a retrieval approach for Tyler's
workflow (exact specifications, vehicle-specific service methods) without broad research or new
infrastructure. ADR-0001 (PostgreSQL as the canonical transactional and knowledge store) was
accepted by the owner on 2026-11-22.

## Options considered

| Option | Assessment |
| --- | --- |
| Keep candidate-first scope (Qdrant scroll, then check) | Projection gaps can hide conflicts, withdrawals and missing steps; rejected |
| PostgreSQL-first authoritative scope, Qdrant as projection plus control witness | Chosen; strictly stronger, no new infrastructure |
| Graph database or full ontology | Modeling and operations overhead with no demonstrated V1 need; deferred |
| ColBERT, SPLADE, GraphRAG or a custom sparse engine | No demonstrated V1 requirement; deferred |
| Structured exact retrieval plus optional reviewed-alias/lexical and dense discovery, adopted only by benchmark | Chosen |
| Replace LlamaParse with Docling now | Unmeasured benefit; conditional alternative only |

## Decision

- One Python/FastAPI modular monolith; PostgreSQL canonical for transactions and knowledge (ADR-0001,
  accepted); Qdrant a rebuildable projection plus the alias-independent control collection
  (ADR-0006); Vapi as conversational transport; Swift/SwiftUI on iOS. No new graph database,
  microservices or model training.
- The serve-time rule enumerates the full applicable scope, with its dependency closure, from one
  consistent PostgreSQL snapshot read first; checks projection completeness in both directions and
  the control witness in a fixed order, with a final witness before release; and evaluates
  conflicts, completeness and dependencies over that full set through one state-specific decision
  table and ordered evaluation stages (`pending` and `rejected` records inert; verified but
  unpublished records never authorize and block only through a material conflict or a required
  dependency), failing closed on size, missing or unknown projections and unreadable stores. The
  gate has no bypass for technical answers
  ([`07-brain.md`](../architecture/07-brain.md), "Serve-time rule"). Approved in principle by the
  owner on 2026-11-22 (roadmap D-13).
- The logical knowledge model, operator-only construction pipeline, outcomes and deterministic
  response compiler are as in [`07-brain.md`](../architecture/07-brain.md).
- Baselines: `BAAI/bge-small-en-v1.5` embeddings and the LlamaParse adapter, behind internal
  interfaces so either can be replaced.
- Discovery beyond structured exact retrieval (reviewed aliases and lexical matching, dense
  discovery, rank fusion) is adopted only through the bounded R3 comparison
  ([`12-m2-roadmap.md`](../architecture/12-m2-roadmap.md), "R3"), and never authorizes evidence.
- Spoken-output integrity is a V1 release gate (roadmap D-14).

## Consequences

- B7 splits into B7a–f ([`12-m2-roadmap.md`](../architecture/12-m2-roadmap.md)); no intermediate
  package serves new evidence.
- Retrieval cost: one snapshot query, one projection read and one control read per query; the
  256-record scope limit refuses rather than truncates.
- Untested targets (R3 thresholds, latency) stay labeled proposed until measured.
- Rollback: the design is additive; until B7f passes, the existing verified path keeps serving.
  After B7f, rolling back means quarantine (`brain_unavailable`), never serving without the gate.

## Verification

The authoritative-scope, tombstone, alias-swap and restore acceptance cases in
[`07-brain.md`](../architecture/07-brain.md) ("Tests") against real PostgreSQL and a Qdrant test
instance; the existing `test_specs_v2.py` and `test_ride_height.py` safety contract unchanged; the R3
safety suite with zero unsupported numerical, wrong-vehicle, conflicting or incomplete-as-complete
answers.

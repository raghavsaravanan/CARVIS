# CARVIS V1 backend architecture (milestone M1)

**Status:** proposed for owner review. Documentation only: no application code, migration, provider
configuration, or infrastructure changed in the PR that introduces these files. The owner approved
the direction in principle on 2026-11-15; each decision record stays `proposed` until the owner moves
it to `accepted` ([`../decisions/README.md`](../decisions/README.md)).

Authority: this set refines, and never overrides, [`../PRD.md`](../PRD.md) and the
[V1 Product Experience Contract](../product/v1-product-experience-contract.md) (§7 data/access, §8
V1 boundary, §11 M1 deliverables). It resolves contract decisions D-08 (single transactional store),
D-11 (identity/database vendors) and D-12 (retention) as **proposals** only.

## Evidence labels

| Label | Meaning |
| --- | --- |
| **[V]** | Verified in the repository code or tests during M1 |
| **[A]** | Taken from the historical [P0 audit](../audits/2026-11-15-p0-readiness-audit.md), not re-verified |
| **[W]** | Checked against vendor documentation during M1 (prices from third-party summaries are flagged) |
| **[R]** | Recommendation / design choice |
| **[?]** | Unverified assumption; an **implementation gate** until validated |

## Principles

Production-grade quality from day one, infrastructure sized for one initial tester, clean
architecture that scales without fundamental redesign, nothing more than necessary.

1. One transactional store (PostgreSQL). Qdrant is a rebuildable evidence projection; it never holds
   identity or transactions.
2. FastAPI is the single policy enforcement point; PostgreSQL row-level security (RLS) is a second
   layer, not a substitute.
3. Authority comes only from a verified principal and server-held state. Anything a client, a
   webhook payload, or an LLM can supply is untrusted correlation data.
4. The deterministic verified-answer pipeline (`backend/spec_retrieval.py`, `spec_schema.py`,
   `conversation.py` verification and refusal behavior) is preserved. Architecture adds checks; it
   never relaxes one.
5. Modular monolith, one container per environment, no microservices, no queue framework.
6. Every change ships as a small PR with tests first, a rollback, and independent review.

## Contents

| Document | Purpose |
| --- | --- |
| [01-current-state.md](01-current-state.md) | What the repository actually does today, with code references |
| [02-target-architecture.md](02-target-architecture.md) | Target design, flows, trust boundaries, external-reference review |
| [03-data-model.md](03-data-model.md) | ER diagram, field dictionary, constraints, retention |
| [04-identity-tenancy-rls.md](04-identity-tenancy-rls.md) | Authentication, authorization, RLS, roles, workers, `resolve_call` |
| [05-api-v1.md](05-api-v1.md) | Versioned iOS/backend contract |
| [06-vapi-ingress.md](06-vapi-ingress.md) | Webhook authentication, call binding, provider validation gates |
| [07-brain.md](07-brain.md) | CARVIS Brain ownership, evidence lifecycle, restore safety |
| [08-migration-and-spacetimedb.md](08-migration-and-spacetimedb.md) | Migration invariants, rollback tests, SpacetimeDB retirement |
| [09-deployment-operations.md](09-deployment-operations.md) | Environments, backups, costs, observability, privacy, runbooks |
| [10-threat-model-and-tests.md](10-threat-model-and-tests.md) | Threats, security acceptance tests, release gates |
| [11-traceability-matrix.md](11-traceability-matrix.md) | P0 requirement → screen → entity → endpoint → test |
| [12-m2-roadmap.md](12-m2-roadmap.md) | Track A / Track B PR sequence and owner decisions |

Decision records: [`../decisions/`](../decisions/) 0001–0009.

## Scope guard for V1

In: personal workspace plus operator-provisioned shop association, Garage, durable conversations,
evidence display, feedback, account deletion, internal Brain review through CLI/internal API, one
staging and one production environment, an independent nightly database dump.

Deferred: invitations/SSO/multi-organization UI, owner dashboards, usage billing, a generic job
queue, OpenTelemetry collectors, hybrid search/reranking, HA/multi-region, Brain upload UI, phone
camera input, a paid VIN-decode vendor. A PR that adds a table or service not required by a P0 row
in [11-traceability-matrix.md](11-traceability-matrix.md) needs written justification.

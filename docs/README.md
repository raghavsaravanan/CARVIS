# CARVIS documentation map

Start here. Engineering policy lives in [`../AGENTS.md`](../AGENTS.md) (with scoped
`AGENTS.md` files under `backend/`, `backend/spacetimedb/`, and `ios/`); this index only says where
each kind of document lives and which one wins when they disagree.

## Terminology and milestones

- **V1** is the first complete field-testable CARVIS release, deployed through TestFlight for Tyler.
  It is the only product version defined today.
- **M1–M5** are the engineering milestones that lead to V1. They are work stages, not product
  versions. [`PRD.md` §6.5](PRD.md#65-engineering-milestones-to-v1) is the authoritative definition.
- **P0** marks requirements mandatory in V1. **P1, P2, P3** are post-V1 priorities. They rank
  importance only; do not assign them product version numbers, release names (such as "V2" or
  "Release B"), or dates.
- A **document revision** (for example PRD revision 1.1) numbers edits to a document and is unrelated
  to V1. "v2" in Qdrant and schema documents (`carvis_specs_v2`, specification schema version 2)
  is a data-schema generation, not a product version.

| Milestone | Purpose |
| --- | --- |
| M1 — Production Architecture | Decide and document the V1 design before application code changes |
| M2 — Backend and Database | Authenticated, tenant-isolated, durable backend state |
| M3 — CARVIS Brain Pilot Configuration | Rights-cleared, reviewed, evaluated pilot knowledge corpus |
| M4 — Native iOS V1 | The five-destination iPhone application on real data |
| M5 — Deployment and TestFlight Validation | Stable release infrastructure and physical-device validation |
| V1 — Tyler Field Test | Tyler uses the TestFlight build; results measured against PRD §14 |

The release gates in [`PRD.md` §15](PRD.md#15-testflight-release-criteria) decide whether V1 is
ready; completing a milestone does not by itself establish readiness. The historical audit's
roadmap groups (its §9, A to D) correspond approximately to M1, M2, and M5 (group A), M3 (group B),
M4 (group C), and post-V1 work (group D); use the audit as a checklist of claims to re-verify, not
as a plan.

## Authority and precedence

| Question | Authoritative source | Status |
| --- | --- | --- |
| What must the product do? | [`PRD.md`](PRD.md) (document revision 1.1) | Product requirements authority |
| What exactly does the V1 pilot include? | [`product/v1-product-experience-contract.md`](product/v1-product-experience-contract.md) | Approved V1 pilot scope. Decisions D-06 to D-09 are proposed defaults and **D-11 (identity/database vendors) and D-12 (retention) remain open**; do not treat them as resolved |
| What did the repository look like on 2026-11-15? | [`audits/2026-11-15-p0-readiness-audit.md`](audits/2026-11-15-p0-readiness-audit.md) | Historical snapshot, not current truth |
| What does the code do now? | The code and its tests | Implementation truth |
| How do we branch, test, review, coordinate agents, and open PRs? | [`development-workflow.md`](development-workflow.md) | Current workflow |
| Which working rules has the owner accepted for the engineering workflow? | [`decisions/operational-decisions.md`](decisions/operational-decisions.md) | Owner-accepted; resolves no decision |
| How is the backend built and operated? | [`backend/architecture.md`](backend/architecture.md) | Current backend architecture |
| What is the proposed V1 production backend design? | [`architecture/README.md`](architecture/README.md) and decision records 0001–0009 in [`decisions/`](decisions/) | Proposed (milestone M1); not implemented until the owner accepts the records |

Conflict rule (from the contract): the PRD and owner-approved decisions define desired behavior;
fresh repository tests and audits define implementation truth; an older audit or prototype never
overrides newer verified evidence. If a document disagrees with `AGENTS.md`, `AGENTS.md` wins for
engineering behavior.

## Layout

```text
docs/
  README.md                  this index
  PRD.md                     product requirements (kept at this path; many links depend on it)
  development-workflow.md    branch, worktree, PR, CI, and agent workflow
  product/                   approved product scope (V1 Product Experience Contract)
  audits/                    dated, immutable audit snapshots: YYYY-MM-DD-<topic>.md
  decisions/                 architecture decision records and owner operational decisions
  architecture/              V1 backend architecture (milestone M1): data model, RLS, API, Vapi, Brain, operations
  backend/                   current backend architecture, Qdrant v2 runbook, demo testing
  ios/                       native iOS setup, hands-free, and wake-listener guides
  archive/                   superseded records; read for history, never for current behavior
```

Conventions: lowercase kebab-case file names; audits are never edited in place (add a new dated
file instead); new architecture decisions go in `decisions/`; do not copy a document's content
into `AGENTS.md` or `CLAUDE.md`, link to it.

## Provenance of imported documents

| Repository file | Received as | SHA-256 of received file | Edits to received text |
| --- | --- | --- | --- |
| `product/v1-product-experience-contract.md` | `CARVIS_V1_Product_Experience_Contract.md` | `d029d7692525fda819267e134e0262beb2270216c4590498ff71742ea8b86927` | Imported byte-identical, then revised to document revision 1.1 on 2026-11-15: V1 / M1–M5 / P0–P3 terminology, "V2" replaced by "post-V1", milestone mapping added to §8, §10, and §11. No decision ID, journey, acceptance criterion, or scope item changed. The hash identifies the received file, not the current text |
| `audits/2026-11-15-p0-readiness-audit.md` | `CARVIS_P0_READINESS_AUDIT.txt` | `2f5cb2eaf06d7d99c935300d4028b4264a883849799077b7b6e576f081f3f58c` | Added a snapshot banner; rewrote 7 machine-specific absolute source links to repo-relative code references so links resolve and no local paths are committed |

`docs/PRD.md` was already in the repository. Document revision 1.1 (2026-11-15) changed terminology
only and removed statements that the repository audit had not yet happened; requirement IDs,
priorities, and acceptance criteria are unchanged. A `CARVIS_PRD.pdf` exists outside the repository; it
was not imported because CI rejects tracked `.pdf` files and `PRD.md` is the maintained text form.
Confirm the two match before treating either as canonical.

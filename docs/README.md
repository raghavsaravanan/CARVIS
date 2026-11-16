# CARVIS documentation map

Start here. Engineering policy lives in [`../AGENTS.md`](../AGENTS.md) (with scoped
`AGENTS.md` files under `backend/`, `backend/spacetimedb/`, and `ios/`); this index only says where
each kind of document lives and which one wins when they disagree.

## Authority and precedence

| Question | Authoritative source | Status |
| --- | --- | --- |
| What must the product do? | [`PRD.md`](PRD.md) (v1.0, 2026-11-14) | Product requirements authority |
| What exactly does the V1 pilot include? | [`product/v1-product-experience-contract.md`](product/v1-product-experience-contract.md) | Approved V1 pilot scope. Decisions D-06 to D-09 are proposed defaults and **D-11 (identity/database vendors) and D-12 (retention) remain open**; do not treat them as resolved |
| What did the repository look like on 2026-11-15? | [`audits/2026-11-15-p0-readiness-audit.md`](audits/2026-11-15-p0-readiness-audit.md) | Historical snapshot, not current truth |
| What does the code do now? | The code and its tests | Implementation truth |
| How do we branch, test, and open PRs? | [`development-workflow.md`](development-workflow.md) | Current workflow |
| How is the backend built and operated? | [`backend/architecture.md`](backend/architecture.md) | Current backend architecture |

Conflict rule (from the contract): the PRD and owner-approved decisions define desired behavior;
fresh repository tests and audits define implementation truth; an older audit or prototype never
overrides newer verified evidence. If a document disagrees with `AGENTS.md`, `AGENTS.md` wins for
engineering behavior.

## Layout

```text
docs/
  README.md                  this index
  PRD.md                     product requirements (kept at this path; many links depend on it)
  development-workflow.md    branch, worktree, PR, and CI workflow
  product/                   approved product scope (V1 Product Experience Contract)
  audits/                    dated, immutable audit snapshots: YYYY-MM-DD-<topic>.md
  decisions/                 architecture decision records (see decisions/README.md)
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
| `product/v1-product-experience-contract.md` | `CARVIS_V1_Product_Experience_Contract.md` | `d029d7692525fda819267e134e0262beb2270216c4590498ff71742ea8b86927` | None (byte-identical) |
| `audits/2026-11-15-p0-readiness-audit.md` | `CARVIS_P0_READINESS_AUDIT.txt` | `2f5cb2eaf06d7d99c935300d4028b4264a883849799077b7b6e576f081f3f58c` | Added a snapshot banner; rewrote 7 machine-specific absolute source links to repo-relative code references so links resolve and no local paths are committed |

`docs/PRD.md` was already in the repository. A `CARVIS_PRD.pdf` exists outside the repository; it
was not imported because CI rejects tracked `.pdf` files and `PRD.md` is the maintained text form.
Confirm the two match before treating either as canonical.

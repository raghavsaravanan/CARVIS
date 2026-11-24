# Architecture decision records

Record a decision here when it is costly to reverse or constrains later work: choice of
transactional store or identity provider, tenant model, API versioning, retention policy, or any
change to a protected boundary in [`../../AGENTS.md`](../../AGENTS.md).

## Convention

- One file per decision: `NNNN-short-kebab-title.md`, numbered from `0001` and never reused.
  Copy [`0000-template.md`](0000-template.md).
- Status is one of `proposed`, `accepted`, `rejected`, `superseded by NNNN`. Only the repository
  owner moves a record to `accepted`.
- Accepted records are not rewritten. Change a decision with a new record that supersedes it.
- Link the PRD requirement or Product Experience Contract decision ID (for example `D-11`) the
  record resolves, and list the tests or checks that prove the decision holds.
- Keep secrets, customer data, and third-party proprietary or confidential material out of records.
- Open decisions stay in the contract's register until a record resolves them.
- Owner working rules for the engineering workflow, which resolve no decision, live in
  [`operational-decisions.md`](operational-decisions.md) rather than in numbered records or skills.

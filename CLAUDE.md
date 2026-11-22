# Claude Code entry point

Read `AGENTS.md` completely before acting, then the nearest scoped `AGENTS.md` for each area you
touch. `AGENTS.md` is the canonical engineering policy; this file only points to it.

- Documentation map and precedence: `docs/README.md` (PRD, V1 Product Experience Contract, dated
  audits, decision records).
- Workflow, branches, required checks, and the agent workflow (roles, task contracts, risk tiers,
  review protocol, worker launch profiles): `docs/development-workflow.md`.

Project skills in `.claude/skills/`: `/carvis-architecture` (design, database/auth selection,
tenancy, ADRs), `/carvis-regression` (run and extend checks, honest validation reporting),
`/carvis-pr-review` (diff and PR readiness review), and `/carvis-continue` (one M2 roadmap task to a
draft PR, then stop; run it only when the user invokes it or explicitly says "continue M2", directly
or through an Orca task contract that records that instruction, never automatically).

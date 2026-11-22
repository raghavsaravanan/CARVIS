# Owner operational decisions

Working rules the repository owner accepted for the engineering workflow, kept here rather than in
numbered records. Only the owner adds, changes, or removes an entry; agents cite them and never
edit them.

## Accepted by the owner on 2026-11-16

Moved without change from `.claude/skills/carvis-continue/SKILL.md` on 2026-11-22. Only the
cross-reference in the last entry was rewritten to name the skill section it points to.

These are working rules for this workflow. Formal ADRs and accepted records in `docs/decisions/`
remain authoritative; these resolve no D-item.

- **A2 boot behavior.** A missing `CARVIS_OPERATOR_TOKEN` keeps `/upload` closed (every request
  gets 401) but does not prevent startup.
- **Render operator token.** Configuring `CARVIS_OPERATOR_TOKEN` on Render is deferred until
  deployment. Do not add it to `render.yaml` or the Render dashboard in a roadmap task.
- **Track B gating.** A Track B row blocks only on unresolved owner decisions that materially
  affect it (`/carvis-continue` section 2, "Select the task").

## Recorded elsewhere

- **A3 interim session limits and refuse-instead-of-evict** (owner, 2026-11-16) remain with the
  behavior they govern in [`../backend/architecture.md`](../backend/architecture.md), "Accepted
  operational decisions". They resolve no D-item either.

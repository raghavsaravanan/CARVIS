---
name: carvis-continue
description: Advance the CARVIS M2 roadmap by exactly one task. Verify the previous M2 PR merged, check the worktree, pick the next roadmap row, implement it on a fresh branch, run regression checks and an independent review, open a draft PR, confirm CI, then stop for owner review. Runs only when the user invokes /carvis-continue or explicitly says "continue M2"; never automatically. Never merges.
argument-hint: "[roadmap row, e.g. A3 — blank selects the next one]"
disable-model-invocation: true
---

# Continue M2: one roadmap task, one draft PR

**Invocation.** `/carvis-continue` is the canonical command. A user who explicitly says "continue
M2" invokes the same workflow: read this file and follow it. Never start it on your own, including
at session start or after finishing another task. Each run completes one task from [`docs/architecture/12-m2-roadmap.md`](../../../docs/architecture/12-m2-roadmap.md)
and ends with a draft PR and a report. A run authorizes creating a branch, committing, pushing,
and opening a draft PR for that task only. It never authorizes a merge, a deployment, or a change
to live infrastructure.

Before starting, read `AGENTS.md`, the scoped `AGENTS.md` for each area you will touch, and
[`docs/development-workflow.md`](../../../docs/development-workflow.md).

## 1. Preflight: stop and report if it fails

```bash
bash .claude/skills/carvis-continue/preflight.sh
```

On exit 1, stop and report its `STOP:` line. Never stash, reset, commit, delete, or push anything
to make the preflight pass. The script does the following:

- Checks that `origin` is `github.com/raghavsaravanan/CARVIS`, over https or ssh.
  `remote.pushDefault` is not required, because every push names `origin` explicitly.
- Runs `git fetch --prune origin`.
- Requires a clean worktree, with no changes to tracked files and no untracked files.
- Requires that the current branch is safe to leave with `git switch`. That holds when one of the
  following is true:
  - it has nothing beyond `origin/main`;
  - it is fully pushed to an `origin` upstream that still exists;
  - it was **squash-merged**, meaning `HEAD` is contained in the final head commit of a merged PR
    into `main` for that branch. A deleted upstream therefore does not block a merged branch.

  Anything else is unpushed or unmerged work, and the script stops.
- Checks the roadmap-row PRs, meaning PRs whose titles contain `(M2 <row>` in any case (so
  `(M2 A3) [WIP]` counts). Other PRs that mention M2 are ignored. None may be open. The latest one must be `MERGED`, and its merge commit
  must be on `origin/main`. The script prints the merged rows.

The script never deletes local branches. Mention every branch it reports in a `NOTE:` line in the
final report. Work only in the current worktree. Never touch another worktree, the primary
checkout, or the external reference checkout.

## 2. Select the task

Take rows in roadmap order: Track A from A1 to A6, then Track B by its dependency column. A row
is done only when two things hold: the preflight lists a merged PR for that row, and `origin/main`
contains the change. If those disagree, stop and report. If the user names a
row as an argument, use it only when its dependencies are merged.

Implement only the engineering part of a row. Any part marked "owner action" (for example A5's
Render plan) belongs to the owner: list it as an open item and do not attempt it. "Open items"
listed in earlier PRs are not tasks unless the owner adds them.

**Track B gate.** A row is blocked only by an unresolved owner decision that materially affects
it. Owner decisions are the roadmap's table, D-1 to D-11; they are separate from the Product
Experience Contract's D-xx IDs. Use the table's "Blocks" column and the row's dependencies to
judge relevance. Open decisions unrelated to the row do not block it.

A D-item is resolved only by an `accepted` record in `docs/decisions/`. The accepted decisions at
the end of this skill are working rules and resolve no D-item. If a relevant decision is open,
stop, name it, and say what the owner must settle. Never edit a decision record's status or this
skill's decision list.

## 3. Implement

```bash
git switch --create <prefix>/<short-scope> origin/main   # prefixes: docs/development-workflow.md
```

- Implement only the selected row. No cleanup, no adjacent rows, and no fixes for out-of-scope
  findings; report those instead.
- Preserve protected contracts, status codes, and response shapes unless the row changes them.
  Update `README.md` and `docs/` wherever behavior or configuration changes.
- Test and validate with `/carvis-regression`. Each new guard must be caught by a test: disable
  it temporarily, confirm the suite fails, restore it, and confirm `git diff` shows no trace.
  Finish with the full baseline that skill describes.

## 4. Review

1. **Independent review.** Give a fresh subagent the roadmap row, the repository policy files, and
   the diff location, but not your conclusions. Ask for findings with `file:line` and a failure
   scenario, with verified findings kept separate from speculation.
2. **`/carvis-pr-review`** on the branch.
3. **Fix in-scope findings** and re-run the affected checks. Record out-of-scope findings as open
   items.

## 5. Commit, draft PR, CI

- Commit message: `<type>(<area>): <summary> (M2 <row>)`. The body covers what changed, why, and
  the test count.
- Push explicitly to `origin` (never `upstream`), then open the PR:
  ```bash
  git push --set-upstream origin HEAD
  gh pr create --draft --repo raghavsaravanan/CARVIS --base main \
    --head "$(git branch --show-current)" --title "<commit subject>" --body-file <file>
  ```
  The body fills every section of `.github/PULL_REQUEST_TEMPLATE.md`. Rollback names the exact
  revert or disable step. Add an "Open items for review" section.
- Watch CI with `gh pr checks <n> --repo raghavsaravanan/CARVIS --watch`. The required checks are
  `Backend and hygiene`, `Swift pure checks`, and `SpacetimeDB typecheck`. Report any failure with
  its output. Fix it only if the cause is in scope, and never weaken a test to make it pass.

## 6. Stop and report

Report:

- the PR link and CI status;
- tests run, with counts and labels (**mocked/unit**, **local**, **simulator**,
  **physical device**, **live provider**, **production**), and what was not run;
- risks, owner decisions needed, and out-of-scope findings.

Then stop. Do not merge, mark the PR ready, or start the next row.

## Accepted operational decisions (owner, 2026-11-16)

These are working rules for this workflow. Formal ADRs and accepted records in `docs/decisions/`
remain authoritative; these resolve no D-item.

- **A2 boot behavior.** A missing `CARVIS_OPERATOR_TOKEN` keeps `/upload` closed (every request
  gets 401) but does not prevent startup.
- **Render operator token.** Configuring `CARVIS_OPERATOR_TOKEN` on Render is deferred until
  deployment. Do not add it to `render.yaml` or the Render dashboard in a roadmap task.
- **Track B gating.** A Track B row blocks only on unresolved owner decisions that materially
  affect it (section 2).

## Never

- Merge, approve, or mark a PR ready.
- Deploy, or change Render, Qdrant, Vapi, Supabase, SpacetimeDB, or any provider configuration.
- Stash, reset, or overwrite uncommitted work, or rewrite history.
- Edit another worktree.
- Skip a failing check or a blocker.
- Introduce an external orchestration service.

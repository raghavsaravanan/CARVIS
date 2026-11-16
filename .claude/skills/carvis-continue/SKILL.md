---
name: carvis-continue
description: Advance the CARVIS M2 roadmap by exactly one task. Verify the previous M2 PR merged, check the worktree, pick the next roadmap row, implement it on a fresh branch, run regression checks and an independent review, open a draft PR, confirm CI, then stop for owner review. Runs only when the user invokes /carvis-continue (or asks to "continue M2"). Never merges.
argument-hint: "[roadmap row, e.g. A3 — blank selects the next one]"
disable-model-invocation: true
---

# Continue M2: one roadmap task, one draft PR

Run only when the user invokes `/carvis-continue` or explicitly asks to continue M2. Each run
completes one task from [`docs/architecture/12-m2-roadmap.md`](../../../docs/architecture/12-m2-roadmap.md)
and ends with a draft PR and a report. A run authorizes creating a branch, committing, pushing,
and opening a draft PR for that task only. It never authorizes a merge, a deployment, or a change
to live infrastructure.

Before starting, read `AGENTS.md`, the scoped `AGENTS.md` for each area you will touch, and
[`docs/development-workflow.md`](../../../docs/development-workflow.md).

## 1. Preconditions — stop and report if any fails

```bash
git fetch origin main
git status --short --branch
git log --oneline @{upstream}..HEAD        # unpushed commits on the current branch
git remote -v && git config --get remote.pushDefault
gh pr list --repo raghavsaravanan/CARVIS --state all --search "M2 in:title" --limit 20 \
  --json number,title,state,isDraft,mergedAt,headRefName
```

1. **Clean worktree.** Stop if the worktree has uncommitted changes, or if the current branch has
   unpushed commits (`@{upstream}..HEAD` is not empty). Also stop if the branch has no upstream
   and holds commits that are not on `origin/main`. Never stash, reset, or overwrite this work.
   You may leave a branch whose PR is `MERGED` by switching away from it.
2. **Remotes.** `origin` must be `raghavsaravanan/CARVIS` and the push default must be `origin`.
   Never push to `upstream`.
3. **No open M2 PR.** Stop if any M2 PR is `OPEN`, draft or not: report its number and status,
   and do not duplicate its work.
4. **Previous PR merged.** The most recent M2 PR must be `MERGED`. If it was `CLOSED` without
   merging, stop and report. Confirm its merge commit is on `origin/main`:
   ```bash
   gh pr view <n> --repo raghavsaravanan/CARVIS --json mergeCommit --jq .mergeCommit.oid
   git merge-base --is-ancestor <sha> origin/main
   ```
5. **This worktree only.** Never touch another worktree, the primary checkout, or the external
   reference checkout.

## 2. Select the task

Take rows in roadmap order: Track A from A1 to A6, then Track B by its dependency column. A row
is done only when two things hold: a PR titled with that row (for example `… (M2 A2)`) is merged,
and `origin/main` contains the change. If those disagree, stop and report. If the user names a
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
- Push and open the PR:
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

## Accepted decisions (owner, 2026-11-16)

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

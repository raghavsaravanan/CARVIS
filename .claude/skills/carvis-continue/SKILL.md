---
name: carvis-continue
description: Advance the CARVIS M2 roadmap by exactly one task. Verify the previous M2 PR merged, check the worktree, pick the next roadmap row, implement it on a fresh branch (or the branch an Orca coordinator assigned), commit a candidate, run regression checks and independent review of that exact candidate, open a draft PR, confirm CI, then stop for owner review. Runs only when the user invokes /carvis-continue or explicitly says "continue M2", directly or through an Orca task contract that records that instruction; never automatically. Never merges.
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

**Modes.** In **standalone** mode the owner invokes the skill in a session, and the skill creates
the task branch. In **Orca** mode an Orca coordinator assigned this task through a task contract
([`docs/development-workflow.md`](../../../docs/development-workflow.md), "Agent workflow"). The
contract's `Authorization` line must record the owner's invocation of this skill for this row; if
it does not, stop before step 1. In Orca mode the coordinator owns the branch, the worktree, and
every review, and this skill never creates a branch, a worktree, a subagent or another worker.

Before starting, read `AGENTS.md`, the scoped `AGENTS.md` for each area you will touch, and
[`docs/development-workflow.md`](../../../docs/development-workflow.md), including "Risk tiers" and
"Review protocol".

## 1. Preflight: stop and report if it fails

```bash
bash .claude/skills/carvis-continue/preflight.sh                       # standalone
bash .claude/skills/carvis-continue/preflight.sh --assigned <branch>   # Orca mode
```

On exit 1, stop and report its `STOP:` line. Never stash, reset, commit, delete, or push anything
to make the preflight pass. The script does the following:

- Checks that `origin` is `github.com/raghavsaravanan/CARVIS`, over https or ssh.
  `remote.pushDefault` is not required, because every push names `origin` explicitly.
- Runs `git fetch --prune origin`.
- Requires a clean worktree, with no changes to tracked files and no untracked files.
- Standalone: requires that the current branch is safe to leave with `git switch`. That holds when
  one of the following is true:
  - it has nothing beyond `origin/main`;
  - it is fully pushed to an `origin` upstream that still exists;
  - it was **squash-merged**, meaning `HEAD` is contained in the final head commit of a merged PR
    into `main` for that branch. A deleted upstream therefore does not block a merged branch.

  Anything else is unpushed or unmerged work, and the script stops.
- Orca mode: requires that the checked-out branch is the assigned one, uses an allowed prefix, has
  no commits beyond `origin/main`, and tracks nothing, `origin/main`, or `origin/<branch>`. Also
  confirm that `git rev-parse --show-toplevel` is the contract's worktree path.
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
row as an argument, use it only when its dependencies are merged. In Orca mode the contract names
the row; stop if it disagrees with the roadmap order or its dependencies are not merged.

Implement only the engineering part of a row. Any part marked "owner action" (for example A5's
Render plan) belongs to the owner: list it as an open item and do not attempt it. "Open items"
listed in earlier PRs are not tasks unless the owner adds them.

**Track B gate.** A row is blocked only by an unresolved owner decision that materially affects
it. Owner decisions are the roadmap's table, D-1 to D-11; they are separate from the Product
Experience Contract's D-xx IDs. Use the table's "Blocks" column and the row's dependencies to
judge relevance. Open decisions unrelated to the row do not block it.

A D-item is resolved only by an `accepted` record in `docs/decisions/`. The owner's operational
decisions in [`docs/decisions/operational-decisions.md`](../../../docs/decisions/operational-decisions.md)
are working rules and resolve no D-item. If a relevant decision is open, stop, name it, and say
what the owner must settle. Never edit a decision record's status or the owner's operational
decisions.

**Tier.** Determine the risk tier (`docs/development-workflow.md`, "Risk tiers"): the contract's
tier in Orca mode, otherwise the highest that applies to the row. Roadmap rows touching identity,
tenancy, persistence, privacy or migration are T3; rows touching evidence, retrieval, answers or
production data are T4. For T3 and T4, an accepted decision record must cover the design; a
`proposed` record does not. Run every requirement of the tier on top of the steps below.

## 3. Implement

Standalone:

```bash
git switch --create <prefix>/<short-scope> origin/main   # prefixes: docs/development-workflow.md
```

Orca mode: stay on the assigned branch and move it to the current base (it has no commits of its
own, so this cannot rewrite anything):

```bash
git merge --ff-only origin/main
```

Then, in both modes, run `scripts/bootstrap-worktree.sh` and record `git rev-parse HEAD` as the
base.

- Implement only the selected row. No cleanup, no adjacent rows, and no fixes for out-of-scope
  findings; report those instead.
- Preserve protected contracts, status codes, and response shapes unless the row changes them.
  Update `README.md` and `docs/` wherever behavior or configuration changes.
- Test and validate with `/carvis-regression`. Each new guard must be caught by a test: disable
  it temporarily, confirm the suite fails, restore it, and confirm `git diff` shows no trace.
  T3 and T4 extend this to every touched check of their kind. Finish with the full baseline that
  skill describes.

## 4. Commit the candidate, then review it

Reviews inspect a committed candidate, never a working tree.

1. **Commit the candidate** locally; do not push yet. Commit message:
   `<type>(<area>): <summary> (M2 <row>)`. The body covers what changed, why, and the test count.
   Later corrections are new commits, never amends.
2. **Review packet.** `git fetch origin main`, then
   `scripts/review-scope.sh --tier <Tn> <base> <candidate>` must exit 0. Exit 1 is a defect to fix
   first; exit 3 means `origin/main` changed this task's files or a policy file: merge it (never
   rebase), rerun the checks, and run the packet again.
3. **Independent review.**
   - Standalone: give a fresh subagent the roadmap row, the tier, the repository policy files, and
     the review-scope output, but not your conclusions, summary or test results. Ask for findings
     on every listed file, with `file:line`, a failure scenario, VERIFIED or INFERRED, and the
     candidate SHA. For T3 and T4 the Codex cross-model review is also required
     (`docs/development-workflow.md`, "Worker launch profiles", isolated profile). If it cannot be
     run, do not open the PR; report the review as outstanding.
   - Orca mode: send the coordinator a handoff (`worker_done`) with the base and candidate SHAs, the
     review-scope exit status, and the checks run with labels, then wait. The coordinator
     commissions every review and sends findings, or approval to open the PR, as a follow-up task.
4. **`/carvis-pr-review`** on the candidate (`<base>..<candidate>`); in Orca mode the coordinator
   runs it.
5. **Fix in-scope findings** as new commits, rerun the affected checks and the full baseline, and
   renew review: a delta review (`review-scope.sh --since <previous candidate>`) for T1 and T2, a
   full review for T3 and T4, by every required reviewer. Record out-of-scope findings as open
   items.

## 5. Revalidate, push, draft PR, CI

- **Revalidate.** `git fetch origin main` and rerun `scripts/review-scope.sh`. Handle exit 3 as in
  step 4. With drift but exit 0, check the drifted files for contract, import or fixture effects on
  this task and record the result. Rerun the open roadmap-PR query and stop if another row's PR is
  now open:
  ```bash
  gh pr list --repo raghavsaravanan/CARVIS --state open --search "M2 in:title" --json number,title
  ```
- Push explicitly to `origin` (never `upstream`), then open the PR:
  ```bash
  git push --set-upstream origin HEAD
  gh pr create --draft --repo raghavsaravanan/CARVIS --base main \
    --head "$(git branch --show-current)" --title "<commit subject>" --body-file <file>
  ```
  The body fills every section of `.github/PULL_REQUEST_TEMPLATE.md`, including the risk tier and
  the "Review and workflow record" with the reviewed candidate SHA. Rollback names the exact
  revert or disable step. Add an "Open items for review" section.
- Confirm the PR head is the reviewed candidate:
  `gh pr view <n> --repo raghavsaravanan/CARVIS --json headRefOid,baseRefName,isCrossRepository`.
- Watch CI with `gh pr checks <n> --repo raghavsaravanan/CARVIS --watch`. The required checks are
  `Backend and hygiene`, `Swift pure checks`, and `SpacetimeDB typecheck`. Report any failure with
  its output. Fix it only if the cause is in scope, and never weaken a test to make it pass. A fix
  is a new candidate: rerun step 4 from the packet.

## 6. Stop and report

Report:

- the PR link and CI status;
- tests run, with counts and labels (**mocked/unit**, **local**, **simulator**,
  **physical device**, **live provider**, **production**), and what was not run;
- the tier, the reviewed candidate SHA and each review's verdict;
- the workflow record from the PR (duration, human interventions, review iterations, CI failures,
  rework, conflicts, agents and models where reported);
- risks, owner decisions needed, and out-of-scope findings.

In Orca mode, send the same report as the final `worker_done`, linking the PR. Then stop. Do not
merge, mark the PR ready, or start the next row.

## Never

- Merge, approve, or mark a PR ready.
- Deploy, or change Render, Qdrant, Vapi, Supabase, SpacetimeDB, or any provider configuration.
- Stash, reset, or overwrite uncommitted work, or rewrite history.
- Edit another worktree.
- Skip a failing check or a blocker.
- Review, or ask for review of, uncommitted changes.
- Create a branch or worktree, dispatch an agent, or start a subagent in Orca mode.
- Introduce an external orchestration service.

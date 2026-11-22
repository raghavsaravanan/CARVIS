# CARVIS development workflow

CARVIS uses `raghavsaravanan/CARVIS` as its authoritative repository and `main` as its only
permanent integration branch. The original HackUTD repository is a historical upstream reference;
never push CARVIS product work to it or merge upstream changes automatically.

Expected remotes and push behavior:

```text
origin    https://github.com/raghavsaravanan/CARVIS.git
upstream  https://github.com/tejaspalukuri/CARVIS.git (fetch)
upstream  DISABLED (push)
push.default = current
remote.pushDefault = origin
gh default repository = raghavsaravanan/CARVIS
```

Confirm these with `git remote -v`, `git config --get push.default`,
`git config --get remote.pushDefault`, and `gh repo set-default --view`. The push settings are
recommended safety defaults; tooling such as `/carvis-continue` verifies the `origin` URL and pushes
to `origin` explicitly instead of relying on them. `upstream` is fetch/reference-only by policy; do
not push to it. Fetching upstream never authorizes an automatic merge into the personal fork.

Because this checkout is a fork with an `upstream` remote, `gh` resolves a bare `gh pr …` command
to `tejaspalukuri/CARVIS` unless a default repository is set (verified 2026-11-22). Always pass
`--repo raghavsaravanan/CARVIS` to `gh` commands that read or create pull requests, even with the
default set. The local configuration is restored with:

```bash
git remote set-url --push upstream DISABLED
gh repo set-default raghavsaravanan/CARVIS
```

These protect only this machine's Git configuration. The maintainer's GitHub account can still
push to `tejaspalukuri/CARVIS` by URL, so an agent holding that account's credentials is
restrained there by policy, not by permissions.

Read `AGENTS.md` and the scoped instructions under `backend/`, `backend/spacetimedb/`, or `ios/`
before changing files. Product scope comes from [`PRD.md`](PRD.md) and the
[V1 Product Experience Contract](product/v1-product-experience-contract.md); see the
[documentation map](README.md) for precedence and the
[decision-record convention](decisions/README.md).

## Branch and pull-request flow

Use a short-lived branch from the latest approved `origin/main`:

```text
Read issue and requirements
        ↓
Check main, branch, and worktree state
        ↓
Create a short-lived branch from origin/main
        ↓
Implement only the assigned scope
        ↓
Run relevant tests and inspect the diff
        ↓
Commit the candidate locally
        ↓
Review packet (scripts/review-scope.sh) and independent review of that candidate
        ↓
Fix as new commits, rerun checks, renew review
        ↓
Revalidate against origin/main, then push to origin
        ↓
Open a draft PR targeting main; CI
        ↓
Human-approved squash merge
```

Branch prefixes are `feat/`, `fix/`, `refactor/`, `docs/`, `chore/`, and `test/`. Do not create
permanent `develop`, `staging`, backend, frontend, or agent-named branches. A general instruction
to finish work never authorizes merging, deployment, production mutation, or history rewriting.

Normal setup from a clean worktree:

```bash
git fetch origin main
git switch --create feat/<scope> origin/main
git status --short --branch
```

Push the matching branch to the personal fork and open a draft PR:

```bash
git push --set-upstream origin HEAD
gh pr create --draft --repo raghavsaravanan/CARVIS --base main --head "$(git branch --show-current)"
```

GitHub `main` protection requires an up-to-date pull request, resolved conversations, linear
history, and the `Backend and hygiene`, `Swift pure checks`, and `SpacetimeDB typecheck` checks.
Force pushes and branch deletion are disabled. Squash merge is the only merge method enabled. The
solo repository requires no approval count, and administrators retain an emergency bypass
(`enforce_admins` is off), so an administrator credential can still push to `main` directly.
These settings were read from the GitHub API on 2026-11-22.

## Worktrees and agent work

Every task gets a fresh bounded branch in its own worktree. Prepare a new checkout with
`scripts/bootstrap-worktree.sh` before running checks.

The detached `.worktrees/platform` and `.worktrees/ios` checkouts created by earlier versions of
this document are no longer the recommended layout. They stay in place until the owner removes
them; do not start new work in them, and never edit one from another worktree.

Do not assign two agents the same file. Agree on shared API/schema changes before either side
implements against them. Platform work owns authentication, database migrations, backend policy,
tenant isolation, and CARVIS Brain backend. iOS work owns SwiftUI, navigation, application state,
UX states, and integration with approved contracts. Neither side changes the other's product or
data contract independently.

## Agent workflow

This section is model-independent: any agent may hold any role below. Claude is the default
coordinator and implementer, Claude subagents give routine fresh-context review, and Codex gives
cross-model review. Cursor and Antigravity take supervised assignments only, because their
read-only modes need a person to approve every shell command (see "Worker launch profiles").

### Roles and authority

| Role | Does | Never |
| --- | --- | --- |
| Owner | Approves architecture, sensitive operations, merges and deployments; authorizes each task's Git writes; accepts decisions; lowers a tier | Delegates those approvals to an agent |
| Coordinator | Writes task contracts, assigns the tier, creates and releases worktrees, dispatches the implementer, commissions every review, records the workflow record, recovers failed workers | Implements in a worker's worktree, merges, marks ready, resolves decisions, lowers a tier, answers another agent's permission prompt, or types into its terminal |
| Implementer | One task in its assigned worktree, to a reviewable committed candidate and, after review, a draft PR | Creates worktrees or branches in Orca mode, dispatches agents or subagents in Orca mode, edits outside its worktree, commits or pushes without the contract's authorization |
| Reviewer | Reviews one review packet and reports findings | Edits, commits, pushes, dispatches, or reads the implementer's conclusions before forming findings |

Workers never dispatch other workers. In Orca mode only the coordinator commissions reviews, so
delegation is never more than one level deep; standalone `/carvis-continue` commissions its own
fresh-context reviewer because there is no coordinator.

Dispatch is not authorization. Git writes need the owner's approval (`../AGENTS.md`), so a task
contract records who authorized which writes (commit, push to `origin`, draft PR). A roadmap row
still needs the owner to invoke `/carvis-continue` or say "continue M2"; the contract records that
instruction. Without an authorization line the implementer stops before committing. The
implementer cannot verify that line, so it is an instruction-only control: it names where the owner
gave the approval (session, message or comment) so the owner can audit it, and it can never cover
merging, marking ready, deployment, or any provider or production change.

### Task contract

The coordinator writes one contract per task and passes it as the Orca task spec. The contract is
the only task state an agent may rely on besides Git and the PR; do not copy project state into it,
link to it.

```text
Task:            <id> — <one-line objective>
Tier:            T1 | T2 | T3 | T4 — <reason; scripts/review-scope.sh reports the path floor>
Authorization:   <owner, date, scope: commit / push to origin / draft PR; for M2, the invocation>
Depends on:      <merged PRs, accepted decision records by path, owner operational decisions>
Base:            <origin/main SHA at assignment>
Branch:          <prefix>/<scope>
Worktree:        <absolute path, Orca worktree id>
Scope:           <owned files or globs>; excluded: <paths that must not change>
Acceptance:      <observable criteria>
Verification:    <narrowest checks, tier requirements, scripts/verify.sh, validation labels>
Completion:      committed candidate SHA, review-scope exit 0, checks with labels, handoff record
Stop if:         an open decision affects the task; preflight STOP; the change needs files outside
                 Scope; a failing check outside scope; a sensitive or production operation is
                 needed; material drift cannot be merged cleanly; the tier rises above what the
                 contract authorizes
```

### Worktree lifecycle

1. **Create (coordinator).** `orca worktree create --name <task> --branch <prefix>/<scope>
   --base-branch origin/main --no-parent --setup skip`. The branch has no upstream. In Orca mode the
   coordinator is the only creator of task branches; `/carvis-continue` creates one only in
   standalone mode.
2. **Prepare (implementer).** `.claude/skills/carvis-continue/preflight.sh --assigned <branch>`
   for a roadmap row, or with `--non-roadmap` added for any other task (it skips the roadmap-row PR
   checks, so an open M2 PR does not block the second package). Then `git merge --ff-only
   origin/main` (the branch has no commits of its own, so this only moves it forward), then
   `scripts/bootstrap-worktree.sh`.
3. **Work and review** as described below. The implementer stays idle while a review runs.
4. **Release (coordinator), after the owner merges.** Remove the worktree only when its branch is
   merged or the owner abandons it, and its tree is clean. Never stash, reset or delete to recover.

Orca can run a committed `orca.yaml` setup script when it creates a worktree. It is not configured:
according to Orca 1.4.269's own settings and trust-dialog text (not tested here), it can start that
script beside the agent and re-prompts for trust only when `orca.yaml` changes, not when the script
it calls changes; its behavior for this repository is untested. Enabling
it is an owner decision after a test in a disposable worktree.

A Git worktree is not a security boundary. Every worktree shares the repository's objects, refs,
configuration, hooks and stash, and runs as the same user with the same credentials. Isolation
between agents comes only from the launch profile and from GitHub-side protections.

### Risk tiers

Tiers only add requirements. Every tier keeps today's gates: the `../AGENTS.md` definition of done,
the scoped `AGENTS.md` rules, every `/carvis-continue` step (including the guard-disabling test and
the full baseline), the full `/carvis-pr-review`, separately labelled simulator, device, live and
production validation, and the required CI checks. When two rules disagree, the stricter applies.

The tier is the highest that applies. `scripts/review-scope.sh` enforces a minimum from the
changed paths and refuses a lower declared tier. The coordinator may set a higher tier, any agent
may raise it, and only the owner may lower it. Workflow, policy, CI, script and dependency
changes are T3.

| | T1 docs and cosmetic | T2 product | T3 security, identity, tenancy, privacy, persistence, migration | T4 evidence, automotive safety, production data |
| --- | --- | --- | --- | --- |
| Architecture | None | Conform to accepted contracts; a contract change makes it T3 | Name the decision records the design relies on; a materially affecting decision that is not accepted blocks it (the Track B gate in `/carvis-continue`) | T3, plus the safety invariants listed in the contract; owner sign-off on any change to evidence policy |
| Regression | Narrowest checks and the full baseline | Plus success and failure tests for new behavior | Plus `/carvis-regression` section 5 isolation and authorization negatives; migrations up and down on a scratch store; `scripts/check-runtime-lock.sh` when dependencies change | Plus `/carvis-regression` sections 3 and 4: pipeline preservation and adversarial refusals |
| Mutation | Each new guard, if any | Each new guard is disabled and the suite must fail | Plus every touched authentication, tenant, secret and limit check | Plus every touched applicability, evidence and refusal condition |
| Security | `/carvis-pr-review` | `/carvis-pr-review` | Plus threat notes in the PR (spoofing, IDOR, replay, secrets, logging) | Plus a provider and production boundary statement |
| Fresh-context review | Required | Required | Required | Required |
| Cross-model review (Codex) | Optional | Optional | Required, isolated profile | Required, isolated profile |
| Renewed review after a correction | Delta | Delta | Full | Full |

### Review protocol

1. **Candidate.** Implement, run the narrow checks, and commit. Corrections are new commits, never
   amends, so each delta stays reviewable.
2. **Packet.** `git fetch origin main`, then `scripts/review-scope.sh --tier <Tn> <base> <candidate>`
   must exit 0. `<base>` is the integration commit the task started from, never a task commit; the
   script refuses a task commit, a missing integration ref, and a declared tier below the path
   floor. Its output, the task contract and the list of policy files form the review packet.
   Reviewers run the integration branch's copy of the script when it has one (`git show
   origin/main:scripts/review-scope.sh | bash -s -- …`), so a candidate cannot weaken its own
   review, and they never run candidate scripts without reading them first. Reviewers do not
   receive the implementer's summary, reasoning, test conclusions, PR body or earlier verdicts; a
   renewed review receives only the list of earlier findings to check.
3. **Review.** Reviewers read the pinned revisions (`git show <sha>:<path>`, `git diff`), not a
   working tree that may change, and also read the callers, contracts and scoped policies that the
   change affects. They report on every listed file, with `file:line`, a failure scenario,
   VERIFIED or INFERRED, and the candidate SHA they reviewed. CI is the independent test
   evidence; a reviewer that can run checks read-only (see the isolated Codex profile) may add its
   own.
4. **Correction.** A fix makes a new candidate: rerun the affected checks and the full baseline,
   then renew review. A delta review uses `review-scope.sh --since <previous candidate>`, which
   lists every file the correction touched, including files reverted to the base; a full review
   covers the effective base to the new candidate. Every required reviewer class renews.
5. **Revalidation before approval.** Fetch again and rerun `review-scope.sh`. Exit 3 means the
   integration branch changed this task's files or a policy, CI, script or dependency file: merge
   `origin/main` (never rebase), rerun the checks and renew review. Exit 0 with drift still needs a
   drift check: read the drifted files for contract, import or fixture effects on this task and
   record the result in the PR. A clean update is a merge of `origin/main` (including GitHub's
   "Update branch") after which `review-scope.sh --since <reviewed candidate>` exits 0 and lists no
   task-file changes. It keeps its reviews, but needs that drift check, the full baseline and green
   CI. Any other change to the candidate, including a conflicted or material update, renews review
   under step 4.
6. **PR head pinning.** The PR records the reviewed candidate SHA. Before asking the owner to
   approve, and again at merge, compare the PR's current head and base with the reviewed values:

   ```bash
   gh pr view <n> --repo raghavsaravanan/CARVIS \
     --json headRefOid,baseRefName,baseRefOid,headRepositoryOwner,isCrossRepository,statusCheckRollup
   ```

   A head that is neither the reviewed candidate nor a clean update of it has stale reviews.

### Handoff and workflow record

The draft PR is the authoritative record of a task. Its "Review and workflow record" section holds
the base and reviewed candidate SHAs, every review (reviewer, model where Orca reports it, SHA,
verdict, findings fixed and open), the final drift check, and the metrics: duration, human
interventions, review iterations, CI failures, rework commits after the first review, integration
conflicts, and agents and models. Token counts are not reliably available; do not estimate them.
Before a PR exists, the worker's `worker_done` body carries the same fields; afterwards it carries
only the outcome and the PR link. Nothing else stores task state.

### Worker launch profiles

Restriction classes:

- **Enforced**: the operating system denies the action (Codex's sandbox), or GitHub does (branch
  protection, repository permissions).
- **Mode-based**: the agent's own plan, ask or approval mode. The agent enforces it and a person can
  bypass it with one keypress ("Run Everything", "always allow"); it is not a security boundary.
- **Instruction-only**: `AGENTS.md`, skills and task specs. Agents usually follow them; nothing
  enforces them.

Profiles tested on 2026-11-21 and 2026-11-22 with Orca 1.4.269 and Codex CLI 0.171.0. Launch a
restricted profile with `orca terminal create --worktree <selector> --command "<command>"`, then
`orca orchestration worker-start --task <id> --terminal <handle>`; `worker-start --agent` has no
permission option and inherits the user's own settings for that agent.

| Profile | Command | Filesystem | Network and GitHub | Orca reporting | Use |
| --- | --- | --- | --- | --- | --- |
| Codex isolated | `codex --cd <scratch> --sandbox workspace-write --ask-for-approval never -c 'projects."<scratch>".trust_level="trusted"'` | Enforced: writes only to `<scratch>` and temporary directories; reads anywhere | Enforced: no network, so no GitHub API, push or DNS | None: the Orca CLI is blocked. The worker writes its report in `<scratch>` and ends its turn; Orca escalates "stopped without reporting" with the last output line. The coordinator reads the report, then settles with `orca orchestration worker-abandon --dispatch <id>` and `task-update --status completed --result "<summary>"` (`worker-stop` reports `stop_unknown` for these terminals). Tested 2026-11-22 | Cross-model review of T3 and T4; can run `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider` read-only |
| Codex connected | the isolated command plus `-c sandbox_workspace_write.network_access=true` | Enforced, as above | **Not restricted**: the user's GitHub credentials in the keyring work (`gh api`, authenticated `git push --dry-run` both succeeded); clearing `GH_*` variables is bypassed by `env -u` | `worker_done` works | T1 and T2 review, and any task whose worker must report through Orca |
| Codex read-only | `--sandbox read-only` | Enforced, no writes at all | No network | Blocked, and no scratch to write a report | Do not use |
| Claude worker | `orca orchestration worker-start --agent claude` | Inherits the user's Claude settings, which may bypass permission prompts | Inherits | Works | Implementer; restrictions are instruction-only. A restricted Claude profile is untested |
| Cursor | `cursor-agent --mode plan --trust` | Mode-based: no edit tool, but approved shell commands can write | Mode-based | Needs a person to approve each `orca` call | Supervised only |
| Antigravity | `agy --mode plan` | Mode-based, as Cursor | Mode-based | Needs approvals; Orca cannot read its transcript, so a missing `worker_done` loses the report | Supervised only; the workspace-trust prompt has no command-line override |

Never answer another agent's approval prompt, choose "Run Everything", or persist an
"always allow" rule on the owner's behalf. Briefs for approval-gated agents must not set targets
that need extra commands to check (a word count caused an approval loop).

Known residual risks, as of 2026-11-22: the maintainer's GitHub account can push to
`tejaspalukuri/CARVIS` by URL; `main` protection does not apply to administrators; any agent
running as the user with network access can use the user's GitHub credentials. Treat these as
procedural controls until the owner changes them.

### Concurrency, serial M2, and recovery

- At most two implementation packages are in flight, each in its own worktree. Count them from
  `orca worktree ps` and the open PRs, not from memory.
- Roadmap rows stay serial until the V1 architecture freeze. The coordinator holds at most one
  active M2 assignment; that rule is authoritative because the preflight only sees open PRs. The
  implementer reruns the open-PR query before pushing and stops if another row's PR appeared.
- The second package must not be a roadmap row, must own disjoint files, and must not change a
  shared contract. File ownership is a planning aid, not a safety proof: reviewers still check
  contract and integration effects.
- Dependency-aware parallel scheduling is deferred until the V1 architecture and roadmap are final.
- A lost or failed worker: inspect `orca orchestration worker-show`, confirm the agent stopped
  (`worker-stop` reports a confirmed stop) before anyone else touches its worktree, and retry only
  after the cause changes; Orca's three-attempt breaker is final. Partial work stays on its branch,
  unpushed or pushed, and the owner decides whether to continue it by hand, re-dispatch it from a
  fresh worktree, or abandon it. There is no automatic resume.
- If Orca is unavailable, `/carvis-continue` still works in standalone mode under its own
  invocation rules for T1 and T2. T3 and T4 need the isolated Codex review, which runs through Orca;
  without it the draft PR is not opened and the review is reported as outstanding. The PR remains
  the record.

## Required checks

Run the narrowest relevant checks first. In a fresh checkout, run `scripts/bootstrap-worktree.sh`
first; `--check` validates without installing. `scripts/verify.sh` is the complete local baseline
and includes the iOS Simulator build when full Xcode is selected. It does not run the
runtime-lockfile check, which needs PyPI access; run `scripts/check-runtime-lock.sh` when
dependencies change. GitHub CI runs these checks without provider credentials or production access:

- an isolated runtime-lockfile install and import check (`scripts/check-runtime-lock.sh`);
- backend tests and compilation;
- repository hygiene and secret-path checks;
- the review-packet tests (`scripts/tests/review-scope-test.sh`);
- pure Swift tests;
- SpacetimeDB TypeScript type checking.

Changes to the workflow scripts also need their manual, network-using tests:
`scripts/tests/bootstrap-worktree-test.sh` (package registries) and
`scripts/tests/preflight-test.sh` (GitHub, read-only).

Full Xcode builds, signing, TestFlight, physical iPhone audio, Meta hardware, and live-provider
checks remain explicit local/release validations. Never describe mocks or simulator results as
physical-device or live-provider evidence.

## AI completion checklist

- [ ] Read the issue, PRD requirement, root instructions, and applicable scoped instructions.
- [ ] Confirm repository, branch, remotes, tracking branch, worktree, and pre-existing changes.
- [ ] Keep the task bounded; do not mix cleanup with product work.
- [ ] Preserve Vapi/FastAPI/Qdrant verification, optional Meta adapters, and SpacetimeDB boundaries.
- [ ] Do not trust caller-supplied identity, tenant, shop, vehicle, or session authority.
- [ ] Keep credentials, local databases, manuals, captures, transcripts, and customer data out of Git.
- [ ] Run relevant success, refusal, isolation, cancellation, and recovery tests.
- [ ] State the risk tier; run every requirement of that tier on top of the baseline.
- [ ] Commit the candidate, then review it with `scripts/review-scope.sh` exiting 0.
- [ ] Inspect the complete diff and list all unavailable validation.
- [ ] Revalidate against `origin/main` and the PR head before asking for approval.
- [ ] Open a draft PR; do not merge or deploy without explicit human authorization.

`CODEOWNERS` is intentionally omitted while there is one confirmed maintainer. Revisit it when a
second maintainer has accepted ownership; do not create a required self-review loop for a solo
repository.

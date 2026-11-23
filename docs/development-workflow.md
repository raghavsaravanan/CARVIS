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
Budget:          <tier review budget>; time budget <agreed estimate>
Stop if:         a stopping condition ("Review budget, findings and stopping"); an open decision affects the task; preflight STOP; the change needs files outside
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
| Mutation | Each new guard is disabled and the suite must fail | Each new guard is disabled and the suite must fail | Plus every touched authentication, tenant, secret and limit check | Plus every touched applicability, evidence and refusal condition |
| Security | `/carvis-pr-review` | `/carvis-pr-review` | Plus threat notes in the PR (spoofing, IDOR, replay, secrets, logging) | Plus a provider and production boundary statement |
| Fresh-context review | Required | Required | Required | Required |
| Cross-model review (Codex) | Optional | Optional | Required, isolated profile | Required, isolated profile |
| Renewed review after a correction | Delta | Delta | Full | Full |
| Design review before implementation | Not required | Not required | Required, both reviewer classes | Required, both reviewer classes |
| Specification coverage matrix | Not required | Not required | Required when the package implements or depends on an external standard or provider behavior ("Churn controls") | As T3 |
| Adversarial pre-review | Recommended | Recommended | Required before the first independent review ("Churn controls") | Required, as T3 |
| Autonomous review budget | 1 round | 2 rounds | 2 implementation rounds | 2 implementation rounds |

### Churn controls (T3 and T4)

These controls move discoveries earlier, so independent review confirms work instead of finding its
gaps. They add to the review protocol below; none replaces an independent review, a mutation check,
CI or an owner decision.

**Specification coverage matrix.** A T3 or T4 package that implements or depends on an external
standard or provider behavior (for example libpq connection parameters and environment variables,
PostgreSQL object kinds and privilege rules, JWT and OIDC claims, an HTTP API's error states)
enumerates that behavior in its design note before implementation. Work from the official
specification for the version in use and cite it. Cover parameters and their environment-variable or
default fallbacks, combinations and counts, object or claim kinds, error and unsupported states, and
known provider quirks. One row per case:

| Case (cited) | Disposition | Verification |
| --- | --- | --- |
| A behavior, input combination or edge condition from the specification | Handled, explicitly refused (with the refusal behavior), or out of scope (with the reason and owning package) | The test or check that proves it, with its label; `[?]` when provider behavior cannot be verified yet, with the gate that will verify it |

Design reviewers examine the matrix: missing cases, wrong dispositions and missing verification are
design findings. Implementation reviewers receive the reviewed design note, including the matrix,
as part of the packet (it is a design artifact, not the implementer's conclusions) and report code
that disagrees with it.

**Adversarial pre-review.** After committing the first candidate and before the packet goes to any
independent reviewer, the implementer reviews that candidate adversarially:

- the full diff against the specification matrix;
- the security invariants of the task contract and the decision records it names;
- the severity rubric below;
- for every rule the change implements, the other paths that implement or depend on the same rule.

Defects found are fixed as new commits before the first independent review. The pre-review is
recorded in the workflow record (what was checked, what was fixed). It is not an independent review,
never counts as an approval or a round, and its conclusions are not given to reviewers.

**Package size.** Aim for cohesive packages of roughly 600–900 changed lines where practical. This
is guidance, not an enforced maximum: when a roadmap row looks larger, propose a split to the owner
before implementation. Never split a security invariant across packages to meet the size target:
a role model, a privilege boundary or an authentication rule and its enforcement land together.

### Review protocol

1. **Candidate.** Implement, run the narrow checks, and commit. Corrections are new commits, never
   amends, so each delta stays reviewable. Before substantial local testing (the full baseline,
   real-database suites, mutation runs) run the disk-space preflight ("Local run hygiene"). For T3
   and T4, complete the adversarial pre-review ("Churn controls") before step 2 sends the packet to
   any reviewer.
2. **Packet.** `git fetch origin main`, then `scripts/review-scope.sh --tier <Tn> <base> <candidate>`
   must exit 0. `<base>` is the integration commit the task started from, never a task commit; the
   script refuses a task commit, a missing integration ref, and a declared tier below the path
   floor. Its output, the task contract and the list of policy files form the review packet.
   Reviewers run the integration branch's copy of the script when it has one, so a candidate
   cannot weaken its own review, and they never run candidate scripts without reading them first.
   Accept a packet only on exit 0 with the last line `REVIEWABLE: <candidate> …`. Never pipe the
   script into `bash`: a pipeline reports `bash`'s status, so a missing copy looks like success.

   ```bash
   if git cat-file -e origin/main:scripts/review-scope.sh 2>/dev/null; then
     rs="$(mktemp "${TMPDIR:-/tmp}/review-scope.XXXXXX")" \
       && git show origin/main:scripts/review-scope.sh > "${rs}" \
       && bash "${rs}" --tier <Tn> <base> <candidate>
     rc=$?; rm -f "${rs}"
   else   # main has no copy yet (the change that adds it): read scripts/review-scope.sh first
     bash scripts/review-scope.sh --tier <Tn> <base> <candidate>
     rc=$?
   fi
   ```

   Use `${rc}` as the packet's exit status. Reviewers do not receive the implementer's
   summary, reasoning, test conclusions, pre-review, PR body or earlier verdicts; a renewed review
   receives only the list of earlier findings to check. The one addition for T3 and T4 is the
   reviewed design note with its specification matrix ("Churn controls"), a design artifact that
   every reviewer class receives alike.
3. **Review.** Reviewers read the pinned revisions (`git show <sha>:<path>`, `git diff`), not a
   working tree that may change, and also read the callers, contracts and scoped policies that the
   change affects. They report on every listed file, with `file:line`, a failure scenario,
   VERIFIED or INFERRED, and the candidate SHA they reviewed. Every reviewer classifies findings
   with the severity rubric ("Review budget, findings and stopping"), and for T3 and T4 checks the
   implementation against the reviewed specification matrix when the package has one. CI is the
   independent test evidence; a reviewer that can run checks read-only (see the isolated Codex
   profile) may add its own.
4. **Correction.** A fix makes a new candidate: rerun the affected checks and the full baseline,
   then renew review. A delta review uses `review-scope.sh --since <previous candidate>`, which
   lists every file the correction touched, including files reverted to the base (if it reports
   a material update, review in full instead); a full review
   covers the effective base to the new candidate. Every required reviewer class renews.
   Corrections follow the correction discipline below, and every renewal counts against the
   review budget.
5. **Revalidation before approval.** Fetch again and rerun `review-scope.sh`. Exit 3 means the
   integration branch changed this task's files or a policy, CI, script or dependency file: merge
   `origin/main` (never rebase), rerun the checks and renew review. Exit 0 with drift still needs a
   drift check: read the drifted files for contract, import or fixture effects on this task and
   record the result in the PR. A clean update is a merge of `origin/main` (including GitHub's
   "Update branch") after which `review-scope.sh --since <reviewed candidate>` exits 0: it lists no
   task-file changes, and nothing merged in changed a task file or has a T3+ floor (otherwise exit
   3, "MATERIAL UPDATE", and the review is renewed in full). It keeps its reviews, but needs that drift check, the full baseline and green
   CI. Any other change to the candidate, including a conflicted or material update, renews review
   under step 4.
6. **PR head pinning.** The PR records the reviewed candidate SHA. Before asking the owner to
   approve, and again at merge, compare the PR's current head and base with the reviewed values:

   ```bash
   gh pr view <n> --repo raghavsaravanan/CARVIS \
     --json headRefOid,baseRefName,baseRefOid,headRepositoryOwner,isCrossRepository,statusCheckRollup
   ```

   A head that is neither the reviewed candidate nor a clean update of it has stale reviews.

### Review budget, findings and stopping

Autonomous iteration is bounded; the budget never waives a mandatory review or acceptance gate.

- **Round.** One round is every required reviewer class reviewing one pinned candidate. A renewed
  review is a round. The T3/T4 design review is one round, by both reviewer classes, before
  implementation; it is outside the implementation budget, but the time budget and stopping
  conditions apply to it, and needing a second design round is a stop.
- **Renewal.** The tier's renewal requirement is unchanged: delta for T1 and T2, always full for T3
  and T4. Focused verification of a correction (rerunning the affected tests, a reviewer's targeted
  check of the corrected paths) may precede a required renewal but never replaces it. A full renewal
  covers the whole effective-base-to-candidate diff, and a new blocking finding in code the
  correction did not touch is as eligible as any other finding of that round.
- **Findings.** Every finding states reproducible evidence (a command and its output, or
  `path:line` with a failure scenario), severity (critical, high, medium or low), affected scope,
  the requirement violated, and BLOCKING or NONBLOCKING under the severity rubric below.
  Nonblocking findings are recorded in the PR as deferred and not implemented within the task.
- **Severity rubric.** Claude and Codex reviewers apply the same rubric, each independently and
  without seeing the other's verdict. A finding is **BLOCKING** when its evidence shows any of:
  1. *A reachable correctness defect*: a wrong result, crash, hang, data loss or misclassified
     outcome on a path reachable in the change as it will ship, under a supported configuration. A
     configuration is supported when the specification matrix marks it handled, when the governing
     specification defines it and the change claims to accept it, or when the change accepts it
     without refusing it, whatever the matrix says.
  2. *A security invariant violation*: a security, privacy, tenancy, evidence-integrity or
     automotive-safety guarantee broken. This includes authority taken from caller input, a
     privilege beyond the approved role model, exposure of secrets or personal data, and a missing
     fail-closed path.
  3. *A security-critical latent defect*: a defect of kind 1 or 2 in code that is not wired yet but
     that an approved downstream package (a roadmap row or task contract) will activate without
     further change to that code.
  4. *An approved-requirement violation*: an accepted decision record, an owner decision, or a task
     contract's acceptance criterion is broken, or a mandatory gate or tier is weakened, bypassed or
     made unusable.
  5. *A contradicted security or contract claim*: documentation or a docstring that states a
     security- or contract-relevant behavior the code does not have.

  A finding is **NONBLOCKING** when it is a design preference, refactoring or style point; hardening
  beyond the approved requirements; a defect that needs a privileged out-of-band change already
  refused by an existing gate (it fails closed); a test-only effect; a configuration the matrix
  marks refused or out of scope *and that the code refuses or leaves untouched as the matrix
  describes*; or documentation imprecision with no security or contract effect. The matrix is
  written by the implementer, so it never shields behavior: code that departs from its
  disposition is judged under kinds 1 to 4, and any reviewer may challenge a disposition itself,
  at the design review or later, as a finding under this rubric.
  A finding any required reviewer classifies BLOCKING with the required evidence is treated as
  blocking. When reviewers classify the same issue differently, record both classifications; if
  they disagree on what the rule requires rather than on evidence, that is an unresolved
  disagreement and the stop rule below applies.
- **Correction discipline.** Collect all blocking findings of a round before changing anything, then
  make one correction that addresses only those findings, with a regression test (and the tier's
  mutation check) for each corrected executable defect; documentation defects need no invented
  executable test. No unrelated refactoring; reviews stay pinned to the exact candidate SHA.
- **Class-level corrections.** Before fixing a blocking defect, name the rule it violates and find
  every other code path, configuration source or object kind that implements or depends on that
  rule: callers and siblings of the faulty code, other readers of the same setting, other object
  kinds governed by the same privilege rule. Fix the class, not only the reported instance. The
  regression tests cover the class (each affected path, or one test parametrized over them), and
  the mutation check disables the fix in each path. The correction commit and the workflow record
  carry a class analysis: the rule, the paths examined, the paths changed and the regression
  evidence. A path in the class that lies outside the task's scope is reported as an out-of-scope
  finding; if fixing the defect requires it, that is a scope expansion and a stop.
- **Stopping conditions.** Stop autonomous iteration when:
  - all mandatory gates pass and no blocking finding remains: the task completes;
  - the review budget is exhausted, including when the last permitted round leaves a blocker;
  - the same defect category (the same requirement violated by the same mechanism) recurs in a
    second round;
  - reviewers disagree on a rule, or a correction would change a safety or review mechanism;
  - elapsed time exceeds twice the agreed time budget;
  - an owner decision, an unexpected permission escalation, or a scope expansion is needed.
- **Escalation.** On every stop except the first, report each blocker with its evidence, severity
  and proposed correction, and the options, then wait for the owner. With the owner's approval a
  draft PR may record open blocking findings, marked not merge-ready, but only after the packet,
  every required review and every mandatory check have run on that candidate and every gate for
  opening a draft PR is met. It never substitutes for a review, packet or check that did not run.

### Handoff and workflow record

The draft PR is the authoritative record of a task. Its "Review and workflow record" section holds
the base and reviewed candidate SHAs, every review (reviewer, model where Orca reports it, SHA,
verdict, findings fixed and open), for T3 and T4 the specification matrix's location, the
adversarial pre-review and each correction's class analysis, the final drift check, where the
continuation checkpoint keeps its logs, and the metrics: duration, human
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
- SpacetimeDB TypeScript type checking;
- the workflow-script tests (`scripts/tests/check-disk-space-test.sh`).

Changes to the workflow scripts also need their manual, network-using tests:
`scripts/tests/bootstrap-worktree-test.sh` (package registries) and
`scripts/tests/preflight-test.sh` (GitHub, read-only).

Full Xcode builds, signing, TestFlight, physical iPhone audio, Meta hardware, and live-provider
checks remain explicit local/release validations. Never describe mocks or simulator results as
physical-device or live-provider evidence.

### Local run hygiene

Long local runs (the full baseline, real-database suites, mutation runs, Docker containers) can
fail in ways that corrupt work in progress, so they follow these rules:

- **Disk-space preflight.** Run `scripts/check-disk-space.sh` before substantial local testing;
  `scripts/verify.sh` runs it first. It is read-only. It exits 1 below the minimum (10 GiB by
  default; `--min-gib N` or `CARVIS_MIN_FREE_GIB` changes it) and 2 on a usage error. Below the
  minimum, stop and ask the owner to free space. Never prune Docker images, volumes, caches or any
  other data automatically: deleting anything outside the task's own temporary files is the owner's
  decision.
- **Persistent logs.** Logs, reviewer reports, packets and mutation results go to the task's
  continuation checkpoint outside the repository, not to a temporary or session scratch directory
  that a restart or cleanup can remove. Record that location in the workflow record.
- **Mutation backup and restore.** Before mutating a file, copy it to the checkpoint and record its
  hash. After each mutation, restore the original and verify the restored file's hash against the
  recorded one before the next mutation; a mismatch stops the run. At the end, compare `git status`
  and `git diff` with their state before the run.
- **Recovery after an interrupted run.** If a run stops partway (crash, full disk, lost session),
  do not stash, reset, check out or re-run anything first. Compare every mutated file against its
  backup and hash, restore from the backup any file that differs, confirm `git diff` matches the
  pre-run state, and record the incident in the workflow record. Restart stopped services, such as
  a scratch database container, only after the worktree is verified.

## AI completion checklist

- [ ] Read the issue, PRD requirement, root instructions, and applicable scoped instructions.
- [ ] Confirm repository, branch, remotes, tracking branch, worktree, and pre-existing changes.
- [ ] Keep the task bounded; do not mix cleanup with product work.
- [ ] Preserve Vapi/FastAPI/Qdrant verification, optional Meta adapters, and SpacetimeDB boundaries.
- [ ] Do not trust caller-supplied identity, tenant, shop, vehicle, or session authority.
- [ ] Keep credentials, local databases, manuals, captures, transcripts, and customer data out of Git.
- [ ] Run relevant success, refusal, isolation, cancellation, and recovery tests.
- [ ] Check free disk space before long local runs; keep logs and mutation backups in the checkpoint.
- [ ] T3/T4: write the specification coverage matrix where it applies, and complete the adversarial
  pre-review before the first independent review.
- [ ] Classify findings with the severity rubric; correct blocking defects at the class level.
- [ ] State the risk tier; run every requirement of that tier on top of the baseline.
- [ ] Commit the candidate, then review it with `scripts/review-scope.sh` exiting 0.
- [ ] Inspect the complete diff and list all unavailable validation.
- [ ] Revalidate against `origin/main` and the PR head before asking for approval.
- [ ] Open a draft PR; do not merge or deploy without explicit human authorization.

`CODEOWNERS` is intentionally omitted while there is one confirmed maintainer. Revisit it when a
second maintainer has accepted ownership; do not create a required self-review loop for a solo
repository.

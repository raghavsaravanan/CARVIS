# CARVIS development workflow

CARVIS uses `raghavsaravanan/CARVIS` as its authoritative repository and `main` as its only
permanent integration branch. The original HackUTD repository is a historical upstream reference;
never push CARVIS product work to it or merge upstream changes automatically.

Expected remotes and push behavior:

```text
origin    https://github.com/raghavsaravanan/CARVIS.git
upstream  https://github.com/tejaspalukuri/CARVIS.git
push.default = current
remote.pushDefault = origin
```

Confirm these with `git remote -v`, `git config --get push.default`, and
`git config --get remote.pushDefault`. The push settings are recommended safety defaults; tooling
such as `/carvis-continue` verifies the `origin` URL and pushes to `origin` explicitly instead of
relying on them. `upstream` is fetch/reference-only by policy; do not push to
it. Fetching upstream never authorizes an automatic merge into the personal fork.

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
Commit and push to origin
        ↓
Open a draft PR targeting main
        ↓
CI and independent review
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
gh pr create --draft --base main --head "$(git branch --show-current)"
```

GitHub `main` protection requires an up-to-date pull request, resolved conversations, linear
history, and the `Backend and hygiene`, `Swift pure checks`, and `SpacetimeDB typecheck` checks.
Force pushes and branch deletion are disabled. Squash merge is the supported merge method. The
solo repository requires no approval count, and administrators retain an emergency bypass.

## Parallel agent worktrees

Keep platform and iOS work isolated, but create a fresh bounded branch for every task. Detached
worktrees may be parked at `origin/main` between tasks.

Prepare or refresh the worktrees from the primary checkout:

```bash
git fetch origin main
git worktree add --detach .worktrees/platform origin/main
git worktree add --detach .worktrees/ios origin/main
```

Start a Claude platform task:

```bash
cd .worktrees/platform
git switch --create feat/platform-<scope> origin/main
open -a Cursor .
```

Start a Codex iOS task:

```bash
cd .worktrees/ios
git switch --create feat/ios-<scope> origin/main
open -a Cursor .
```

Do not assign two agents the same file. Agree on shared API/schema changes before either side
implements against them. Platform work owns authentication, database migrations, backend policy,
tenant isolation, and CARVIS Brain backend. iOS work owns SwiftUI, navigation, application state,
UX states, and integration with approved contracts. Neither side changes the other's product or
data contract independently.

## Required checks

Run the narrowest relevant checks first. `scripts/verify.sh` is the complete local baseline and
includes the iOS Simulator build when full Xcode is selected. It does not run the runtime-lockfile
check, which needs PyPI access; run `scripts/check-runtime-lock.sh` when dependencies change.
GitHub CI runs these checks without provider credentials or production access:

- an isolated runtime-lockfile install and import check (`scripts/check-runtime-lock.sh`);
- backend tests and compilation;
- repository hygiene and secret-path checks;
- pure Swift tests;
- SpacetimeDB TypeScript type checking.

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
- [ ] Inspect the complete diff and list all unavailable validation.
- [ ] Open a draft PR; do not merge or deploy without explicit human authorization.

`CODEOWNERS` is intentionally omitted while there is one confirmed maintainer. Revisit it when a
second maintainer has accepted ownership; do not create a required self-review loop for a solo
repository.

---
name: carvis-pr-review
description: Review a CARVIS branch or pull request — git diff, scope, protected boundaries, security and privacy, migration safety, test verification, CI status, PR readiness, and rollback documentation. Use before opening or marking ready a PR, or when asked to review a diff, branch, or PR number. Read-only; never merges, approves, or pushes.
argument-hint: "[PR number | branch | blank for current branch]"
allowed-tools: Read Grep Glob Bash(git status *) Bash(git fetch origin main) Bash(git diff *) Bash(git log *) Bash(git show *) Bash(git ls-files *) Bash(git grep *) Bash(gh pr view *) Bash(gh pr diff *) Bash(gh pr checks *)
---

# CARVIS pull-request review

Target: `$ARGUMENTS` (a PR number or branch), otherwise the current branch against `origin/main`.
This skill reports; it does not edit, commit, push, approve, or merge.

## 1. Collect the change

```bash
git fetch origin main
git status --short --branch
git log --oneline origin/main..HEAD
git diff --stat origin/main...HEAD
git diff --check origin/main...HEAD
gh pr view <n> --json title,baseRefName,headRefName,isDraft,statusCheckRollup   # when a PR exists
gh pr checks <n>
```

Read the full diff (`git diff origin/main...HEAD`) and every changed file's nearest `AGENTS.md`.
Confirm: base is `main` of `raghavsaravanan/CARVIS`; branch uses an allowed prefix (`feat/`, `fix/`,
`refactor/`, `docs/`, `chore/`, `test/`); the PR is a draft; nothing targets `upstream`
(`tejaspalukuri/CARVIS`); the change is one bounded task, with no cleanup mixed into feature work.

## 2. Review checklist

**Protected boundaries (`AGENTS.md`).** `/vapi-tool`, `/upload`, `/vision-query`, conversation/camera
contracts, ingestion, Vapi, Nemotron, and Meta Wearables are unchanged unless a scoped migration says
otherwise. Ingestion writes pending-review v2 records only to unaliased staging; no OCR auto-verified,
no alias mutation, no weakened evidence checks, no cross-vehicle fallback, no change to the legacy
collection outside `docs/backend/qdrant-v2-migration.md`. No web product UI added.

**Safety of answers.** No invented specs, part numbers, warnings, or procedures; refusal and
clarification paths intact; similarity, model confidence, OCR, or images never act as proof.

**Security and tenancy.** Authority derives from an authenticated principal, never from a caller-supplied
user, shop, vehicle, or session ID. Look for new routes without auth, IDOR-prone lookups, optional
secrets that should fail closed, tokens in URLs, and `shop_id`/owner fields trusted from request bodies.

**Privacy and secrets.** Run the CI patterns locally against the diff and tracked files:

```bash
git ls-files | grep -E '(^|/)(\.env($|\.)|VapiConfig\.plist$|carvis_mvp_db/|node_modules/|xcuserdata/|__pycache__/)|\.(pdf|pem|p12)$'
git grep -I -n -E 'BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|github_pat_[A-Za-z0-9_]{20,}|gh[p]_[A-Za-z0-9]{20,}|sk_(live|test)_[A-Za-z0-9]{16,}' -- . ':!docs/archive/**'
```

Also check for raw audio, transcripts, captured images, manuals, local Qdrant data, review exports,
machine-specific absolute paths, personal/shop/vehicle data, and logging of questions, vehicle
context, or identity. Signing/entitlement edits in `ios/Carvis/*.plist`, `*.entitlements`, or
`project.pbxproj` must be intentional and separate.

**Migration safety.** For database changes: additive/expand-contract steps, reversible, tested on a
scratch store, no destructive DDL, no production mutation. For Qdrant: never mutate an aliased
collection; new generation staged and validated before activation; rollback target is a previously
validated v2 generation. For SpacetimeDB: no publish, clear, rename, or schema migration without
explicit approval, authorization regression tests, and a rollback plan; generated bindings are never
hand-edited.

**Tests.** Failure, refusal, isolation, cancellation, and recovery paths are tested, not only success.
New behavior has tests that fail without the change. No assertions weakened or tests skipped. Use the
`carvis-regression` skill to run the narrowest checks (and `scripts/verify.sh` when warranted); compare
with CI jobs `Backend and hygiene`, `Swift pure checks`, `SpacetimeDB typecheck`.

**Docs and contracts.** Behavior or API changes update `docs/` (and ADRs under `docs/decisions/` for
architecture decisions). `AGENTS.md`/`CLAUDE.md` stay concise and link instead of duplicating.
Local links resolve (the `scripts/verify.sh` documentation-link check).

## 3. PR readiness and rollback

Compare the PR body with `.github/PULL_REQUEST_TEMPLATE.md`: Summary, Related work, Scope,
Verification (commands and results, with mocked/local/simulator/device/live/production labeled
separately), Evidence, Risk review, **Rollback**, and the completion checklist. A change is not ready
if rollback is empty or vague. A rollback entry names the exact revert or disable step, data or
schema implications, and what is irreversible. Required status checks must be green and the branch
up to date with `main` before human-approved squash merge.

## 4. Report

Findings first, most severe first, each with `file:line`, the concrete failure scenario, and a
suggested fix. Then:

- **Verdict:** ready for review / needs changes / blocked (with the reason).
- **Verified by running:** commands and results.
- **Not verified:** physical-device, live-provider, production, or unavailable tooling, stated plainly.
- **CI:** per-check status from `gh pr checks`, or "no PR yet".
- **Needs human decision:** anything only the owner can approve (merge, deploy, provider or alias changes).

Never claim a check passed that you did not run or read from CI.

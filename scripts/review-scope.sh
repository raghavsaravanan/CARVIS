#!/usr/bin/env bash
# Print the review packet for one committed candidate and refuse a candidate that cannot be
# reviewed. Model-independent: any reviewer or coordinator runs it. It never fetches, writes, or
# changes anything; run `git fetch origin main` first so drift is current.
#
# Usage: scripts/review-scope.sh [--tier T1|T2|T3|T4] [--since <previous-candidate>] <base> <candidate>
#
#   <base>       the integration commit the task started from (or was last updated from)
#   <candidate>  the committed revision under review; it must be checked out (HEAD)
#   --tier       the task contract's tier; refused if lower than the tier the changed paths require
#   --since      the previously reviewed candidate; prints the delta to re-review, limited to the
#                task's own files so integration-branch changes merged in are not mixed into it
#
# The reviewed diff runs from the effective base: <base>, or the merge-base with the integration
# branch when the task branch has been updated from it since (git merge, never rebase).
# REVIEW_SCOPE_AGAINST overrides the integration ref (default origin/main).
#
# Exit status:
#   0  reviewable; any integration drift is not material (it still needs a drift check)
#   1  not reviewable: dirty or untracked files, HEAD is not the candidate, base or --since is not
#      an ancestor, empty diff, whitespace errors, a submodule change, tier below the path floor,
#      or an unresolvable revision
#   2  usage error
#   3  reviewable, but the integration branch changed files this task touches, or policy, CI,
#      script or dependency files: update the branch, rerun checks, and renew review
set -euo pipefail

usage() { echo "usage: scripts/review-scope.sh [--tier T1|T2|T3|T4] [--since <sha>] <base> <candidate>" >&2; exit 2; }
tier=""; since=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tier) [[ $# -ge 2 ]] || usage; tier="$2"; shift 2 ;;
    --since) [[ $# -ge 2 ]] || usage; since="$2"; shift 2 ;;
    -*) usage ;;
    *) break ;;
  esac
done
[[ $# -eq 2 ]] || usage
case "${tier}" in ""|T1|T2|T3|T4) ;; *) usage ;; esac
against="${REVIEW_SCOPE_AGAINST:-origin/main}"

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "NOT REVIEWABLE: not a git work tree"; exit 1; }
cd "$(git rev-parse --show-toplevel)"
# Resolve in the main shell: an exit inside $(...) would only leave the subshell.
resolve() { # <var> <rev>
  local sha
  sha="$(git rev-parse --verify --quiet "$2^{commit}")" || { echo "NOT REVIEWABLE: cannot resolve $2"; exit 1; }
  printf -v "$1" '%s' "${sha}"
}
resolve base "$1"
resolve candidate "$2"
head="$(git rev-parse HEAD)"
blocked=0
block() { echo "NOT REVIEWABLE: $*"; blocked=1; }

# Minimum tier for a path (docs/development-workflow.md, "Risk tiers"). A floor, never a ceiling.
path_tier() {
  case "$1" in
    backend/spec_*.py|backend/qdrant_v2.py|backend/migrate_v2.py|backend/ingest.py|\
    backend/purge_db.py|backend/conversation.py|backend/vapi_assistant.py|backend/vapi/*|\
    backend/schemas/*|backend/tests/test_specs_v2.py|backend/tests/test_ride_height.py|\
    backend/tests/test_conversation.py|backend/tests/test_vapi_assistant.py|\
    backend/tests/fixtures/*|docs/backend/qdrant-v2-migration.md) echo 4 ;;
    backend/main.py|backend/webhook_auth.py|backend/upload_security.py|backend/request_limits.py|\
    backend/deployment_config.py|backend/log_config.py|backend/setup.sh|backend/requirements*|\
    backend/spacetimedb/*|backend/tests/*|requirements.txt|runtime.txt|render.yaml|Procfile|\
    .renderignore|.gitignore|.gitattributes|.github/*|scripts/*|.claude/*|AGENTS.md|*/AGENTS.md|\
    CLAUDE.md|orca.yaml|docs/decisions/*|docs/PRD.md|docs/product/*|docs/development-workflow.md|\
    ios/Carvis/Carvis/Backend/*|ios/Carvis/Carvis/Config/*|ios/Carvis/*.plist|\
    ios/Carvis/*.entitlements|ios/Carvis/Carvis.xcodeproj/*) echo 3 ;;
    backend/*|ios/*) echo 2 ;;
    *) echo 1 ;;
  esac
}

# Effective base: re-anchor to the integration merge-base when the branch was updated from it.
effective="${base}"
git merge-base --is-ancestor "${base}" "${candidate}" || block "base is not an ancestor of the candidate"
against_sha=""
if git rev-parse --verify --quiet "${against}^{commit}" >/dev/null; then
  against_sha="$(git rev-parse "${against}")"
  fork="$(git merge-base "${candidate}" "${against_sha}")"
  if [[ "${fork}" != "${base}" ]] && git merge-base --is-ancestor "${base}" "${fork}"; then
    effective="${fork}"
  fi
fi

echo "== Review packet =="
echo "worktree:    $(pwd)"
echo "branch:      $(git branch --show-current || true)"
echo "base:        ${base}"
[[ "${effective}" == "${base}" ]] || echo "re-anchored: ${effective} (branch was updated from ${against}; review from here)"
echo "candidate:   ${candidate}"
echo "${against}: ${against_sha:-unavailable} (pinned for this packet)"

# 1. Exactly the candidate: no local edits, no untracked files, HEAD is the candidate.
dirty="$(git status --porcelain=v1 --untracked-files=all --ignore-submodules=none)"
if [[ -n "${dirty}" ]]; then
  block "working tree is not clean (commit or remove these first):"
  printf '%s\n' "${dirty}" | sed 's/^/  /'
fi
[[ "${head}" == "${candidate}" ]] || block "HEAD ${head} is not the candidate"

# 2. Every changed file with type and mode, renames and copies detected, no external drivers.
echo "== Commits (subjects only; reviewers form findings before reading commit bodies) =="
git log --no-decorate --format='%h %s' "${effective}..${candidate}"
merges="$(git rev-list --merges --count "${effective}..${candidate}")"
[[ "${merges}" == "0" ]] || echo "NOTE: ${merges} merge commit(s); review the combined diff, not single commits."

echo "== Changed files (every one must be reviewed) =="
raw="$(git diff --no-ext-diff --no-textconv --raw -M -C "${effective}" "${candidate}")"
count="$(printf '%s' "${raw}" | grep -c . || true)"
printf '%s\n' "${raw}" | awk -F'\t' 'NF { split($1, f, " "); printf "%-6s %s -> %s  %s%s\n", f[5], f[1], f[2], $2, (NF > 2 ? " -> " $3 : "") }'
echo "total: ${count}"
[[ "${count}" -gt 0 ]] || block "no changes between the effective base and the candidate"
paths="$(git diff --no-ext-diff --name-only -M -C "${effective}" "${candidate}"; \
         git diff --no-ext-diff --name-status -M -C "${effective}" "${candidate}" | awk -F'\t' '$1 ~ /^[RC]/ {print $2}')"

flag() { echo "== $1 =="; printf '%s\n' "$2" | sed 's/^/  /'; }
symlinks="$(printf '%s\n' "${raw}" | awk -F'\t' '$1 ~ /(^:| )120000 / {print $NF}')"
[[ -z "${symlinks}" ]] || flag "Symlinks (check each target)" "${symlinks}"
gitlinks="$(printf '%s\n' "${raw}" | awk -F'\t' '$1 ~ /(^:| )160000 / {print $NF}')"
[[ -z "${gitlinks}" ]] || { flag "Submodule changes" "${gitlinks}"; block "submodule changes are not reviewable here"; }
binary="$(git diff --no-ext-diff --no-textconv --numstat "${effective}" "${candidate}" | awk -F'\t' '$1=="-" {print $3}')"
[[ -z "${binary}" ]] || flag "Binary files (text checks and secret scans skip these; justify each)" "${binary}"
modes="$(git diff --no-ext-diff --summary "${effective}" "${candidate}" | grep -E 'mode change|create mode 100755' || true)"
[[ -z "${modes}" ]] || flag "Executable or mode changes" "${modes}"
archive="$(printf '%s\n' "${paths}" | grep -E '^docs/archive/' || true)"
[[ -z "${archive}" ]] || flag "Paths under docs/archive (excluded from the CI secret scan)" "${archive}"
gates="$(printf '%s\n' "${paths}" | grep -E '^(\.github/|scripts/verify\.sh|scripts/check-runtime-lock\.sh|\.claude/skills/)' || true)"
[[ -z "${gates}" ]] || flag "Quality-gate changes (a change that weakens a gate can pass that gate; review against the previous gate)" "${gates}"
locks="$(printf '%s\n' "${paths}" | grep -E '^(backend/requirements|requirements\.txt|runtime\.txt|backend/spacetimedb/module/package)' || true)"
[[ -z "${locks}" ]] || flag "Dependency changes (also run scripts/check-runtime-lock.sh)" "${locks}"
hooks_path="$(git config --get core.hooksPath || true)"
hooks="$(find "$(git rev-parse --git-common-dir)/hooks" -type f ! -name '*.sample' 2>/dev/null || true)"
[[ -z "${hooks_path}${hooks}" ]] || flag "Shared git hooks (run in every worktree, appear in no diff)" "${hooks_path:+core.hooksPath=${hooks_path}}${hooks}"

# 3. Tier floor from the changed paths.
floor=1; raisers=""
while IFS= read -r p; do
  [[ -n "${p}" ]] || continue
  t="$(path_tier "${p}")"
  if [[ "${t}" -gt "${floor}" ]]; then floor="${t}"; raisers=""; fi
  [[ "${t}" -eq "${floor}" && "${t}" -gt 1 ]] && raisers="${raisers}${p}"$'\n'
done < <(printf '%s\n' "${paths}" | sort -u)
echo "== Tier =="
echo "declared: ${tier:-none}; minimum for these paths: T${floor}"
[[ -z "${raisers}" ]] || printf '%s' "${raisers}" | sort -u | head -n 10 | sed 's/^/  requires T'"${floor}"': /'
if [[ -n "${tier}" && "${tier#T}" -lt "${floor}" ]]; then
  block "declared ${tier} is below the T${floor} these paths require; only the owner may lower a tier"
fi

echo "== Size =="
git diff --no-ext-diff --stat=120 "${effective}" "${candidate}" | tail -n 1
echo "== Whitespace (git diff --check) =="
if git diff --no-ext-diff --check "${effective}" "${candidate}"; then echo "clean"; else block "whitespace errors above"; fi

# 4. Delta since the previous review, limited to this task's files.
if [[ -n "${since}" ]]; then
  resolve prev "${since}"
  echo "== Delta since ${prev} (re-review these) =="
  if git merge-base --is-ancestor "${prev}" "${candidate}"; then
    task_files="$(printf '%s\n' "${paths}" | sort -u | grep . || true)"
    if [[ -n "${task_files}" ]]; then
      delta="$(printf '%s\n' "${task_files}" | tr '\n' '\0' | xargs -0 git diff --no-ext-diff --name-status "${prev}" "${candidate}" --)"
      printf '%s\n' "${delta:-no task-file changes}"
    fi
  else
    block "previous candidate ${prev} is not an ancestor; history changed, so a full review is required"
  fi
fi

# 5. Drift: integration commits the candidate does not contain, pinned to the SHA printed above.
echo "== Integration drift =="
material=0
if [[ -n "${against_sha}" ]]; then
  drift="$(git rev-list --count "${candidate}..${against_sha}")"
  echo "commits on ${against} not in candidate: ${drift}"
  if [[ "${drift}" -gt 0 ]]; then
    fork="$(git merge-base "${candidate}" "${against_sha}")"
    drifted="$(git diff --no-ext-diff --name-only "${fork}" "${against_sha}")"
    overlap="$(comm -12 <(printf '%s\n' "${drifted}" | sort -u) <(printf '%s\n' "${paths}" | sort -u) | grep . || true)"
    policy="$(printf '%s\n' "${drifted}" | grep -E '^(AGENTS\.md|CLAUDE\.md|orca\.yaml|\.claude/|\.github/|scripts/|backend/requirements|requirements\.txt|runtime\.txt|backend/spacetimedb/module/package)|/AGENTS\.md$' || true)"
    [[ -z "${overlap}" ]] || { flag "Drift overlaps this task's files" "${overlap}"; material=1; }
    [[ -z "${policy}" ]] || { flag "Drift changes policy, CI, script or dependency files" "${policy}"; material=1; }
    if [[ "${material}" -eq 1 ]]; then
      echo "MATERIAL DRIFT: merge ${against} (no rebase), rerun checks, renew review."
    else
      echo "Drift is not material by path. Before approval, check the drifted files for contract,"
      echo "import or fixture effects on this task, and record the result in the PR."
      printf '%s\n' "${drifted}" | head -n 20 | sed 's/^/  drifted: /'
    fi
  fi
else
  echo "WARN: ${against} not found; drift unchecked (run git fetch origin main)."
fi

[[ "${blocked}" -eq 0 ]] || exit 1
[[ "${material}" -eq 0 ]] || exit 3
echo "REVIEWABLE: ${candidate} (effective base ${effective})"

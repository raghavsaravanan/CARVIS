#!/usr/bin/env bash
# Print the review packet for one committed candidate and refuse a candidate that cannot be
# reviewed. Model-independent: any reviewer or coordinator runs it. It never fetches, writes, or
# changes anything; run `git fetch origin main` first so drift is current.
#
# Usage: scripts/review-scope.sh [--tier T1|T2|T3|T4] [--since <previous-candidate>] <base> <candidate>
#
#   <base>       the integration commit the task started from (or was last updated from); it must
#                be on the integration branch, never a task commit
#   <candidate>  the committed revision under review; it must be checked out (HEAD)
#   --tier       the task's tier; refused if lower than the tier the changed paths require
#   --since      the previously reviewed candidate; prints the delta to re-review, including files
#                the correction reverted, but not files that only arrived by merging the
#                integration branch. A merge that brought in T3+ files is a material update (exit 3)
#
# The reviewed diff runs from the effective base: <base>, or the merge-base with the integration
# branch when the task branch has been updated from it since (git merge, never rebase).
# The integration ref is always origin/main; there is deliberately no override. Reviewers run the
# integration branch's copy of this script when it has one, so a candidate cannot weaken the check
# that reviews it (docs/development-workflow.md, "Review protocol"). Never pipe it into bash: a
# pipeline reports bash's status, so a missing copy would look like success. Accept a packet only
# on exit 0 with the last line "REVIEWABLE: <candidate> ...".
#
# Exit status:
#   0  reviewable; any integration drift is not material (it still needs a drift check)
#   1  not reviewable: dirty or untracked files, HEAD is not the candidate, base or --since is not
#      an ancestor, base is not an integration commit, missing integration ref, empty diff,
#      whitespace errors, a submodule change, an unusual path name, tier below the path floor, or an
#      unresolvable revision
#   2  usage error
#   3  reviewable, but the integration branch changed files this task touches, or files whose
#      minimum tier is T3 or higher (policy, CI, scripts, dependencies), either still unmerged or
#      merged since the --since candidate: update the branch if needed, rerun checks, renew review
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
against="origin/main"

# Unquoted UTF-8 path names; names git must still quote (quotes, backslashes, control characters)
# are refused below rather than matched wrongly.
g() { git -c core.quotePath=false "$@"; }

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
git rev-parse --verify --quiet "${against}^{commit}" >/dev/null \
  || { echo "NOT REVIEWABLE: integration ref ${against} not found; run git fetch origin main"; exit 1; }
resolve against_sha "${against}"
head="$(git rev-parse HEAD)"
blocked=0
material=0
block() { echo "NOT REVIEWABLE: $*"; blocked=1; }

# Minimum tier for a path (docs/development-workflow.md, "Risk tiers"). A floor, never a ceiling.
path_tier() {
  case "$1" in
    backend/spec_*.py|backend/qdrant_v2.py|backend/migrate_v2.py|backend/ingest.py|\
    backend/purge_db.py|backend/conversation.py|backend/vapi_assistant.py|backend/vapi/*|\
    backend/schemas/*|backend/tests/test_specs_v2.py|backend/tests/test_ride_height.py|\
    backend/tests/test_conversation.py|backend/tests/test_vapi_assistant.py|\
    backend/tests/fixtures/*|docs/backend/qdrant-v2-migration.md|docs/architecture/07-brain.md|\
    backend/main.py|backend/tests/test_main.py|docs/architecture/10-threat-model-and-tests.md) echo 4 ;;
    backend/webhook_auth.py|backend/upload_security.py|backend/request_limits.py|\
    backend/deployment_config.py|backend/log_config.py|backend/setup.sh|backend/requirements*|\
    backend/spacetimedb/*|backend/tests/*|requirements.txt|runtime.txt|render.yaml|Procfile|\
    .renderignore|.gitignore|.gitattributes|.github/*|scripts/*|.claude/*|AGENTS.md|*/AGENTS.md|\
    CLAUDE.md|orca.yaml|docs/decisions/*|docs/PRD.md|docs/product/*|docs/README.md|\
    docs/development-workflow.md|docs/architecture/*|docs/backend/*|\
    ios/Carvis/Carvis/Backend/*|ios/Carvis/Carvis/Config/*|ios/Carvis/*.plist|\
    ios/Carvis/*.entitlements|ios/Carvis/Carvis.xcodeproj/*) echo 3 ;;
    backend/*|ios/*) echo 2 ;;
    *) echo 1 ;;
  esac
}
max_tier() {
  local m=1 p t
  while IFS= read -r p; do
    [[ -n "${p}" ]] || continue
    t="$(path_tier "${p}")"
    if [[ "${t}" -gt "${m}" ]]; then m="${t}"; fi
  done
  echo "${m}"
}

# Effective base: re-anchor to the integration merge-base when the branch was updated from it.
git merge-base --is-ancestor "${base}" "${candidate}" || block "base is not an ancestor of the candidate"
git merge-base --is-ancestor "${base}" "${against_sha}" \
  || block "base ${base} is not on ${against}; pass the integration commit the task started from (use --since for a previous candidate)"
effective="${base}"
fork="$(git merge-base "${candidate}" "${against_sha}")" \
  || { echo "NOT REVIEWABLE: the candidate shares no history with ${against}"; exit 1; }
if [[ "${fork}" != "${base}" ]] && git merge-base --is-ancestor "${base}" "${fork}"; then
  effective="${fork}"
fi

echo "== Review packet =="
echo "worktree:    $(pwd)"
echo "branch:      $(git branch --show-current || true)"
echo "base:        ${base}"
[[ "${effective}" == "${base}" ]] || echo "re-anchored: ${effective} (branch was updated from ${against}; review from here)"
echo "candidate:   ${candidate}"
echo "${against}: ${against_sha} (pinned for this packet)"

# 1. Exactly the candidate: no local edits, no untracked files, HEAD is the candidate.
dirty="$(g status --porcelain=v1 --untracked-files=all --ignore-submodules=none)"
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
raw="$(g diff --no-ext-diff --no-textconv --raw -M -C "${effective}" "${candidate}")"
count="$(printf '%s' "${raw}" | grep -c . || true)"
printf '%s\n' "${raw}" | awk -F'\t' 'NF { split($1, f, " "); printf "%-6s %s -> %s  %s%s\n", f[5], f[1], f[2], $2, (NF > 2 ? " -> " $3 : "") }'
echo "total: ${count}"
[[ "${count}" -gt 0 ]] || block "no changes between the effective base and the candidate"
# Current paths plus rename and copy sources, so a move out of a protected path keeps its tier.
paths="$(printf '%s\n' "${raw}" | awk -F'\t' 'NF { for (i = 2; i <= NF; i++) print $i }' | sort -u)"
odd="$(printf '%s\n' "${paths}" | grep '^"' || true)"
if [[ -n "${odd}" ]]; then
  printf '%s\n' "${odd}" | sed 's/^/  /'
  block "path names that git quotes (quotes, backslashes or control characters) cannot be classified"
fi

flag() { echo "== $1 =="; printf '%s\n' "$2" | sed 's/^/  /'; }
symlinks="$(printf '%s\n' "${raw}" | awk -F'\t' '$1 ~ /(^:| )120000 / {print $NF}')"
[[ -z "${symlinks}" ]] || flag "Symlinks (check each target)" "${symlinks}"
gitlinks="$(printf '%s\n' "${raw}" | awk -F'\t' '$1 ~ /(^:| )160000 / {print $NF}')"
if [[ -n "${gitlinks}" ]]; then flag "Submodule changes" "${gitlinks}"; block "submodule changes are not reviewable here"; fi
binary="$(g diff --no-ext-diff --no-textconv --numstat "${effective}" "${candidate}" | awk -F'\t' '$1=="-" {print $3}')"
[[ -z "${binary}" ]] || flag "Binary files (text checks and secret scans skip these; justify each)" "${binary}"
modes="$(g diff --no-ext-diff --summary "${effective}" "${candidate}" | grep -E 'mode change|create mode 100755' || true)"
[[ -z "${modes}" ]] || flag "Executable or mode changes" "${modes}"
archive="$(printf '%s\n' "${paths}" | grep -E '^docs/archive/' || true)"
[[ -z "${archive}" ]] || flag "Paths under docs/archive (excluded from the CI secret scan)" "${archive}"
gates="$(printf '%s\n' "${paths}" | grep -E '^(\.github/|scripts/|\.claude/skills/)' || true)"
[[ -z "${gates}" ]] || flag "Quality-gate changes (a change that weakens a gate can pass that gate; review against the previous gate)" "${gates}"
if printf '%s\n' "${paths}" | grep -qx 'scripts/review-scope.sh'; then
  echo "NOTE: this script changed; the review must use ${against}'s copy if it has one"
  echo "  (docs/development-workflow.md, Review protocol; never pipe it into bash)."
fi
locks="$(printf '%s\n' "${paths}" | grep -E '^(backend/requirements|requirements\.txt|runtime\.txt|backend/spacetimedb/module/package)' || true)"
[[ -z "${locks}" ]] || flag "Dependency changes (also run scripts/check-runtime-lock.sh)" "${locks}"
hooks_path="$(git config --get core.hooksPath || true)"
hooks="$(find "$(git rev-parse --git-common-dir)/hooks" -type f ! -name '*.sample' 2>/dev/null || true)"
[[ -z "${hooks_path}${hooks}" ]] || flag "Shared git hooks (run in every worktree, appear in no diff)" "${hooks_path:+core.hooksPath=${hooks_path}}${hooks}"

# 3. Tier floor from the changed paths.
floor="$(printf '%s\n' "${paths}" | max_tier)"
echo "== Tier =="
echo "declared: ${tier:-none}; minimum for these paths: T${floor}"
if [[ "${floor}" -gt 1 ]]; then
  shown=0
  while IFS= read -r p; do
    [[ -n "${p}" ]] || continue
    if [[ "$(path_tier "${p}")" -eq "${floor}" && "${shown}" -lt 10 ]]; then
      echo "  requires T${floor}: ${p}"; shown=$((shown + 1))
    fi
  done <<< "${paths}"
fi
if [[ -n "${tier}" && "${tier#T}" -lt "${floor}" ]]; then
  block "declared ${tier} is below the T${floor} these paths require; only the owner may lower a tier"
fi

echo "== Size =="
g diff --no-ext-diff --stat=120 "${effective}" "${candidate}" | tail -n 1
echo "== Whitespace (git diff --check) =="
if g diff --no-ext-diff --check "${effective}" "${candidate}"; then echo "clean"; else block "whitespace errors above"; fi

# 4. Delta since the previous review: every file the correction touched, including files it
# reverted to the base, minus files that only arrived by merging the integration branch.
if [[ -n "${since}" ]]; then
  resolve prev "${since}"
  echo "== Delta since ${prev} (re-review these) =="
  if git merge-base --is-ancestor "${prev}" "${candidate}"; then
    prev_effective="${base}"
    prev_fork="$(git merge-base "${prev}" "${against_sha}")"
    if git merge-base --is-ancestor "${base}" "${prev_fork}"; then prev_effective="${prev_fork}"; fi
    task_paths="$( { printf '%s\n' "${paths}"; g diff --no-ext-diff --name-only "${prev_effective}" "${prev}"; } | sort -u)"
    merged_in="$(g diff --no-ext-diff --no-renames --name-only "${prev_effective}" "${effective}" | sort -u)"
    # Path lists go through the environment: BSD awk rejects newlines in -v values.
    delta="$(g diff --no-ext-diff --no-renames --name-status "${prev}" "${candidate}" \
      | RS_TASK="${task_paths}" RS_MERGED="${merged_in}" awk -F'\t' '
          BEGIN { n = split(ENVIRON["RS_TASK"], t, "\n"); for (i = 1; i <= n; i++) T[t[i]] = 1
                  n = split(ENVIRON["RS_MERGED"], m, "\n"); for (i = 1; i <= n; i++) M[m[i]] = 1 }
          ($2 in T) || !($2 in M)')"
    printf '%s\n' "${delta:-no task-file changes}"
    merged_policy=""
    while IFS= read -r p; do
      if [[ -n "${p}" && "$(path_tier "${p}")" -ge 3 ]]; then merged_policy="${merged_policy}${p}"$'\n'; fi
    done <<< "${merged_in}"
    merged_task="$(comm -12 <(printf '%s\n' "${task_paths}") <(printf '%s\n' "${merged_in}") | grep . || true)"
    if [[ -n "${merged_task}" ]]; then
      flag "Merged in since ${prev}: changes to this task's files" "${merged_task}"
      material=1
    fi
    if [[ -n "${merged_policy}" ]]; then
      flag "Merged in since ${prev}: T3+ files (policy, CI, scripts, dependencies, security)" "${merged_policy%$'\n'}"
      material=1
    fi
    if [[ "${material}" -eq 1 ]]; then
      echo "MATERIAL UPDATE: the reviews of ${prev} do not carry over. Renew review in full: rerun"
      echo "without --since and review the effective base to the candidate."
    fi
  else
    block "previous candidate ${prev} is not an ancestor; history changed, so a full review is required"
  fi
fi

# 5. Drift: integration commits the candidate does not contain, pinned to the SHA printed above.
echo "== Integration drift =="
drift="$(git rev-list --count "${candidate}..${against_sha}")"
echo "commits on ${against} not in candidate: ${drift}"
if [[ "${drift}" -gt 0 ]]; then
  drifted="$(g diff --no-ext-diff --no-renames --name-only "${fork}" "${against_sha}" | sort -u)"
  overlap="$(comm -12 <(printf '%s\n' "${drifted}") <(printf '%s\n' "${paths}") | grep . || true)"
  policy=""
  while IFS= read -r p; do
    if [[ -n "${p}" && "$(path_tier "${p}")" -ge 3 ]]; then policy="${policy}${p}"$'\n'; fi
  done <<< "${drifted}"
  if [[ -n "${overlap}" ]]; then flag "Drift overlaps this task's files" "${overlap}"; material=1; fi
  if [[ -n "${policy}" ]]; then flag "Drift changes T3+ files (policy, CI, scripts, dependencies, security)" "${policy%$'\n'}"; material=1; fi
  if [[ "${material}" -eq 1 ]]; then
    echo "MATERIAL DRIFT: merge ${against} (no rebase), rerun checks, renew review."
  else
    echo "Drift is not material by path. Before approval, check the drifted files for contract,"
    echo "import or fixture effects on this task, and record the result in the PR."
    printf '%s\n' "${drifted}" | head -n 20 | sed 's/^/  drifted: /'
  fi
fi

[[ "${blocked}" -eq 0 ]] || exit 1
[[ "${material}" -eq 0 ]] || exit 3
echo "REVIEWABLE: ${candidate} (effective base ${effective})"

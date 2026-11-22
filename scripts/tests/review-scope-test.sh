#!/usr/bin/env bash
# Scenario tests for scripts/review-scope.sh in throwaway local repositories (no network).
# Usage: scripts/tests/review-scope-test.sh        (run by scripts/verify.sh and CI)
set -u
SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/review-scope.sh"
T="$(mktemp -d "${TMPDIR:-/tmp}/carvis-review-scope-test.XXXXXX")"
finished=0
# Bash 3.2 reports status 0 to an EXIT trap after a `set -u` abort: only a run that reaches the end
# can pass.
trap 'status=$?; rm -rf "${T}"; [[ "${finished}" -eq 1 ]] || status=1; exit "${status}"' EXIT
pass=0; fail=0
expect() { # <name> <exit> <output-regex or ''> <cmd...>
  local name="$1" want="$2" re="$3"; shift 3
  local out rc; out="$("$@" 2>&1)"; rc=$?
  if [[ "${rc}" == "${want}" ]] && { [[ -z "${re}" ]] || printf '%s' "${out}" | grep -Eq -- "${re}"; }; then
    pass=$((pass+1)); echo "PASS ${name} (exit ${rc})"
  else
    fail=$((fail+1)); echo "FAIL ${name}: want exit ${want}${re:+ and /${re}/}, got ${rc}"; printf '%s\n' "${out}" | sed 's/^/    /'
  fi
}
refute() { # <name> <regex that must NOT appear in the named section> <section-start> <section-end> <cmd...>
  local name="$1" re="$2" from="$3" to="$4"; shift 4
  local out rc; out="$("$@" 2>&1)"; rc=$?
  if [[ "${rc}" -ne 0 ]]; then
    fail=$((fail+1)); echo "FAIL ${name}: command exited ${rc}"; printf '%s\n' "${out}" | sed 's/^/    /'
  elif ! printf '%s\n' "${out}" | grep -q -- "${from#^}"; then
    fail=$((fail+1)); echo "FAIL ${name}: section ${from} missing"
  elif printf '%s\n' "${out}" | sed -n "/${from}/,/${to}/p" | grep -Eq -- "${re}"; then
    fail=$((fail+1)); echo "FAIL ${name}: /${re}/ present"
  else
    pass=$((pass+1)); echo "PASS ${name}"
  fi
}
quiet() { "$@" >/dev/null 2>&1; }
cfg() { git config user.email t@example.invalid; git config user.name t; git config commit.gpgsign false; }
drift() { # <file> <content>: commit a change on origin/main and fetch it
  (cd "${T}/origin" && mkdir -p "$(dirname "$1")" && printf '%s\n' "$2" >> "$1" && git add -A && git commit -qm "drift $1")
  quiet git fetch origin
}

git init -q -b main "${T}/origin" && cd "${T}/origin" && cfg
mkdir -p docs scripts backend; printf 'a\n' > docs/a.md; printf 'b\n' > docs/b.md
printf 'x\n' > scripts/x.sh; printf 'm\n' > backend/main.py
git add -A; git commit -qm base
git clone -q "${T}/origin" "${T}/work" && cd "${T}/work" && cfg
BASE="$(git rev-parse HEAD)"
R="${SCRIPT}"

# Usage and unreviewable inputs.
expect usage-none 2 '' bash "${R}"
expect usage-one 2 '' bash "${R}" "${BASE}"
expect usage-bad-tier 2 '' bash "${R}" --tier T9 "${BASE}" HEAD
expect usage-bad-flag 2 '' bash "${R}" --bogus "${BASE}" HEAD
expect empty-diff 1 'no changes' bash "${R}" "${BASE}" "${BASE}"
expect bad-revision 1 'cannot resolve nosuchref' bash "${R}" nosuchref HEAD
git clone -q "${T}/origin" "${T}/noref" && (cd "${T}/noref" && git update-ref -d refs/remotes/origin/main)
expect missing-integration-ref 1 'integration ref origin/main not found' bash -c 'cd "$1" && bash "$2" "$3" HEAD' _ "${T}/noref" "${R}" "${BASE}"
expect no-override 1 'integration ref origin/main not found' bash -c 'cd "$1" && REVIEW_SCOPE_AGAINST=origin/HEAD bash "$2" "$3" HEAD' _ "${T}/noref" "${R}" "${BASE}"

git switch -qc docs/t; printf 'a2\n' >> docs/a.md; git commit -qam change
C1="$(git rev-parse HEAD)"
expect clean-T1 0 'REVIEWABLE' bash "${R}" --tier T1 "${BASE}" "${C1}"
expect lists-file 0 'M +:100644 -> 100644  docs/a\.md' bash "${R}" "${BASE}" "${C1}"
expect floor-T1 0 'minimum for these paths: T1' bash "${R}" "${BASE}" "${C1}"
expect runs-from-stdin 0 'REVIEWABLE' bash -s -- --tier T1 "${BASE}" "${C1}" < "${R}"
printf 'dirty\n' >> docs/b.md
expect dirty-tracked 1 'not clean' bash "${R}" "${BASE}" "${C1}"
git checkout -q -- docs/b.md
printf 'u\n' > untracked.txt
expect untracked 1 'not clean' bash "${R}" "${BASE}" "${C1}"
rm untracked.txt
quiet git switch --detach "${BASE}"
expect head-not-candidate 1 'is not the candidate' bash "${R}" "${BASE}" "${C1}"
quiet git switch docs/t
ORPHAN="$(git commit-tree "$(git rev-parse 'HEAD^{tree}')" -m orphan)"
expect base-not-ancestor 1 'not an ancestor of the candidate' bash "${R}" "${ORPHAN}" "${C1}"

# Tier floors: T3 (scripts, backend/main.py), T4 (evidence path), rename source keeps its tier.
printf 'x2\n' >> scripts/x.sh; git commit -qam script
C2="$(git rev-parse HEAD)"
expect tier-below-floor 1 'below the T3' bash "${R}" --tier T1 "${BASE}" "${C2}"
expect tier-at-floor 0 'REVIEWABLE' bash "${R}" --tier T3 "${BASE}" "${C2}"
expect gate-flagged 0 'Quality-gate changes.*' bash "${R}" --tier T3 "${BASE}" "${C2}"
expect gate-names-path 0 '^  scripts/x\.sh$' bash "${R}" --tier T3 "${BASE}" "${C2}"
# A task commit passed as the base hides earlier task changes (and their tier); it is refused.
printf 'm2\n' >> backend/main.py; git commit -qam main-py
printf 'a3\n' >> docs/a.md; git commit -qam docs-after
expect base-is-task-commit 1 'is not on origin/main' bash "${R}" --tier T1 HEAD~1 HEAD
mkdir -p backend/vapi; printf 'v\n' > backend/vapi/new.py; git add -A; git commit -qm t4
expect floor-T4 1 'below the T4' bash "${R}" --tier T3 "${BASE}" HEAD
git rm -q backend/vapi/new.py; git commit -qm undo-t4
mkdir -p backend/vapi; printf 'p\n' > backend/vapi/assistant_prompt.md; git add -A; git commit -qm t4-file
(cd "${T}/origin" && mkdir -p backend/vapi && printf 'p\n' > backend/vapi/assistant_prompt.md && git add -A && git commit -qm add-prompt)
quiet git fetch origin; quiet git merge --no-edit origin/main
git mv backend/vapi/assistant_prompt.md docs/prompt-moved.md; git commit -qm move-out
expect rename-source-tier 1 'below the T4' bash "${R}" --tier T3 "$(git rev-parse origin/main)" HEAD
quiet git revert --no-edit HEAD

# Unusual path names cannot be classified and are refused; UTF-8 names are read unquoted.
printf 'c\n' > "backend/vapi/café.py"; git add -A; git commit -qm utf8
expect utf8-path-tier 1 'below the T4' bash "${R}" --tier T3 "${BASE}" HEAD
quiet git revert --no-edit HEAD
printf 'q\n' > 'docs/odd"name.md'; git add -A; git commit -qm odd
expect quoted-path-refused 1 'cannot be classified' bash "${R}" --tier T4 "${BASE}" HEAD
quiet git revert --no-edit HEAD

# Dependency and archive flags, binary, symlink, mode change.
printf 'dep\n' > requirements.txt; git add -A; git commit -qm dep
expect dependency-flagged 0 'Dependency changes' bash "${R}" --tier T4 "${BASE}" HEAD
printf '\000\001' > docs/bin.dat; git add docs/bin.dat; git commit -qm bin
expect binary-listed 0 'Binary files' bash "${R}" --tier T4 "${BASE}" HEAD
ln -s a.md docs/link.md; git add docs/link.md; git commit -qm link
expect symlink-listed 0 'Symlinks' bash "${R}" --tier T4 "${BASE}" HEAD
chmod +x docs/a.md; git commit -qam mode
expect mode-listed 0 'mode change' bash "${R}" --tier T4 "${BASE}" HEAD
mkdir -p docs/archive; git mv docs/b.md docs/archive/b.md; git commit -qm archive
expect archive-listed 0 'docs/archive' bash "${R}" --tier T4 "${BASE}" HEAD
expect rename-detected 0 'R100 .*docs/b\.md -> docs/archive/b\.md' bash "${R}" --tier T4 "${BASE}" HEAD
printf '#!/bin/sh\n' > "$(git rev-parse --git-common-dir)/hooks/pre-commit"
expect hooks-flagged 0 'Shared git hooks' bash "${R}" --tier T4 "${BASE}" HEAD
rm "$(git rev-parse --git-common-dir)/hooks/pre-commit"

# Whitespace error, then fixed by a new commit.
printf 'trailing \n' >> docs/a.md; git commit -qam ws
expect whitespace 1 'whitespace errors' bash "${R}" --tier T4 "${BASE}" HEAD
printf 'a\na2\na3\n' > docs/a.md; git commit -qam fix-ws
C3="$(git rev-parse HEAD)"
expect clean-again 0 'REVIEWABLE' bash "${R}" --tier T4 "${BASE}" "${C3}"

# Delta since a previous review, including a file the correction reverted to the base.
printf 'more\n' >> docs/bin.dat; git commit -qam more
git checkout -q "${BASE}" -- scripts/x.sh; git commit -qm revert-x
C4="$(git rev-parse HEAD)"
expect since-names-change 0 'M	docs/bin\.dat' bash "${R}" --tier T4 --since "${C3}" "${BASE}" "${C4}"
expect since-names-reverted 0 'M	scripts/x\.sh' bash "${R}" --tier T4 --since "${C3}" "${BASE}" "${C4}"
expect since-not-ancestor 1 'full review is required' bash "${R}" --tier T4 --since "${ORPHAN}" "${BASE}" "${C4}"

# Integration drift: unrelated, then a merge (re-anchor), then T3+ policy files, then overlap.
drift docs/c.md other
expect drift-unrelated 0 'not material by path' bash "${R}" --tier T4 "${BASE}" "${C4}"
quiet git merge --no-edit origin/main
C5="$(git rev-parse HEAD)"
expect reanchored 0 're-anchored' bash "${R}" --tier T4 "${BASE}" "${C5}"
refute reanchor-excludes-main-files 'docs/c\.md' '== Changed files' '^total:' bash "${R}" --tier T4 "${BASE}" "${C5}"
refute delta-excludes-main-files 'docs/c\.md' '== Delta since' '== Integration' bash "${R}" --tier T4 --since "${C4}" "${BASE}" "${C5}"
for policy_file in AGENTS.md .claude/skills/s/SKILL.md docs/development-workflow.md docs/decisions/x.md scripts/y.sh; do
  drift "${policy_file}" p
  expect "drift-policy:${policy_file}" 3 'Drift changes T3\+ files' bash "${R}" --tier T4 "${BASE}" "${C5}"
  quiet git merge --no-edit origin/main
  C5="$(git rev-parse HEAD)"
done
drift docs/bin.dat conflict-free-append
expect drift-overlap 3 'overlaps this task' bash "${R}" --tier T4 "${BASE}" "${C5}"

# A correction that reverts a task change to a file main also changed (and that was merged in)
# still appears in the delta.
(cd "${T}/origin" && printf 'l1\nl2\nl3\n' > docs/shared.md && git add -A && git commit -qm shared)
quiet git fetch origin
git switch -qc docs/u origin/main
UBASE="$(git rev-parse HEAD)"
printf 'L1-task\nl2\nl3\n' > docs/shared.md; git commit -qam task-edits-shared
UPREV="$(git rev-parse HEAD)"
(cd "${T}/origin" && printf 'l1\nl2\nl3-main\n' > docs/shared.md && git commit -qam main-edits-shared)
quiet git fetch origin; quiet git merge --no-edit origin/main
printf 'l1\nl2\nl3-main\n' > docs/shared.md; printf 'other\n' > docs/u.md; git add -A; git commit -qm revert-task-change
expect since-merged-and-reverted 0 'M	docs/shared\.md' bash "${R}" --tier T1 --since "${UPREV}" "${UBASE}" HEAD
git switch -q docs/t

# A clean-looking update that merged in T3+ files is a material update: reviews do not carry over.
git switch -qc docs/v origin/main
VBASE="$(git rev-parse HEAD)"
printf 'v\n' > docs/v.md; git add -A; git commit -qm v-task
VREV="$(git rev-parse HEAD)"
drift AGENTS.md policy-change
quiet git merge --no-edit origin/main
expect material-update-after-merge 3 'MATERIAL UPDATE' bash "${R}" --tier T1 --since "${VREV}" "${VBASE}" HEAD
drift docs/unrelated.md not-policy
quiet git merge --no-edit origin/main
VREV2="$(git rev-parse HEAD~1)"
expect clean-update-keeps-review 0 'no task-file changes' bash "${R}" --tier T1 --since "${VREV2}" "${VBASE}" HEAD

# The documented reviewer command (docs/development-workflow.md, "Review protocol"): it falls
# back to the candidate's copy when main has none, uses main's copy when present, and its result
# ends with REVIEWABLE. Piping instead would report success for a missing copy.
run_documented() {
  if git cat-file -e origin/main:scripts/review-scope.sh 2>/dev/null; then
    git show origin/main:scripts/review-scope.sh > "${T}/review-scope.main.sh" \
      && bash "${T}/review-scope.main.sh" --tier T3 "$1" "$2"
  else
    bash scripts/review-scope.sh --tier T3 "$1" "$2"
  fi
}
git switch -qc chore/w origin/main
WBASE="$(git rev-parse HEAD)"
cp "${R}" scripts/review-scope.sh; git add -A; git commit -qm add-script
expect documented-fallback 0 'REVIEWABLE: ' run_documented "${WBASE}" HEAD
out="$(run_documented "${WBASE}" HEAD 2>&1)"; last="$(printf '%s\n' "${out}" | tail -n 1)"
[[ "${last}" == "REVIEWABLE: $(git rev-parse HEAD)"* ]] && { pass=$((pass+1)); echo "PASS documented-last-line"; } || { fail=$((fail+1)); echo "FAIL documented-last-line: ${last}"; }
pipe_out="$(git show origin/main:scripts/review-scope.sh 2>/dev/null | bash -s -- --tier T3 "${WBASE}" HEAD; echo "rc=$?")"
[[ "${pipe_out}" == "rc=0" ]] && { pass=$((pass+1)); echo "PASS pipe-hazard-demonstrated (empty output, exit 0)"; } || { fail=$((fail+1)); echo "FAIL pipe hazard not reproduced: ${pipe_out}"; }
(cd "${T}/origin" && mkdir -p scripts && cp "${R}" scripts/review-scope.sh && git add -A && git commit -qm main-gets-script)
quiet git fetch origin; quiet git merge --no-edit origin/main
printf 'w\n' > docs/w.md; git add -A; git commit -qm w-task
expect documented-main-copy 0 'REVIEWABLE: ' run_documented "$(git rev-parse origin/main)" HEAD
git switch -q docs/t

# A submodule (gitlink) change is refused.
git update-index --add --cacheinfo "160000,${BASE},vendor/sub"; git commit -qm gitlink
expect gitlink-refused 1 'submodule changes' bash "${R}" --tier T4 "${BASE}" HEAD

st="$(git status --porcelain --ignore-submodules=all)"
[[ -z "${st}" ]] && { pass=$((pass+1)); echo "PASS read-only"; } || { fail=$((fail+1)); echo "FAIL script left changes: ${st}"; }
echo "review-scope tests: ${pass} passed, ${fail} failed"
finished=1
[[ "${fail}" -eq 0 ]]

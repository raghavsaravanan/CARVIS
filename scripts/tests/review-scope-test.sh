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
quiet() { "$@" >/dev/null 2>&1; }
cfg() { git config user.email t@example.invalid; git config user.name t; git config commit.gpgsign false; }

git init -q -b main "${T}/origin" && cd "${T}/origin" && cfg
mkdir -p docs scripts; printf 'a\n' > docs/a.md; printf 'b\n' > docs/b.md; printf 'x\n' > scripts/x.sh
git add -A; git commit -qm base
git clone -q "${T}/origin" "${T}/work" && cd "${T}/work" && cfg
BASE="$(git rev-parse HEAD)"
R="${SCRIPT}"

expect usage-none 2 '' bash "${R}"
expect usage-one 2 '' bash "${R}" "${BASE}"
expect usage-bad-tier 2 '' bash "${R}" --tier T9 "${BASE}" HEAD
expect usage-bad-flag 2 '' bash "${R}" --bogus "${BASE}" HEAD
expect empty-diff 1 'no changes' bash "${R}" "${BASE}" "${BASE}"

git switch -qc docs/t; printf 'a2\n' >> docs/a.md; git commit -qam change
C1="$(git rev-parse HEAD)"
expect clean-T1 0 'REVIEWABLE' bash "${R}" --tier T1 "${BASE}" "${C1}"
expect lists-file 0 'M +:100644 -> 100644  docs/a\.md' bash "${R}" "${BASE}" "${C1}"
expect floor-reported 0 'minimum for these paths: T1' bash "${R}" "${BASE}" "${C1}"
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
expect base-not-ancestor 1 'not an ancestor' bash "${R}" "${ORPHAN}" "${C1}"
expect bad-revision 1 'cannot resolve' bash "${R}" nosuchref "${C1}"

# Tier floor: a scripts/ change needs T3.
printf 'x2\n' >> scripts/x.sh; git commit -qam script
C2="$(git rev-parse HEAD)"
expect tier-below-floor 1 'below the T3' bash "${R}" --tier T1 "${BASE}" "${C2}"
expect tier-at-floor 0 'REVIEWABLE' bash "${R}" --tier T3 "${BASE}" "${C2}"
expect gate-flagged 0 '' bash "${R}" --tier T3 "${BASE}" "${C2}"

# Rename, binary, symlink, mode change, archive move.
git mv docs/b.md docs/renamed.md; git commit -qm rename
expect rename-detected 0 'R100 .*docs/b\.md -> docs/renamed\.md' bash "${R}" --tier T3 "${BASE}" HEAD
printf '\000\001' > docs/bin.dat; git add docs/bin.dat; git commit -qm bin
expect binary-listed 0 'Binary files' bash "${R}" --tier T3 "${BASE}" HEAD
ln -s a.md docs/link.md; git add docs/link.md; git commit -qm link
expect symlink-listed 0 'Symlinks' bash "${R}" --tier T3 "${BASE}" HEAD
chmod +x docs/a.md; git commit -qam mode
expect mode-listed 0 'mode change' bash "${R}" --tier T3 "${BASE}" HEAD
mkdir -p docs/archive; git mv docs/renamed.md docs/archive/renamed.md; git commit -qm archive
expect archive-listed 0 'docs/archive' bash "${R}" --tier T3 "${BASE}" HEAD

# Whitespace error, then fixed by a new commit.
printf 'trailing \n' >> docs/a.md; git commit -qam ws
expect whitespace 1 'whitespace errors' bash "${R}" --tier T3 "${BASE}" HEAD
printf 'a\na2\n' > docs/a.md; git commit -qam fix-ws
C3="$(git rev-parse HEAD)"
expect clean-again 0 'REVIEWABLE' bash "${R}" --tier T3 "${BASE}" "${C3}"

# Delta since a previous review.
printf 'more\n' >> docs/bin.dat; git commit -qam more
C4="$(git rev-parse HEAD)"
expect since-delta 0 'Delta since .*' bash "${R}" --tier T3 --since "${C3}" "${BASE}" "${C4}"
expect since-names-file 0 'M	docs/bin\.dat' bash "${R}" --tier T3 --since "${C3}" "${BASE}" "${C4}"
expect since-not-ancestor 1 'full review is required' bash "${R}" --tier T3 --since "${ORPHAN}" "${BASE}" "${C4}"

# Integration drift.
cd "${T}/origin"; printf 'other\n' > docs/c.md; git add -A; git commit -qm drift-unrelated
cd "${T}/work"; quiet git fetch origin
expect drift-unrelated 0 'not material by path' bash "${R}" --tier T3 "${BASE}" "${C4}"
# Updating the branch with git merge re-anchors the base; main's files are not in the review.
quiet git merge --no-edit origin/main
C5="$(git rev-parse HEAD)"
expect reanchored 0 're-anchored' bash "${R}" --tier T3 "${BASE}" "${C5}"
out="$(bash "${R}" --tier T3 "${BASE}" "${C5}" 2>&1 | sed -n '/== Changed files/,/^total:/p')"
if printf '%s' "${out}" | grep -q 'docs/c\.md'; then fail=$((fail+1)); echo "FAIL reanchor-excludes-main-files"; else pass=$((pass+1)); echo "PASS reanchor-excludes-main-files"; fi
out="$(bash "${R}" --tier T3 --since "${C4}" "${BASE}" "${C5}" 2>&1 | sed -n '/== Delta since/,/== Integration/p')"
if printf '%s' "${out}" | grep -q 'docs/c\.md'; then fail=$((fail+1)); echo "FAIL delta-excludes-main-files"; else pass=$((pass+1)); echo "PASS delta-excludes-main-files"; fi
# Drift on a policy path the task does not touch.
cd "${T}/origin"; printf 'y\n' > scripts/y.sh; git add -A; git commit -qm drift-policy
cd "${T}/work"; quiet git fetch origin
expect drift-policy 3 'policy, CI, script' bash "${R}" --tier T3 "${BASE}" "${C5}"
quiet git merge --no-edit origin/main
C5="$(git rev-parse HEAD)"

# Drift on a file this task touches.
cd "${T}/origin"; printf 'conflict\n' >> docs/bin.dat; git add -A; git commit -qm drift-overlap
cd "${T}/work"; quiet git fetch origin
expect drift-overlap 3 'overlaps this task' bash "${R}" --tier T3 "${BASE}" "${C5}"

# A submodule (gitlink) change is refused.
git update-index --add --cacheinfo "160000,${BASE},vendor/sub"; git commit -qm gitlink
expect gitlink-refused 1 'submodule changes' bash "${R}" --tier T3 "${BASE}" HEAD

st="$(git status --porcelain --ignore-submodules=all)"; [[ -z "${st}" ]] && { pass=$((pass+1)); echo "PASS read-only"; } || { fail=$((fail+1)); echo "FAIL script left changes: ${st}"; }
echo "review-scope tests: ${pass} passed, ${fail} failed"
finished=1
[[ "${fail}" -eq 0 ]]

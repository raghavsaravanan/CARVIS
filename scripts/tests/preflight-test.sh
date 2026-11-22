#!/usr/bin/env bash
# Scenario tests for .claude/skills/carvis-continue/preflight.sh in a throwaway clone whose origin is
# the real fork. Uses the network read-only (git fetch, gh pr list) and never pushes, so it is a
# manual check, not part of scripts/verify.sh or CI.
# Usage: scripts/tests/preflight-test.sh
set -u
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PF="${SRC}/.claude/skills/carvis-continue/preflight.sh"
T="$(mktemp -d "${TMPDIR:-/tmp}/carvis-preflight-test.XXXXXX")"
finished=0
# Bash 3.2 reports status 0 to an EXIT trap after a `set -u` abort: only a run that reaches the end
# can pass.
trap 'status=$?; rm -rf "$T"; [[ "${finished}" -eq 1 ]] || status=1; exit "${status}"' EXIT
pass=0; fail=0
expect() { # <name> <exit> <stdout-regex> <cmd...>
  local name="$1" want="$2" re="$3"; shift 3
  local out rc; out="$("$@" 2>&1)"; rc=$?
  if [[ "$rc" == "$want" ]] && printf '%s' "$out" | grep -Eq -- "$re"; then pass=$((pass+1)); echo "PASS $name (exit $rc)"
  else fail=$((fail+1)); echo "FAIL $name: want exit $want and /$re/, got $rc"; printf '%s\n' "$out" | sed 's/^/    /'; fi
}
git clone -q --no-local "$SRC" "$T/c" && cd "$T/c" || exit 1
git config user.email t@example.invalid; git config user.name t
git remote set-url origin https://github.com/raghavsaravanan/CARVIS.git
git fetch -q origin main
git switch -q --detach origin/main
expect usage-bad-flag 1 'usage' bash "$PF" --bogus
expect usage-missing-branch 1 'usage' bash "$PF" --assigned
expect usage-extra-arg 1 'usage' bash "$PF" --assigned chore/x extra
git switch -qc chore/wf-test origin/main
expect standalone-ok 0 '^OK: merged M2 rows' bash "$PF"
expect assigned-ok 0 'OK: assigned branch chore/wf-test is fresh' bash "$PF" --assigned chore/wf-test
expect assigned-wrong-branch 1 'not the assigned branch chore/other' bash "$PF" --assigned chore/other
git switch -qc wip/no-prefix origin/main
expect assigned-bad-prefix 1 'lacks an allowed prefix' bash "$PF" --assigned wip/no-prefix
git switch -qc chore/behind "origin/main~1"
expect assigned-behind-ok 0 'is fresh \(1 commit\(s\) behind' bash "$PF" --assigned chore/behind
git switch -qc chore/has-commit origin/main
git commit -q --allow-empty -m local
expect assigned-has-commits 1 'already has commits' bash "$PF" --assigned chore/has-commit
git switch -qc chore/tracks-main origin/main
expect assigned-tracks-main-ok 0 'is fresh' bash "$PF" --assigned chore/tracks-main
git branch -q --set-upstream-to=chore/wf-test
expect assigned-wrong-upstream 1 'tracks chore/wf-test, not origin/main' bash "$PF" --assigned chore/tracks-main
git switch -q chore/wf-test
printf 'x\n' > untracked.txt
expect assigned-dirty 1 'uncommitted or untracked' bash "$PF" --assigned chore/wf-test
rm untracked.txt
git switch -q --detach origin/main
expect assigned-detached 1 'detached HEAD' bash "$PF" --assigned chore/wf-test
git remote set-url origin https://github.com/tejaspalukuri/CARVIS.git
expect wrong-origin 1 'origin is not' bash "$PF" --assigned chore/wf-test
echo "preflight tests: ${pass} passed, ${fail} failed"
finished=1
[[ "$fail" -eq 0 ]]

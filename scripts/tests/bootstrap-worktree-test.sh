#!/usr/bin/env bash
# Scenario tests for scripts/bootstrap-worktree.sh in a throwaway clone of this repository.
# Needs network access to the Python and npm package registries (installs are cached by pip/npm),
# so it is a manual check, not part of scripts/verify.sh or CI.
# Usage: scripts/tests/bootstrap-worktree-test.sh
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
T="$(mktemp -d "${TMPDIR:-/tmp}/carvis-bootstrap-test.XXXXXX")"
finished=0
# Bash 3.2 reports status 0 to an EXIT trap after a `set -u` abort: only a run that reaches the end
# can pass.
trap 'status=$?; rm -rf "${T}"; [[ "${finished}" -eq 1 ]] || status=1; exit "${status}"' EXIT
pass=0; fail=0
expect() { # <name> <exit> <output-regex> <cmd...>
  local name="$1" want="$2" re="$3"; shift 3
  local out rc; out="$("$@" 2>&1)"; rc=$?
  if [[ "${rc}" == "${want}" ]] && printf '%s' "${out}" | grep -Eq -- "${re}"; then
    pass=$((pass+1)); echo "PASS ${name} (exit ${rc})"
  else
    fail=$((fail+1)); echo "FAIL ${name}: want exit ${want} and /${re}/, got ${rc}"; printf '%s\n' "${out}" | tail -n 8 | sed 's/^/    /'
  fi
}
git clone -q --no-local "${ROOT}" "${T}/c"
cp "${ROOT}/scripts/bootstrap-worktree.sh" "${T}/c/scripts/bootstrap-worktree.sh"
cd "${T}/c"
B=scripts/bootstrap-worktree.sh
expect usage 2 'usage' bash "${B}" --bogus
expect check-fresh 1 'MISSING: \.venv' bash "${B}" --check
[[ ! -e .venv ]] && { pass=$((pass+1)); echo "PASS check-creates-nothing"; } || { fail=$((fail+1)); echo "FAIL check created .venv"; }
expect install 0 'Bootstrap complete' bash "${B}"
expect rerun-skips 0 'validates; skipped\..*' bash "${B}"
expect check-ok 0 'Bootstrap complete' bash "${B}" --check
[[ -z "$(git status --porcelain --untracked-files=all | grep -v '^?? scripts/bootstrap-worktree.sh$')" ]] \
  && { pass=$((pass+1)); echo "PASS tree-clean-after-install"; } || { fail=$((fail+1)); echo "FAIL install left files in git status"; git status --short; }
# Corrupt the Python environment: the stamp still matches, validation must catch it.
rm -rf .venv/lib/python3.12/site-packages/fastapi
expect check-detects-broken-venv 1 'MISSING: \.venv' bash "${B}" --check
expect repairs-venv 0 'OK: \.venv installed' bash "${B}"
# Corrupt node_modules.
rm -rf backend/spacetimedb/module/node_modules/typescript
expect check-detects-broken-node 1 'MISSING: .*node_modules' bash "${B}" --check
expect repairs-node 0 'OK: node_modules installed' bash "${B}"
# Wrong interpreter requested, and an existing .venv on another minor version.
other="$(command -v python3.14 || command -v python3.13 || true)"
if [[ -n "${other}" ]]; then
  expect wrong-python 1 'use 3\.12' env CARVIS_BOOTSTRAP_PYTHON="${other}" bash "${B}"
  mv .venv .venv-312
  "${other}" -m venv --without-pip .venv
  expect wrong-venv-version 1 'existing \.venv uses Python 3\.1[3-9]' bash "${B}"
  [[ -d .venv ]] && { pass=$((pass+1)); echo "PASS wrong-venv-kept"; } || { fail=$((fail+1)); echo "FAIL .venv deleted"; }
  rm -rf .venv; mv .venv-312 .venv
else
  echo "SKIP wrong-python scenarios: no other Python 3 minor version available"
fi
# A failing step must fail the script (the lock cleanup must not mask the status).
mv .venv .venv-good; mkdir -p .venv/bin; printf '#!/bin/sh\nexit 3\n' > .venv/bin/python; chmod +x .venv/bin/python
expect failure-propagates 3 '' bash "${B}"
rm -rf .venv; mv .venv-good .venv
# A `set -u` abort must fail the script too (bash 3.2 hides it from the EXIT trap).
awk '{ print } /^trap .status=/ { print ": \"${carvis_test_unbound_variable}\"" }' "${B}" > scripts/bootstrap-abort.sh
grep -q carvis_test_unbound_variable scripts/bootstrap-abort.sh || { fail=$((fail+1)); echo "FAIL could not inject abort"; }
expect unbound-abort-fails 1 'unbound variable' bash scripts/bootstrap-abort.sh --check
rm -f scripts/bootstrap-abort.sh
# Lock held by a live process, then a stale lock.
LOCK="$(git rev-parse --absolute-git-dir)/carvis-bootstrap.lock"
sleep 30 & live=$!
mkdir "${LOCK}"; echo "${live}" > "${LOCK}/pid"
expect lock-held 1 'another bootstrap' bash "${B}" --check
kill "${live}" 2>/dev/null; wait "${live}" 2>/dev/null
expect lock-stale 0 'removing a stale bootstrap lock' bash "${B}" --check
[[ ! -e "${LOCK}" ]] && { pass=$((pass+1)); echo "PASS lock-released"; } || { fail=$((fail+1)); echo "FAIL lock left behind"; }
grep -nE '(^|[^_A-Z])(source|\.)[[:space:]]+[^ ]*\.env|load_dotenv|dotenv_values' "${B}" \
  && { fail=$((fail+1)); echo "FAIL script references .env loading"; } || { pass=$((pass+1)); echo "PASS no-dotenv-loading"; }
echo "bootstrap tests: ${pass} passed, ${fail} failed"
finished=1
[[ "${fail}" -eq 0 ]]

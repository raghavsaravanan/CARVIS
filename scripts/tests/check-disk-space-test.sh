#!/usr/bin/env bash
# Tests for scripts/check-disk-space.sh. Read-only and offline; runs in CI and in scripts/verify.sh.
set -uo pipefail

SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/check-disk-space.sh"
pass=0
fail=0

expect() { # expect <name> <exit status> <output pattern or ''> <command...>
  local name="$1" want="$2" pattern="$3"
  shift 3
  local out status
  out="$("$@" 2>&1)"
  status=$?
  if [[ "${status}" -eq "${want}" ]] && { [[ -z "${pattern}" ]] || grep -qE "${pattern}" <<<"${out}"; }; then
    pass=$((pass + 1)); echo "PASS ${name} (exit ${status})"
  else
    fail=$((fail + 1)); echo "FAIL ${name}: exit ${status}, wanted ${want}"; printf '%s\n' "${out}" | sed 's/^/    /'
  fi
}

T="$(mktemp -d "${TMPDIR:-/tmp}/check-disk-space-test.XXXXXX")"
trap 'rm -rf "${T}"' EXIT

expect zero-minimum-passes 0 '^OK: [0-9]+ GiB free \(minimum 0 GiB\)' bash "${SCRIPT}" --min-gib 0 "${T}"
expect huge-minimum-stops 1 '^STOP: [0-9]+ GiB free .*at least 999999999 GiB' bash "${SCRIPT}" --min-gib 999999999 "${T}"
expect stop-says-it-deletes-nothing 1 'never deletes anything' bash "${SCRIPT}" --min-gib 999999999 "${T}"
expect environment-minimum 1 'at least 999999999 GiB' env CARVIS_MIN_FREE_GIB=999999999 bash "${SCRIPT}" "${T}"
expect flag-overrides-environment 0 '^OK' env CARVIS_MIN_FREE_GIB=999999999 bash "${SCRIPT}" --min-gib 0 "${T}"
expect default-path-is-current-directory 0 '^OK' bash -c "cd '${T}' && bash '${SCRIPT}' --min-gib 0"
expect non-numeric-minimum 2 'whole number' bash "${SCRIPT}" --min-gib ten "${T}"
expect negative-minimum 2 'whole number' bash "${SCRIPT}" --min-gib -1 "${T}"
expect missing-minimum-value 2 'usage' bash "${SCRIPT}" --min-gib
expect unknown-flag 2 'usage' bash "${SCRIPT}" --prune
expect extra-argument 2 'usage' bash "${SCRIPT}" "${T}" "${T}"
expect missing-path 2 'does not exist' bash "${SCRIPT}" --min-gib 0 "${T}/missing"

# An unreadable df result is a usage error, never a pass: a fake df that prints no number.
mkdir -p "${T}/fakebin"
printf '#!/usr/bin/env bash\necho "Filesystem 1024-blocks Used Available"\necho "weird output"\n' > "${T}/fakebin/df"
chmod +x "${T}/fakebin/df"
expect unreadable-free-space 2 'could not read free space' env PATH="${T}/fakebin:${PATH}" bash "${SCRIPT}" --min-gib 0 "${T}"

# Read-only: the script must never contain a command that deletes or prunes data.
if grep -nE '^[^#]*\b(rm|rmdir|unlink|truncate|shred|prune|docker|git[[:space:]]+(clean|reset|stash))\b' "${SCRIPT}"; then
  fail=$((fail + 1)); echo "FAIL read-only: a deleting or pruning command appears in the script"
else
  pass=$((pass + 1)); echo "PASS read-only"
fi
# And running it changes nothing in the directory it checks.
touch "${T}/keep"
before="$(ls -la "${T}")"
bash "${SCRIPT}" --min-gib 999999999 "${T}" >/dev/null 2>&1
[[ "$(ls -la "${T}")" == "${before}" ]] && { pass=$((pass + 1)); echo "PASS leaves-directory-unchanged"; } \
  || { fail=$((fail + 1)); echo "FAIL the checked directory changed"; }

echo "check-disk-space tests: ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]

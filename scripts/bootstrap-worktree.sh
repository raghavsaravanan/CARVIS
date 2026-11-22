#!/usr/bin/env bash
# Prepare a CARVIS checkout (primary or linked worktree) for local checks from the existing
# lockfiles. Idempotent: a step whose lockfile and interpreter are unchanged and whose installed
# dependencies still validate is skipped.
#
# Usage: scripts/bootstrap-worktree.sh [--check]
#   --check   validate only; install nothing; exit 1 if anything is missing or invalid.
#
# Creates .venv from backend/requirements-dev.txt (hash-pinned, wheels only, so no package build
# code runs) and backend/spacetimedb/module/node_modules from package-lock.json (install scripts
# disabled), then reports whether full Xcode is available. The script never reads or sources .env
# files, provider settings or credentials, starts no service and touches no database. pip and npm
# still read their own user configuration (for example a registry mirror) and contact the
# configured package registries. Run it by hand; it is not configured as an Orca setup hook
# (docs/development-workflow.md, "Worktree lifecycle").
#
# Interpreter: CARVIS_BOOTSTRAP_PYTHON, else python3.12 (runtime.txt and CI), else python3. An
# existing .venv on another Python minor version is an error; it is never deleted.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

CHECK_ONLY=0
case "${1:-}" in
  "") ;;
  --check) CHECK_ONLY=1 ;;
  *) echo "usage: scripts/bootstrap-worktree.sh [--check]" >&2; exit 2 ;;
esac

# Never let tooling pick up a local .env or interactive prompts.
export PYTHON_DOTENV_DISABLED=1 PIP_NO_INPUT=1 PIP_DISABLE_PIP_VERSION_CHECK=1
unset PYTHONSTARTUP

REQUIREMENTS="backend/requirements-dev.txt"
MODULE="backend/spacetimedb/module"
VENV_STAMP=".venv/.carvis-bootstrap"
NODE_STAMP="${MODULE}/node_modules/.carvis-bootstrap"
TARGET_PYTHON="3.12"
problems=0

# One bootstrap per checkout at a time. The lock lives in this worktree's private git directory,
# never in the working tree, so it cannot appear in a diff or block review-scope.
LOCK="$(git rev-parse --absolute-git-dir)/carvis-bootstrap.lock"
if ! mkdir "${LOCK}" 2>/dev/null; then
  holder="$(cat "${LOCK}/pid" 2>/dev/null || true)"
  if [[ -n "${holder}" ]] && kill -0 "${holder}" 2>/dev/null; then
    echo "ERROR: another bootstrap (pid ${holder}) is running in this checkout." >&2
    exit 1
  fi
  echo "NOTE: removing a stale bootstrap lock."
  rm -rf "${LOCK}"
  mkdir "${LOCK}"
fi
echo $$ > "${LOCK}/pid"
# The cleanup must never turn a failure into success. Bash 3.2 (macOS) reports status 0 to an EXIT
# trap after a `set -u` abort, so success is only what reaches the end of the script.
finished=0
trap 'status=$?; rm -rf "${LOCK}"; [[ "${finished}" -eq 1 || "${status}" -ne 0 ]] || status=1; exit "${status}"' EXIT

digest() { shasum -a 256 "$@" | awk '{print $1}' | tr '\n' ' '; }

if [[ -n "${CARVIS_BOOTSTRAP_PYTHON:-}" ]]; then
  PYTHON="${CARVIS_BOOTSTRAP_PYTHON}"
elif command -v python3.12 >/dev/null 2>&1; then
  PYTHON="python3.12"
else
  PYTHON="python3"
fi

echo "== Python environment (.venv) =="
python_version() { "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])'; }
want_version="$(python_version "${PYTHON}")"
if [[ "${want_version}" != "${TARGET_PYTHON}" ]]; then
  echo "ERROR: ${PYTHON} is Python ${want_version}; CI and runtime.txt use ${TARGET_PYTHON}." >&2
  echo "Install Python ${TARGET_PYTHON} or set CARVIS_BOOTSTRAP_PYTHON." >&2
  exit 1
fi
if [[ -x .venv/bin/python ]]; then
  venv_version="$(python_version .venv/bin/python)"
  if [[ "${venv_version}" != "${TARGET_PYTHON}" ]]; then
    echo "ERROR: existing .venv uses Python ${venv_version}, not ${TARGET_PYTHON}." >&2
    echo "Move it aside yourself if it is not needed; this script never deletes it." >&2
    exit 1
  fi
fi
venv_want="${TARGET_PYTHON} $(digest "${REQUIREMENTS}" backend/requirements.txt)"
venv_valid() {
  [[ -f "${VENV_STAMP}" && "$(cat "${VENV_STAMP}")" == "${venv_want}" ]] \
    && .venv/bin/python -m pip check >/dev/null 2>&1 \
    && .venv/bin/python -c 'import fastapi, pytest' >/dev/null 2>&1
}
if venv_valid; then
  echo "OK: .venv matches ${REQUIREMENTS} and validates; skipped."
elif [[ "${CHECK_ONLY}" -eq 1 ]]; then
  echo "MISSING: .venv absent, out of date with ${REQUIREMENTS}, or failing pip check."
  problems=1
else
  reinstall=()
  if [[ -x .venv/bin/python ]]; then
    # An existing environment failed validation: pip would call damaged packages "already
    # satisfied", so reinstall every locked package in place instead of deleting .venv.
    reinstall=(--force-reinstall)
  else
    "${PYTHON}" -m venv .venv
  fi
  rm -f "${VENV_STAMP}"
  .venv/bin/python -m pip install --quiet --require-hashes --only-binary=:all: ${reinstall[@]+"${reinstall[@]}"} \
    -r "${REQUIREMENTS}"
  .venv/bin/python -m pip check
  printf '%s\n' "${venv_want}" > "${VENV_STAMP}"
  venv_valid || { echo "ERROR: .venv did not validate after install." >&2; exit 1; }
  echo "OK: .venv installed from ${REQUIREMENTS}."
fi

echo "== SpacetimeDB module dependencies =="
if ! command -v npm >/dev/null 2>&1; then
  echo "ERROR: npm is not installed; install Node.js 20 or later." >&2
  exit 1
fi
node_want="$(node --version) $(digest "${MODULE}/package-lock.json")"
node_valid() {
  [[ -f "${NODE_STAMP}" && "$(cat "${NODE_STAMP}")" == "${node_want}" ]] \
    && npm ls --prefix "${MODULE}" --all >/dev/null 2>&1 \
    && "${MODULE}/node_modules/.bin/tsc" --version >/dev/null 2>&1
}
if node_valid; then
  echo "OK: node_modules matches package-lock.json and validates; skipped."
elif [[ "${CHECK_ONLY}" -eq 1 ]]; then
  echo "MISSING: ${MODULE}/node_modules absent, out of date with package-lock.json, or invalid."
  problems=1
else
  # Lockfile-exact install. Install scripts are disabled; CI runs plain `npm ci`, and no locked
  # package currently declares an install script, so the installed trees match.
  npm ci --prefix "${MODULE}" --ignore-scripts --no-audit --no-fund --loglevel=error
  printf '%s\n' "${node_want}" > "${NODE_STAMP}"
  node_valid || { echo "ERROR: node_modules did not validate after install." >&2; exit 1; }
  echo "OK: node_modules installed from package-lock.json."
fi

echo "== Xcode =="
if xcodebuild -version >/dev/null 2>&1; then
  echo "OK: $(xcodebuild -version | head -n 1); scripts/verify.sh will run the simulator build."
else
  echo "NOTE: full Xcode is unavailable; scripts/verify.sh will skip the simulator build."
fi

if [[ "${problems}" -ne 0 ]]; then
  echo "Bootstrap incomplete: run scripts/bootstrap-worktree.sh without --check." >&2
  exit 1
fi
finished=1
echo "Bootstrap complete: run scripts/verify.sh for the repository baseline."

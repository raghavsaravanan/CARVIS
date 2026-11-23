#!/usr/bin/env bash
# Install only the runtime lockfile (what Render installs) into an isolated virtual environment,
# confirm test tooling is absent, and import every backend module with network access blocked.
# Usage: scripts/check-runtime-lock.sh [python-interpreter]   (default: python3)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${1:-python3}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/carvis-runtime-lock.XXXXXX")"
trap 'rm -rf "${WORK}"' EXIT

echo "== Runtime lockfile: isolated install =="
"${PYTHON}" -m venv "${WORK}/venv"
VENV_PYTHON="${WORK}/venv/bin/python"
"${VENV_PYTHON}" -m pip install --quiet --disable-pip-version-check --require-hashes \
  -r "${ROOT}/backend/requirements.txt"
"${VENV_PYTHON}" -m pip check

echo "== Runtime lockfile: test tooling absent =="
"${VENV_PYTHON}" - <<'PY'
import importlib.util
import sys

present = [name for name in ("pytest", "_pytest", "pluggy", "iniconfig") if importlib.util.find_spec(name)]
if present:
    sys.exit(f"Test tooling installed from the runtime lockfile: {', '.join(present)}")
print("pytest, pluggy and iniconfig are not installed.")
PY

echo "== Runtime lockfile: backend imports, network blocked =="
# A clean environment with no provider settings, and python-dotenv disabled so a local backend/.env
# is never read; any variable that appears during import fails the check (names only are printed).
# An audit hook records and refuses Python-level network events (DNS lookups, connects, sends and
# urllib requests) and process launches, so a module that swallows the error still fails. Import
# must also leave no extra threads running, which would escape the check by acting later. Network
# access from native code that bypasses Python's socket module is outside what this check can see.
mkdir "${WORK}/run"
(
  cd "${WORK}/run"
  env -i PATH="/usr/bin:/bin" HOME="${WORK}/run" CARVIS_ENV=local PYTHON_DOTENV_DISABLED=1 \
    "${VENV_PYTHON}" -I -B - "${ROOT}/backend" <<'PY'
import importlib
import os
import sys
import threading
from pathlib import Path

NETWORK_EVENTS = {
    "socket.connect",
    "socket.getaddrinfo",
    "socket.gethostbyname",
    "socket.gethostbyaddr",
    "socket.getnameinfo",
    "socket.sendto",
    "socket.sendmsg",
    "urllib.Request",
}
PROCESS_EVENTS = {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork"}
attempts = []


def _audit(event, args):
    if event in NETWORK_EVENTS or event in PROCESS_EVENTS:
        attempts.append(event)
        raise RuntimeError(f"network or process access attempted while importing the backend ({event})")


sys.addaudithook(_audit)
environment_before = dict(os.environ)
threads_before = set(threading.enumerate())

backend = Path(sys.argv[1])
sys.path.insert(0, str(backend))
modules = sorted(path.stem for path in backend.glob("*.py"))
# Packages and lazily imported dependencies that no top-level module imports at load time (M2 B2a):
# the database and auth packages and the drivers they load on first use.
modules += ["db.conninfo", "db.engine", "db.history", "db.readiness", "db.roles", "db.runtime_login",
            "auth.jwks", "auth.tokens", "psycopg", "sqlalchemy.ext.asyncio", "jwt", "jwt.algorithms",
            "cryptography.hazmat.primitives.asymmetric.ec", "cryptography.hazmat.primitives.asymmetric.rsa"]
for name in modules:
    importlib.import_module(name)

if attempts:
    sys.exit(f"Network or process access attempted during import: {', '.join(sorted(set(attempts)))}")
started = sorted(thread.name for thread in set(threading.enumerate()) - threads_before)
if started:
    sys.exit(f"Threads still running after import: {', '.join(started)}")
changed = sorted(k for k in os.environ if environment_before.get(k) != os.environ[k])
if changed:
    sys.exit(f"Environment variables set during import (was .env read?): {', '.join(changed)}")
print(f"Imported {len(modules)} backend modules: {', '.join(modules)}")
PY
)

echo "Runtime lockfile check passed."

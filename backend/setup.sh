#!/usr/bin/env bash
# Validate Carvis prerequisites for cloud-first demos.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT}"

# Read settings as data. `.env` is never sourced or evaluated by the shell, so a value such as
# $(...) or `...` is inert. The file is loaded with load_dotenv(override=False), exactly as the API
# loads it: variables present in the environment, even empty ones, win over `.env`, `${VAR}`
# references resolve the same way, and PYTHON_DOTENV_DISABLED is honoured.
# CARVIS_SETUP_PYTHON overrides the interpreter; it needs python-dotenv when `.env` exists.
PYTHON="${CARVIS_SETUP_PYTHON:-}"
if [[ -z "${PYTHON}" ]]; then
  if [[ -x "${ROOT}/../.venv/bin/python" ]]; then
    PYTHON="${ROOT}/../.venv/bin/python"
  else
    PYTHON="python3"
  fi
fi

REFUSED_VALUE=3
settings_status=0
SETTINGS="$("${PYTHON}" - <<'PY'
import os
import sys
from pathlib import Path

env_file = Path(".env")
if env_file.is_file():
    try:
        from dotenv import load_dotenv
    except ImportError:
        sys.exit("python-dotenv is not installed, so backend/.env cannot be read safely.")
    load_dotenv(env_file, override=False)

for name in ("QDRANT_URL", "QDRANT_API_KEY"):
    # Surrounding whitespace is trimmed and internal whitespace kept. A value spanning lines is
    # refused rather than reshaped; the message names the variable, never its value.
    value = os.environ.get(name, "").strip()
    if "\n" in value or "\r" in value:
        print(f"{name} spans more than one line, so it cannot be read safely.", file=sys.stderr)
        sys.exit(3)
    print(value)
PY
)" || settings_status=$?

if [[ "${settings_status}" -eq "${REFUSED_VALUE}" ]]; then
  exit 2
elif [[ "${settings_status}" -ne 0 ]]; then
  echo "Could not read settings with ${PYTHON}; see the error above." >&2
  echo "If Python or python-dotenv is missing, install the backend dependencies (see README.md," >&2
  echo "Development setup) or set CARVIS_SETUP_PYTHON." >&2
  exit 2
fi

{
  IFS= read -r QDRANT_URL || true
  IFS= read -r QDRANT_API_KEY || true
} <<< "${SETTINGS}"

if [[ -n "${QDRANT_URL}" && -n "${QDRANT_API_KEY}" ]]; then
  echo "Cloud Qdrant configured: ${QDRANT_URL}"
  echo "Runtime DB is Qdrant Cloud. Local carvis_mvp_db/ is optional."
  echo "Staging:     ../.venv/bin/python qdrant_v2.py"
  echo "Re-seed:     ../.venv/bin/python ingest.py <pdf> --shop-id shop_demo ..."
  exit 0
fi

DB_PATH="${ROOT}/carvis_mvp_db"
if [[ ! -d "${DB_PATH}" ]]; then
  echo "Database missing. Run \`python ingest.py\` first."
  echo "(Or set QDRANT_URL + QDRANT_API_KEY in backend/.env for cloud.)"
  exit 1
fi

echo "Local carvis_mvp_db found at ${DB_PATH}"
exit 0

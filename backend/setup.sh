#!/usr/bin/env bash
# Validate Carvis prerequisites for cloud-first demos.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT}"

# Read settings as data. `.env` is never sourced or evaluated by the shell, so a value such as
# $(...) or `...` is inert. Variables already in the environment win, as with load_dotenv().
# CARVIS_SETUP_PYTHON overrides the interpreter; it needs python-dotenv when `.env` exists.
PYTHON="${CARVIS_SETUP_PYTHON:-}"
if [[ -z "${PYTHON}" ]]; then
  if [[ -x "${ROOT}/../.venv/bin/python" ]]; then
    PYTHON="${ROOT}/../.venv/bin/python"
  else
    PYTHON="python3"
  fi
fi

if ! SETTINGS="$("${PYTHON}" - <<'PY'
import os
import sys
from pathlib import Path

values = {}
env_file = Path(".env")
if env_file.is_file():
    try:
        from dotenv import dotenv_values
    except ImportError:
        sys.exit("python-dotenv is not installed, so backend/.env cannot be read safely.")
    values = dotenv_values(env_file)

for name in ("QDRANT_URL", "QDRANT_API_KEY"):
    # One line each, surrounding whitespace trimmed.
    print(" ".join((os.environ.get(name) or values.get(name) or "").split()))
PY
)"; then
  echo "Could not read settings with ${PYTHON}." >&2
  echo "Install the backend dependencies (see README.md, Development setup) or set CARVIS_SETUP_PYTHON." >&2
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

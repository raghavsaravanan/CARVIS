#!/usr/bin/env bash
# Documentation checks shared by scripts/verify.sh and CI (Hygiene job): stale active-path references and local
# Markdown links. Read-only. Exit 1 on a finding, or when a check cannot run.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
PYTHON="${PYTHON:-python3}"

echo "== Stale path references =="
# git grep searches tracked and untracked text files (-I skips binary files) and skips ignored ones. Status 0 means a
# match, 1 means none, and anything else is an error that must not pass silently. A searched path that no longer
# exists would silently narrow the check, so its absence fails too.
stale_paths=(README.md AGENTS.md backend ios docs)
for stale_path in "${stale_paths[@]}"; do
  if [[ ! -e "${stale_path}" ]]; then
    echo "Stale path check: ${stale_path} is missing; update scripts/check-docs.sh." >&2
    exit 1
  fi
done
stale_status=0
git grep --untracked -I -n -E 'carvis-module|frontend/(src|package\.json)' \
  -- "${stale_paths[@]}" ':(exclude)docs/archive/**' || stale_status=$?
case "${stale_status}" in
  0)
    echo "Stale active path reference found." >&2
    exit 1
    ;;
  1) ;;
  *)
    echo "Stale path check could not run (git grep exit ${stale_status})." >&2
    exit 1
    ;;
esac

echo "== Documentation links =="
"$PYTHON" - <<'PY'
import pathlib
import re

bad = []
documents = [
    pathlib.Path("README.md"),
    pathlib.Path("AGENTS.md"),
    pathlib.Path("CLAUDE.md"),
    *pathlib.Path("docs").rglob("*.md"),
    *pathlib.Path(".claude/skills").rglob("*.md"),
]
for path in documents:
    for target in re.findall(r"\[[^]]*\]\(([^)#]+)(?:#[^)]*)?\)", path.read_text()):
        if re.match(r"^(?:https?:|mailto:)", target):
            continue
        if not (path.parent / target).resolve().exists():
            bad.append(f"{path}: {target}")
if bad:
    raise SystemExit("Broken local links:\n" + "\n".join(bad))
PY
echo "Documentation checks passed."

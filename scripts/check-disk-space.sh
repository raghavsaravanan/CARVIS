#!/usr/bin/env bash
# Disk-space preflight before substantial local testing (docs/development-workflow.md, "Local run
# hygiene"): the full baseline, real-database suites, mutation runs and Docker containers.
#
# Usage: scripts/check-disk-space.sh [--min-gib N] [path]
#   N defaults to CARVIS_MIN_FREE_GIB, else 10. path defaults to the current directory; the check
#   applies to the filesystem that holds it.
#
# Exit 0: at least N GiB are free. Exit 1: less than N GiB are free (stop and ask the owner to free
# space). Exit 2: usage error, or free space could not be read.
#
# Read-only by design: it never deletes, prunes or cleans anything. Freeing space is the owner's
# decision.
set -euo pipefail

usage() {
  echo "usage: scripts/check-disk-space.sh [--min-gib N] [path]" >&2
  exit 2
}

min="${CARVIS_MIN_FREE_GIB:-10}"
path="."
while [[ $# -gt 0 ]]; do
  case "$1" in
    --min-gib)
      [[ $# -ge 2 ]] || usage
      min="$2"
      shift 2
      ;;
    -*) usage ;;
    *)
      path="$1"
      shift
      [[ $# -eq 0 ]] || usage
      ;;
  esac
done

[[ "${min}" =~ ^[0-9]+$ ]] || { echo "check-disk-space: the minimum must be a whole number of GiB" >&2; exit 2; }
[[ -e "${path}" ]] || { echo "check-disk-space: path does not exist" >&2; exit 2; }

# POSIX output (-P) in 1024-byte blocks (-k): the fourth field of the second line is "Available".
available_kb="$(df -Pk "${path}" 2>/dev/null | awk 'NR == 2 { print $4 }')"
[[ "${available_kb}" =~ ^[0-9]+$ ]] || { echo "check-disk-space: could not read free space" >&2; exit 2; }

available_gib=$((available_kb / 1024 / 1024))
if (( available_kb < min * 1024 * 1024 )); then
  echo "STOP: ${available_gib} GiB free on the filesystem holding ${path}; at least ${min} GiB are required." >&2
  echo "Free space by hand (or ask the owner); this check never deletes anything." >&2
  exit 1
fi
echo "OK: ${available_gib} GiB free (minimum ${min} GiB)."

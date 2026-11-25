#!/usr/bin/env python3
"""CI plan: change categories, test shards and checks of a shard's results (CI packages 2+3).

Commands (standard library only, so the plan and hygiene jobs need no dependency install):

    ci-plan.py categories --event <name> [--base <sha> --head <sha>]   # prints KEY=value lines for $GITHUB_OUTPUT
    ci-plan.py shard <unit|db-1|db-2|db-3>                            # prints the pytest paths/args, one per line
    ci-plan.py partition                                               # every collected test in exactly one shard
    ci-plan.py junit <file>                                            # zero tests, a skip or an error fails

Categories fail closed. ``full`` is true for push, schedule and workflow_dispatch events, for any diff that cannot be
computed, is empty or holds an undecodable path, and for any change to the workflow, these CI scripts or the
workflow policy document. ``full`` makes every category true. A path counts as documentation only if it is
``README.md`` or ``docs/**.md`` other than ``docs/development-workflow.md``. Every unknown path counts as backend.
Paths come from ``git diff --name-only --no-renames -z`` (NUL-separated, unquoted; a rename lists both sides).
"""
from __future__ import annotations

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = "backend/tests"
# Balanced from measured local durations (2026-11-24): db-1 ~170 s, db-2 ~188 s, db-3 ~193 s. A new
# real-PostgreSQL test file must be added to a shard; left out, it runs in unit, which has no PostgreSQL and requires
# it, so it fails instead of skipping. Add a fourth shard when any shard exceeds about 8 minutes in CI.
DB_SHARDS = {
    "db-1": ["test_b1_migrations.py", "test_b2a_migrations.py", "test_b2a_runtime_login.py", "test_b2a_connection.py"],
    "db-2": ["test_b2b1_identity.py", "test_b2c_v1_postgres.py"],
    "db-3": ["test_b3a_garage.py", "test_b2b2_context.py"],
}
SHARDS = ("unit", *DB_SHARDS)
CATEGORIES = ("full", "backend", "ios", "spacetimedb", "deps", "lockfile")
FULL_EVENTS = {"push", "schedule", "workflow_dispatch"}
# Any CI script (scripts/ci-*, existing or new), its tests, the docs check the workflow runs, the workflow and the
# workflow policy document force a full run.
FULL_PATHS = (".github/", "scripts/ci-", "scripts/tests/ci-", "scripts/check-docs.sh", "docs/development-workflow.md")
DEPS_PATHS = ("backend/requirements", "scripts/check-runtime-lock.sh", "runtime.txt", "requirements.txt")


def is_doc(path: str) -> bool:
    # docs/development-workflow.md (CI and gate policy) never reaches here: it is in FULL_PATHS.
    return path == "README.md" or (path.startswith("docs/") and path.endswith(".md"))


def categorize(event: str, paths: list[str] | None) -> dict[str, bool]:
    """``paths`` is None when the diff could not be computed or decoded."""
    full = event in FULL_EVENTS or not paths or any(p.startswith(FULL_PATHS) for p in paths)
    if full:
        return {name: True for name in CATEGORIES}
    backend = any(not is_doc(p) and not p.startswith(("ios/", "backend/spacetimedb/")) for p in paths)
    deps = any(p.startswith(DEPS_PATHS) for p in paths)
    return {
        "full": False,
        "backend": backend,
        "ios": any(p.startswith("ios/") for p in paths),
        "spacetimedb": any(p.startswith("backend/spacetimedb/") for p in paths),
        "deps": deps,
        # The isolated runtime import check covers every backend change, not only dependency changes.
        "lockfile": backend or deps,
    }


def changed_paths(base: str, head: str) -> list[str] | None:
    try:
        raw = subprocess.run(["git", "diff", "--name-only", "--no-renames", "-z", base, head], cwd=ROOT, check=True,
                             capture_output=True).stdout
        paths = raw.decode("utf-8").split("\0")
    except (subprocess.CalledProcessError, OSError, UnicodeDecodeError):
        return None
    paths = [p for p in paths if p != ""]
    if any(not p.isprintable() for p in paths):
        return None  # control characters (a newline in a name) cannot be classified safely
    return paths


def shard_args(shard: str) -> list[str]:
    if shard in DB_SHARDS:
        return [f"{TESTS}/{name}" for name in DB_SHARDS[shard]]
    if shard == "unit":
        listed = {name for names in DB_SHARDS.values() for name in names}
        return [f"{TESTS}/{p.name}" for p in sorted((ROOT / TESTS).glob("test_*.py")) if p.name not in listed]
    raise SystemExit(f"unknown shard {shard!r}")


def collect(args: list[str]) -> list[str]:
    result = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *args],
                            cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit("collection failed:\n" + result.stdout[-2000:] + result.stderr[-2000:])
    return [line for line in result.stdout.splitlines() if "::" in line]


def partition() -> list[str]:
    problems = []
    for shard, names in DB_SHARDS.items():
        for name in names:
            if not (ROOT / TESTS / name).is_file():
                problems.append(f"{shard}: {name} does not exist")
    listed = [name for names in DB_SHARDS.values() for name in names]
    if len(listed) != len(set(listed)):
        problems.append("a test file is listed in more than one database shard")
    if problems:
        return problems
    # Compared per test function with counts: parametrize IDs are not stable across collections (one test builds
    # its IDs from random UUIDs), but every function must appear in exactly one shard, as often as in the full run.
    from collections import Counter

    def key(node: str) -> str:
        return node.split("[", 1)[0]

    full = Counter(key(node) for node in collect([TESTS]))
    combined: Counter = Counter()
    owner: dict[str, str] = {}
    for shard in SHARDS:
        counts = Counter(key(node) for node in collect(shard_args(shard)))
        for function in counts:
            if function in owner:
                problems.append(f"{function} is in {owner[function]} and {shard}")
            owner[function] = shard
        combined += counts
    for function in sorted(set(full) | set(combined)):
        if full[function] != combined[function]:
            problems.append(f"{function}: {full[function]} collected in the full run, {combined[function]} in shards")
    return problems


def junit_problems(path: str) -> list[str]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        return [f"junit report unreadable: {exc}"]
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    tests = sum(int(s.get("tests", 0)) for s in suites)
    problems = []
    if tests == 0:
        problems.append("no tests ran")
    for case in root.iter("testcase"):
        for kind in ("skipped", "error", "failure"):
            if case.find(kind) is not None:
                problems.append(f"{kind}: {case.get('classname')}::{case.get('name')}")
    return problems


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    command, rest = argv[0], argv[1:]
    if command == "categories":
        options = dict(zip(rest[::2], rest[1::2]))
        event = options.get("--event", "")
        paths = None
        if event not in FULL_EVENTS:
            base, head = options.get("--base", ""), options.get("--head", "")
            paths = changed_paths(base, head) if base and head else None
        for name, value in categorize(event, paths).items():
            print(f"{name}={'true' if value else 'false'}")
        return 0
    if command == "shard" and len(rest) == 1:
        print("\n".join(shard_args(rest[0])))
        return 0
    if command == "partition":
        problems = partition()
        print("\n".join(problems) if problems else "partition OK: every collected test is in exactly one shard")
        return 1 if problems else 0
    if command == "junit" and len(rest) == 1:
        problems = junit_problems(rest[0])
        print("\n".join(problems) if problems else "junit OK")
        return 1 if problems else 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

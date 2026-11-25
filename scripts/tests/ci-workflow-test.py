#!/usr/bin/env python3
"""Structural test of .github/workflows/ci.yml (CI packages 2+3): the wiring that makes the gates fail closed.

Run in CI's unit job (PyYAML is in the dev lockfile) and by scripts/verify.sh. Exit 1 on any violation.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = {"gate-backend": ("Backend and hygiene", ["plan", "hygiene", "lockfile", "unit", "db-1", "db-2", "db-3"]),
            "gate-swift": ("Swift pure checks", ["plan", "swift"]),
            "gate-spacetimedb": ("SpacetimeDB typecheck", ["plan", "spacetimedb"])}
CONDITIONS = {"lockfile": "needs.plan.outputs.lockfile == 'true'", "unit": "needs.plan.outputs.backend == 'true'",
              "db-1": "needs.plan.outputs.backend == 'true'", "db-2": "needs.plan.outputs.backend == 'true'",
              "db-3": "needs.plan.outputs.backend == 'true'", "swift": "needs.plan.outputs.ios == 'true'",
              "spacetimedb": "needs.plan.outputs.spacetimedb == 'true'"}


def problems(workflow: dict) -> list[str]:
    found = []
    on = workflow.get(True, workflow.get("on")) or {}  # PyYAML reads the bare key `on` as True
    for trigger in ("pull_request", "push", "schedule", "workflow_dispatch"):
        if trigger not in on:
            found.append(f"trigger {trigger} missing")
    if (on.get("push") or {}).get("branches") != ["main"]:
        found.append("push must be limited to main")
    if "paths" in str(on) or "paths-ignore" in str(on):
        found.append("path filters on triggers leave required checks pending")
    if (workflow.get("concurrency") or {}).get("cancel-in-progress") != "${{ github.event_name == 'pull_request' }}":
        found.append("cancel-in-progress must apply to pull requests only")
    jobs = workflow.get("jobs") or {}
    names = [job.get("name") for job in jobs.values()]
    for job_id, (name, needs) in REQUIRED.items():
        job = jobs.get(job_id) or {}
        if job.get("name") != name or names.count(name) != 1:
            found.append(f"{name} must be the name of exactly one job, {job_id}")
        if job.get("if") != "always()":
            found.append(f"{job_id} must run with if: always()")
        if sorted(job.get("needs") or []) != sorted(needs):
            found.append(f"{job_id} needs must be {needs}")
        gate_name = job_id.removeprefix("gate-")
        if not any(f"scripts/ci-gate.py {gate_name}" in (step.get("run") or "") for step in job.get("steps") or []):
            found.append(f"{job_id} must run scripts/ci-gate.py {gate_name}")
    for job_id, condition in CONDITIONS.items():
        if (jobs.get(job_id) or {}).get("if") != condition:
            found.append(f"{job_id} must run if {condition}")
    for job_id in ("plan", "hygiene"):
        if "if" in (jobs.get(job_id) or {}):
            found.append(f"{job_id} must always run")
    for job_id, job in jobs.items():
        for step in job.get("steps") or []:
            if "|" in (step.get("run") or "") and step.get("shell") != "bash":
                # GitHub's default Linux shell is `bash -e` without pipefail; `shell: bash` adds -o pipefail.
                found.append(f"{job_id}: a step with a pipe must set shell: bash (pipefail)")
    unit = jobs.get("unit") or {}
    if "services" in unit:
        found.append("unit must have no database service")
    unit_runs = " ".join(step.get("run") or "" for step in unit.get("steps") or [])
    for needle in ("ci-plan.py partition", "ci-workflow-test.py", "ci-plan.py shard unit", "ci-plan.py junit"):
        if needle not in unit_runs:
            found.append(f"unit must run {needle}")
    if (unit.get("env") or {}).get("CARVIS_REQUIRE_POSTGRES") != "1":
        found.append("unit must set CARVIS_REQUIRE_POSTGRES=1")
    reference = None
    for shard in ("db-1", "db-2", "db-3"):
        job = jobs.get(shard) or {}
        env = job.get("env") or {}
        if "postgres" not in (job.get("services") or {}):
            found.append(f"{shard} needs its own postgres service")
        if env.get("CARVIS_REQUIRE_POSTGRES") != "1" or not env.get("CARVIS_TEST_POSTGRES_URL"):
            found.append(f"{shard} must set CARVIS_REQUIRE_POSTGRES=1 and CARVIS_TEST_POSTGRES_URL")
        steps = [step.get("run") or "" for step in job.get("steps") or []]
        if not any(f"ci-plan.py shard {shard}" in run for run in steps) or not any("ci-plan.py junit" in r for r in steps):
            found.append(f"{shard} must run its shard and the junit check")
        common = [s for s in steps if "Migrations up" not in s and "alembic -c migrations" not in s]
        normalized = [s.replace(shard, "db-N") for s in common]
        if reference is None:
            reference = normalized
        elif normalized != reference:
            found.append(f"{shard} steps differ from db-1 apart from the shard name")
    db1 = [step.get("run") or "" for step in (jobs.get("db-1") or {}).get("steps") or []]
    pytest_index = next((i for i, run in enumerate(db1) if "ci-plan.py shard db-1" in run), None)
    trip_index = next((i for i, run in enumerate(db1) if "downgrade base" in run), None)
    if pytest_index is None or trip_index is None or trip_index < pytest_index:
        found.append("db-1 must run the migration round trip after its tests")
    lock = " ".join(step.get("run") or "" for step in (jobs.get("lockfile") or {}).get("steps") or [])
    if "check-runtime-lock.sh" not in lock:
        found.append("lockfile must run scripts/check-runtime-lock.sh")
    hygiene = " ".join(step.get("run") or "" for step in (jobs.get("hygiene") or {}).get("steps") or [])
    for needle in ("check-docs.sh", "review-scope-test.sh", "check-disk-space-test.sh", "ci-scripts-test.sh",
                   "git diff --check", "PRIVATE KEY", "plistlib"):
        if needle not in hygiene:
            found.append(f"hygiene must run {needle}")
    for job_id, job in jobs.items():
        for step in job.get("steps") or []:
            uses = step.get("uses")
            if uses and "@" in uses and len(uses.split("@", 1)[1]) != 40:
                found.append(f"{job_id}: {uses} must be pinned to a full commit SHA")
    return found


def main() -> int:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    found = problems(workflow)
    print("\n".join(found) if found else "workflow structure OK")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())

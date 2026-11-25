#!/usr/bin/env python3
"""Required-check gate decision (CI packages 2+3).

    ci-gate.py <gate> <needs-json>      # needs-json is ${{ toJSON(needs) }}; exit 0 pass, 1 fail

A gate passes only when ``plan`` succeeded and every job the gate requires either succeeded, or was skipped while
``plan`` reported ``full=false`` and that job's category ``false``. A failure, a cancellation, any other result or a
missing job fails the gate. GitHub reports a skipped job as passing a required check, so the required check names
belong only to these gates, which always run.
"""
from __future__ import annotations

import json
import sys

# gate -> {job id: category output of plan that justifies skipping it (None: the job must always succeed)}
GATES = {
    "backend": {"hygiene": None, "lockfile": "lockfile", "unit": "backend", "db-1": "backend", "db-2": "backend",
                "db-3": "backend"},
    "swift": {"swift": "ios"},
    "spacetimedb": {"spacetimedb": "spacetimedb"},
}


def decide(gate: str, needs: dict) -> list[str]:
    if gate not in GATES:
        return [f"unknown gate {gate!r}"]
    plan = needs.get("plan")
    if not isinstance(plan, dict) or plan.get("result") != "success":
        return ["plan did not succeed, so no skip can be justified"]
    outputs = plan.get("outputs") or {}
    full = outputs.get("full")
    problems = []
    for job, category in GATES[gate].items():
        entry = needs.get(job)
        result = entry.get("result") if isinstance(entry, dict) else None
        if result == "success":
            continue
        if result == "skipped" and category is not None and full == "false" and outputs.get(category) == "false":
            continue
        problems.append(f"{job}: {result or 'missing'}")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        needs = json.loads(argv[1])
    except json.JSONDecodeError:
        print("needs is not valid JSON")
        return 1
    problems = decide(argv[0], needs if isinstance(needs, dict) else {})
    for job in GATES.get(argv[0], {}):
        entry = needs.get(job) if isinstance(needs, dict) else None
        print(f"{job}: {entry.get('result') if isinstance(entry, dict) else 'missing'}")
    print("GATE FAIL: " + "; ".join(problems) if problems else "GATE PASS")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

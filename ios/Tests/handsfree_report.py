#!/usr/bin/env python3
"""Score hands-free runs from real logs. It reports only what the logs show.

    python ios/Tests/handsfree_report.py APP_CONSOLE.log SERVER.log

APP_CONSOLE.log: output of `devicectl device process launch --console`.
SERVER.log: Uvicorn output from the backend (INFO).
"""
import re
import sys
from pathlib import Path

APP_STAGES = [
    ("wake heard", r"\[Conversation\] wake heard"),
    ("wake released", r"wake listeners released"),
    ("muted until verified", r"microphone held muted until the route is verified"),
    ("assistant connected", r"\[Vapi\] assistant connected"),
    ("glasses route verified", r"route check: ready"),
    ("mic live", r"\[Vapi\] microphone live"),
    ("photo captured", r"\[Conversation\] captured \d+ bytes"),
    ("photo identified", r"\[Conversation\] photo identified"),
    ("call ended", r"\[Vapi\] call ended"),
    ("shutdown complete", r"\[Conversation\] shutdown complete"),
]
SERVER_STAGES = ["vehicle_confirmed", "camera_requested", "camera_delivered", "vision_done", "lookup_answered", "call_ended"]


def app_runs(lines):
    """Split the app log at each wake that started a call."""
    runs, current = [], None
    for line in lines:
        if re.search(r"\[Conversation\] wake heard", line):
            if current:
                runs.append(current)
            current = []
        if current is not None:
            current.append(line)
    if current:
        runs.append(current)
    return runs


def server_runs(lines):
    runs = {}
    for line in lines:
        match = re.search(r"session=(\w+) gen=(\d+) stage=(\w+)", line)
        if match:
            runs.setdefault((match[1], int(match[2])), []).append(match[3])
    return {key: stages for key, stages in runs.items() if key[1] > 0}


def main():
    app = app_runs(Path(sys.argv[1]).read_text(errors="replace").splitlines())
    server = list(server_runs(Path(sys.argv[2]).read_text(errors="replace").splitlines()).items())
    complete = 0
    for index, lines in enumerate(app, 1):
        text = "\n".join(lines)
        missing = [name for name, pattern in APP_STAGES if not re.search(pattern, text)]
        touches = len(re.findall(r"\[Conversation\] touch:", text))
        phone_mic = bool(re.search(r"route check: (noMicrophone|noSpeaker|otherDevice)", text))
        stages = server[index - 1][1] if index - 1 < len(server) else []
        missing_server = [stage for stage in SERVER_STAGES if stage not in stages]
        ok = not missing and not missing_server and touches == 0
        complete += ok
        print(f"Run {index}: {'PASS' if ok else 'INCOMPLETE'}  touches={touches}  route_problem_seen={phone_mic}")
        if missing:
            print("  app missing:", ", ".join(missing))
        if missing_server:
            print("  server missing:", ", ".join(missing_server))
    print(f"\n{complete} complete touch-free runs of {len(app)} (5 required)")


if __name__ == "__main__":
    main()

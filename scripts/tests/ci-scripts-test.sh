#!/usr/bin/env bash
# Tests for scripts/ci-plan.py (categories, shards, junit) and scripts/ci-gate.py (gate decisions). Standard library
# only; runs in CI's Hygiene job and in scripts/verify.sh. Git cases use a throwaway repository in a temp directory.
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
PYTHON="${PYTHON:-python3}"
exec "$PYTHON" - "$root" <<'PY'
import importlib.util, json, os, subprocess, sys, tempfile
from pathlib import Path

root = Path(sys.argv[1])
def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), root / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module
plan, gate = load("ci-plan"), load("ci-gate")
passed = failed = 0
def check(label, condition):
    global passed, failed
    if condition: passed += 1
    else:
        failed += 1; print(f"FAIL: {label}")

ALL = {k: True for k in plan.CATEGORIES}
pr = lambda paths: plan.categorize("pull_request", paths)
# full events and fail-closed inputs
for event in ("push", "schedule", "workflow_dispatch"):
    check(f"{event} is full", plan.categorize(event, ["docs/x.md"]) == ALL)
check("no diff is full", pr(None) == ALL)
check("empty diff is full", pr([]) == ALL)
for path in (".github/workflows/ci.yml", "scripts/ci-plan.py", "scripts/ci-gate.py", "scripts/check-docs.sh",
             "scripts/tests/ci-scripts-test.sh", "scripts/tests/ci-workflow-test.py", "docs/development-workflow.md"):
    check(f"{path} forces full", pr([path]) == ALL)
# categories
docs = pr(["docs/architecture/03-data-model.md", "README.md"])
check("docs-only runs nothing", not any(docs.values()))
for path in ("AGENTS.md", "CLAUDE.md", ".claude/skills/x/SKILL.md", "backend/tests/fixtures/openapi-v1.json",
             "backend/README.md", "ios/README.md", "docs/x.txt", "unknown-file"):
    out = pr([path])
    check(f"{path} is not docs", any(out.values()))
check("unknown path is backend", pr(["unknown-file"])["backend"])
check("backend change runs lockfile", pr(["backend/main.py"])["lockfile"] and pr(["backend/main.py"])["backend"])
ios = pr(["ios/Carvis/x.swift"])
check("ios-only", ios["ios"] and not ios["backend"] and not ios["lockfile"])
check("backend/README.md is backend", pr(["backend/README.md"])["backend"])
stdb = pr(["backend/spacetimedb/module/src/index.ts"])
check("spacetimedb-only", stdb["spacetimedb"] and not stdb["backend"])
deps = pr(["backend/requirements.txt"])
check("deps runs lockfile and backend", deps["deps"] and deps["lockfile"] and deps["backend"])
mixed = pr(["docs/x.md", "ios/a.swift", "backend/db/catalog.py"])
check("mixed", mixed["ios"] and mixed["backend"] and not mixed["full"])
# git paths: rename, non-ASCII, control characters, git failure
with tempfile.TemporaryDirectory() as d:
    g = lambda *a: subprocess.run(["git", "-C", d, *a], check=True, capture_output=True)
    g("init", "-q"); g("config", "user.email", "t@example.test"); g("config", "user.name", "t")
    (Path(d) / "backend").mkdir(); (Path(d) / "backend" / "m.py").write_text("x = 1\n")
    (Path(d) / "ios").mkdir(); g("add", "-A"); g("commit", "-qm", "a")
    base = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    (Path(d) / "docs").mkdir(); g("mv", "backend/m.py", "docs/m.md"); (Path(d) / "ios" / "é.swift").write_text("")
    g("add", "-A"); g("commit", "-qm", "b")
    head = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    plan.ROOT = Path(d)
    paths = plan.changed_paths(base, head)
    check("rename lists both sides", paths is not None and "backend/m.py" in paths and "docs/m.md" in paths)
    check("non-ASCII ios path unquoted", paths is not None and "ios/é.swift" in paths)
    out = pr(paths)
    check("rename out of backend runs backend", out["backend"])
    check("non-ASCII ios path runs swift", out["ios"])
    (Path(d) / "docs" / "a\nb.md").write_text(""); g("add", "-A"); g("commit", "-qm", "c")
    head2 = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    check("control character forces full", plan.changed_paths(head, head2) is None)
    check("git failure forces full", plan.changed_paths("0" * 40, head) is None)
    plan.ROOT = root
# shards map sanity
listed = [n for names in plan.DB_SHARDS.values() for n in names]
check("db shards disjoint", len(listed) == len(set(listed)))
check("db shard files exist", all((root / plan.TESTS / n).is_file() for n in listed))
check("unit excludes db files", not set(plan.shard_args("unit")) & {f"{plan.TESTS}/{n}" for n in listed})
# partition (needs pytest: runs in verify.sh; the CI unit job runs the real check itself)
try:
    import pytest as _pytest  # noqa: F401
    have_pytest = True
except ImportError:
    have_pytest = False
if have_pytest:
    check("partition OK on the real suite", plan.partition() == [])
    saved, saved_collect = dict(plan.DB_SHARDS), plan.collect
    plan.DB_SHARDS = {**saved, "db-3": saved["db-3"] + [saved["db-1"][0]]}
    check("partition refuses a file in two shards", plan.partition() != [])
    plan.DB_SHARDS = {**saved, "db-3": saved["db-3"] + ["test_does_not_exist.py"]}
    check("partition refuses a missing file", plan.partition() != [])
    plan.DB_SHARDS = saved
    def dropping(args, real=saved_collect):
        nodes = real(args)
        if args != plan.shard_args("db-1"):
            return nodes
        # Drop one instance of a parametrized function, so only the per-function count can reveal the loss.
        functions = [n.split("[", 1)[0] for n in nodes]
        index = next(i for i, f in enumerate(functions) if "[" in nodes[i] and functions.count(f) > 1)
        return nodes[:index] + nodes[index + 1:]
    plan.collect = dropping
    check("partition refuses a shard that loses a test", plan.partition() != [])
    plan.collect = saved_collect
else:
    print("partition tests skipped: pytest is not installed here (the CI unit job runs the check)")
# junit
with tempfile.TemporaryDirectory() as d:
    def junit(body, tests):
        path = Path(d) / "j.xml"
        path.write_text(f'<testsuites><testsuite tests="{tests}">{body}</testsuite></testsuites>'); return str(path)
    check("junit ok", plan.junit_problems(junit('<testcase classname="a" name="b"/>', 1)) == [])
    check("junit zero tests", plan.junit_problems(junit("", 0)))
    for kind in ("skipped", "error", "failure"):
        check(f"junit {kind}", plan.junit_problems(junit(f'<testcase classname="a" name="b"><{kind}/></testcase>', 1)))
    check("junit unreadable", plan.junit_problems(str(Path(d) / "missing.xml")))
# gate decisions
outputs = lambda **kw: {k: ("true" if kw.get(k, False) else "false") for k in plan.CATEGORIES}
def needs(gate_name, results, out):
    n = {"plan": {"result": "success", "outputs": out}}
    n.update({job: {"result": results.get(job, "success"), "outputs": {}} for job in gate.GATES[gate_name]})
    return n
check("all success passes", gate.decide("backend", needs("backend", {}, outputs(backend=True, lockfile=True))) == [])
for result in ("failure", "cancelled", "neutral", ""):
    check(f"unit {result!r} fails", gate.decide("backend", needs("backend", {"unit": result}, outputs(backend=True))))
docs_only = {j: "skipped" for j in ("lockfile", "unit", "db-1", "db-2", "db-3")}
check("docs-only skips pass", gate.decide("backend", needs("backend", docs_only, outputs())) == [])
check("skip with category true fails", gate.decide("backend", needs("backend", docs_only, outputs(backend=True))))
check("skip under full fails", gate.decide("backend", needs("backend", docs_only, {**outputs(), "full": "true"})))
check("skip with missing category output fails", gate.decide("backend", needs("backend", docs_only, {"full": "false"})))
check("hygiene skipped fails", gate.decide("backend", needs("backend", {"hygiene": "skipped"}, outputs())))
missing = needs("backend", {}, outputs(backend=True)); missing.pop("db-3")
check("missing job fails", gate.decide("backend", missing))
for result in ("failure", "cancelled", "skipped"):
    n = needs("backend", {}, outputs(backend=True)); n["plan"]["result"] = result
    check(f"plan {result} fails", gate.decide("backend", n))
check("no plan fails", gate.decide("swift", {"swift": {"result": "skipped"}}))
check("swift skipped when no ios passes", gate.decide("swift", needs("swift", {"swift": "skipped"}, outputs())) == [])
check("swift skipped with ios fails", gate.decide("swift", needs("swift", {"swift": "skipped"}, outputs(ios=True))))
check("spacetimedb failure fails", gate.decide("spacetimedb", needs("spacetimedb", {"spacetimedb": "failure"}, outputs())))
check("unknown gate fails", gate.decide("other", needs("swift", {}, outputs())))
cli = subprocess.run([sys.executable, str(root / "scripts" / "ci-gate.py"), "backend", "not json"], capture_output=True)
check("gate CLI invalid JSON fails", cli.returncode == 1)
cli = subprocess.run([sys.executable, str(root / "scripts" / "ci-gate.py"), "backend",
                      json.dumps(needs("backend", {}, outputs(backend=True)))], capture_output=True)
check("gate CLI pass exits 0", cli.returncode == 0)
print(f"ci-scripts tests: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
PY

"""Dependency lockfiles stay pinned, hashed, current and free of test tooling at runtime (M2 A5)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

BACKEND = Path(__file__).resolve().parents[1]
RUNTIME_LOCK = BACKEND / "requirements.txt"
DEV_LOCK = BACKEND / "requirements-dev.txt"
RUNTIME_IN = BACKEND / "requirements.in"
DEV_IN = BACKEND / "requirements-dev.in"
TEST_ONLY = {"pytest", "pluggy", "iniconfig"}


def _direct(path: Path) -> dict[str, Requirement]:
    """Direct requirements of an input file; `-r`/`-c` include lines are skipped."""
    requirements: dict[str, Requirement] = {}
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            requirement = Requirement(line)
            requirements[canonicalize_name(requirement.name)] = requirement
    return requirements


def _locked(path: Path) -> dict[str, list[tuple[str, str]]]:
    """Map each locked package to its (requirement, hash block) entries, one per marker variant."""
    entries: dict[str, list[tuple[str, str]]] = {}
    for block in re.split(r"\n(?=\S)", path.read_text()):
        head = block.split("\n", 1)[0]
        if not head.strip() or head.startswith("#"):
            continue
        spec = head.rstrip("\\").strip()
        assert not spec.startswith("-"), f"{path.name}: unexpected option line {spec!r}"
        requirement = Requirement(spec)
        entries.setdefault(canonicalize_name(requirement.name), []).append((spec, block))
    return entries


def _pin(spec: str) -> str:
    specifiers = list(Requirement(spec).specifier)
    assert len(specifiers) == 1 and specifiers[0].operator == "==", f"not an exact pin: {spec!r}"
    return specifiers[0].version


@pytest.mark.parametrize("lock", [RUNTIME_LOCK, DEV_LOCK], ids=["runtime", "dev"])
def test_every_entry_is_exactly_pinned_with_hashes(lock: Path) -> None:
    entries = _locked(lock)
    assert entries
    for variants in entries.values():
        for spec, block in variants:
            _pin(spec)
            assert "--hash=sha256:" in block, f"{lock.name}: no hash for {spec!r}"


def test_runtime_lock_excludes_test_tooling() -> None:
    assert TEST_ONLY.isdisjoint(_locked(RUNTIME_LOCK))
    assert TEST_ONLY.isdisjoint(_direct(RUNTIME_IN))


@pytest.mark.parametrize(
    "lock, inputs",
    [(RUNTIME_LOCK, [RUNTIME_IN]), (DEV_LOCK, [RUNTIME_IN, DEV_IN])],
    ids=["runtime", "dev"],
)
def test_locks_satisfy_their_inputs(lock: Path, inputs: list[Path]) -> None:
    """A lockfile that was not regenerated after an input bound changed fails here."""
    locked = _locked(lock)
    for path in inputs:
        for name, requirement in _direct(path).items():
            assert name in locked, f"{name} from {path.name} is missing from {lock.name}; regenerate it"
            for spec, _ in locked[name]:
                assert requirement.specifier.contains(_pin(spec), prereleases=True), (
                    f"{lock.name} pins {spec!r}, outside {path.name} bound {requirement}; regenerate it"
                )


def test_dev_lock_matches_runtime_pins() -> None:
    runtime = _locked(RUNTIME_LOCK)
    dev = _locked(DEV_LOCK)
    assert "pytest" in dev
    for name, variants in runtime.items():
        assert [spec for spec, _ in dev.get(name, [])] == [spec for spec, _ in variants], name


def test_marker_with_comparison_is_still_an_exact_pin() -> None:
    _pin("numpy==2.5.5 ; python_full_version >= '3.13'")
    with pytest.raises(AssertionError):
        _pin("numpy>=2.5.5")

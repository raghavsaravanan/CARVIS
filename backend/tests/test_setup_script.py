"""backend/setup.sh reads backend/.env as data and never executes it (M2 A5)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SETUP = Path(__file__).resolve().parents[1] / "setup.sh"


def _run(tmp_path: Path, env_text: str | None, **extra_env: str) -> subprocess.CompletedProcess[str]:
    shutil.copy(SETUP, tmp_path / "setup.sh")
    if env_text is not None:
        (tmp_path / ".env").write_text(env_text)
    env = {k: v for k, v in os.environ.items() if k not in {"QDRANT_URL", "QDRANT_API_KEY"}}
    env.update(CARVIS_SETUP_PYTHON=sys.executable)
    env.update(extra_env)
    return subprocess.run(
        ["bash", str(tmp_path / "setup.sh")], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30
    )


@pytest.mark.parametrize(
    "payload",
    ["$(touch {marker})", "`touch {marker}`", "x; touch {marker}"],
    ids=["command-substitution", "backticks", "statement"],
)
def test_env_file_is_never_executed(tmp_path: Path, payload: str) -> None:
    marker = tmp_path / "executed"
    body = f"QDRANT_URL=https://q.invalid\nQDRANT_API_KEY={payload.format(marker=marker)}\n"
    body += f"touch {marker}\n"
    result = _run(tmp_path, body)
    assert not marker.exists(), result.stdout + result.stderr
    assert result.returncode == 0
    assert "Cloud Qdrant configured: https://q.invalid" in result.stdout


def test_reads_values_and_trims_spaces(tmp_path: Path) -> None:
    result = _run(tmp_path, "QDRANT_URL = https://q.invalid  \nQDRANT_API_KEY = secret-value\n")
    assert result.returncode == 0
    assert "Cloud Qdrant configured: https://q.invalid\n" in result.stdout
    assert "secret-value" not in result.stdout + result.stderr


def test_url_without_key_is_not_cloud(tmp_path: Path) -> None:
    result = _run(tmp_path, "QDRANT_URL=https://q.invalid\n")
    assert result.returncode == 1
    assert "Cloud Qdrant configured" not in result.stdout
    assert "Database missing" in result.stdout


def test_missing_dotenv_fails_clearly_instead_of_ignoring_env_file(tmp_path: Path) -> None:
    # An interpreter without site-packages cannot import python-dotenv.
    bare = tmp_path / "bare-python"
    bare.write_text(f'#!/bin/sh\nexec "{sys.executable}" -I -S "$@"\n')
    bare.chmod(0o755)
    result = _run(tmp_path, "QDRANT_URL=https://q.invalid\nQDRANT_API_KEY=k\n", CARVIS_SETUP_PYTHON=str(bare))
    assert result.returncode == 2
    assert "python-dotenv is not installed" in result.stderr
    assert "Database missing" not in result.stdout


def test_unusable_interpreter_fails_clearly(tmp_path: Path) -> None:
    result = _run(tmp_path, None, CARVIS_SETUP_PYTHON=str(tmp_path / "no-such-python"))
    assert result.returncode == 2
    assert "Could not read settings" in result.stderr


def test_environment_overrides_env_file(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "QDRANT_URL=https://file.invalid\nQDRANT_API_KEY=k\n",
        QDRANT_URL="https://environment.invalid",
    )
    assert "Cloud Qdrant configured: https://environment.invalid" in result.stdout


def test_without_cloud_settings_requires_local_database(tmp_path: Path) -> None:
    result = _run(tmp_path, None)
    assert result.returncode == 1
    assert "Database missing" in result.stdout

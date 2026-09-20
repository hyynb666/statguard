"""Exercise installed entry points from outside the checkout."""

import os
import subprocess
import sys
import sysconfig
from importlib.metadata import version
from pathlib import Path

import pytest


@pytest.fixture(params=["console", "module"])
def cli(request: pytest.FixtureRequest) -> list[str]:
    if request.param == "module":
        return [sys.executable, "-m", "statguard"]
    name = "statguard.exe" if os.name == "nt" else "statguard"
    return [str(Path(sysconfig.get_path("scripts")) / name)]


@pytest.mark.parametrize("args", [[], ["--help"]])
def test_help(cli: list[str], tmp_path: Path, args: list[str]) -> None:
    result = subprocess.run(
        [*cli, *args], cwd=tmp_path, capture_output=True, text=True, timeout=10, check=False
    )
    assert result.returncode == 0
    assert "usage: statguard" in result.stdout
    assert "--version" in result.stdout
    assert "check" in result.stdout
    assert result.stderr == ""


def test_version_matches_distribution(cli: list[str], tmp_path: Path) -> None:
    result = subprocess.run(
        [*cli, "--version"], cwd=tmp_path, capture_output=True, text=True, timeout=10, check=False
    )
    assert result.returncode == 0
    assert result.stdout.strip() == f"statguard {version('statguard')}"
    assert result.stderr == ""


def test_unknown_option(cli: list[str], tmp_path: Path) -> None:
    result = subprocess.run(
        [*cli, "--unknown"], cwd=tmp_path, capture_output=True, text=True, timeout=10, check=False
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "unrecognized arguments" in result.stderr


def test_check_scans_without_executing_input(cli: list[str], tmp_path: Path) -> None:
    target = tmp_path / "analysis.py"
    target.write_text("from pathlib import Path\nPath('executed').touch()\n", encoding="utf-8")
    result = subprocess.run(
        [*cli, "check", str(target)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    assert "No detection rules enabled" in result.stdout
    assert not (tmp_path / "executed").exists()

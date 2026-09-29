"""Unit tests for safe input translation in the GitHub Action wrapper."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.run_github_action import build_cli_args, main

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def default_inputs(tmp_path: Path) -> dict[str, str]:
    return {
        "GITHUB_WORKSPACE": str(tmp_path),
        "INPUT_PATH": ".",
        "INPUT_FORMAT": "console",
        "INPUT_OUTPUT": "",
        "INPUT_FAIL_ON": "",
        "INPUT_DISABLE_RULES": "",
        "INPUT_EXCLUDE": "",
    }


def test_default_arguments_scan_workspace(default_inputs: dict[str, str], monkeypatch) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("scripts.run_github_action.subprocess.run", fake_run)

    assert main(default_inputs) == 0
    command, kwargs = calls[0]
    assert command == [sys.executable, "-m", "statguard", "check", ".", "--format", "console"]
    assert kwargs == {
        "cwd": Path(default_inputs["GITHUB_WORKSPACE"]),
        "check": False,
        "shell": False,
    }


@pytest.mark.parametrize("report_format", ["console", "json", "html"])
def test_report_format_is_mapped(report_format: str) -> None:
    assert build_cli_args({"INPUT_FORMAT": report_format}) == [
        "check",
        ".",
        "--format",
        report_format,
    ]


def test_empty_format_uses_console_default() -> None:
    assert build_cli_args({"INPUT_FORMAT": ""}) == ["check", ".", "--format", "console"]


def test_optional_output_and_threshold_are_omitted_when_empty() -> None:
    args = build_cli_args({"INPUT_OUTPUT": "", "INPUT_FAIL_ON": ""})
    assert "--output" not in args
    assert "--fail-on" not in args


@pytest.mark.parametrize("threshold", ["warning", "error"])
def test_failure_threshold_is_mapped(threshold: str) -> None:
    assert build_cli_args({"INPUT_FAIL_ON": threshold})[-2:] == ["--fail-on", threshold]


def test_output_path_with_spaces_is_one_argument() -> None:
    args = build_cli_args({"INPUT_OUTPUT": "reports/weekly report.html"})
    assert args[-2:] == ["--output", "reports/weekly report.html"]


def test_scan_path_with_spaces_is_one_argument() -> None:
    args = build_cli_args({"INPUT_PATH": "analysis projects/current"})
    assert args[1] == "analysis projects/current"


def test_rule_ids_are_split_and_trimmed() -> None:
    args = build_cli_args({"INPUT_DISABLE_RULES": "ML006, ST002,, "})
    assert args[-4:] == ["--disable-rule", "ML006", "--disable-rule", "ST002"]


def test_multiline_excludes_keep_spaces_and_ignore_empty_lines() -> None:
    args = build_cli_args({"INPUT_EXCLUDE": "generated files\n\n examples/legacy file.py \n"})
    assert args[-4:] == [
        "--exclude",
        "generated files",
        "--exclude",
        " examples/legacy file.py ",
    ]


@pytest.mark.parametrize("report_format", ["yaml", "JSON"])
def test_invalid_format_is_rejected(report_format: str) -> None:
    with pytest.raises(ValueError, match="format"):
        build_cli_args({"INPUT_FORMAT": report_format})


@pytest.mark.parametrize("threshold", ["info", "Warning", "all"])
def test_invalid_fail_on_is_rejected(threshold: str) -> None:
    with pytest.raises(ValueError, match="fail-on"):
        build_cli_args({"INPUT_FAIL_ON": threshold})


def test_shell_like_path_is_passed_as_literal_argument(
    default_inputs: dict[str, str], monkeypatch
) -> None:
    literal = "repo; echo BAD"
    default_inputs["INPUT_PATH"] = literal
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("scripts.run_github_action.subprocess.run", fake_run)

    assert main(default_inputs) == 0
    command = captured["command"]
    assert isinstance(command, list)
    assert command[4] == literal
    assert captured["kwargs"]["shell"] is False


def test_unknown_rule_id_is_delegated_to_statguard() -> None:
    assert build_cli_args({"INPUT_DISABLE_RULES": "NEW999"})[-2:] == [
        "--disable-rule",
        "NEW999",
    ]


@pytest.mark.parametrize("child_status", [0, 1, 2])
def test_child_exit_code_is_propagated(
    default_inputs: dict[str, str], monkeypatch, child_status: int
) -> None:
    monkeypatch.setattr(
        "scripts.run_github_action.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, child_status),
    )
    assert main(default_inputs) == child_status


@pytest.mark.parametrize("path", ["../outside", "sub/../../outside", "C:\\outside"])
def test_path_cannot_escape_workspace(path: str) -> None:
    with pytest.raises(ValueError, match="GITHUB_WORKSPACE"):
        build_cli_args({"INPUT_PATH": path})


def test_invalid_workspace_returns_error_code(default_inputs: dict[str, str], capsys) -> None:
    default_inputs["GITHUB_WORKSPACE"] = str(Path(default_inputs["GITHUB_WORKSPACE"]) / "missing")
    assert main(default_inputs) == 2
    assert "GITHUB_WORKSPACE is not a directory" in capsys.readouterr().err


def test_action_metadata_uses_composite_action_and_local_package_source() -> None:
    action = (ROOT / "action.yml").read_text(encoding="utf-8")

    assert "using: composite" in action
    assert "actions/setup-python@v6" in action
    assert "STATGUARD_ACTION_PATH: ${{ github.action_path }}" in action
    assert "pip', 'install', '--no-deps', os.environ['STATGUARD_ACTION_PATH']" in action
    assert "check=False, shell=False" in action
    assert "pip install statguard" not in action


def test_action_smoke_workflow_covers_both_hosted_platforms() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "os: [ubuntu-latest, windows-latest]" in workflow
    assert "uses: ./" in workflow
    assert "fail-on: warning" in workflow
    assert "disable-rules: ML001" in workflow
    assert "format: json" in workflow and "format: html" in workflow
    assert "action_no_execution.py" in workflow

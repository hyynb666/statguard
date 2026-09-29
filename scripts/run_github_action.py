"""Build a safe argv and run StatGuard from a composite GitHub Action."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path, PureWindowsPath


def build_cli_args(inputs: Mapping[str, str]) -> list[str]:
    """Translate Action environment inputs into CLI arguments without a shell."""
    path = inputs.get("INPUT_PATH", ".") or "."
    _validate_relative_workspace_path(path, "path")

    config_path = inputs.get("INPUT_CONFIG", "")
    no_config = inputs.get("INPUT_NO_CONFIG", "false")
    if no_config not in {"true", "false"}:
        raise ValueError("no-config must be exactly true or false")
    if config_path and no_config == "true":
        raise ValueError("config cannot be combined with no-config")
    if config_path:
        _validate_relative_workspace_path(config_path, "config")

    report_format = (inputs.get("INPUT_FORMAT", "console") or "console").strip()
    if report_format not in {"console", "json", "html", "sarif"}:
        raise ValueError("format must be console, json, html, or sarif")

    fail_on = inputs.get("INPUT_FAIL_ON", "").strip()
    if fail_on not in {"", "warning", "error"}:
        raise ValueError("fail-on must be empty, warning, or error")

    args = ["check", path, "--format", report_format]
    if config_path:
        args.extend(("--config", config_path))
    if no_config == "true":
        args.append("--no-config")
    output = inputs.get("INPUT_OUTPUT", "")
    if output:
        _validate_relative_workspace_path(output, "output")
        args.extend(("--output", output))
    if fail_on:
        args.extend(("--fail-on", fail_on))
    for rule_id in inputs.get("INPUT_DISABLE_RULES", "").split(","):
        normalized_id = rule_id.strip()
        if normalized_id:
            args.extend(("--disable-rule", normalized_id))
    for exclude_path in inputs.get("INPUT_EXCLUDE", "").splitlines():
        if exclude_path.strip():
            args.extend(("--exclude", exclude_path))
    return args


def _validate_relative_workspace_path(value: str, name: str) -> None:
    native_path = Path(value)
    windows_path = PureWindowsPath(value)
    path_parts = value.replace("\\", "/").split("/")
    if (
        native_path.is_absolute()
        or windows_path.is_absolute()
        or value.startswith(("/", "\\"))
        or ".." in path_parts
    ):
        raise ValueError(f"{name} must stay within GITHUB_WORKSPACE")


def main(environ: Mapping[str, str] | None = None) -> int:
    """Run the installed package in the checked-out repository directory."""
    inputs = os.environ if environ is None else environ
    workspace_value = inputs.get("GITHUB_WORKSPACE")
    if not workspace_value:
        print("statguard-action: GITHUB_WORKSPACE is not set", file=sys.stderr)
        return 2
    workspace = Path(workspace_value).resolve()
    if not workspace.is_dir():
        print("statguard-action: GITHUB_WORKSPACE is not a directory", file=sys.stderr)
        return 2

    try:
        args = build_cli_args(inputs)
        relative_paths = [args[1]]
        if "--output" in args:
            relative_paths.append(args[args.index("--output") + 1])
        if "--config" in args:
            relative_paths.append(args[args.index("--config") + 1])
        for value in relative_paths:
            (workspace / value).resolve().relative_to(workspace)
    except (OSError, ValueError):
        print("statguard-action: invalid Action input path or options", file=sys.stderr)
        return 2

    command = [sys.executable, "-m", "statguard", *args]
    try:
        result = subprocess.run(command, cwd=workspace, check=False, shell=False)
    except OSError as error:
        print(f"statguard-action: cannot start StatGuard ({type(error).__name__})", file=sys.stderr)
        return 2
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

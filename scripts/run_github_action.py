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
    native_path = Path(path)
    windows_path = PureWindowsPath(path)
    path_parts = path.replace("\\", "/").split("/")
    if native_path.is_absolute() or windows_path.is_absolute() or ".." in path_parts:
        raise ValueError("path must stay within GITHUB_WORKSPACE")

    report_format = (inputs.get("INPUT_FORMAT", "console") or "console").strip()
    if report_format not in {"console", "json", "html"}:
        raise ValueError("format must be console, json, or html")

    fail_on = inputs.get("INPUT_FAIL_ON", "").strip()
    if fail_on not in {"", "warning", "error"}:
        raise ValueError("fail-on must be empty, warning, or error")

    args = ["check", path, "--format", report_format]
    output = inputs.get("INPUT_OUTPUT", "")
    if output:
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
        target = Path(args[1])
        resolved_target = (workspace / target).resolve()
        resolved_target.relative_to(workspace)
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

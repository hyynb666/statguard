"""Command-line entry point for deterministic, non-executing scans."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from statguard import __version__
from statguard.analyzer import Analyzer
from statguard.context import AnalysisContext
from statguard.core import RuleRegistry
from statguard.reporters import render_console, render_json
from statguard.reporters.models import reaches_threshold
from statguard.scanner import Scanner


def main(
    argv: Sequence[str] | None = None,
    *,
    registry: RuleRegistry[AnalysisContext] | None = None,
) -> int:
    """Run one scan; optional registry is for explicit trusted integrations."""
    parser = argparse.ArgumentParser(
        prog="statguard",
        description="Static analysis for statistical Python workflows.",
    )
    parser.add_argument("--version", action="version", version=f"statguard {__version__}")
    commands = parser.add_subparsers(dest="command")
    check = commands.add_parser("check", help="Scan a Python file, Notebook, or directory")
    check.add_argument("path", help="File or directory to scan")
    check.add_argument("--format", choices=("console", "json"), default="console")
    check.add_argument("--output", help="Write the complete report to this file")
    check.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="RELATIVE_PATH",
        help="Exclude a path relative to the scanned directory (repeatable)",
    )
    check.add_argument(
        "--fail-on",
        choices=("warning", "error"),
        default=None,
        help="Exit 1 at this diagnostic severity or higher",
    )
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    scanner = Scanner(Analyzer(registry if registry is not None else RuleRegistry()))
    try:
        report = scanner.scan(args.path, exclude=tuple(args.exclude))
    except ValueError as error:
        print(f"statguard: error: {error}", file=sys.stderr)
        return 2
    rendered = render_json(report) if args.format == "json" else render_console(report)
    if args.output is not None:
        destination = Path(args.output)
        scanned = {Path(result.path).resolve() for result in report.results}
        if destination.resolve() in scanned:
            print("statguard: error: --output must not overwrite a scanned input", file=sys.stderr)
            return 2
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(rendered, encoding="utf-8")
        except (OSError, ValueError) as error:
            print(f"statguard: error: cannot write report: {type(error).__name__}", file=sys.stderr)
            return 2
    else:
        sys.stdout.write(rendered)

    if report.analysis_errors:
        return 2
    if reaches_threshold(report, args.fail_on):
        return 1
    return 0

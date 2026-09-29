"""Command-line entry point for deterministic, non-executing scans."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from statguard import __version__
from statguard.analyzer import Analyzer
from statguard.config import ConfigError, StatGuardConfig, discover_config, load_config
from statguard.context import AnalysisContext
from statguard.core import RuleRegistry
from statguard.reporters import render_console, render_html, render_json
from statguard.reporters.models import reaches_threshold
from statguard.rules import default_registry
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
    check.add_argument("--format", choices=("console", "json", "html"), default="console")
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
    check.add_argument(
        "--disable-rule",
        action="append",
        default=[],
        metavar="RULE_ID",
        help="Disable a registered rule (repeatable)",
    )
    config_group = check.add_mutually_exclusive_group()
    config_group.add_argument(
        "--config", metavar="PATH", help="Read project policy from a TOML file"
    )
    config_group.add_argument(
        "--no-config", action="store_true", help="Disable automatic pyproject.toml discovery"
    )
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    selected = _copy_registry(registry if registry is not None else default_registry())
    try:
        if args.config is not None:
            config = load_config(args.config)
        elif args.no_config:
            config = StatGuardConfig()
        else:
            automatic_config = Path.cwd() / "pyproject.toml"
            config = discover_config(automatic_config)
    except ConfigError as error:
        print(f"statguard: error: {error}", file=sys.stderr)
        return 2

    disable_rules = _stable_unique((*config.disable_rules, *args.disable_rule))
    for rule_id in disable_rules:
        try:
            selected.get(rule_id)
        except KeyError:
            if rule_id in config.disable_rules:
                print(
                    f"statguard: error: configuration references unknown rule ID: {rule_id}",
                    file=sys.stderr,
                )
                return 2
            parser.error(f"Unknown rule ID: {rule_id}")
    for rule_id in disable_rules:
        try:
            selected.disable(rule_id)
        except KeyError:
            parser.error(f"Unknown rule ID: {rule_id}")
    scanner = Scanner(Analyzer(selected))
    try:
        report = scanner.scan(args.path, exclude=_stable_unique((*config.exclude, *args.exclude)))
    except ValueError as error:
        print(f"statguard: error: {error}", file=sys.stderr)
        return 2
    renderers = {"console": render_console, "json": render_json, "html": render_html}
    rendered = renderers[args.format](report)
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
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(rendered)

    if report.analysis_errors:
        return 2
    fail_on = args.fail_on if args.fail_on is not None else config.fail_on
    if reaches_threshold(report, fail_on):
        return 1
    return 0


def _stable_unique(values: Sequence[str]) -> tuple[str, ...]:
    """Remove repeated policy values without changing their first-seen order."""
    return tuple(dict.fromkeys(values))


def _copy_registry(registry: RuleRegistry[AnalysisContext]) -> RuleRegistry[AnalysisContext]:
    """Snapshot rule objects and enabled state so one CLI run cannot leak policy."""
    snapshot: RuleRegistry[AnalysisContext] = RuleRegistry()
    for rule in registry:
        snapshot.register(rule, enabled=registry.is_enabled(rule.rule_id))
    return snapshot

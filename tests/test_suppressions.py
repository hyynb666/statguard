"""Explicit inline suppression parsing and Analyzer integration tests."""

import json

from statguard.analyzer import AnalysisErrorCode, Analyzer
from statguard.context import AnalysisContext
from statguard.core import Evidence, Finding, Rule, RuleRegistry
from statguard.parsers import PythonSourceParser
from statguard.suppressions import SuppressionIndex


class FixedRule(Rule[AnalysisContext]):
    rule_id = "CUSTOM-01"
    name = "Fixed finding"
    description = "A custom rule used to test policy filtering."

    def check(self, context):
        yield Finding(
            self.rule_id,
            file_path=context.path,
            line=2,
            column=1,
            message="Observed pattern",
            explanation="Risk text",
            suggestion="Review it",
            evidence=Evidence.POTENTIAL_STATISTICAL_RISK,
        )


def make_analyzer(rule=None):
    registry = RuleRegistry[AnalysisContext]()
    registry.register(rule or FixedRule())
    return Analyzer(registry)


def test_suppression_index_parses_only_real_comment_tokens_and_exact_ids():
    source = """
"# statguard: ignore CUSTOM-01"
# statguard: ignore CUSTOM-01, ML001
result = "# statguard: ignore-next-line CUSTOM-01"
# statguard: ignore-next-line CUSTOM-01,ST002
next_call()
# statguard: ignore *
# statguard: ignore ALL
# statguard: Ignore CUSTOM-01
# statguard: ignore CUSTOM-01 because it looks odd
"""
    index = SuppressionIndex.from_source(source)

    assert index.suppresses(line=3, rule_id="CUSTOM-01")
    assert index.suppresses(line=3, rule_id="ML001")
    assert not index.suppresses(line=3, rule_id="ml001")
    assert index.suppresses(line=6, rule_id="CUSTOM-01")
    assert index.suppresses(line=6, rule_id="ST002")
    assert not index.suppresses(line=2, rule_id="CUSTOM-01")
    assert not index.suppresses(line=5, rule_id="CUSTOM-01")
    assert not index.suppresses(line=7, rule_id="CUSTOM-01")
    assert not index.suppresses(line=10, rule_id="CUSTOM-01")
    assert not index.suppresses(line=11, rule_id="CUSTOM-01")
    assert not index.suppresses(line=12, rule_id="CUSTOM-01")


def test_same_line_uses_physical_finding_line_and_next_line_does_not_skip():
    index = SuppressionIndex.from_source(
        "one()  # statguard: ignore CUSTOM-01\n"
        "# statguard: ignore-next-line CUSTOM-01\n"
        "\n"
        "four()\n"
        "# statguard: ignore-next-line CUSTOM-01\n"
        "# comment line is the next physical line\n"
    )

    assert index.suppresses(line=1, rule_id="CUSTOM-01")
    assert index.suppresses(line=3, rule_id="CUSTOM-01")
    assert index.suppresses(line=6, rule_id="CUSTOM-01")
    assert not index.suppresses(line=4, rule_id="CUSTOM-01")


def test_analyzer_filters_after_validated_rule_result_and_keeps_other_ids():
    source = "first()\nsecond() # statguard: ignore CUSTOM-01\n"
    result = make_analyzer().analyze_source(source, path="sample.py")

    assert result.errors == ()
    # The fixture Finding is on line 2, so only that exact ID/location is hidden.
    assert result.findings == ()


def test_suppression_changes_only_presence_not_finding_semantics():
    class RecordingRule(FixedRule):
        observed = None

        def check(self, context):
            finding = next(super().check(context))
            self.observed = finding
            yield finding

    rule = RecordingRule()
    analyzer = make_analyzer(rule)
    plain = analyzer.analyze_source("first()\nsecond()\n", path="same.py")
    expected = rule.observed
    commented = analyzer.analyze_source(
        "first()\nsecond()  # statguard: ignore CUSTOM-01\n", path="same.py"
    )

    assert len(plain.findings) == 1
    assert commented.findings == ()
    assert plain.findings[0].line == 2
    assert plain.findings[0].rule_id == "CUSTOM-01"
    assert rule.observed == expected


def test_malformed_or_unknown_directives_are_noops_and_custom_ids_work():
    assert (
        make_analyzer()
        .analyze_source("# statguard: ignore UNKNOWN\nsecond()\n", path="unknown.py")
        .findings
    )
    result = make_analyzer().analyze_source(
        "# statguard: ignore CUSTOM-01\nsecond()\n", path="custom.py"
    )
    assert len(result.findings) == 1  # Directive line is not Finding line 2.
    assert result.findings[0].line == 2

    next_line = make_analyzer().analyze_source(
        "# statguard: ignore-next-line CUSTOM-01\nsecond()\n", path="custom.py"
    )
    assert next_line.findings == ()


def test_notebook_suppression_is_code_cell_local_and_preserves_locations():
    document = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"language_info": {"name": "python"}},
        "cells": [
            {"cell_type": "markdown", "metadata": {}, "source": "# statguard: ignore CUSTOM-01"},
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": "work()\nwork() # statguard: ignore CUSTOM-01",
            },
            {
                "cell_type": "raw",
                "metadata": {},
                "source": "# statguard: ignore-next-line CUSTOM-01",
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": "work()\n",
            },
        ],
    }
    result = make_analyzer().analyze_notebook_json(json.dumps(document), path="study.ipynb")

    # The fixed test rule emits line 2. It is suppressed only in the first code cell.
    assert len(result.findings) == 1
    assert result.findings[0].cell_index == 4
    assert result.findings[0].cell == 2
    assert result.findings[0].line == 2


def test_parse_and_rule_errors_are_not_suppressed():
    parse_result = make_analyzer().analyze_source(
        "# statguard: ignore CUSTOM-01\nvalue = )", path="bad.py"
    )
    assert parse_result.errors

    class BrokenRule(FixedRule):
        rule_id = "BROKEN"

        def check(self, context):
            raise RuntimeError("failure")

    registry = RuleRegistry[AnalysisContext]()
    registry.register(BrokenRule())
    result = Analyzer(registry).analyze_source(
        "# statguard: ignore BROKEN\nvalue()", path="error.py"
    )
    assert result.errors[0].code is AnalysisErrorCode.RULE_EXECUTION
    assert result.errors[0].rule_id == "BROKEN"


def test_source_comments_and_notebook_outputs_are_never_executed(tmp_path):
    marker = tmp_path / "marker"
    source = (
        f"from pathlib import Path\nPath({str(marker)!r}).touch()  # statguard: ignore CUSTOM-01\n"
    )
    parsed = PythonSourceParser().parse_source(source, path="unsafe.py")
    result = make_analyzer().analyze(parsed)
    assert result.findings == ()
    assert not marker.exists()

    # A stored output is inert JSON data; neither output nor code is evaluated.
    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"language_info": {"name": "python"}},
        "cells": [
            {
                "cell_type": "code",
                "execution_count": 1,
                "metadata": {},
                "source": f"Path({str(marker)!r}).touch() # statguard: ignore CUSTOM-01",
                "outputs": [{"output_type": "stream", "text": "Path.touch()"}],
            }
        ],
    }
    make_analyzer().analyze_notebook_json(json.dumps(notebook), path="unsafe.ipynb")
    assert not marker.exists()


def test_real_cli_applies_suppression_before_all_reporters_and_thresholds(tmp_path, capsys):
    from statguard.cli import main
    from statguard.rules import default_registry

    path = tmp_path / "risk.py"
    path.write_text(
        "from sklearn.preprocessing import StandardScaler\n"
        "from sklearn.model_selection import train_test_split\n"
        "scaled = StandardScaler().fit_transform(X)  # statguard: ignore ML001\n"
        "train, test = train_test_split(scaled)\n",
        encoding="utf-8",
    )
    for report_format in ("console", "json", "html", "sarif"):
        code = main(
            [
                "check",
                str(path),
                "--format",
                report_format,
                "--fail-on",
                "warning",
                "--disable-rule",
                "ML006",
            ]
        )
        output = capsys.readouterr().out
        assert code == 0
        if report_format == "console":
            assert "ML001" not in output
        elif report_format == "json":
            data = json.loads(output)
            assert data["schema_version"] == "1.0" and data["findings"] == []
        elif report_format == "html":
            assert "ML001" not in output and "Content-Security-Policy" in output
        else:
            data = json.loads(output)
            assert data["version"] == "2.1.0" and data["runs"][0]["results"] == []

    path.write_text(path.read_text(encoding="utf-8").replace("  # statguard: ignore ML001", ""))
    assert main(["check", str(path), "--format", "json", "--disable-rule", "ML006"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert [finding["rule_id"] for finding in report["findings"]] == ["ML001"]
    assert main(["check", str(path), "--fail-on", "warning", "--disable-rule", "ML006"]) == 1
    capsys.readouterr()

    disabled_registry = default_registry()
    assert (
        main(
            [
                "check",
                str(path),
                "--format",
                "json",
                "--fail-on",
                "warning",
                "--disable-rule",
                "ML001",
                "--disable-rule",
                "ML006",
            ],
            registry=disabled_registry,
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["findings"] == []

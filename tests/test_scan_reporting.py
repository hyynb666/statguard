"""CLI scanner and both reporters use only parsed source and fixture rules."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from statguard.analyzer import Analyzer
from statguard.cli import main
from statguard.context import AnalysisContext
from statguard.core import Evidence, Finding, Rule, RuleRegistry, Severity
from statguard.scanner import Scanner


def notebook(*cells: dict, language: str = "python") -> str:
    return json.dumps(
        {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {"language_info": {"name": language}},
            "cells": list(cells),
        }
    )


def cell(source: str, *, outputs: list | None = None) -> dict:
    return {"cell_type": "code", "metadata": {}, "source": source, "outputs": outputs or []}


def invoke(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "statguard", *args],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


class FixtureRule(Rule[AnalysisContext]):
    rule_id = "FIX001"
    description = "Reports calls in fixture source."

    def __init__(self, severity: Severity = Severity.WARNING):
        self.severity = severity

    def check(self, context: AnalysisContext):
        for call in context.calls:
            yield Finding(
                self.rule_id,
                context.path,
                call.location.line,
                call.location.column,
                f"Call {call.name}",
                "Fixture risk",
                "Fixture fix",
                Evidence.CONFIRMED_CODE_PATTERN,
                severity=self.severity,
            )


def registry(*rules: Rule[AnalysisContext]) -> RuleRegistry[AnalysisContext]:
    result = RuleRegistry[AnalysisContext]()
    for rule in rules:
        result.register(rule)
    return result


def test_single_python_file_and_parseable_json(tmp_path: Path) -> None:
    target = tmp_path / "分析.py"
    target.write_text("# 中文\nx = 1\n", encoding="utf-8")
    result = invoke("check", str(target), "--format", "json")
    payload = json.loads(result.stdout)
    assert result.stdout.isascii()  # Portable even with a non-UTF-8 Windows console.
    assert result.returncode == 0 and result.stderr == ""
    assert payload["tool"] == "statguard" and payload["schema_version"] == "1.0"
    assert payload["summary"]["scanned_files"] == 1
    assert payload["summary"]["complete_files"] == 1
    assert payload["findings"] == payload["analysis_errors"] == []


def test_single_notebook_file_and_output_ignored(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    target = tmp_path / "book.ipynb"
    target.write_text(
        notebook(
            cell("x = 1", outputs=[{"output_type": "stream", "text": f"open('{marker}', 'w')"}])
        ),
        encoding="utf-8",
    )
    result = invoke("check", str(target), "--format", "json")
    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload["summary"]["complete_files"] == 1
    assert payload["findings"] == []
    assert not marker.exists()


def test_directory_order_default_exclusions_and_extra_exclude(tmp_path: Path) -> None:
    (tmp_path / "b.py").write_text("b()\n")
    (tmp_path / "a.ipynb").write_text(notebook(cell("a()")))
    (tmp_path / "skip.txt").write_text("invalid")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "ignored.py").write_text("broken = )")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "c.py").write_text("c()")
    first = invoke("check", str(tmp_path), "--format", "json")
    second = invoke("check", str(tmp_path), "--format", "json")
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    payload = json.loads(first.stdout)
    assert [Path(item["file_path"]).name for item in payload["files"]] == [
        "a.ipynb",
        "b.py",
        "c.py",
    ]
    excluded = invoke("check", str(tmp_path), "--format", "json", "--exclude", "nested")
    assert json.loads(excluded.stdout)["summary"]["scanned_files"] == 2


def test_empty_inputs_and_empty_directory_notice(tmp_path: Path) -> None:
    source = tmp_path / "empty.py"
    source.touch()
    book = tmp_path / "empty.ipynb"
    book.write_text(notebook())
    for target in (source, book):
        result = invoke("check", str(target), "--format", "json")
        assert result.returncode == 0
        assert json.loads(result.stdout)["summary"]["complete_files"] == 1
    empty = tmp_path / "empty"
    empty.mkdir()
    result = invoke("check", str(empty), "--format", "json")
    assert result.returncode == 0
    assert json.loads(result.stdout)["notices"][0]["code"] == "no_supported_files"


def test_fixture_rule_console_and_json_have_same_location(tmp_path: Path, capsys) -> None:
    target = tmp_path / "book.ipynb"
    target.write_text(
        notebook(
            {"cell_type": "markdown", "metadata": {}, "source": "ignore()"},
            cell("first()\nsecond()"),
        )
    )
    rules = registry(FixtureRule())
    assert main(["check", str(target)], registry=rules) == 0
    console = capsys.readouterr().out
    assert f"{target}:cell 2:1:1: FIX001 warning: Call first" in console
    assert "Risk: Fixture risk" in console and "Fix: Fixture fix" in console
    assert main(["check", str(target), "--format", "json"], registry=rules) == 0
    payload = json.loads(capsys.readouterr().out)
    findings = payload["findings"]
    assert [(f["cell_index"], f["cell"], f["line"], f["column"]) for f in findings] == [
        (2, 1, 1, 1),
        (2, 1, 2, 1),
    ]
    assert findings[0]["explanation"] == "Fixture risk"
    assert findings[0]["suggestion"] == "Fixture fix"
    assert findings[0]["evidence"] == "confirmed code pattern"
    assert payload["summary"]["warning"] == 2


def test_fail_threshold_and_disabled_rule(tmp_path: Path, capsys) -> None:
    target = tmp_path / "code.py"
    target.write_text("run()\n")
    warning = registry(FixtureRule())
    assert main(["check", str(target)], registry=warning) == 0
    capsys.readouterr()
    assert main(["check", str(target), "--fail-on", "warning"], registry=warning) == 1
    capsys.readouterr()
    assert main(["check", str(target), "--fail-on", "error"], registry=warning) == 0
    capsys.readouterr()
    warning.disable("FIX001")
    assert main(["check", str(target), "--fail-on", "warning"], registry=warning) == 0
    assert "No detection rules enabled" in capsys.readouterr().out
    error = registry(FixtureRule(Severity.ERROR))
    assert main(["check", str(target), "--fail-on", "error"], registry=error) == 1
    capsys.readouterr()


def test_output_creates_parent_and_never_overwrites_input(tmp_path: Path, capsys) -> None:
    source = tmp_path / "code.py"
    source.write_text("x = 1")
    output = tmp_path / "reports" / "scan.json"
    assert main(["check", str(source), "--format", "json", "--output", str(output)]) == 0
    assert capsys.readouterr().out == ""
    assert json.loads(output.read_text(encoding="utf-8"))["summary"]["scanned_files"] == 1
    assert main(["check", str(source), "--output", str(source)]) == 2
    assert source.read_text() == "x = 1"
    assert "must not overwrite" in capsys.readouterr().err
    assert main(["check", str(source), "--output", str(tmp_path)]) == 2
    assert "cannot write report" in capsys.readouterr().err


def test_parse_errors_partial_notebook_and_other_files_continue(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("x = )")
    (tmp_path / "invalid.ipynb").write_text("{")
    (tmp_path / "partial.ipynb").write_text(notebook(cell("x = )"), cell("good()")))
    (tmp_path / "good.py").write_text("okay()")
    result = invoke("check", str(tmp_path), "--format", "json")
    payload = json.loads(result.stdout)
    assert result.returncode == 2 and result.stderr == ""
    assert payload["summary"]["scanned_files"] == 4
    assert payload["summary"]["partial_files"] == 1
    assert payload["summary"]["failed_files"] == 2
    assert payload["summary"]["complete_files"] == 1
    assert {item["code"] for item in payload["analysis_errors"]} == {"syntax_error", "invalid_json"}
    partial_error = next(
        item for item in payload["analysis_errors"] if item["file_path"].endswith("partial.ipynb")
    )
    assert partial_error["cell_index"] == 1


def test_rule_failure_does_not_leak_exception_text(tmp_path: Path, capsys) -> None:
    class Broken(Rule[AnalysisContext]):
        rule_id = "FIX002"
        description = "Failure fixture"

        def check(self, context):
            raise RuntimeError("secret token must stay private")

    target = tmp_path / "code.py"
    target.write_text("run()")
    assert (
        main(["check", str(target), "--format", "json"], registry=registry(Broken(), FixtureRule()))
        == 2
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["rule_errors"] == 1
    assert payload["summary"]["failed_files"] == 1
    assert payload["findings"][0]["rule_id"] == "FIX001"
    assert payload["analysis_errors"][0]["code"] == "rule_execution"
    assert "secret token" not in json.dumps(payload)


@pytest.mark.parametrize("name", ["missing.py", "unsupported.txt"])
def test_invalid_input_and_arguments(tmp_path: Path, name: str) -> None:
    target = tmp_path / name
    if name == "unsupported.txt":
        target.write_text("data")
    result = invoke("check", str(target), "--format", "json")
    payload = json.loads(result.stdout)
    assert result.returncode == 2
    assert payload["analysis_errors"] and payload["summary"]["parse_errors"] == 1
    invalid = invoke("check", str(target), "--format", "yaml")
    assert invalid.returncode == 2 and invalid.stdout == ""


def test_no_execution_of_source_or_notebook(tmp_path: Path) -> None:
    marker = tmp_path / "marker"
    (tmp_path / "side.py").write_text(f"open({str(marker)!r}, 'w').close()")
    (tmp_path / "side.ipynb").write_text(notebook(cell(f"open({str(marker)!r}, 'w').close()")))
    result = invoke("check", str(tmp_path), "--format", "json")
    assert result.returncode == 0
    assert not marker.exists()


def test_scanner_reports_unreadable_directory_and_bad_exclusion(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "source"
    root.mkdir()
    original = Path.iterdir

    def denied(path):
        if path == root:
            raise PermissionError("private")
        return original(path)

    monkeypatch.setattr(Path, "iterdir", denied)
    report = Scanner(Analyzer(registry())).scan(root)
    assert report.analysis_errors[0].code == "read_error"
    assert report.findings == ()
    with pytest.raises(ValueError):
        Scanner(Analyzer(registry())).scan(root, exclude=("../outside",))


def test_findings_sorted_across_files_and_repeated_runs(tmp_path: Path, capsys) -> None:
    (tmp_path / "z.py").write_text("z()")
    (tmp_path / "A.py").write_text("a()")
    rules = registry(FixtureRule())
    assert main(["check", str(tmp_path), "--format", "json"], registry=rules) == 0
    first = capsys.readouterr().out
    assert main(["check", str(tmp_path), "--format", "json"], registry=rules) == 0
    assert capsys.readouterr().out == first
    paths = [Path(item["file_path"]).name for item in json.loads(first)["findings"]]
    assert paths == ["A.py", "z.py"]


def test_notebook_magic_and_unsupported_language_are_explicit(tmp_path: Path) -> None:
    magic = tmp_path / "magic.ipynb"
    magic.write_text(notebook(cell("%time x = 1"), cell("valid()")))
    result = invoke("check", str(magic), "--format", "json")
    payload = json.loads(result.stdout)
    assert result.returncode == 2
    assert payload["summary"]["partial_files"] == 1
    assert payload["analysis_errors"][0]["code"] == "unsupported_syntax"
    assert payload["analysis_errors"][0]["cell_index"] == 1

    foreign = tmp_path / "foreign.ipynb"
    foreign.write_text(notebook(cell("1 + 1"), language="julia"))
    result = invoke("check", str(foreign), "--format", "json")
    payload = json.loads(result.stdout)
    assert result.returncode == 2
    assert payload["analysis_errors"][0]["code"] == "unsupported_language"


def test_output_report_contains_partial_failure(tmp_path: Path, capsys) -> None:
    source = tmp_path / "bad.py"
    source.write_text("x = )")
    output = tmp_path / "nested" / "report.json"
    assert main(["check", str(source), "--format", "json", "--output", str(output)]) == 2
    assert capsys.readouterr().out == ""
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["analysis_errors"][0]["code"] == "syntax_error"


def test_html_cli_output_threshold_disable_and_notebook_safety(tmp_path: Path, capsys) -> None:
    source = tmp_path / "risk.py"
    source.write_text("dangerous_call()\n", encoding="utf-8")
    output = tmp_path / "nested" / "report.html"
    rules = registry(FixtureRule())

    assert (
        main(["check", str(source), "--format", "html", "--output", str(output)], registry=rules)
        == 0
    )
    assert capsys.readouterr().out == ""
    rendered = output.read_text(encoding="utf-8")
    assert "FIX001" in rendered and "dangerous_call" in rendered
    assert "Risk explanation" in rendered and "Suggested action" in rendered

    assert (
        main(
            [
                "check",
                str(source),
                "--format",
                "html",
                "--output",
                str(output),
                "--fail-on",
                "warning",
            ],
            registry=rules,
        )
        == 1
    )
    assert "FIX001" in output.read_text(encoding="utf-8")
    capsys.readouterr()

    disabled = registry(FixtureRule())
    assert (
        main(
            ["check", str(source), "--format", "html", "--disable-rule", "FIX001"],
            registry=disabled,
        )
        == 0
    )
    empty_html = capsys.readouterr().out
    assert "Findings (0)" in empty_html
    assert "FIX001" not in empty_html

    marker = tmp_path / "executed"
    book = tmp_path / "book.ipynb"
    book.write_text(
        notebook(
            cell("# ordinary Python"),
            cell(
                "source_call()",
                outputs=[{"data": {"text/html": f"<script>open('{marker}','w')</script>"}}],
            ),
        ),
        encoding="utf-8",
    )
    notebook_output = tmp_path / "book.html"
    assert (
        main(
            ["check", str(book), "--format", "html", "--output", str(notebook_output)],
            registry=registry(FixtureRule()),
        )
        == 0
    )
    notebook_html = notebook_output.read_text(encoding="utf-8")
    assert "source_call" in notebook_html
    assert "<script>open(" not in notebook_html
    assert not marker.exists()


def test_html_cli_invalid_output_path_reports_error(tmp_path: Path, capsys) -> None:
    source = tmp_path / "code.py"
    source.write_text("x = 1", encoding="utf-8")
    assert (
        main(
            ["check", str(source), "--format", "html", "--output", str(tmp_path)],
            registry=registry(),
        )
        == 2
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "cannot write report" in captured.err


def test_html_stdout_is_a_complete_document_without_status_text(tmp_path: Path, capsys) -> None:
    source = tmp_path / "plain.py"
    source.write_text("value = 1\n", encoding="utf-8")

    assert main(["check", str(source), "--format", "html"], registry=registry()) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.startswith("<!doctype html>")
    assert captured.out.rstrip().endswith("</html>")
    assert "StatGuard Analysis Report" in captured.out


def test_console_handles_unicode_path(tmp_path: Path) -> None:
    target = tmp_path / "分析.py"
    target.write_text("x = 1", encoding="utf-8")
    result = invoke("check", str(target))
    assert result.returncode == 0
    assert "Scanned 1 files" in result.stdout

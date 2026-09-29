"""SARIF output remains deterministic, located, and safe for untrusted inputs."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from statguard.analyzer import AnalysisError, AnalysisErrorCode, AnalysisErrorStage
from statguard.cli import main
from statguard.context import AnalysisContext
from statguard.core import Confidence, Evidence, Finding, Rule, RuleRegistry, Severity
from statguard.reporters import RuleMetadata, render_sarif
from statguard.scanner import ScanNotice, ScanReport


def make_finding(path: str, *, line: int = 4, column: int | None = 7) -> Finding:
    return Finding(
        "CUSTOM001",
        path,
        line,
        column,
        "Potential issue",
        "This is a possible risk.",
        "Review the analysis.",
        Evidence.POTENTIAL_STATISTICAL_RISK,
        severity=Severity.WARNING,
        confidence=Confidence.MEDIUM,
    )


def sarif(report: ScanReport, **kwargs: object) -> dict[str, object]:
    return json.loads(render_sarif(report, **kwargs))


def unit(findings: tuple[Finding, ...]) -> SimpleNamespace:
    return SimpleNamespace(findings=findings, errors=(), notices=())


def test_sarif_schema_metadata_severity_and_python_region(tmp_path: Path) -> None:
    # A manually supplied report keeps this formatter test independent of rule execution.
    result = sarif(
        ScanReport(
            (unit((make_finding(str(tmp_path / "src" / "model.py")),)),),
        ),
        base_path=tmp_path,
        rule_metadata={
            "CUSTOM001": RuleMetadata("Custom check", "An explicit custom description.", "warning")
        },
    )
    assert result["$schema"].endswith("sarif-schema-2.1.0.json")
    assert result["version"] == "2.1.0"
    run = result["runs"][0]
    assert run["tool"]["driver"]["name"] == "StatGuard"
    assert run["tool"]["driver"]["rules"][0]["id"] == "CUSTOM001"
    assert run["tool"]["driver"]["rules"][0]["name"] == "Custom check"
    finding = run["results"][0]
    assert finding["level"] == "warning"
    physical = finding["locations"][0]["physicalLocation"]
    assert physical["artifactLocation"]["uri"] == "src/model.py"
    assert physical["region"] == {"startLine": 4, "startColumn": 7}
    assert finding["properties"]["statguardConfidence"] == "medium"
    assert finding["properties"]["statguardEvidence"] == "potential statistical risk"
    assert "statguardFingerprint/v1" in finding["partialFingerprints"]
    assert run["invocations"][0]["executionSuccessful"] is True


@pytest.mark.parametrize(
    ("severity", "level"),
    [(Severity.ERROR, "error"), (Severity.WARNING, "warning"), (Severity.INFO, "note")],
)
def test_severity_mapping(severity: Severity, level: str) -> None:
    finding = make_finding("sample.py")
    finding = Finding(
        finding.rule_id,
        finding.path,
        finding.line,
        finding.column,
        finding.message,
        finding.risk,
        finding.recommendation,
        finding.evidence,
        severity=severity,
        confidence=finding.confidence,
    )
    result = sarif(ScanReport((unit((finding,)),)), base_path=Path.cwd())
    assert result["runs"][0]["results"][0]["level"] == level


def test_notebook_cell_location_is_properties_only() -> None:
    finding = Finding(
        "CUSTOM001",
        "notebooks/analysis.ipynb",
        12,
        5,
        "Notebook issue",
        "Potential risk",
        "Review it",
        Evidence.POTENTIAL_STATISTICAL_RISK,
        cell=3,
        cell_index=5,
    )
    result = sarif(ScanReport((unit((finding,)),)), base_path=Path.cwd())
    item = result["runs"][0]["results"][0]
    assert item["locations"][0]["physicalLocation"] == {
        "artifactLocation": {"uri": "notebooks/analysis.ipynb"}
    }
    assert item["properties"]["statguardCell"] == 3
    assert item["properties"]["statguardCellIndex"] == 5
    assert item["properties"]["statguardCellLine"] == 12
    assert item["properties"]["statguardCellColumn"] == 5


def test_missing_column_is_not_fabricated() -> None:
    result = sarif(
        ScanReport((unit((make_finding("source.py", line=8, column=None),)),)),
        base_path=Path.cwd(),
    )
    region = result["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]
    assert region == {"startLine": 8}


def test_relative_windows_path_is_normalized() -> None:
    result = sarif(
        ScanReport((unit((make_finding(r"D:\repo\src\file.py"),)),)),
        base_path=r"D:\repo",
    )
    uri = result["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
    assert uri["artifactLocation"]["uri"] == "src/file.py"


def test_outside_path_uses_file_uri_without_machine_path_in_workspace_case() -> None:
    result = sarif(
        ScanReport((unit((make_finding("../outside.py"),)),)),
        base_path=Path("/workspace/repo"),
    )
    uri = result["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
    assert uri["artifactLocation"]["uri"].startswith("file:")
    fingerprint = result["runs"][0]["results"][0]["partialFingerprints"]["statguardFingerprint/v1"]
    assert (
        fingerprint
        == sarif(
            ScanReport((unit((make_finding(r"C:\different-machine\outside.py"),)),)),
            base_path=r"C:\workspace\repo",
        )["runs"][0]["results"][0]["partialFingerprints"]["statguardFingerprint/v1"]
    )


def test_deterministic_output_and_fingerprint() -> None:
    report = ScanReport((unit((make_finding("src/a.py"),)),))
    first = render_sarif(report, base_path=Path("/repo"))
    second = render_sarif(report, base_path=Path("/repo"))
    assert first == second
    assert first.endswith("\n")
    assert "startTimeUtc" not in first
    assert "source" not in first


def test_analysis_errors_and_notices_are_notifications_not_results(tmp_path: Path) -> None:
    error = AnalysisError(
        AnalysisErrorStage.RULE,
        AnalysisErrorCode.RULE_EXECUTION,
        str(tmp_path / "broken.py"),
        "Rule execution raised with untrusted detail",
        rule_id="CUSTOM001",
    )
    report = ScanReport(
        (),
        scan_errors=(error,),
        scan_notices=(ScanNotice("no_supported_files", str(tmp_path), "No Python files found"),),
    )
    invocation = sarif(report, base_path=tmp_path)["runs"][0]["invocations"][0]
    assert invocation["executionSuccessful"] is False
    notices = invocation["toolExecutionNotifications"]
    assert [item["level"] for item in notices] == ["error", "note"]
    assert "untrusted detail" not in notices[0]["message"]["text"]
    assert sarif(report, base_path=tmp_path)["runs"][0]["results"] == []


class CallRule(Rule[AnalysisContext]):
    rule_id = "CUSTOM001"
    name = "Custom call check"
    description = "Fixture rule for SARIF CLI coverage."

    def check(self, context: AnalysisContext):
        for call in context.calls:
            yield Finding(
                self.rule_id,
                context.path,
                call.location.line,
                call.location.column,
                "Fixture diagnostic",
                "Fixture risk",
                "Fixture suggestion",
                Evidence.CONFIRMED_CODE_PATTERN,
            )


def test_cli_sarif_custom_metadata_output_and_threshold(tmp_path: Path, capsys) -> None:
    source = tmp_path / "risk.py"
    source.write_text("inspect_me()\n", encoding="utf-8")
    output = tmp_path / "report.sarif"
    registry: RuleRegistry[AnalysisContext] = RuleRegistry()
    registry.register(CallRule())
    status = main(
        [
            "check",
            str(source),
            "--format",
            "sarif",
            "--output",
            str(output),
            "--fail-on",
            "warning",
        ],
        registry=registry,
    )
    assert status == 1
    assert capsys.readouterr().out == ""
    report = json.loads(output.read_text(encoding="utf-8"))
    finding = report["runs"][0]["results"][0]
    assert finding["ruleId"] == "CUSTOM001"
    assert report["runs"][0]["tool"]["driver"]["rules"][0]["name"] == "Custom call check"
    assert finding["locations"][0]["physicalLocation"]["region"] == {
        "startLine": 1,
        "startColumn": 1,
    }


def test_cli_sarif_stdout_and_output_before_warning_exit(tmp_path: Path, capsys) -> None:
    source = tmp_path / "risk.py"
    source.write_text(
        "from sklearn.preprocessing import StandardScaler\n"
        "from sklearn.model_selection import train_test_split\n"
        "scaler = StandardScaler()\n"
        "X_scaled = scaler.fit_transform(X)\n"
        "X_train, X_test = train_test_split(X_scaled)\n",
        encoding="utf-8",
    )
    output = tmp_path / "result.sarif"
    status = main(
        ["check", str(source), "--format", "sarif", "--output", str(output), "--fail-on", "warning"]
    )
    assert status == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["runs"][0]["results"][0]["ruleId"] == "ML001"

    stdout_status = main(["check", str(source), "--format", "sarif"])
    captured = capsys.readouterr()
    assert stdout_status == 0
    assert json.loads(captured.out)["version"] == "2.1.0"
    assert captured.err == ""


def test_cli_sarif_rule_can_be_disabled_independently(tmp_path: Path, capsys) -> None:
    source = tmp_path / "risk.py"
    source.write_text(
        "from sklearn.preprocessing import StandardScaler\n"
        "from sklearn.model_selection import train_test_split\n"
        "scaled = StandardScaler().fit_transform(X)\n"
        "train_test_split(scaled)\n",
        encoding="utf-8",
    )
    assert main(["check", str(source), "--format", "sarif", "--disable-rule", "ML001"]) == 0
    payload = json.loads(capsys.readouterr().out)
    rule_ids = {item["ruleId"] for item in payload["runs"][0]["results"]}
    assert "ML001" not in rule_ids
    assert "ML006" in rule_ids


def test_cli_sarif_notebook_finding_keeps_cell_location(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    book = tmp_path / "analysis.ipynb"
    book.write_text(
        json.dumps(
            {
                "nbformat": 4,
                "nbformat_minor": 5,
                "metadata": {"language_info": {"name": "python"}},
                "cells": [
                    {"cell_type": "markdown", "metadata": {}, "source": "# note"},
                    {
                        "cell_type": "code",
                        "metadata": {},
                        "source": "\ninspect_me()\n",
                        "outputs": [],
                        "execution_count": None,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    registry: RuleRegistry[AnalysisContext] = RuleRegistry()
    registry.register(CallRule())
    assert main(["check", str(book), "--format", "sarif"], registry=registry) == 0
    item = json.loads(capsys.readouterr().out)["runs"][0]["results"][0]
    assert item["locations"][0]["physicalLocation"] == {"artifactLocation": {"uri": book.name}}
    assert item["properties"]["statguardCell"] == 1
    assert item["properties"]["statguardCellIndex"] == 2
    assert item["properties"]["statguardCellLine"] == 2


def test_cli_parse_error_is_notification_and_sets_unsuccessful(tmp_path: Path, capsys) -> None:
    broken = tmp_path / "broken.py"
    broken.write_text("if :\n", encoding="utf-8")
    assert main(["check", str(broken), "--format", "sarif"]) == 2
    payload = json.loads(capsys.readouterr().out)
    invocation = payload["runs"][0]["invocations"][0]
    assert invocation["executionSuccessful"] is False
    assert invocation["toolExecutionNotifications"][0]["level"] == "error"
    assert payload["runs"][0]["results"] == []


def test_cli_sarif_does_not_execute_python_or_notebook_outputs(tmp_path: Path, capsys) -> None:
    marker = tmp_path / "executed"
    source = tmp_path / "unsafe.py"
    source.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n", encoding="utf-8"
    )
    assert main(["check", str(source), "--format", "sarif"]) == 0
    capsys.readouterr()
    notebook = tmp_path / "safe.ipynb"
    notebook.write_text(
        json.dumps(
            {
                "nbformat": 4,
                "nbformat_minor": 5,
                "metadata": {"language_info": {"name": "python"}},
                "cells": [
                    {
                        "cell_type": "code",
                        "metadata": {},
                        "source": "value = 1",
                        "execution_count": None,
                        "outputs": [{"output_type": "stream", "text": f"touch {marker}"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert main(["check", str(notebook), "--format", "sarif"]) == 0
    capsys.readouterr()
    assert not marker.exists()


def test_cli_sarif_output_cannot_replace_scanned_source(tmp_path: Path, capsys) -> None:
    source = tmp_path / "source.py"
    source.write_text("pass\n", encoding="utf-8")
    assert main(["check", str(source), "--format", "sarif", "--output", str(source)]) == 2
    assert "must not overwrite" in capsys.readouterr().err
    assert source.read_text(encoding="utf-8") == "pass\n"

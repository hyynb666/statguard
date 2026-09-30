"""Bounded robustness checks for scans and large reporter result collections."""

from __future__ import annotations

import json
from pathlib import Path

from statguard.analyzer import AnalysisResult, Analyzer
from statguard.core import Confidence, Evidence, Finding, Severity
from statguard.reporters import render_html, render_json, render_sarif
from statguard.rules import default_registry
from statguard.scanner import Scanner, ScanReport


def _notebook(sources: list[str]) -> str:
    return json.dumps(
        {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {"language_info": {"name": "python"}},
            "cells": [
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": source,
                }
                for source in sources
            ],
        }
    )


def test_many_file_directory_scan_is_complete_stable_and_repeatable(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    for index in range(80):
        (project / f"module_{index:03d}.py").write_text(
            f"value_{index} = {index}\n", encoding="utf-8"
        )

    scanner = Scanner(Analyzer(default_registry()))
    first = scanner.scan(project)
    second = scanner.scan(project)
    assert first == second
    assert first.analysis_errors == ()
    assert len(first.results) == 80
    assert [Path(item.path).name for item in first.results] == [
        f"module_{index:03d}.py" for index in range(80)
    ]
    assert all(result.is_complete for result in first.results)
    assert render_json(first) == render_json(second)


def test_many_notebook_cells_are_analyzed_independently(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sources = [
        "from sklearn.model_selection import train_test_split\n"
        "from sklearn.preprocessing import StandardScaler\n"
        "scaled = StandardScaler().fit_transform(X)",
        "train, test = train_test_split(scaled, random_state=42)",
        *(f"cell_value_{index} = {index}" for index in range(48)),
    ]
    notebook_path = project / "many_cells.ipynb"
    notebook_path.write_text(_notebook(sources), encoding="utf-8")

    scanner = Scanner(Analyzer(default_registry()))
    first = scanner.scan(notebook_path)
    second = scanner.scan(notebook_path)
    assert first == second
    assert first.analysis_errors == ()
    assert len(first.results) == 1
    result = first.results[0]
    assert result.analyzed_units == result.completed_units == 50
    assert not [finding for finding in result.findings if finding.rule_id == "ML001"]
    assert {notice.code.value for notice in result.notices} == {"document_order"}


def test_reporters_render_a_large_finding_set_stably(tmp_path: Path) -> None:
    findings = tuple(
        Finding(
            rule_id="ML001",
            file_path="many.py",
            line=index,
            column=1,
            severity=Severity.WARNING,
            confidence=Confidence.MEDIUM,
            evidence=Evidence.POTENTIAL_STATISTICAL_RISK,
            message=f"Synthetic finding {index}",
            explanation="Synthetic report-size fixture.",
            suggestion="No action; generated test data.",
        )
        for index in range(1, 501)
    )
    report = ScanReport(
        (AnalysisResult("many.py", findings=findings),),
        enabled_rule_count=1,
    )

    json_first = render_json(report)
    json_second = render_json(report)
    assert json_first == json_second
    assert len(json.loads(json_first)["findings"]) == 500

    sarif_first = render_sarif(report, base_path=tmp_path)
    sarif_second = render_sarif(report, base_path=tmp_path)
    assert sarif_first == sarif_second
    assert len(json.loads(sarif_first)["runs"][0]["results"]) == 500

    html_first = render_html(report)
    html_second = render_html(report)
    assert html_first == html_second
    assert "Findings (500)" in html_first

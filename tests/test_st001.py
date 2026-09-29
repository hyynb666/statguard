"""ST001 positive, negative, boundary and CLI checks."""

import json
import subprocess
import sys

import pytest

from statguard.analyzer import Analyzer
from statguard.core import Evidence
from statguard.rules import default_registry


def code(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def notebook(cells: list[str], *, output: str = "ignored output") -> str:
    return json.dumps(
        {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {"language_info": {"name": "python"}},
            "cells": [
                {
                    "cell_type": "code",
                    "metadata": {},
                    "source": source,
                    "outputs": [{"output_type": "stream", "text": output}],
                }
                for source in cells
            ],
        }
    )


def analyze(source: str):
    result = Analyzer(default_registry()).analyze_source(source, path="analysis.py")
    assert not result.errors
    return tuple(finding for finding in result.findings if finding.rule_id == "ST001")


def risk(imports: str = "from scipy.stats import ttest_ind") -> str:
    return (
        imports
        + "\n"
        + code(
            "for column in columns:",
            "    statistic, p = ttest_ind(group_a[column], group_b[column])",
            "    if p < 0.05:",
            "        selected.append(column)",
        )
    )


@pytest.mark.parametrize(
    ("imports", "test_call", "comparison"),
    [
        ("from scipy.stats import ttest_ind", "ttest_ind(a, b)", "p < 0.05"),
        (
            "from scipy.stats import ttest_ind as test",
            "test(a, b)",
            "p <= 0.01",
        ),
        ("import scipy.stats as stats", "stats.mannwhitneyu(a, b)", "p < 0.1"),
        ("from scipy import stats", "stats.pearsonr(a, b)", "0.01 >= p"),
    ],
)
def test_import_sources_tuple_pvalue_and_literal_thresholds(imports, test_call, comparison):
    source = (
        imports
        + "\n"
        + code(
            "for feature in features:",
            f"    statistic, p = {test_call}",
            f"    if {comparison}:",
            "        selected.append(feature)",
        )
    )
    findings = analyze(source)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "ST001"
    assert finding.evidence is Evidence.POTENTIAL_STATISTICAL_RISK
    assert (finding.severity, finding.confidence) == ("warning", "medium")
    assert (finding.line, finding.column) == (4, 8)
    assert "may increase" in finding.explanation
    assert "does not establish" in finding.explanation
    assert "Consider whether" in finding.suggestion


def test_result_pvalue_and_callable_alias_are_followed():
    source = code(
        "import scipy.stats as stats",
        "test = stats.spearmanr",
        "for feature in features:",
        "    result = test(a[feature], b[feature])",
        "    if result.pvalue <= 0.01:",
        "        selected.append(feature)",
    )
    findings = analyze(source)
    assert len(findings) == 1
    assert findings[0].line == 5


def test_tuple_pvalue_alias_is_followed():
    source = code(
        "from scipy.stats import ttest_ind",
        "for feature in features:",
        "    statistic, p = ttest_ind(a[feature], b[feature])",
        "    observed = p",
        "    if observed < 0.05:",
        "        selected.append(feature)",
    )
    assert len(analyze(source)) == 1


def test_direct_result_pvalue_is_followed():
    source = code(
        "from scipy.stats import ttest_ind",
        "for feature in features:",
        "    p = ttest_ind(a[feature], b[feature]).pvalue",
        "    if p <= 0.05:",
        "        selected.append(feature)",
    )
    assert len(analyze(source)) == 1


@pytest.mark.parametrize(
    "test_name",
    [
        "ttest_ind",
        "ttest_rel",
        "ttest_1samp",
        "mannwhitneyu",
        "wilcoxon",
        "pearsonr",
        "spearmanr",
        "chi2_contingency",
        "f_oneway",
    ],
)
def test_all_whitelisted_scipy_tests_are_recognized(test_name):
    source = code(
        "import scipy.stats as stats",
        "for feature in features:",
        f"    result = stats.{test_name}(a, b)",
        "    if result.pvalue < 0.05:",
        "        selected.append(feature)",
    )
    assert len(analyze(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        code(
            "from scipy.stats import ttest_ind",
            "_, p = ttest_ind(a, b)",
            "if p < 0.05:",
            "    print(p)",
        ),
        code(
            "from scipy.stats import ttest_ind",
            "for column in columns:",
            "    statistic, _ = ttest_ind(a[column], b[column])",
        ),
        code(
            "from scipy.stats import ttest_ind",
            "for column in columns:",
            "    result = ttest_ind(a[column], b[column])",
            "    values.append(result.statistic)",
        ),
        code(
            "from scipy.stats import ttest_ind",
            "for column in columns:",
            "    _, p = ttest_ind(a[column], b[column])",
            "    if p < alpha:",
            "        selected.append(column)",
        ),
        code(
            "from scipy.stats import ttest_ind",
            "for column in columns:",
            "    p = wrapper(ttest_ind(a[column], b[column]))",
            "    if p < 0.05:",
            "        selected.append(column)",
        ),
        code(
            "from scipy.stats import ttest_ind",
            "while columns:",
            "    _, p = ttest_ind(a, b)",
            "    if p < 0.05:",
            "        selected.append(p)",
        ),
        code(
            "from scipy.stats import ttest_ind",
            "for column in columns:",
            "    _, p = ttest_ind(a[column], b[column])",
            "    if evaluate(p < 0.05):",
            "        selected.append(column)",
        ),
        code(
            "from scipy.stats import ttest_ind",
            "for column in columns:",
            "    _, p = ttest_ind(a[column], b[column])",
            "    if p < 0.05:",
            "        selected.append(column)",
            "        ttest_ind = custom_test",
        ),
        code(
            "from scipy.stats import ttest_ind",
            "for only in [1]:",
            "    _, p = ttest_ind(a, b)",
            "    if p < 0.05:",
            "        print(p)",
        ),
        code(
            "from scipy.stats import ttest_ind",
            "p1 = ttest_ind(a, b).pvalue",
            "p2 = ttest_ind(c, d).pvalue",
            "if p1 < 0.05:",
            "    print(p1)",
        ),
    ],
)
def test_single_unrelated_unknown_and_nonrepeating_patterns_abstain(source):
    assert analyze(source) == ()


def test_unknown_test_function_and_unrelated_p_values_do_not_match_names():
    source = code(
        "def ttest_ind(a, b):",
        "    return 0, 0.001",
        "for feature in features:",
        "    statistic, p = ttest_ind(a, b)",
        "    if p < 0.05:",
        "        print(feature)",
    )
    assert analyze(source) == ()


@pytest.mark.parametrize(
    "replacement",
    [
        "ttest_ind = custom_test",
        "ttest_ind = []",
        "stats = custom_module",
        "stats = []",
    ],
)
def test_import_rebinding_and_shadowing_abstain(replacement):
    imported = (
        "from scipy.stats import ttest_ind"
        if replacement.startswith("ttest")
        else "import scipy.stats as stats"
    )
    call = "ttest_ind(a, b)" if replacement.startswith("ttest") else "stats.ttest_ind(a, b)"
    source = (
        imported
        + "\n"
        + code(
            replacement,
            "for feature in features:",
            f"    _, p = {call}",
            "    if p < 0.05:",
            "        print(feature)",
        )
    )
    assert analyze(source) == ()


def test_rebinding_p_value_before_comparison_abstains():
    source = code(
        "from scipy.stats import ttest_ind",
        "for feature in features:",
        "    _, p = ttest_ind(a, b)",
        "    p = custom_value(feature)",
        "    if p < 0.05:",
        "        print(feature)",
    )
    assert analyze(source) == ()

    source = code(
        "from scipy.stats import ttest_ind",
        "for feature in features:",
        "    p = custom_function(feature)",
        "    if p < 0.05:",
        "        print(feature)",
    )
    assert analyze(source) == ()


def test_function_import_alias_is_supported_but_module_global_is_not_assumed():
    local_import = code(
        "def inspect(columns):",
        "    from scipy.stats import ttest_ind as test",
        "    for column in columns:",
        "        _, p = test(a[column], b[column])",
        "        if p < 0.05:",
        "            print(column)",
    )
    assert len(analyze(local_import)) == 1

    global_import = code(
        "from scipy.stats import ttest_ind",
        "def inspect(columns):",
        "    for column in columns:",
        "        _, p = ttest_ind(a[column], b[column])",
        "        if p < 0.05:",
        "            print(column)",
    )
    assert analyze(global_import) == ()


def test_explicit_multipletests_collection_is_safe_and_irrelevant_correction_does_not_suppress():
    corrected = code(
        "from scipy.stats import ttest_ind",
        "from statsmodels.stats.multitest import multipletests",
        "pvalues = []",
        "for feature in features:",
        "    _, p = ttest_ind(a[feature], b[feature])",
        "    pvalues.append(p)",
        "reject, adjusted, _, _ = multipletests(pvalues, method='fdr_bh')",
    )
    assert analyze(corrected) == ()

    unrelated = corrected.replace(
        "    pvalues.append(p)",
        "    pvalues.append(p)\n    if p < 0.05:\n        selected.append(feature)",
    ).replace("multipletests(pvalues", "multipletests(other_pvalues")
    findings = analyze(unrelated)
    assert len(findings) == 1


def test_multiple_loops_report_separately_and_stably():
    source = code(
        "from scipy.stats import ttest_ind",
        "for feature in features:",
        "    _, first = ttest_ind(a[feature], b[feature])",
        "    if first < 0.05:",
        "        print(feature)",
        "for feature in other_features:",
        "    _, second = ttest_ind(c[feature], d[feature])",
        "    if second <= 0.01:",
        "        print(feature)",
    )
    first = analyze(source)
    second = analyze(source)
    assert [finding.line for finding in first] == [4, 8]
    assert first == second


def test_notebook_cell_location_and_no_cross_cell_state_or_output_execution(tmp_path):
    marker = tmp_path / "executed"
    source = risk() + code(f"open({str(marker)!r}, 'w').close()")
    result = Analyzer(default_registry()).analyze_notebook_json(
        notebook([source], output=f"open({str(marker)!r}, 'w').close()"), path="book.ipynb"
    )
    finding = next(item for item in result.findings if item.rule_id == "ST001")
    assert (finding.cell_index, finding.cell, finding.line) == (1, 1, 4)
    assert not marker.exists()

    path = tmp_path / "book.ipynb"
    path.write_text(notebook([source]), encoding="utf-8")
    cli_result = subprocess.run(
        [sys.executable, "-m", "statguard", "check", str(path), "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert cli_result.returncode == 0
    cli_finding = json.loads(cli_result.stdout)["findings"][0]
    assert (cli_finding["rule_id"], cli_finding["cell_index"], cli_finding["line"]) == (
        "ST001",
        1,
        4,
    )
    assert not marker.exists()

    split_source = code(
        "from scipy.stats import ttest_ind",
        "for feature in features:",
        "    _, p = ttest_ind(a, b)",
        "    if p < 0.05:",
        "        print(feature)",
    )
    mixed_notebook = json.loads(notebook(["", split_source]))
    mixed_notebook["cells"][0]["cell_type"] = "markdown"
    mixed_notebook["cells"][0].pop("outputs")
    result = Analyzer(default_registry()).analyze_notebook_json(
        json.dumps(mixed_notebook), path="book.ipynb"
    )
    finding = next(item for item in result.findings if item.rule_id == "ST001")
    assert (finding.cell_index, finding.cell, finding.line) == (2, 1, 4)

    first_cell = "from scipy.stats import ttest_ind\n"
    second_cell = code(
        "for feature in features:",
        "    _, p = ttest_ind(a, b)",
        "    if p < 0.05:",
        "        print(feature)",
    )
    result = Analyzer(default_registry()).analyze_notebook_json(
        notebook([first_cell, second_cell]), path="book.ipynb"
    )
    assert not any(item.rule_id == "ST001" for item in result.findings)


def test_default_registration_disable_and_cli_console_json_html(tmp_path):
    assert "ST001" in {rule.rule_id for rule in default_registry().iter_enabled()}
    path = tmp_path / "risk.py"
    path.write_text(risk(), encoding="utf-8")
    safe_path = tmp_path / "safe.py"
    safe_path.write_text(
        code(
            "from scipy.stats import ttest_ind",
            "_, p = ttest_ind(a, b)",
            "if p < 0.05:",
            "    print(p)",
        ),
        encoding="utf-8",
    )

    def run(target, *args):
        return subprocess.run(
            [sys.executable, "-m", "statguard", "check", str(target), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    console = run(path)
    assert console.returncode == 0
    assert "ST001 warning" in console.stdout
    assert "unadjusted p-value thresholds" in console.stdout

    json_result = run(path, "--format", "json")
    assert json_result.returncode == 0 and json_result.stderr == ""
    finding = json.loads(json_result.stdout)["findings"][0]
    assert finding["rule_id"] == "ST001"
    assert finding["evidence"] == "potential statistical risk"

    html_result = run(path, "--format", "html")
    assert html_result.returncode == 0
    assert 'option value="ST001"' in html_result.stdout
    assert "ST001" in html_result.stdout and "potential statistical risk" in html_result.stdout
    assert finding["explanation"] in html_result.stdout
    assert finding["suggestion"] in html_result.stdout
    assert "script-src 'sha256-" in html_result.stdout

    assert run(path, "--fail-on", "warning").returncode == 1
    assert run(path, "--disable-rule", "ST001").returncode == 0
    assert "ST001" not in run(path, "--disable-rule", "ST001").stdout
    assert run(safe_path).returncode == 0

    combined_path = tmp_path / "combined.py"
    combined_path.write_text(
        code(
            "from scipy.stats import ttest_ind",
            "from sklearn.preprocessing import StandardScaler",
            "from sklearn.model_selection import train_test_split",
            "scaled = StandardScaler().fit_transform(X)",
            "train, test = train_test_split(scaled)",
            "for feature in features:",
            "    _, p = ttest_ind(a[feature], b[feature])",
            "    if p < 0.05:",
            "        print(feature)",
        ),
        encoding="utf-8",
    )
    combined_findings = json.loads(run(combined_path, "--format", "json").stdout)["findings"]
    assert {item["rule_id"] for item in combined_findings} == {"ML001", "ST001"}
    assert {
        item["rule_id"]
        for item in json.loads(
            run(combined_path, "--format", "json", "--disable-rule", "ST001").stdout
        )["findings"]
    } == {"ML001"}
    assert {
        item["rule_id"]
        for item in json.loads(
            run(combined_path, "--format", "json", "--disable-rule", "ML001").stdout
        )["findings"]
    } == {"ST001"}


def test_analysis_source_is_never_executed(tmp_path):
    marker = tmp_path / "source_executed"
    path = tmp_path / "analysis.py"
    path.write_text(risk() + code(f"open({str(marker)!r}, 'w').close()"), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "statguard", "check", str(path), "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0
    assert len(json.loads(result.stdout)["findings"]) == 1
    assert not marker.exists()

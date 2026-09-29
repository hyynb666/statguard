"""ST002 positive, negative, boundary, reporting, and safety coverage."""

import json
import subprocess
import sys

import pytest

from statguard.analyzer import Analyzer
from statguard.core import Evidence
from statguard.rules import ST002, default_registry


def code(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def notebook(cells: list[dict[str, object]]) -> str:
    return json.dumps(
        {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {"language_info": {"name": "python"}},
            "cells": cells,
        }
    )


def analyze(source: str):
    result = Analyzer(default_registry()).analyze_source(source, path="analysis.py")
    assert not result.errors
    return tuple(item for item in result.findings if item.rule_id == "ST002")


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
def test_supported_scipy_test_as_bare_expression_is_reported(test_name):
    findings = analyze(f"import scipy.stats as stats\nstats.{test_name}(a, b)\n")
    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "ST002"
    assert finding.evidence is Evidence.CONFIRMED_CODE_PATTERN
    assert (finding.severity, finding.confidence) == ("info", "high")
    assert (finding.line, finding.column) == (2, 1)
    assert "may go uninspected" in finding.explanation
    assert "when it is relevant" in finding.suggestion


@pytest.mark.parametrize(
    ("imports", "call"),
    [
        ("from scipy.stats import ttest_ind", "ttest_ind(a, b)"),
        ("import scipy.stats as stats", "stats.ttest_ind(a, b)"),
        ("from scipy import stats", "stats.ttest_ind(a, b)"),
        (
            "from scipy.stats import ttest_ind as test\ntest_alias = test",
            "test_alias(a, b)",
        ),
    ],
)
def test_import_forms_and_resolved_aliases_are_supported(imports, call):
    findings = analyze(f"{imports}\n{call}\n")
    assert len(findings) == 1
    assert findings[0].line == len(imports.splitlines()) + 1


def test_whole_result_assigned_to_underscore_is_reported_as_deliberate_discard():
    (finding,) = analyze("from scipy.stats import mannwhitneyu\n_ = mannwhitneyu(a, b)\n")
    assert (finding.line, finding.column) == (2, 5)
    assert "explicitly assigned to `_`" in finding.explanation
    assert "deliberate discard" in finding.explanation
    assert "may be intentional" in finding.explanation
    assert "If the test output is relevant" in finding.suggestion


def test_distinct_underscore_discards_produce_distinct_stable_findings():
    source = code(
        "from scipy.stats import ttest_ind, mannwhitneyu",
        "_ = ttest_ind(a, b)",
        "_ = mannwhitneyu(c, d)",
    )
    first = analyze(source)
    second = analyze(source)
    assert [item.line for item in first] == [2, 3]
    assert first == second


@pytest.mark.parametrize(
    "statement",
    [
        "result = ttest_ind(a, b)",
        "stat, p = ttest_ind(a, b)",
        "_, p = ttest_ind(a, b)",
        "stat, _ = ttest_ind(a, b)",
        "return ttest_ind(a, b)",
        "yield ttest_ind(a, b)",
        "print(ttest_ind(a, b))",
        "logger.info(ttest_ind(a, b))",
        "consume(ttest_ind(a, b))",
        "p = ttest_ind(a, b).pvalue",
        "value = ttest_ind(a, b)[1]",
        "if ttest_ind(a, b).pvalue < 0.05:\n    pass",
        "x = ttest_ind(a, b).statistic + 1",
        "assert ttest_ind(a, b).pvalue > 0",
    ],
)
def test_consumed_or_partially_discarded_results_do_not_trigger(statement):
    source = f"from scipy.stats import ttest_ind\n{statement}\n"
    assert analyze(source) == ()


def test_custom_same_name_and_foreign_import_do_not_trigger():
    custom = code(
        "def ttest_ind(a, b):",
        "    return None",
        "ttest_ind(a, b)",
    )
    foreign = "from mylib import ttest_ind\nttest_ind(a, b)\n"
    assert analyze(custom) == ()
    assert analyze(foreign) == ()


def test_function_shadowing_and_module_global_import_abstain():
    shadowed = code(
        "from scipy.stats import ttest_ind",
        "def inspect():",
        "    def ttest_ind(a, b):",
        "        return None",
        "    ttest_ind(x, y)",
    )
    global_import = code(
        "from scipy.stats import ttest_ind",
        "def inspect():",
        "    ttest_ind(x, y)",
    )
    local_import = code(
        "def inspect():",
        "    from scipy.stats import ttest_ind as test",
        "    test(x, y)",
    )
    assert analyze(shadowed) == ()
    # The current resolver intentionally does not assume a module global is the
    # runtime binding inside a deferred function body.
    assert analyze(global_import) == ()
    local_findings = analyze(local_import)
    assert len(local_findings) == 1
    assert local_findings[0].line == 3


def test_alias_rebinding_uses_the_call_site_binding():
    source = code(
        "from scipy.stats import ttest_ind",
        "test = ttest_ind",
        "test(a, b)",
        "test = custom_function",
        "test(c, d)",
    )
    findings = analyze(source)
    assert len(findings) == 1
    assert findings[0].line == 3


def test_unknown_wrapper_and_unknown_function_call_do_not_trigger():
    source = code(
        "from scipy.stats import ttest_ind",
        "wrapped = make_test(ttest_ind)",
        "wrapped(a, b)",
        "custom_test(c, d)",
    )
    assert analyze(source) == ()


def test_multiple_calls_in_one_statement_are_not_misidentified():
    source = "from scipy.stats import ttest_ind\nconsume(ttest_ind(a, b), ttest_ind(c, d))\n"
    assert analyze(source) == ()


def test_notebook_location_consumed_result_and_cross_cell_isolation(tmp_path):
    safe_output = "Path('output_executed').touch()"
    document = notebook(
        [
            {"cell_type": "markdown", "metadata": {}, "source": "intro"},
            {
                "cell_type": "code",
                "metadata": {},
                "execution_count": 1,
                "source": "from scipy.stats import ttest_ind\nttest_ind(a, b)\n",
                "outputs": [{"output_type": "stream", "text": safe_output}],
            },
        ]
    )
    result = Analyzer(default_registry()).analyze_notebook_json(document, path="book.ipynb")
    finding = next(item for item in result.findings if item.rule_id == "ST002")
    assert (finding.cell_index, finding.cell, finding.line, finding.column) == (2, 1, 2, 1)
    assert not (tmp_path / "output_executed").exists()

    consumed = notebook(
        [
            {
                "cell_type": "code",
                "metadata": {},
                "execution_count": None,
                "source": "from scipy.stats import ttest_ind\nresult = ttest_ind(a, b)\n",
                "outputs": [{"output_type": "stream", "text": safe_output}],
            }
        ]
    )
    safe_result = Analyzer(default_registry()).analyze_notebook_json(consumed)
    assert not any(item.rule_id == "ST002" for item in safe_result.findings)

    split_import = "from scipy.stats import ttest_ind\n"
    call_cell = "ttest_ind(a, b)\n"
    cross_cell = notebook(
        [
            {"cell_type": "code", "metadata": {}, "source": split_import, "outputs": []},
            {"cell_type": "code", "metadata": {}, "source": call_cell, "outputs": []},
        ]
    )
    isolated = Analyzer(default_registry()).analyze_notebook_json(cross_cell)
    assert not any(item.rule_id == "ST002" for item in isolated.findings)


def test_cli_console_json_html_disable_and_severity_thresholds(tmp_path):
    path = tmp_path / "discarded.py"
    path.write_text("from scipy.stats import ttest_ind\nttest_ind(a, b)\n", encoding="utf-8")

    def run(*args: str):
        return subprocess.run(
            [sys.executable, "-m", "statguard", "check", str(path), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    console = run()
    assert console.returncode == 0
    assert "ST002 info" in console.stdout
    assert "Discarded statistical test result." in console.stdout

    json_result = run("--format", "json")
    assert json_result.returncode == 0
    assert json_result.stderr == ""
    finding = json.loads(json_result.stdout)["findings"][0]
    assert finding["rule_id"] == "ST002"
    assert finding["evidence"] == "confirmed code pattern"
    assert finding["severity"] == "info"
    assert "may go uninspected" in finding["explanation"]
    assert "when it is relevant" in finding["suggestion"]

    html = run("--format", "html")
    assert html.returncode == 0
    assert '<option value="ST002">ST002</option>' in html.stdout
    assert "Discarded statistical test result." in html.stdout
    assert "script-src 'sha256-" in html.stdout

    assert run("--fail-on", "warning").returncode == 0
    assert run("--disable-rule", "ST002").returncode == 0
    assert "ST002" not in run("--disable-rule", "ST002").stdout


def test_st001_and_ml_rules_coexist_with_deterministic_finding_order():
    source = code(
        "from scipy.stats import ttest_ind",
        "from sklearn.model_selection import train_test_split",
        "from sklearn.preprocessing import StandardScaler",
        "scaled = StandardScaler().fit_transform(X)",
        "train, test = train_test_split(scaled)",
        "ttest_ind(a, b)",
        "for feature in features:",
        "    _, p = ttest_ind(a[feature], b[feature])",
        "    if p < 0.05:",
        "        pass",
    )
    first = Analyzer(default_registry()).analyze_source(source, path="analysis.py")
    second = Analyzer(default_registry()).analyze_source(source, path="analysis.py")
    first_ids = [item.rule_id for item in first.findings]
    assert first_ids == ["ML001", "ML006", "ST002", "ST001"]
    assert first.findings == second.findings
    assert first_ids.count("ST002") == 1
    assert "ST001" in first_ids


def test_default_registry_exports_and_independently_disables_st002():
    registry = default_registry()
    enabled = [rule.rule_id for rule in registry.iter_enabled()]
    assert enabled == [
        "ML001",
        "ML002",
        "ML003",
        "ML004",
        "ML005",
        "ML006",
        "ML009",
        "ST001",
        "ST002",
    ]
    assert len(enabled) == len(set(enabled))
    assert isinstance(registry.get("ST002"), ST002)
    registry.disable("ST002")
    assert "ST002" not in {rule.rule_id for rule in registry.iter_enabled()}


def test_python_and_notebook_scan_do_not_execute_source_or_outputs(tmp_path):
    marker = tmp_path / "should-not-exist"
    source = code(
        "from pathlib import Path",
        "from scipy.stats import ttest_ind",
        "ttest_ind(a, b)",
        f"Path({str(marker)!r}).write_text('executed')",
    )
    python_file = tmp_path / "analysis.py"
    python_file.write_text(source, encoding="utf-8")
    python_result = subprocess.run(
        [sys.executable, "-m", "statguard", "check", str(python_file), "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert python_result.returncode == 0
    assert any(item["rule_id"] == "ST002" for item in json.loads(python_result.stdout)["findings"])
    assert not marker.exists()

    notebook_file = tmp_path / "analysis.ipynb"
    notebook_file.write_text(
        notebook(
            [
                {
                    "cell_type": "code",
                    "metadata": {},
                    "execution_count": None,
                    "source": source,
                    "outputs": [
                        {"output_type": "stream", "text": f"Path({str(marker)!r}).touch()"}
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    notebook_result = subprocess.run(
        [sys.executable, "-m", "statguard", "check", str(notebook_file), "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert notebook_result.returncode == 0
    assert any(
        item["rule_id"] == "ST002" for item in json.loads(notebook_result.stdout)["findings"]
    )
    assert not marker.exists()

"""Positive, negative, boundary and integration tests for ML007."""

import json
import subprocess
import sys

import pytest

from statguard.analyzer import Analyzer
from statguard.core import Evidence
from statguard.parsers import NotebookParser
from statguard.rules import ML007, default_registry


def source(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def imports(api: str = "GridSearchCV", alias: str | None = None) -> str:
    local = f" as {alias}" if alias else ""
    return source(
        f"from sklearn.model_selection import {api}{local}, train_test_split",
        "from sklearn.linear_model import LogisticRegression",
    )


def positive(api: str = "GridSearchCV", fit: str = "search.fit(X_test, y_test)") -> str:
    return imports(api) + source(
        "X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)",
        f"search = {api}(LogisticRegression(), {'{}' if api == 'GridSearchCV' else '[]'})",
        fit,
    )


def findings(text: str):
    result = Analyzer(default_registry()).analyze_source(text, path="analysis.py")
    assert not result.errors
    return tuple(item for item in result.findings if item.rule_id == "ML007")


def test_grid_search_with_both_test_inputs_reports_one_located_finding():
    (finding,) = findings(positive())
    assert (finding.rule_id, finding.line, finding.column) == ("ML007", 5, 1)
    assert (finding.severity, finding.confidence) == ("warning", "medium")
    assert finding.evidence is Evidence.POTENTIAL_STATISTICAL_RISK
    assert "test features and test labels" in finding.explanation
    assert "analysis.py:3:" in finding.explanation
    assert "does not establish" in finding.explanation
    assert "training data for model selection" in finding.suggestion


@pytest.mark.parametrize("api", ["GridSearchCV", "RandomizedSearchCV"])
def test_both_supported_search_apis_are_recognized(api):
    assert len(findings(positive(api))) == 1


@pytest.mark.parametrize(
    ("fit", "expected"),
    [
        ("search.fit(X_test, y_train)", "test features"),
        ("search.fit(X_train, y_test)", "test labels"),
        ("search.fit(X=X_test, y=y_test)", "test features and test labels"),
        ("search.fit(X_test, y=y_test)", "test features and test labels"),
        ("search.fit(X_test, y_test, groups=groups)", "test features and test labels"),
    ],
)
def test_fit_input_forms_report_only_proven_test_inputs(fit, expected):
    (finding,) = findings(positive(fit=fit))
    assert expected in finding.explanation


def test_randomized_search_import_alias_and_module_alias_are_supported():
    aliased_import = source(
        (
            "from sklearn.model_selection import RandomizedSearchCV as Search, "
            "train_test_split as split"
        ),
        "X_train, X_test, y_train, y_test = split(X, y, random_state=42)",
        "search = Search(None, distributions)",
        "search.fit(X_test, y_test)",
    )
    module_alias = source(
        "import sklearn.model_selection as ms",
        "X_train, X_test, y_train, y_test = ms.train_test_split(X, y, random_state=42)",
        "search = ms.GridSearchCV(None, grid)",
        "search.fit(X_test, y_test)",
    )
    assert len(findings(aliased_import)) == len(findings(module_alias)) == 1


def test_from_sklearn_model_selection_and_constructor_alias_are_supported():
    text = source(
        "from sklearn import model_selection",
        "from sklearn.model_selection import train_test_split as split",
        "Search = model_selection.GridSearchCV",
        "X_train, X_test, y_train, y_test = split(X, y, random_state=42)",
        "search = Search(None, grid, refit=False)",
        "alias = search",
        "alias.fit(X_test, y_test)",
    )
    assert len(findings(text)) == 1


def test_direct_constructor_chaining_is_supported():
    text = imports() + source(
        "X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)",
        "GridSearchCV(LogisticRegression(), grid).fit(X_test, y_test)",
    )
    result = Analyzer(default_registry()).analyze_source(text, path="direct.py")
    assert [item.rule_id for item in result.findings] == ["ML007"]
    assert result.findings[0].line == 4


def test_supported_transform_alias_retains_test_role_for_search_fit():
    text = source(
        "from sklearn.model_selection import GridSearchCV, train_test_split",
        "from sklearn.preprocessing import StandardScaler",
        "X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)",
        "prepared = StandardScaler().transform(X_test)",
        "search = GridSearchCV(None, grid)",
        "search.fit(prepared, y_train)",
    )
    (finding,) = findings(text)
    assert finding.line == 6
    assert "test features" in finding.explanation
    assert "test labels" not in finding.explanation


def test_training_search_and_final_test_score_are_safe():
    text = imports() + source(
        "X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)",
        "search = GridSearchCV(LogisticRegression(), grid)",
        "search.fit(X_train, y_train)",
        "search.score(X_test, y_test)",
        "search.predict(X_test)",
    )
    assert findings(text) == ()


def test_search_construction_without_fit_is_not_a_finding():
    text = imports() + source("search = GridSearchCV(LogisticRegression(), grid)")
    assert findings(text) == ()


def test_pipeline_fit_is_outside_the_search_receiver_rule():
    text = source(
        "from sklearn.model_selection import GridSearchCV, train_test_split",
        "from sklearn.pipeline import Pipeline",
        "X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)",
        "pipeline = Pipeline([('search', GridSearchCV(None, grid))])",
        "pipeline.fit(X_test, y_test)",
    )
    assert findings(text) == ()


@pytest.mark.parametrize(
    "fit",
    [
        "search.fit(*args)",
        "search.fit(**kwargs)",
        "search.fit(X_test, X=X_train)",
        "search.fit(X_train, y_test, y=y_train)",
    ],
)
def test_ambiguous_fit_inputs_abstain(fit):
    assert findings(positive(fit=fit)) == ()


@pytest.mark.parametrize(
    "text",
    [
        source(
            "from sklearn.model_selection import train_test_split",
            "from sklearn.linear_model import LogisticRegression",
            "from sklearn.model_selection import RandomizedSearchCV",
            "X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)",
            "RandomizedSearchCV(LogisticRegression(), dist).fit(X_train, y_train)",
            "search.score(X_test, y_test)",
        ),
        imports()
        + source(
            "X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)",
            "test_data = X",
            "labels = y",
            "search = GridSearchCV(LogisticRegression(), grid)",
            "search.fit(test_data, labels)",
        ),
        imports()
        + source(
            "X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)",
            "search = GridSearchCV(LogisticRegression(), grid)",
            "search.fit(X_train, y_train)",
        ),
    ],
)
def test_training_lineage_and_misleading_names_do_not_report(text):
    assert findings(text) == ()


def test_fit_is_reported_when_either_test_features_or_labels_are_used():
    assert len(findings(positive(fit="search.fit(X_test, y_train)"))) == 1
    assert len(findings(positive(fit="search.fit(X_train, y_test)"))) == 1


def test_search_and_input_reassignment_use_point_of_use_bindings():
    safe_data_rebind = imports() + source(
        "X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)",
        "heldout = X_test",
        "heldout = X_train",
        "search = GridSearchCV(LogisticRegression(), grid)",
        "search.fit(heldout, y_train)",
    )
    unsafe_search_rebind = imports() + source(
        "X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)",
        "search = GridSearchCV(LogisticRegression(), grid)",
        "search = custom_search",
        "search.fit(X_test, y_test)",
    )
    assert findings(safe_data_rebind) == ()
    assert findings(unsafe_search_rebind) == ()


def test_import_shadowing_custom_search_and_factory_are_not_recognized():
    shadowed = source(
        "from sklearn.model_selection import GridSearchCV, train_test_split",
        "X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)",
        "GridSearchCV = custom_search",
        "search = GridSearchCV(None, grid)",
        "search.fit(X_test, y_test)",
    )
    custom_api = source(
        "from sklearn.model_selection import train_test_split",
        "def GridSearchCV(estimator, grid): return estimator",
        "X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)",
        "search = GridSearchCV(None, grid)",
        "search.fit(X_test, y_test)",
    )
    custom_class = source(
        "from sklearn.model_selection import GridSearchCV, train_test_split",
        "X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)",
        "class GridSearchCV:",
        "    def fit(self, X, y): pass",
        "search = GridSearchCV()",
        "search.fit(X_test, y_test)",
    )
    factory = imports() + source(
        "X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)",
        "search = make_search(GridSearchCV(LogisticRegression(), grid))",
        "search.fit(X_test, y_test)",
    )
    assert (
        findings(shadowed)
        == findings(custom_api)
        == findings(custom_class)
        == findings(factory)
        == ()
    )


def test_unresolved_escape_and_mutation_cause_abstention():
    text = imports() + source(
        "X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)",
        "search = GridSearchCV(LogisticRegression(), grid)",
        "mutate(search)",
        "search.fit(X_test, y_test)",
    )
    assert findings(text) == ()


def test_unknown_constructor_effects_and_control_flow_abstain():
    dynamic_grid = imports() + source(
        "X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)",
        "search = GridSearchCV(LogisticRegression(), make_grid())",
        "search.fit(X_test, y_test)",
    )
    branch = imports() + source(
        "if condition:",
        "    X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)",
        "    search = GridSearchCV(LogisticRegression(), grid)",
        "    search.fit(X_test, y_test)",
    )
    assert findings(dynamic_grid) == ()
    assert findings(branch) == ()


def test_distinct_splits_aliases_and_multiple_fits_keep_findings_distinct():
    text = imports() + source(
        "a_train, a_test, b_train, b_test = train_test_split(A, B, random_state=42)",
        "c_train, c_test, d_train, d_test = train_test_split(C, D, random_state=42)",
        "first = GridSearchCV(LogisticRegression(), grid)",
        "second = GridSearchCV(LogisticRegression(), grid)",
        "first.fit(a_test, b_test)",
        "second.fit(c_test, d_train)",
    )
    first = findings(text)
    second = findings(text)
    assert len(first) == 2
    assert first == second
    assert [item.line for item in first] == [7, 8]
    assert "features and test labels" in first[0].explanation
    assert "test features" in first[1].explanation
    assert "analysis.py:4:" in first[1].explanation


def test_same_function_scope_is_supported_but_cross_scope_is_not():
    local = source(
        "def tune(X, y):",
        "    from sklearn.model_selection import train_test_split, GridSearchCV",
        "    X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)",
        "    search = GridSearchCV(None, grid)",
        "    search.fit(X_test, y_test)",
    )
    cross_scope = imports() + source(
        "X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)",
        "def tune():",
        "    search = GridSearchCV(LogisticRegression(), grid)",
        "    search.fit(X_test, y_test)",
    )
    assert len(findings(local)) == 1
    assert findings(cross_scope) == ()


def test_notebook_same_cell_reports_location_but_cross_cell_does_not():
    same_cell = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"kernelspec": {"language": "python"}},
        "cells": [
            {
                "cell_type": "code",
                "metadata": {},
                "execution_count": None,
                "outputs": [],
                "source": positive(),
            }
        ],
    }
    result = Analyzer(default_registry()).analyze(
        NotebookParser().parse_json(json.dumps(same_cell), path="same.ipynb")
    )
    (finding,) = [item for item in result.findings if item.rule_id == "ML007"]
    assert (finding.cell_index, finding.cell, finding.line) == (1, 1, 5)

    imports_text = (
        imports() + "X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)\n"
    )
    fit_text = "search = GridSearchCV(LogisticRegression(), grid)\nsearch.fit(X_test, y_test)\n"
    cross_cell = {
        **same_cell,
        "cells": [same_cell["cells"][0], {**same_cell["cells"][0], "source": fit_text}],
    }
    cross_cell["cells"][0] = {**same_cell["cells"][0], "source": imports_text}
    other = Analyzer(default_registry()).analyze(
        NotebookParser().parse_json(json.dumps(cross_cell), path="cross.ipynb")
    )
    assert not any(item.rule_id == "ML007" for item in other.findings)


def test_cli_formats_disable_threshold_and_suppression(tmp_path):
    risky = tmp_path / "risk.py"
    risky.write_text(positive(), encoding="utf-8")
    common = [sys.executable, "-m", "statguard", "check", str(risky)]

    console = subprocess.run(common, capture_output=True, text=True, encoding="utf-8", check=False)
    assert console.returncode == 0
    assert "ML007" in console.stdout and "warning" in console.stdout
    assert "test features and test labels" in console.stdout

    json_run = subprocess.run(
        [*common, "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    payload = json.loads(json_run.stdout)
    (finding,) = [item for item in payload["findings"] if item["rule_id"] == "ML007"]
    assert (finding["severity"], finding["confidence"], finding["evidence"]) == (
        "warning",
        "medium",
        "potential statistical risk",
    )
    assert payload["schema_version"] == "1.0"

    for report_format, marker in (
        ("html", '<option value="ML007">ML007</option>'),
        ("sarif", '"ruleId": "ML007"'),
    ):
        rendered = subprocess.run(
            [*common, "--format", report_format],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert rendered.returncode == 0 and marker in rendered.stdout
        if report_format == "html":
            assert "content-security-policy" in rendered.stdout.lower()
        else:
            assert '"version": "2.1.0"' in rendered.stdout

    assert (
        subprocess.run(
            [*common, "--fail-on", "warning"], capture_output=True, check=False
        ).returncode
        == 1
    )
    disabled = subprocess.run(
        [*common, "--disable-rule", "ML007", "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert disabled.returncode == 0
    assert not any(item["rule_id"] == "ML007" for item in json.loads(disabled.stdout)["findings"])

    risky.write_text(
        positive(fit="search.fit(X_test, y_test)  # statguard: ignore ML007"), encoding="utf-8"
    )
    suppressed = subprocess.run(
        [*common, "--format", "json", "--fail-on", "warning"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert suppressed.returncode == 0
    assert not any(item["rule_id"] == "ML007" for item in json.loads(suppressed.stdout)["findings"])


def test_project_configuration_can_disable_ml007(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[tool.statguard]\ndisable-rules=["ML007"]\n', encoding="utf-8"
    )
    (project / "risk.py").write_text(positive(), encoding="utf-8")
    cli = subprocess.run(
        [sys.executable, "-m", "statguard", "check", str(project / "risk.py"), "--format", "json"],
        cwd=project,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert cli.returncode == 0
    assert not any(item["rule_id"] == "ML007" for item in json.loads(cli.stdout)["findings"])


def test_scan_does_not_execute_source_or_notebook_output(tmp_path):
    marker = tmp_path / "executed"
    py_source = positive().replace(
        "from sklearn.linear_model import LogisticRegression",
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed')\n"
        "from sklearn.linear_model import LogisticRegression",
    )
    assert len(findings(py_source)) == 1
    assert not marker.exists()

    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"kernelspec": {"language": "python"}},
        "cells": [
            {
                "cell_type": "code",
                "metadata": {},
                "execution_count": 1,
                "outputs": [{"output_type": "stream", "text": f"Path({str(marker)!r}).touch()"}],
                "source": py_source,
            }
        ],
    }
    result = Analyzer(default_registry()).analyze(
        NotebookParser().parse_json(json.dumps(notebook), path="safe.ipynb")
    )
    assert any(item.rule_id == "ML007" for item in result.findings)
    assert not marker.exists()


def test_rule_registration_is_unique_ordered_disableable_and_exported():
    registry = default_registry()
    rule_ids = [rule.rule_id for rule in registry.iter_enabled()]
    assert rule_ids == [
        "ML001",
        "ML002",
        "ML003",
        "ML004",
        "ML005",
        "ML006",
        "ML007",
        "ML009",
        "ST001",
        "ST002",
    ]
    assert len(rule_ids) == len(set(rule_ids))
    assert isinstance(ML007(), ML007)
    registry.disable("ML007")
    assert "ML007" not in {rule.rule_id for rule in registry.iter_enabled()}

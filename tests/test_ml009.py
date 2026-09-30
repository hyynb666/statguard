"""Positive, negative, boundary, CLI, Notebook, and safety tests for ML009."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from statguard.analyzer import Analyzer
from statguard.core import Evidence
from statguard.parsers import NotebookParser
from statguard.rules import default_registry


def source(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def analyze(code: str):
    result = Analyzer(default_registry()).analyze_source(code, path="analysis.py")
    assert not result.errors
    return tuple(finding for finding in result.findings if finding.rule_id == "ML009")


def base_imports(transformer: str = "StandardScaler") -> str:
    return source(
        f"from sklearn.preprocessing import {transformer}",
        "from sklearn.model_selection import cross_val_score",
    )


@pytest.mark.parametrize(
    ("module", "name", "options", "mechanism"),
    [
        ("sklearn.preprocessing", "StandardScaler", "", "StandardScaler"),
        ("sklearn.preprocessing", "MinMaxScaler", "", "MinMaxScaler"),
        ("sklearn.preprocessing", "RobustScaler", "", "RobustScaler"),
        ("sklearn.impute", "SimpleImputer", 'strategy="mean"', "column means"),
        ("sklearn.impute", "SimpleImputer", 'strategy="median"', "column medians"),
        ("sklearn.impute", "KNNImputer", "n_neighbors=5", "neighbor reference samples"),
        (
            "sklearn.impute",
            "IterativeImputer",
            "random_state=42",
            "iteratively fitted estimation models",
        ),
        (
            "sklearn.feature_selection",
            "SelectKBest",
            "score_func=f_classif, k=10",
            "supervised f_classif scores",
        ),
        (
            "sklearn.feature_selection",
            "SelectPercentile",
            "score_func=f_classif, percentile=20",
            "supervised f_classif scores",
        ),
        (
            "sklearn.feature_selection",
            "VarianceThreshold",
            "",
            "feature variances estimated from all fitting samples",
        ),
    ],
)
def test_supported_transformers_produce_component_specific_findings(
    module: str, name: str, options: str, mechanism: str
):
    if name == "IterativeImputer":
        imports = source("from sklearn.experimental import enable_iterative_imputer")
    else:
        imports = ""
    imports += source(
        f"from {module} import {name} as Transformer"
        + (", f_classif" if name in {"SelectKBest", "SelectPercentile"} else ""),
        "from sklearn.model_selection import cross_val_score",
    )
    target = ", y" if name in {"SelectKBest", "SelectPercentile"} else ""
    (finding,) = analyze(
        imports
        + source(
            f"transformer = Transformer({options})",
            f"prepared = transformer.fit_transform(X{target})",
            "scores = cross_val_score(model, prepared, y, cv=5)",
        )
    )
    assert finding.rule_id == "ML009"
    assert (finding.severity, finding.confidence) == ("warning", "medium")
    assert finding.evidence is Evidence.POTENTIAL_STATISTICAL_RISK
    fit_line = 5 if name == "IterativeImputer" else 4
    cv_line = fit_line + 1
    assert finding.line == fit_line
    assert f"cross_val_score at analysis.py:{cv_line}" in finding.explanation
    assert mechanism in finding.explanation
    assert "may" in finding.explanation
    assert "Consider" in finding.suggestion


@pytest.mark.parametrize(
    "imports",
    [
        source(
            "from sklearn.preprocessing import StandardScaler as Scale",
            "from sklearn.model_selection import cross_val_score as cv_score",
        ),
        source(
            "import sklearn.preprocessing as prep",
            "import sklearn.model_selection as ms",
        ),
        source(
            "from sklearn.preprocessing import StandardScaler as Scale",
            "from sklearn.model_selection import cross_validate as validate",
        ),
    ],
)
def test_import_aliases_and_supported_cv_apis(imports: str):
    if "import sklearn.preprocessing as prep" in imports:
        body = source(
            "scaler = prep.StandardScaler()",
            "prepared = scaler.fit_transform(X)",
            "scores = ms.cross_val_score(model, prepared, y, cv=5)",
        )
    elif "cross_validate as validate" in imports:
        body = source(
            "scaler = Scale()",
            "prepared = scaler.fit_transform(X)",
            "scores = validate(model, X=prepared, y=y, cv=5)",
        )
    else:
        body = source(
            "scaler = Scale()",
            "prepared = scaler.fit_transform(X)",
            "scores = cv_score(model, prepared, y, cv=5)",
        )
    assert len(analyze(imports + body)) == 1


def test_from_sklearn_import_model_selection_module_alias():
    findings = analyze(
        source(
            "from sklearn.preprocessing import StandardScaler",
            "from sklearn import model_selection as ms",
            "prepared = StandardScaler().fit_transform(X)",
            "ms.cross_val_score(model, prepared, y)",
        )
    )
    assert len(findings) == 1


def test_separate_fit_transform_reuses_fitted_transform_evidence():
    findings = analyze(
        source(
            "def run(X):",
            "    from sklearn.preprocessing import StandardScaler",
            "    from sklearn.model_selection import cross_val_score",
            "    scaler = StandardScaler()",
            "    scaler.fit(X)",
            "    prepared = scaler.transform(X)",
            "    scores = cross_val_score(model, prepared, y, cv=5)",
        )
    )
    assert len(findings) == 1
    assert findings[0].line == 5
    assert "cross_val_score" in findings[0].explanation
    assert "analysis.py:7" in findings[0].explanation


def test_separate_fit_transform_supports_alias_and_preserves_fit_location():
    (finding,) = analyze(
        source(
            "def run(X):",
            "    from sklearn.preprocessing import StandardScaler",
            "    from sklearn.model_selection import cross_val_score",
            "    scaler = StandardScaler()",
            "    scaler.fit(X)",
            "    prepared = scaler.transform(X)",
            "    alias = prepared",
            "    scores = cross_val_score(model, alias, y)",
        )
    )
    assert finding.line == 5
    assert "analysis.py:8" in finding.explanation


def test_keyword_X_and_multiple_cv_calls_produce_distinct_findings():
    findings = analyze(
        base_imports()
        + source(
            "prepared = StandardScaler().fit_transform(X)",
            "first = cross_val_score(model_a, X=prepared, y=y)",
            "second = cross_val_score(model_b, X=prepared, y=y)",
        )
    )
    assert len(findings) == 2
    assert ["analysis.py:4" in finding.explanation for finding in findings] == [True, False]
    assert ["analysis.py:5" in finding.explanation for finding in findings] == [False, True]
    assert findings == analyze(
        base_imports()
        + source(
            "prepared = StandardScaler().fit_transform(X)",
            "first = cross_val_score(model_a, X=prepared, y=y)",
            "second = cross_val_score(model_b, X=prepared, y=y)",
        )
    )


def test_rebinding_transformer_after_transform_keeps_historical_output_evidence():
    findings = analyze(
        base_imports()
        + source(
            "scaler = StandardScaler()",
            "prepared = scaler.fit_transform(X)",
            "scaler = other_scaler",
            "scores = cross_val_score(model, prepared, y)",
        )
    )
    assert len(findings) == 1
    assert findings[0].line == 4


def test_separate_fit_transform_reassignment_and_scope_barriers_abstain():
    snippets = [
        source(
            "def run(X):",
            "    from sklearn.preprocessing import StandardScaler",
            "    from sklearn.model_selection import cross_val_score",
            "    scaler = StandardScaler()",
            "    scaler.fit(X)",
            "    scaler.fit(other)",
            "    prepared = scaler.transform(X)",
            "    cross_val_score(model, prepared, y)",
        ),
        source(
            "def run(X):",
            "    from sklearn.preprocessing import StandardScaler",
            "    from sklearn.model_selection import cross_val_score",
            "    scaler = StandardScaler()",
            "    scaler.fit(X)",
            "    mutate(scaler)",
            "    prepared = scaler.transform(X)",
            "    cross_val_score(model, prepared, y)",
        ),
        source(
            "from sklearn.preprocessing import StandardScaler",
            "from sklearn.model_selection import cross_val_score",
            "prepared = StandardScaler().fit_transform(X)",
            "def run():",
            "    cross_val_score(model, prepared, y)",
        ),
    ]
    for snippet in snippets:
        assert analyze(snippet) == ()


def test_ambiguous_cross_validation_X_arguments_abstain():
    assert (
        analyze(
            base_imports()
            + source(
                "prepared = StandardScaler().fit_transform(X)",
                "cross_val_score(model, prepared, y, X=other)",
            )
        )
        == ()
    )
    assert (
        analyze(
            base_imports()
            + source(
                "prepared = StandardScaler().fit_transform(X)",
                "cross_val_score(X=prepared)",
            )
        )
        == ()
    )
    findings = analyze(
        base_imports()
        + source(
            "prepared = StandardScaler().fit_transform(X)",
            "cross_val_score(estimator=model, X=prepared, y=y)",
        )
    )
    assert len(findings) == 1


@pytest.mark.parametrize(
    "body",
    [
        source(
            "from sklearn.pipeline import Pipeline",
            "pipe = Pipeline([('scale', StandardScaler())])",
            "scores = cross_val_score(pipe, X, y)",
        ),
        source(
            "from sklearn.pipeline import make_pipeline",
            "pipe = make_pipeline(StandardScaler(), model)",
            "scores = cross_val_score(pipe, X, y)",
        ),
        source(
            "def cross_val_score(estimator, X, y):",
            "    return []",
            "prepared = StandardScaler().fit_transform(X)",
            "scores = cross_val_score(model, prepared, y)",
        ),
        source(
            "class StandardScaler:",
            "    def fit_transform(self, X):",
            "        return X",
            "prepared = StandardScaler().fit_transform(X)",
            "scores = cross_val_score(model, prepared, y)",
        ),
        source(
            "scaler = StandardScaler()",
            "prepared = scaler.transform(X)",
            "scores = cross_val_score(model, prepared, y)",
        ),
        source(
            "prepared = StandardScaler().fit_transform(X)",
            "scores = cross_val_score(model, unrelated, y)",
        ),
        source(
            "prepared = StandardScaler().fit_transform(X)",
            "prepared = unrelated",
            "scores = cross_val_score(model, prepared, y)",
        ),
        source(
            "prepared = StandardScaler().fit_transform(X)",
            "wrapped = custom_wrapper(prepared)",
            "scores = cross_val_score(model, wrapped, y)",
        ),
        source(
            "scores = cross_val_score(model, prepared, y)",
            "prepared = StandardScaler().fit_transform(X)",
        ),
        source(
            "from sklearn.preprocessing import PolynomialFeatures",
            "prepared = PolynomialFeatures().fit_transform(X)",
            "scores = cross_val_score(model, prepared, y)",
        ),
        source(
            "prepared = SimpleImputer(strategy='constant').fit_transform(X)",
            "scores = cross_val_score(model, prepared, y)",
        ),
        source(
            "prepared = IterativeImputer(max_iter=0, initial_strategy='constant').fit_transform(X)",
            "scores = cross_val_score(model, prepared, y)",
        ),
        source(
            "prepared = SelectKBest(k='all').fit_transform(X, y)",
            "scores = cross_val_score(model, prepared, y)",
        ),
        source(
            "from sklearn.preprocessing import StandardScaler as Scale",
            "def analyze():",
            "    prepared = Scale().fit_transform(X)",
            "    return cross_val_score(model, prepared, y)",
        ),
    ],
)
def test_unsupported_or_safe_patterns_abstain(body: str):
    imports = base_imports()
    assert analyze(imports + body) == ()


def test_imputer_and_selector_noop_semantics_match_existing_rules():
    assert (
        analyze(
            source(
                "from sklearn.impute import SimpleImputer",
                "from sklearn.model_selection import cross_val_score",
                "prepared = SimpleImputer(strategy='constant').fit_transform(X)",
                "cross_val_score(model, prepared, y)",
            )
        )
        == ()
    )
    assert (
        analyze(
            source(
                "from sklearn.feature_selection import SelectKBest",
                "from sklearn.model_selection import cross_val_score",
                "prepared = SelectKBest(k='all').fit_transform(X, y)",
                "cross_val_score(model, prepared, y)",
            )
        )
        == ()
    )
    assert (
        analyze(
            source(
                "from sklearn.experimental import enable_iterative_imputer",
                "from sklearn.impute import IterativeImputer",
                "from sklearn.model_selection import cross_val_score",
                "prepared = IterativeImputer(max_iter=0, initial_strategy='constant')."
                "fit_transform(X)",
                "cross_val_score(model, prepared, y)",
            )
        )
        == ()
    )


def test_ml001_and_ml009_can_report_independent_split_and_cv_risks():
    result = Analyzer(default_registry()).analyze_source(
        source(
            "from sklearn.preprocessing import StandardScaler",
            "from sklearn.model_selection import train_test_split, cross_val_score",
            "from scipy.stats import ttest_ind",
            "prepared = StandardScaler().fit_transform(X)",
            "train, test = train_test_split(prepared)",
            "scores = cross_val_score(model, prepared, y)",
            "for feature in features:",
            "    _, p = ttest_ind(a[feature], b[feature])",
            "    if p < 0.05:",
            "        pass",
        ),
        path="analysis.py",
    )
    assert {finding.rule_id for finding in result.findings} == {
        "ML001",
        "ML006",
        "ML009",
        "ST001",
    }
    assert [finding.rule_id for finding in result.findings] == [
        "ML001",
        "ML009",
        "ML006",
        "ST001",
    ]


def test_notebook_cell_location_and_cross_cell_isolation():
    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"kernelspec": {"language": "python"}},
        "cells": [
            {"cell_type": "markdown", "metadata": {}, "source": "intro"},
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "from sklearn.preprocessing import StandardScaler\n",
                    "from sklearn.model_selection import cross_val_score\n",
                    "prepared = StandardScaler().fit_transform(X)\n",
                    "scores = cross_val_score(model, prepared, y)\n",
                ],
            },
        ],
    }
    parsed = NotebookParser().parse_json(json.dumps(notebook), path="demo.ipynb")
    result = Analyzer(default_registry()).analyze(parsed)
    (finding,) = [item for item in result.findings if item.rule_id == "ML009"]
    assert (finding.cell_index, finding.line, finding.column) == (2, 3, 12)

    split_notebook = {
        **notebook,
        "cells": [
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": (
                    "from sklearn.preprocessing import StandardScaler\n"
                    "prepared = StandardScaler().fit_transform(X)\n"
                ),
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": (
                    "from sklearn.model_selection import cross_val_score\n"
                    "cross_val_score(model, prepared, y)\n"
                ),
            },
        ],
    }
    split_result = Analyzer(default_registry()).analyze(
        NotebookParser().parse_json(json.dumps(split_notebook), path="split.ipynb")
    )
    assert not any(item.rule_id == "ML009" for item in split_result.findings)


def test_cli_console_json_html_disable_and_fail_threshold(tmp_path: Path):
    target = tmp_path / "risk.py"
    target.write_text(
        base_imports()
        + source(
            "prepared = StandardScaler().fit_transform(X)",
            "scores = cross_val_score(model, prepared, y)",
        ),
        encoding="utf-8",
    )
    common = [sys.executable, "-m", "statguard", "check", str(target)]
    console = subprocess.run(common, capture_output=True, text=True, encoding="utf-8", check=False)
    assert console.returncode == 0
    assert "ML009" in console.stdout and "Potential preprocessing leakage" in console.stdout
    assert "potential statistical risk" in console.stdout

    json_result = subprocess.run(
        [*common, "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert json_result.returncode == 0
    report = json.loads(json_result.stdout)
    assert any(item["rule_id"] == "ML009" for item in report["findings"])

    html_result = subprocess.run(
        [*common, "--format", "html"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert html_result.returncode == 0
    assert "ML009" in html_result.stdout
    assert "potential statistical risk" in html_result.stdout
    assert '<option value="ML009">ML009</option>' in html_result.stdout
    assert 'class="finding-summary"' in html_result.stdout
    assert "content-security-policy" in html_result.stdout.lower()
    assert "https://" not in html_result.stdout

    failed = subprocess.run(
        [*common, "--fail-on", "warning"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert failed.returncode == 1

    disabled = subprocess.run(
        [*common, "--disable-rule", "ML009"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert disabled.returncode == 0
    assert "ML009" not in disabled.stdout


def test_scanning_python_and_notebook_never_executes_code_or_output(tmp_path: Path):
    marker = tmp_path / "executed"
    py_file = tmp_path / "side_effect.py"
    py_file.write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('ran')\n"
        "from sklearn.preprocessing import StandardScaler\n"
        "from sklearn.model_selection import cross_val_score\n"
        "prepared = StandardScaler().fit_transform(X)\n"
        "cross_val_score(model, prepared, y)\n",
        encoding="utf-8",
    )
    cli = [sys.executable, "-m", "statguard", "check", str(py_file)]
    result = subprocess.run(cli, capture_output=True, text=True, encoding="utf-8", check=False)
    assert "ML009" in result.stdout
    assert not marker.exists()

    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"kernelspec": {"language": "python"}},
        "cells": [
            {
                "cell_type": "code",
                "execution_count": 1,
                "metadata": {},
                "outputs": [{"output_type": "stream", "text": f"Path({str(marker)!r}).touch()"}],
                "source": (
                    "from pathlib import Path\n"
                    f"Path({str(marker)!r}).write_text('ran')\n"
                    "from sklearn.preprocessing import StandardScaler\n"
                    "from sklearn.model_selection import cross_val_score\n"
                    "prepared = StandardScaler().fit_transform(X)\n"
                    "cross_val_score(model, prepared, y)\n"
                ),
            }
        ],
    }
    ipynb = tmp_path / "side_effect.ipynb"
    ipynb.write_text(json.dumps(notebook), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "statguard", "check", str(ipynb)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert "ML009" in result.stdout
    assert not marker.exists()


def test_rule_is_default_registered_but_individually_selectable():
    registry = default_registry()
    registered_ids = [rule.rule_id for rule in registry.iter_enabled()]
    assert registered_ids == [
        "ML001",
        "ML002",
        "ML003",
        "ML004",
        "ML005",
        "ML006",
        "ML007",
        "ML008",
        "ML009",
        "ST001",
        "ST002",
    ]
    assert len(registered_ids) == len(set(registered_ids))
    assert "ML005" in registered_ids
    registry.disable("ML009")
    assert "ML009" not in {rule.rule_id for rule in registry.iter_enabled()}

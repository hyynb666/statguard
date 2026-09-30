"""Evidence, boundary, CLI, Notebook, and safety tests for ML008."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from statguard.analyzer import Analyzer
from statguard.core import Confidence, Evidence, Severity
from statguard.parsers import NotebookParser
from statguard.rules import ML008, default_registry


def code(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def analyze(source: str):
    result = Analyzer(default_registry()).analyze_source(source, path="analysis.py")
    assert not result.errors
    return tuple(finding for finding in result.findings if finding.rule_id == "ML008")


@pytest.mark.parametrize(
    ("module", "name", "options", "target", "mechanism"),
    [
        ("sklearn.preprocessing", "StandardScaler", "", "", "learned scaling parameters"),
        ("sklearn.preprocessing", "MinMaxScaler", "", "", "learned scaling parameters"),
        ("sklearn.preprocessing", "RobustScaler", "", "", "learned scaling parameters"),
        ("sklearn.impute", "SimpleImputer", 'strategy="mean"', "", "column means"),
        ("sklearn.impute", "KNNImputer", "n_neighbors=5", "", "neighbor reference samples"),
        (
            "sklearn.impute",
            "IterativeImputer",
            "random_state=42",
            "",
            "iteratively fitted estimation models",
        ),
        (
            "sklearn.feature_selection",
            "SelectKBest",
            "score_func=f_classif, k=5",
            ", y_train",
            "supervised f_classif scores",
        ),
        (
            "sklearn.feature_selection",
            "SelectPercentile",
            "score_func=f_classif, percentile=25",
            ", y_train",
            "supervised f_classif scores",
        ),
        (
            "sklearn.feature_selection",
            "VarianceThreshold",
            "threshold=0.0",
            "",
            "feature variances estimated from all fitting samples",
        ),
    ],
)
def test_supported_preprocessors_pair_same_split_roles(
    module: str, name: str, options: str, target: str, mechanism: str
):
    prefix = code(
        f"from {module} import {name} as Transformer"
        + (", f_classif" if name in {"SelectKBest", "SelectPercentile"} else ""),
        "from sklearn.model_selection import train_test_split as split",
    )
    if name == "IterativeImputer":
        prefix = code("from sklearn.experimental import enable_iterative_imputer") + prefix
    test_target = target.replace("_train", "_test")
    result = analyze(
        prefix
        + code(
            "X_train, X_test, y_train, y_test = split(X, y, random_state=42)",
            "train_transformer = Transformer(" + options + ")",
            "test_transformer = Transformer(" + options + ")",
            f"train_output = train_transformer.fit_transform(X_train{target})",
            f"test_output = test_transformer.fit_transform(X_test{test_target})",
        )
    )
    assert len(result) == 1
    finding = result[0]
    assert finding.rule_id == "ML008"
    assert (finding.severity, finding.confidence) == (Severity.WARNING, Confidence.MEDIUM)
    assert finding.evidence is Evidence.POTENTIAL_STATISTICAL_RISK
    assert mechanism in finding.explanation
    assert "same train_test_split" in finding.explanation
    assert "does not establish downstream use" in finding.explanation


def test_separate_instances_fit_transform_and_finding_evidence_locations():
    source = code(
        "from sklearn.model_selection import train_test_split",
        "from sklearn.preprocessing import StandardScaler",
        "X_train, X_test = train_test_split(X, random_state=42)",
        "train = StandardScaler().fit_transform(X_train)",
        "test = StandardScaler().fit_transform(X_test)",
    )
    (finding,) = analyze(source)
    assert finding.line == 5
    assert finding.column == 8
    assert "analysis.py:4:9" in finding.explanation
    assert "analysis.py:3:19" in finding.explanation
    assert "StandardScaler" in finding.explanation
    assert "held-out data" in finding.explanation


def test_same_instance_refit_on_test_is_reported_once():
    (finding,) = analyze(
        code(
            "from sklearn.model_selection import train_test_split",
            "from sklearn.preprocessing import StandardScaler",
            "X_train, X_test = train_test_split(X, random_state=42)",
            "scaler = StandardScaler()",
            "train = scaler.fit_transform(X_train)",
            "test = scaler.fit_transform(X_test)",
        )
    )
    assert finding.line == 6
    assert "analysis.py:5:" in finding.explanation


def test_proven_separate_fit_transform_pair_and_refit_same_instance():
    (finding,) = analyze(
        code(
            "from sklearn.model_selection import train_test_split",
            "from sklearn.preprocessing import StandardScaler",
            "X_train, X_test = train_test_split(X, random_state=42)",
            "scaler = StandardScaler()",
            "scaler.fit(X_train)",
            "train = scaler.transform(X_train)",
            "scaler.fit(X_test)",
            "test = scaler.transform(X_test)",
        )
    )
    assert finding.line == 7
    assert "analysis.py:5:1" in finding.explanation
    assert "analysis.py:3:19" in finding.explanation


def test_separate_instances_fit_transform_pair():
    findings = analyze(
        code(
            "from sklearn.model_selection import train_test_split",
            "from sklearn.preprocessing import StandardScaler",
            "X_train, X_test = train_test_split(X, random_state=42)",
            "train_scaler = StandardScaler()",
            "test_scaler = StandardScaler()",
            "train_scaler.fit(X_train)",
            "train = train_scaler.transform(X_train)",
            "test_scaler.fit(X_test)",
            "test = test_scaler.transform(X_test)",
        )
    )
    assert len(findings) == 1
    assert findings[0].line == 8


def test_mixed_direct_and_separated_application_forms_pair():
    findings = analyze(
        code(
            "from sklearn.model_selection import train_test_split",
            "from sklearn.preprocessing import StandardScaler",
            "X_train, X_test = train_test_split(X, random_state=42)",
            "train_scaler = StandardScaler()",
            "test_scaler = StandardScaler()",
            "train_scaler.fit(X_train)",
            "train = train_scaler.transform(X_train)",
            "test = test_scaler.fit_transform(X_test)",
        )
    )
    assert len(findings) == 1
    assert findings[0].line == 8


def test_aliases_are_resolved_and_reassignment_uses_point_of_use_binding():
    positive = code(
        "import sklearn.preprocessing as prep",
        "from sklearn.model_selection import train_test_split as split",
        "X_train, X_test = split(X, random_state=42)",
        "train_alias = X_train",
        "test_alias = X_test",
        "prep.StandardScaler().fit_transform(train_alias)",
        "prep.StandardScaler().fit_transform(test_alias)",
    )
    assert len(analyze(positive)) == 1

    reassigned = code(
        "from sklearn.preprocessing import StandardScaler",
        "from sklearn.model_selection import train_test_split",
        "X_train, X_test = train_test_split(X, random_state=42)",
        "value = X_test",
        "value = X_train",
        "StandardScaler().fit_transform(X_train)",
        "StandardScaler().fit_transform(value)",
    )
    assert analyze(reassigned) == ()


def test_module_import_alias_and_same_class_different_options_are_supported():
    findings = analyze(
        code(
            "import sklearn.preprocessing as prep",
            "from sklearn import model_selection as ms",
            "X_train, X_test = ms.train_test_split(X, random_state=42)",
            "prep.StandardScaler(with_mean=True).fit_transform(X_train)",
            "prep.StandardScaler(with_mean=False).fit_transform(X_test)",
        )
    )
    assert len(findings) == 1
    assert findings[0].line == 5


@pytest.mark.parametrize(
    "snippet",
    [
        code(
            "from sklearn.model_selection import train_test_split",
            "from sklearn.preprocessing import StandardScaler",
            "X_train, X_test = train_test_split(X, random_state=42)",
            "scaler = StandardScaler()",
            "train = scaler.fit_transform(X_train)",
            "test = scaler.transform(X_test)",
        ),
        code(
            "from sklearn.model_selection import train_test_split",
            "from sklearn.preprocessing import StandardScaler",
            "X_train, X_test = train_test_split(X, random_state=42)",
            "train = StandardScaler().fit_transform(X_train)",
            "test = StandardScaler().transform(X_test)",
        ),
        code(
            "from sklearn.model_selection import train_test_split",
            "from sklearn.preprocessing import StandardScaler",
            "X_train, X_test = train_test_split(X, random_state=42)",
            "StandardScaler().fit(X_train)",
            "StandardScaler().fit(X_test)",
        ),
        code(
            "from sklearn.preprocessing import StandardScaler",
            "from sklearn.model_selection import train_test_split",
            "X_train, X_test = train_test_split(X, random_state=42)",
            "StandardScaler().fit_transform(X_train)",
        ),
        code(
            "from sklearn.preprocessing import StandardScaler",
            "from sklearn.model_selection import train_test_split",
            "X_train, X_test = train_test_split(X, random_state=42)",
            "StandardScaler().fit_transform(X_test)",
        ),
    ],
)
def test_safe_single_fit_one_sided_or_bare_fit_patterns_abstain(snippet: str):
    assert analyze(snippet) == ()


def test_different_classes_and_unrelated_split_inputs_do_not_pair():
    different_classes = code(
        "from sklearn.model_selection import train_test_split",
        "from sklearn.preprocessing import StandardScaler, RobustScaler",
        "X_train, X_test = train_test_split(X, random_state=42)",
        "StandardScaler().fit_transform(X_train)",
        "RobustScaler().fit_transform(X_test)",
    )
    different_inputs = code(
        "from sklearn.model_selection import train_test_split",
        "from sklearn.preprocessing import StandardScaler",
        "X_train, y_test = train_test_split(X, y, random_state=42)",
        "StandardScaler().fit_transform(X_train)",
        "StandardScaler().fit_transform(y_test)",
    )
    assert analyze(different_classes) == ()
    assert analyze(different_inputs) == ()


def test_different_split_ids_do_not_cross_pair():
    assert (
        analyze(
            code(
                "from sklearn.model_selection import train_test_split",
                "from sklearn.preprocessing import StandardScaler",
                "A_train, A_test = train_test_split(A, random_state=1)",
                "B_train, B_test = train_test_split(B, random_state=2)",
                "StandardScaler().fit_transform(A_train)",
                "StandardScaler().fit_transform(B_test)",
            )
        )
        == ()
    )


def test_multiple_test_fits_produce_one_stable_finding_per_fit_site():
    snippet = code(
        "from sklearn.model_selection import train_test_split",
        "from sklearn.preprocessing import StandardScaler",
        "X_train, X_test = train_test_split(X, random_state=42)",
        "StandardScaler().fit_transform(X_train)",
        "StandardScaler().fit_transform(X_test)",
        "StandardScaler().fit_transform(X_test)",
    )
    findings = analyze(snippet)
    assert [finding.line for finding in findings] == [5, 6]
    assert findings == analyze(snippet)


@pytest.mark.parametrize(
    "transformer",
    [
        'SimpleImputer(strategy="constant", fill_value=0)',
        "SimpleImputer(strategy=dynamic_strategy)",
        "SelectKBest(score_func=custom_score, k=5)",
        "Pipeline([('scale', StandardScaler())])",
        "CustomTransformer()",
    ],
)
def test_unknown_or_unsupported_semantics_abstain(transformer: str):
    if transformer.startswith("SimpleImputer"):
        imp = "from sklearn.impute import SimpleImputer"
        left = transformer
    elif transformer.startswith("SelectKBest"):
        imp = "from sklearn.feature_selection import SelectKBest"
        left = transformer
    else:
        imp = "from sklearn.preprocessing import StandardScaler"
        left = transformer
    assert (
        analyze(
            code(
                "from sklearn.model_selection import train_test_split",
                imp,
                "from sklearn.pipeline import Pipeline",
                "X_train, X_test = train_test_split(X, random_state=42)",
                f"train = {left}.fit_transform(X_train)",
                f"test = {left}.fit_transform(X_test)",
            )
        )
        == ()
    )


def test_shadowing_and_custom_same_name_classes_do_not_match():
    snippets = [
        code(
            "from sklearn.preprocessing import StandardScaler",
            "from sklearn.model_selection import train_test_split",
            "X_train, X_test = train_test_split(X, random_state=42)",
            "StandardScaler = factory",
            "StandardScaler().fit_transform(X_train)",
            "StandardScaler().fit_transform(X_test)",
        ),
        code(
            "from sklearn.model_selection import train_test_split",
            "X_train, X_test = train_test_split(X, random_state=42)",
            "class StandardScaler:",
            "    def fit_transform(self, X): return X",
            "StandardScaler().fit_transform(X_train)",
            "StandardScaler().fit_transform(X_test)",
        ),
    ]
    assert all(analyze(snippet) == () for snippet in snippets)


def test_unknown_receiver_mutation_poisoning_abstains_for_direct_calls():
    assert (
        analyze(
            code(
                "from sklearn.model_selection import train_test_split",
                "from sklearn.preprocessing import StandardScaler",
                "X_train, X_test = train_test_split(X, random_state=42)",
                "scaler = StandardScaler()",
                "scaler.set_params(with_mean=False)",
                "scaler.fit_transform(X_train)",
                "scaler.fit_transform(X_test)",
            )
        )
        == ()
    )


def test_opaque_input_mutation_invalidates_separated_fit_transform_evidence():
    assert (
        analyze(
            code(
                "from sklearn.model_selection import train_test_split",
                "from sklearn.preprocessing import StandardScaler",
                "X_train, X_test = train_test_split(X, random_state=42)",
                "train_scaler = StandardScaler()",
                "test_scaler = StandardScaler()",
                "train_scaler.fit(X_train)",
                "train = train_scaler.transform(X_train)",
                "mutate(X_test)",
                "test_scaler.fit(X_test)",
                "test = test_scaler.transform(X_test)",
            )
        )
        == ()
    )


def test_function_scope_is_not_paired_with_module_scope():
    assert (
        analyze(
            code(
                "from sklearn.model_selection import train_test_split",
                "from sklearn.preprocessing import StandardScaler",
                "X_train, X_test = train_test_split(X, random_state=42)",
                "StandardScaler().fit_transform(X_train)",
                "def transform(X_test):",
                "    StandardScaler().fit_transform(X_test)",
            )
        )
        == ()
    )


def test_notebook_reports_same_cell_only_and_preserves_cell_location():
    document = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"kernelspec": {"language": "python"}},
        "cells": [
            {
                "cell_type": "code",
                "source": code(
                    "from sklearn.model_selection import train_test_split",
                    "from sklearn.preprocessing import StandardScaler",
                    "X_train, X_test = train_test_split(X, random_state=42)",
                    "StandardScaler().fit_transform(X_train)",
                    "StandardScaler().fit_transform(X_test)",
                ),
                "outputs": [{"data": {"text/html": "ignored"}}],
                "execution_count": 1,
                "metadata": {},
            },
            {
                "cell_type": "code",
                "source": code(
                    "from sklearn.preprocessing import StandardScaler",
                    "StandardScaler().fit_transform(X_test)",
                ),
                "outputs": [],
                "execution_count": None,
                "metadata": {},
            },
        ],
    }
    parsed = NotebookParser().parse_json(json.dumps(document), path="book.ipynb")
    result = Analyzer(default_registry()).analyze(parsed)
    findings = [item for item in result.findings if item.rule_id == "ML008"]
    assert len(findings) == 1
    assert findings[0].cell_index == 1
    assert findings[0].line == 5


def test_notebook_output_is_not_an_analysis_input():
    document = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"kernelspec": {"language": "python"}},
        "cells": [
            {
                "cell_type": "code",
                "source": "value = 1\n",
                "outputs": [{"data": {"text/plain": "fit_transform(X_test)"}}],
                "execution_count": 1,
                "metadata": {},
            },
        ],
    }
    result = Analyzer(default_registry()).analyze(
        NotebookParser().parse_json(json.dumps(document), path="outputs.ipynb")
    )
    assert not [finding for finding in result.findings if finding.rule_id == "ML008"]


def test_cli_console_json_html_sarif_notebook_disable_and_threshold(tmp_path: Path):
    source_path = tmp_path / "risk.py"
    source_path.write_text(
        code(
            "from sklearn.model_selection import train_test_split",
            "from sklearn.preprocessing import StandardScaler",
            "X_train, X_test = train_test_split(X, random_state=42)",
            "StandardScaler().fit_transform(X_train)",
            "StandardScaler().fit_transform(X_test)",
        ),
        encoding="utf-8",
    )
    command = [sys.executable, "-m", "statguard", "check", str(source_path), "--no-config"]
    console = subprocess.run(command, capture_output=True, text=True, check=False)
    assert console.returncode == 0
    assert "ML008 warning" in console.stdout
    assert "Potential separate preprocessing fits" in console.stdout
    assert (
        subprocess.run(
            [*command, "--fail-on", "warning"], capture_output=True, text=True, check=False
        ).returncode
        == 1
    )
    disabled = subprocess.run(
        [*command, "--disable-rule", "ML008"], capture_output=True, text=True, check=False
    )
    assert disabled.returncode == 0
    assert "ML008" not in disabled.stdout
    report = subprocess.run(
        [*command, "--format", "json"], capture_output=True, text=True, check=False
    )
    assert report.returncode == 0
    finding = next(
        item for item in json.loads(report.stdout)["findings"] if item["rule_id"] == "ML008"
    )
    assert finding["line"] == 5
    assert finding["evidence"] == "potential statistical risk"
    assert "train_test_split" in finding["explanation"]

    html = subprocess.run(
        [*command, "--format", "html"], capture_output=True, text=True, check=False
    )
    assert html.returncode == 0
    assert "ML008" in html.stdout
    assert "Potential separate preprocessing fits" in html.stdout
    sarif = subprocess.run(
        [*command, "--format", "sarif"], capture_output=True, text=True, check=False
    )
    assert sarif.returncode == 0
    assert "ML008" in json.loads(sarif.stdout)["runs"][0]["results"][0]["ruleId"]

    notebook_path = tmp_path / "risk.ipynb"
    notebook_path.write_text(
        json.dumps(
            {
                "nbformat": 4,
                "nbformat_minor": 5,
                "metadata": {"kernelspec": {"language": "python"}},
                "cells": [
                    {
                        "cell_type": "code",
                        "source": "\n".join(
                            [
                                "from sklearn.model_selection import train_test_split",
                                "from sklearn.preprocessing import StandardScaler",
                                "X_train, X_test = train_test_split(X, random_state=42)",
                                "StandardScaler().fit_transform(X_train)",
                                "StandardScaler().fit_transform(X_test)",
                            ]
                        ),
                        "outputs": [{"data": {"text/plain": "ignored"}}],
                        "execution_count": 1,
                        "metadata": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    notebook_report = subprocess.run(
        [
            sys.executable,
            "-m",
            "statguard",
            "check",
            str(notebook_path),
            "--format",
            "json",
            "--no-config",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert notebook_report.returncode == 0
    notebook_finding = next(
        item
        for item in json.loads(notebook_report.stdout)["findings"]
        if item["rule_id"] == "ML008"
    )
    assert notebook_finding["cell_index"] == 1
    assert notebook_finding["line"] == 5


def test_inline_suppression_and_project_config_disable_are_generic(tmp_path: Path):
    source_path = tmp_path / "suppressed.py"
    source_path.write_text(
        code(
            "from sklearn.model_selection import train_test_split",
            "from sklearn.preprocessing import StandardScaler",
            "X_train, X_test = train_test_split(X, random_state=42)",
            "StandardScaler().fit_transform(X_train)",
            "StandardScaler().fit_transform(X_test)  # statguard: ignore ML008",
        ),
        encoding="utf-8",
    )
    suppressed = subprocess.run(
        [sys.executable, "-m", "statguard", "check", str(source_path), "--no-config"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert suppressed.returncode == 0
    assert "ML008" not in suppressed.stdout

    source_path.write_text(
        source_path.read_text(encoding="utf-8").replace("  # statguard: ignore ML008", ""),
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        '[tool.statguard]\ndisable-rules = ["ML008"]\n', encoding="utf-8"
    )
    configured = subprocess.run(
        [sys.executable, "-m", "statguard", "check", str(source_path), "--format", "json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert configured.returncode == 0
    assert not [
        item for item in json.loads(configured.stdout)["findings"] if item["rule_id"] == "ML008"
    ]


def test_scanning_source_with_side_effect_does_not_execute_it(tmp_path: Path):
    marker = tmp_path / "executed.txt"
    source_path = tmp_path / "side_effect.py"
    source_path.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "statguard", "check", str(source_path), "--no-config"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert not marker.exists()


def test_default_registry_exports_and_enables_ml008():
    assert ML008.rule_id == "ML008"
    registry = default_registry()
    assert "ML008" in {rule.rule_id for rule in registry.iter_enabled()}
    assert len(tuple(registry.iter_enabled())) == 11

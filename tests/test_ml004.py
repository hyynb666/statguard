"""ML004 positive, negative, boundary and CLI integration fixtures."""

import json
import subprocess
import sys

import pytest

from statguard.analyzer import Analyzer
from statguard.context import AnalysisContext
from statguard.core import Evidence
from statguard.parsers import PythonSourceParser
from statguard.rules import ML004, default_registry


def code(*lines: str) -> str:
    return chr(10).join(lines) + chr(10)


SPLIT = code("from sklearn.model_selection import train_test_split as split")


MODELS = {
    "LogisticRegression": "sklearn.linear_model",
    "LinearRegression": "sklearn.linear_model",
    "RandomForestClassifier": "sklearn.ensemble",
    "RandomForestRegressor": "sklearn.ensemble",
}


def imports(model="LogisticRegression", alias="Model"):
    return code(f"from {MODELS[model]} import {model} as {alias}") + SPLIT


def fit_source(model="LogisticRegression", alias="Model", X="X_test", y="y_test"):
    return imports(model, alias) + code(
        "X_train, X_test, y_train, y_test = split(X, y)",
        f"estimator = {alias}()",
        f"estimator.fit({X}, {y})",
    )


def analyze(source: str):
    result = Analyzer(default_registry()).analyze_source(source, path="analysis.py")
    assert not result.errors
    return tuple(f for f in result.findings if f.rule_id == "ML004")


@pytest.mark.parametrize("model", list(MODELS))
def test_supported_sklearn_estimators_detect_test_features_and_labels(model):
    findings = analyze(fit_source(model))
    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "ML004"
    assert (finding.line, finding.column) == (5, 1)
    assert (finding.severity, finding.confidence) == ("warning", "medium")
    assert finding.evidence is Evidence.POTENTIAL_STATISTICAL_RISK
    assert "test features and test labels" in finding.explanation
    assert "analysis.py:3:" in finding.explanation
    assert "does not establish actual overfitting" in finding.explanation
    assert "training data only" in finding.suggestion


def test_test_features_only_and_test_labels_only_are_distinguished():
    features = analyze(fit_source(X="X_test", y="y_train"))
    labels = analyze(fit_source(X="X_train", y="y_test"))
    assert len(features) == len(labels) == 1
    assert "test features" in features[0].explanation
    assert "test labels" not in features[0].explanation
    assert "test labels" in labels[0].explanation
    assert "test features" not in labels[0].explanation


def test_fit_with_both_test_inputs_emits_one_finding():
    assert len(analyze(fit_source())) == 1


def test_inline_estimator_constructor_fit_is_traced_to_the_same_split():
    source = imports() + code(
        "a, b, c, d = split(X, y)",
        "Model().fit(b, d)",
    )
    findings = analyze(source)
    assert len(findings) == 1
    assert findings[0].line == 4


def test_model_alias_and_data_aliases_retain_binding_provenance():
    source = imports("RandomForestClassifier", "RFC") + code(
        "X_train, X_test, y_train, y_test = split(X, y)",
        "features = X_test",
        "labels = y_test",
        "model = RFC()",
        "estimator = model",
        "estimator.fit(X=features, y=labels)",
    )
    finding = analyze(source)[0]
    assert finding.line == 8
    assert "test features and test labels" in finding.explanation


def test_module_alias_resolves_estimator_and_constructor_alias():
    source = code(
        "from sklearn import linear_model as lm",
        "from sklearn.model_selection import train_test_split as split",
        "Estimator = lm.LogisticRegression",
        "train_x, test_x, train_y, test_y = split(X, y)",
        "model = Estimator()",
        "model.fit(test_x, train_y)",
    )
    findings = analyze(source)
    assert len(findings) == 1
    assert "test features" in findings[0].explanation
    assert "test labels" not in findings[0].explanation


def test_train_only_fit_and_test_predict_score_do_not_report():
    source = imports() + code(
        "X_train, X_test, y_train, y_test = split(X, y)",
        "model = Model()",
        "model.fit(X_train, y_train)",
        "model.predict(X_test)",
        "model.predict_proba(X_test)",
        "model.decision_function(X_test)",
        "model.score(X_test, y_test)",
        "model.transform(X_test)",
        "model.partial_fit(X_test, y_test)",
    )
    assert analyze(source) == ()


def test_unresolved_same_name_split_does_not_create_test_roles():
    source = code(
        "from sklearn.linear_model import LogisticRegression",
        "def train_test_split(X, y): return X, X, y, y",
        "X_train, X_test, y_train, y_test = train_test_split(X, y)",
        "model = LogisticRegression()",
        "model.fit(X_test, y_test)",
    )
    assert analyze(source) == ()


def test_second_fit_on_test_data_is_the_only_finding():
    source = imports() + code(
        "X_train, X_test, y_train, y_test = split(X, y)",
        "model = Model()",
        "model.fit(X_train, y_train)",
        "model.fit(X_test, y_test)",
    )
    findings = analyze(source)
    assert len(findings) == 1
    assert findings[0].line == 6


def test_test_features_with_train_labels_are_still_reported_as_features_only():
    finding = analyze(fit_source(X="X_test", y="y_train"))[0]
    assert "test features" in finding.explanation
    assert "test labels" not in finding.explanation


def test_training_features_with_test_labels_are_reported_as_label_input():
    finding = analyze(fit_source(X="X_train", y="y_test"))[0]
    assert "receives test labels" in finding.explanation


def test_misleading_names_and_unknown_full_data_have_no_test_role():
    source = imports() + code(
        "X_test = X",
        "y_test = y",
        "model = Model()",
        "model.fit(X_test, y_test)",
        "other = X",
        "model.fit(other, labels)",
    )
    assert analyze(source) == ()


def test_unknown_wrapper_transform_does_not_inherit_test_role():
    source = imports() + code(
        "X_train, X_test, y_train, y_test = split(X, y)",
        "transformed = custom_transform(X_test)",
        "model = Model()",
        "model.fit(transformed, y_train)",
    )
    assert analyze(source) == ()


@pytest.mark.parametrize(
    "source",
    [
        code(
            "from sklearn.model_selection import train_test_split as split",
            "class LogisticRegression:",
            "    def fit(self, X, y): pass",
            "a, b, c, d = split(X, y)",
            "model = LogisticRegression()",
            "model.fit(b, d)",
        ),
        code(
            "from sklearn.model_selection import train_test_split as split",
            "from custom import LogisticRegression as Model",
            "a, b, c, d = split(X, y)",
            "model = Model()",
            "model.fit(b, d)",
        ),
        code(
            "from sklearn.model_selection import train_test_split as split",
            "class Model:",
            "    def fit(self, X, y): pass",
            "a, b, c, d = split(X, y)",
            "model = Model()",
            "model.fit(b, d)",
        ),
    ],
)
def test_custom_same_name_model_or_method_does_not_report(source):
    assert analyze(source) == ()


def test_rebinding_model_or_test_alias_respects_binding_version():
    source = imports() + code(
        "a, b, c, d = split(X, y)",
        "test_alias = b",
        "test_alias = other",
        "model = Model()",
        "model.fit(test_alias, c)",
    )
    assert analyze(source) == ()
    saved_version = imports() + code(
        "a, b, c, d = split(X, y)",
        "test_alias = b",
        "model = Model()",
        "model.fit(test_alias, c)",
        "test_alias = other",
    )
    assert len(analyze(saved_version)) == 1


def test_model_rebinding_and_independent_instances_keep_identity_separate():
    rebound = imports() + code(
        "a, b, c, d = split(X, y)",
        "model = Model()",
        "model = make_custom_model()",
        "model.fit(b, d)",
    )
    assert analyze(rebound) == ()

    separate = imports() + code(
        "a, b, c, d = split(X, y)",
        "train_model = Model()",
        "test_model = Model()",
        "train_model.fit(a, c)",
        "test_model.fit(b, d)",
    )
    findings = analyze(separate)
    assert len(findings) == 1
    assert findings[0].line == 7


def test_independent_splits_keep_roles_and_locations_separate():
    source = imports() + code(
        "a_train, a_test, ay_train, ay_test = split(A, ay)",
        "b_train, b_test, by_train, by_test = split(B, by)",
        "model = Model()",
        "model.fit(a_test, by_test)",
    )
    finding = analyze(source)[0]
    assert "analysis.py:3:" in finding.explanation
    assert "analysis.py:4:" in finding.explanation
    assert "test features and test labels" in finding.explanation


def test_multiple_fits_produce_separate_stable_findings():
    source = imports() + code(
        "a, b, c, d = split(X, y)",
        "model = Model()",
        "model.fit(b, c)",
        "model.fit(a, d)",
        "model.fit(b, d)",
    )
    findings = analyze(source)
    assert [finding.line for finding in findings] == [5, 6, 7]
    context = AnalysisContext(PythonSourceParser().parse_source(source))
    rule = ML004()
    assert rule.check(context) == rule.check(context)


def test_ml004_coexists_with_ml001_and_each_rule_disables_independently():
    source = code(
        "from sklearn.preprocessing import StandardScaler",
        "from sklearn.model_selection import train_test_split",
        "from sklearn.linear_model import LogisticRegression",
        "scaled = StandardScaler().fit_transform(X)",
        "X_train, X_test, y_train, y_test = train_test_split(scaled, y)",
        "model = LogisticRegression()",
        "model.fit(X_test, y_test)",
    )
    result = Analyzer(default_registry()).analyze_source(source)
    assert [finding.rule_id for finding in result.findings] == ["ML001", "ML004"]

    registry = default_registry()
    registry.disable("ML004")
    assert [f.rule_id for f in Analyzer(registry).analyze_source(source).findings] == ["ML001"]

    registry = default_registry()
    registry.disable("ML001")
    assert [f.rule_id for f in Analyzer(registry).analyze_source(source).findings] == ["ML004"]


def test_known_supported_transform_preserves_test_role():
    source = code(
        "from sklearn.model_selection import train_test_split",
        "from sklearn.preprocessing import StandardScaler",
        "from sklearn.linear_model import LogisticRegression",
        "X_train, X_test, y_train, y_test = train_test_split(X, y)",
        "scaler = StandardScaler()",
        "X_test_scaled = scaler.transform(X_test)",
        "model = LogisticRegression()",
        "model.fit(X_test_scaled, y_train)",
    )
    finding = analyze(source)[0]
    assert finding.line == 8
    assert "test features" in finding.explanation


@pytest.mark.parametrize(
    "body",
    [
        code("if flag:", "    model.fit(X_test, y_test)"),
        code("for batch in batches:", "    model.fit(X_test, y_test)"),
        code("model.fit(*values)"),
        code("model.fit(**kwargs)"),
        code("model.fit(X_test, y_test, extra)"),
        code("model.fit(X=X_test, y=y_test, **kwargs)"),
    ],
)
def test_control_flow_and_unsupported_fit_signatures_abstain(body):
    prefix = imports() + code(
        "X_train, X_test, y_train, y_test = split(X, y)",
        "model = Model()",
    )
    assert analyze(prefix + body) == ()


def test_model_mutation_or_unknown_call_before_fit_abstains():
    cases = [
        code("model.set_params(C=5)", "model.fit(X_test, y_test)"),
        code("alter(model)", "model.fit(X_test, y_test)"),
        code("model.fit = custom_fit", "model.fit(X_test, y_test)"),
    ]
    for body in cases:
        source = (
            imports()
            + code(
                "X_train, X_test, y_train, y_test = split(X, y)",
                "model = Model()",
            )
            + body
        )
        assert analyze(source) == ()


def test_fit_alias_mutation_invalidates_model_identity():
    source = imports() + code(
        "a, b, c, d = split(X, y)",
        "model = Model()",
        "alias = model",
        "alias.set_params(C=5)",
        "model.fit(b, d)",
    )
    assert analyze(source) == ()


def test_dynamic_mutation_through_receiver_alias_abstains():
    cases = [
        code(
            "alias = model",
            "alias.fit = custom_fit",
            "model.fit(b, d)",
        ),
        code(
            "model.__dict__.update({'fit': custom_fit})",
            "model.fit(b, d)",
        ),
    ]
    for body in cases:
        source = (
            imports()
            + code(
                "a, b, c, d = split(X, y)",
                "model = Model()",
            )
            + body
        )
        assert analyze(source) == ()


def test_pipeline_and_partial_fit_are_not_inferred_as_direct_estimator_fit():
    source = code(
        "from sklearn.model_selection import train_test_split",
        "from sklearn.pipeline import Pipeline",
        "from sklearn.preprocessing import StandardScaler",
        "from sklearn.linear_model import LogisticRegression",
        "X_train, X_test, y_train, y_test = train_test_split(X, y)",
        "pipeline = Pipeline([('scale', StandardScaler()), ('model', LogisticRegression())])",
        "pipeline.fit(X_test, y_test)",
        "model = LogisticRegression()",
        "model.partial_fit(X_test, y_test)",
    )
    assert analyze(source) == ()


def test_local_imports_work_but_module_imports_in_functions_remain_unknown():
    local = code(
        "def run(X, y):",
        "    from sklearn.model_selection import train_test_split",
        "    from sklearn.linear_model import LogisticRegression",
        "    a,b,c,d=train_test_split(X,y)",
        "    model=LogisticRegression()",
        "    model.fit(b,d)",
    )
    assert len(analyze(local)) == 1
    global_import = imports() + code(
        "def run(X,y):",
        "    a,b,c,d=split(X,y)",
        "    model=Model()",
        "    model.fit(b,d)",
    )
    assert analyze(global_import) == ()


def notebook(source: str, *, outputs=None):
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
                    "outputs": outputs or [],
                    "execution_count": None,
                }
            ],
        }
    )


def test_notebook_location_and_cross_cell_isolation():
    analyzer = Analyzer(default_registry())
    source = imports() + code(
        "X_train, X_test, y_train, y_test = split(X, y)",
        "model = Model()",
        "model.fit(X_test, y_test)",
    )
    result = analyzer.analyze_notebook_json(
        notebook(source.splitlines(keepends=True)), path="book.ipynb"
    )
    findings = [finding for finding in result.findings if finding.rule_id == "ML004"]
    assert len(findings) == 1
    assert (findings[0].cell_index, findings[0].cell, findings[0].line) == (1, 1, 5)

    first = imports() + code("a,b,c,d=split(X,y)")
    second = code(
        "from sklearn.linear_model import LogisticRegression",
        "m=LogisticRegression()",
        "m.fit(b,d)",
    )
    result = analyzer.analyze_notebook_json(
        json.dumps(
            {
                "nbformat": 4,
                "nbformat_minor": 5,
                "metadata": {"language_info": {"name": "python"}},
                "cells": [
                    {"cell_type": "code", "metadata": {}, "source": first, "outputs": []},
                    {"cell_type": "code", "metadata": {}, "source": second, "outputs": []},
                ],
            }
        ),
        path="book.ipynb",
    )
    assert not [finding for finding in result.findings if finding.rule_id == "ML004"]


@pytest.mark.parametrize(
    ("args", "code_expected", "count"),
    [
        ([], 0, 1),
        (["--fail-on", "warning"], 1, 1),
        (["--disable-rule", "ML004"], 0, 0),
    ],
)
def test_cli_json_and_warning_thresholds(tmp_path, args, code_expected, count):
    path = tmp_path / "risk.py"
    path.write_text(fit_source(), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "statguard", "check", str(path), "--format", "json", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == code_expected
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert len(report["findings"]) == count
    if count:
        finding = report["findings"][0]
        assert finding["rule_id"] == "ML004"
        assert finding["severity"] == "warning"
        assert finding["confidence"] == "medium"
        assert finding["file_path"] == str(path)
        assert finding["line"] == 5
        assert finding["evidence"] == "potential statistical risk"
        assert finding["explanation"]
        assert finding["suggestion"]


def test_cli_console_and_no_python_or_notebook_output_execution(tmp_path):
    py_marker = tmp_path / "python-executed"
    output_marker = tmp_path / "notebook-output-executed"
    source = fit_source() + code(f"open({str(py_marker)!r}, 'w').close()")
    py_path = tmp_path / "risk.py"
    py_path.write_text(source, encoding="utf-8")
    console = subprocess.run(
        [sys.executable, "-m", "statguard", "check", str(py_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert console.returncode == 0
    assert (
        f"{py_path}:5:1: ML004 warning: Potential test data leakage during model fitting."
        in console.stdout
    )
    assert "test features and test labels" in console.stdout

    notebook_source = fit_source()
    out = [
        {
            "output_type": "stream",
            "name": "stdout",
            "text": f"open({str(output_marker)!r}, 'w').close()",
        }
    ]
    nb_path = tmp_path / "risk.ipynb"
    nb_path.write_text(notebook(notebook_source, outputs=out), encoding="utf-8")
    nb = subprocess.run(
        [sys.executable, "-m", "statguard", "check", str(nb_path), "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert nb.returncode == 0
    assert json.loads(nb.stdout)["findings"][0]["cell_index"] == 1
    assert not py_marker.exists()
    assert not output_marker.exists()


def test_parse_error_is_not_a_clean_finding():
    result = Analyzer(default_registry()).analyze_source("if (", path="bad.py")
    assert result.status.value == "failed"
    assert not result.findings

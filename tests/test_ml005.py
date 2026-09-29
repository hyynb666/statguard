"""ML005 training-only evaluation: provenance, scope, reporting and safety tests."""

import json
import subprocess
import sys

from statguard.analyzer import Analyzer
from statguard.core import Evidence
from statguard.rules import default_registry


def code(*lines: str) -> str:
    return "\n".join(lines) + "\n"


BASE = code(
    "from sklearn.model_selection import train_test_split as split",
    "from sklearn.linear_model import LogisticRegression as Model",
    "a, b, c, d = split(X, y)",
    "model = Model()",
    "model.fit(a, c)",
    "train_score = model.score(a, c)",
)


def findings(source: str):
    result = Analyzer(default_registry()).analyze_source(source, path="analysis.py")
    assert not result.errors
    return tuple(item for item in result.findings if item.rule_id == "ML005")


def test_training_only_score_uses_split_roles_not_names_and_finds_potential_risk():
    found = findings(BASE)
    assert len(found) == 1
    finding = found[0]
    assert (finding.rule_id, finding.line, finding.column) == ("ML005", 6, 15)
    assert (finding.severity, finding.confidence) == ("warning", "medium")
    assert finding.evidence is Evidence.POTENTIAL_STATISTICAL_RISK
    assert "Within this supported analysis scope" in finding.explanation
    assert "Training scores can be useful for diagnostics" in finding.explanation
    assert "held-out data" in finding.suggestion


def test_aliases_and_keyword_score_arguments_keep_provenance():
    source = BASE + code(
        "train_alias = a", "label_alias = c", "model.score(X=train_alias, y=label_alias)"
    )
    assert len(findings(source)) == 1


def test_supported_estimator_families_are_resolved():
    for module, name in (
        ("linear_model", "LinearRegression"),
        ("ensemble", "RandomForestClassifier"),
        ("ensemble", "RandomForestRegressor"),
    ):
        source = BASE.replace(
            "from sklearn.linear_model import LogisticRegression as Model",
            f"from sklearn.{module} import {name} as Model",
        )
        assert len(findings(source)) == 1


def test_heldout_score_after_training_score_suppresses_scope_candidate():
    assert findings(BASE + code("test_score = model.score(b, d)")) == ()


def test_repeated_training_scores_are_one_stable_finding():
    source = BASE + code("model.score(a, c)", "model.score(a, c)")
    first = findings(source)
    second = findings(source)
    assert len(first) == 1
    assert first == second


def test_heldout_score_without_training_score_is_not_training_only_evaluation():
    source = BASE.rsplit("train_score = model.score(a, c)\n", 1)[0]
    assert findings(source + code("model.score(b, d)")) == ()


def test_full_data_fit_and_score_without_split_is_outside_rule_scope():
    source = code(
        "from sklearn.linear_model import LogisticRegression",
        "model = LogisticRegression()",
        "model.fit(X, y)",
        "model.score(X, y)",
    )
    assert findings(source) == ()


def test_function_local_scope_is_analyzed_without_cross_function_leakage():
    source = code(
        "def train_local(X, y):",
        "    from sklearn.model_selection import train_test_split as local_split",
        "    from sklearn.linear_model import LogisticRegression as LocalModel",
        "    a, b, c, d = local_split(X, y)",
        "    model = LocalModel()",
        "    model.fit(a, c)",
        "    model.score(a, c)",
        "def unrelated(X, y):",
        "    model = build_model()",
        "    model.score(X, y)",
    )
    assert len(findings(source)) == 1


def test_other_model_or_other_split_test_score_does_not_suppress():
    another_model = BASE + code(
        "other = Model()",
        "other.fit(a, c)",
        "other.score(b, d)",
    )
    assert len(findings(another_model)) == 1
    another_split = BASE + code(
        "e, f, g, h = split(Z, w)",
        "model.score(f, h)",
    )
    assert len(findings(another_split)) == 1


def test_mixed_feature_and_label_roles_are_not_heldout_evaluation():
    assert len(findings(BASE + code("model.score(b, c)"))) == 1
    assert len(findings(BASE + code("model.score(a, d)"))) == 1


def test_unrelated_score_does_not_create_training_candidate():
    source = BASE.replace("model.score(a, c)", "model.score(other_x, other_y)")
    assert findings(source) == ()


def test_custom_same_name_model_and_unknown_factory_are_not_recognized():
    custom = code(
        "from sklearn.model_selection import train_test_split as split",
        "class LogisticRegression:",
        "    def fit(self, X, y): pass",
        "    def score(self, X, y): return 1",
        "a, b, c, d = split(X, y)",
        "model = LogisticRegression()",
        "model.fit(a, c)",
        "model.score(a, c)",
    )
    unknown = code(
        "from sklearn.model_selection import train_test_split as split",
        "a, b, c, d = split(X, y)",
        "model = build_model()",
        "model.fit(a, c)",
        "model.score(a, c)",
    )
    assert findings(custom) == findings(unknown) == ()


def test_fit_on_test_data_is_ml004_not_ml005():
    source = BASE.rsplit("train_score = model.score(a, c)\n", 1)[0]
    result = Analyzer(default_registry()).analyze_source(
        source.replace("model.fit(a, c)", "model.fit(b, d)"), path="analysis.py"
    )
    assert "ML004" in {item.rule_id for item in result.findings}
    assert "ML005" not in {item.rule_id for item in result.findings}


def test_rebinding_model_and_split_data_uses_point_of_use_versions():
    no_score = BASE.rsplit("train_score = model.score(a, c)\n", 1)[0]
    assert findings(no_score + code("model = build_model()", "model.score(a, c)")) == ()
    assert findings(no_score + code("a = unrelated", "model.score(a, c)")) == ()
    assert len(findings(BASE + code("model.score(a, c)", "a = unrelated"))) == 1


def test_two_independent_training_only_model_fit_episodes_report_separately():
    source = BASE + code(
        "second = Model()",
        "second.fit(a, c)",
        "second.score(a, c)",
    )
    assert len(findings(source)) == 2


def test_unknown_wrapper_or_unknown_score_input_causes_conservative_abstention():
    assert findings(BASE + code("evaluate(model)")) == ()
    assert findings(BASE + code("model.score(dynamic_X, dynamic_y)")) == ()
    assert findings(BASE + code("model.set_params(C=2)")) == ()
    assert findings(BASE + code("model.__dict__.update({'marker': True})")) == ()


def test_unsupported_control_flow_after_fit_makes_absence_undetermined():
    assert findings(BASE + code("if validate:", "    model.score(b, d)")) == ()
    assert findings(BASE + code("for fold in folds:", "    model.score(b, d)")) == ()


def test_prediction_and_arbitrary_metric_are_not_treated_as_supported_score():
    assert (
        findings(BASE + code("predicted = model.predict(b)", "accuracy_score(d, predicted)")) == ()
    )


def test_cross_validation_does_not_count_as_matching_test_score():
    source = BASE + code(
        "from sklearn.model_selection import cross_val_score",
        "cv_scores = cross_val_score(model, X, y)",
    )
    assert len(findings(source)) == 1


def test_pipeline_and_ml009_rule_identity_remain_separate():
    assert {rule.rule_id for rule in default_registry()} == {
        "ML001",
        "ML002",
        "ML003",
        "ML004",
        "ML005",
        "ML006",
        "ML009",
        "ST001",
        "ST002",
    }
    pipeline = code(
        "from sklearn.model_selection import train_test_split",
        "from sklearn.pipeline import Pipeline",
        "from sklearn.preprocessing import StandardScaler",
        "from sklearn.linear_model import LogisticRegression",
        "a, b, c, d = train_test_split(X, y)",
        "model = Pipeline([('scale', StandardScaler()), ('model', LogisticRegression())])",
        "model.fit(a, c)",
        "model.score(a, c)",
    )
    assert findings(pipeline) == ()


def test_notebook_cell_positions_and_cross_cell_isolation():
    analyzer = Analyzer(default_registry())
    payload = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"language_info": {"name": "python"}},
        "cells": [
            {"cell_type": "code", "metadata": {}, "source": BASE, "outputs": []},
            {
                "cell_type": "code",
                "metadata": {},
                "source": "model.score(b, d)\n",
                "outputs": [],
            },
        ],
    }
    result = analyzer.analyze_notebook_json(json.dumps(payload), path="book.ipynb")
    hits = [item for item in result.findings if item.rule_id == "ML005"]
    assert len(hits) == 1
    assert (hits[0].cell_index, hits[0].cell, hits[0].line) == (1, 1, 6)

    payload["cells"][0]["source"] = BASE + "model.score(b, d)\n"
    safe = analyzer.analyze_notebook_json(json.dumps(payload), path="safe.ipynb")
    assert not [finding for finding in safe.findings if finding.rule_id == "ML005"]


def run_cli(path, *args):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "statguard",
            "check",
            str(path),
            *args,
            "--disable-rule",
            "ML006",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )


def test_cli_console_json_html_disable_and_threshold(tmp_path):
    path = tmp_path / "training_only.py"
    ml009 = code(
        "from sklearn.preprocessing import StandardScaler",
        "from sklearn.model_selection import cross_val_score",
        "prepared = StandardScaler().fit_transform(Z)",
        "cv_scores = cross_val_score(model, prepared, target)",
    )
    path.write_text(BASE + ml009, encoding="utf-8")

    console = run_cli(path)
    assert console.returncode == 0
    assert "ML005 warning" in console.stdout
    assert "Potential training-only evaluation" in console.stdout

    json_result = run_cli(path, "--format", "json")
    assert json_result.returncode == 0 and json_result.stderr == ""
    finding = json.loads(json_result.stdout)["findings"][0]
    assert finding["rule_id"] == "ML005"
    assert finding["line"] == 6
    assert finding["evidence"] == "potential statistical risk"
    assert finding["explanation"] and finding["suggestion"]

    html = run_cli(path, "--format", "html")
    assert html.returncode == 0
    assert 'option value="ML005"' in html.stdout
    assert "ML009" in html.stdout
    assert "script-src 'sha256-" in html.stdout

    assert run_cli(path, "--fail-on", "warning").returncode == 1
    assert run_cli(path, "--disable-rule", "ML009").returncode == 0
    assert "ML005" in run_cli(path, "--disable-rule", "ML009").stdout
    disabled = run_cli(path, "--disable-rule", "ML005", "--format", "json")
    assert disabled.returncode == 0
    disabled_ids = {item["rule_id"] for item in json.loads(disabled.stdout)["findings"]}
    assert "ML005" not in disabled_ids
    assert "ML009" in disabled_ids


def test_scan_never_executes_python_or_notebook_code_or_outputs(tmp_path):
    marker = tmp_path / "executed"
    source = BASE + code("from pathlib import Path", f"Path({str(marker)!r}).write_text('bad')")
    path = tmp_path / "side_effect.py"
    path.write_text(source, encoding="utf-8")
    assert run_cli(path).returncode == 0
    assert not marker.exists()

    notebook = tmp_path / "side_effect.ipynb"
    notebook_source = f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')"
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
                        "source": notebook_source,
                        "outputs": [
                            {"output_type": "execute_result", "data": {"text/plain": "bad"}}
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert run_cli(notebook).returncode == 0
    assert not marker.exists()

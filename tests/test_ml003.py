"""ML003 positive, negative, boundary, registry and CLI integration fixtures."""

import json
import subprocess
import sys

import pytest

from statguard.analyzer import Analyzer
from statguard.context import AnalysisContext
from statguard.core import Evidence
from statguard.parsers import PythonSourceParser
from statguard.rules import ML003, default_registry


def code(*lines: str) -> str:
    return chr(10).join(lines) + chr(10)


SPLIT = code("from sklearn.model_selection import train_test_split as split")


def imports(name: str = "SelectKBest", score: str = "f_classif") -> str:
    return code(f"from sklearn.feature_selection import {name} as S, {score} as score") + SPLIT


def risk(name: str = "SelectKBest", options: str = "score_func=score", target: str = ", y"):
    return imports(name) + code(
        f"selector = S({options})",
        f"selected = selector.fit_transform(X{target})",
        "train, test = split(selected)",
    )


def analyze(source: str):
    result = Analyzer(default_registry()).analyze_source(source, path="analysis.py")
    assert not result.errors
    return tuple(f for f in result.findings if f.rule_id == "ML003")


@pytest.mark.parametrize(
    ("name", "options", "target", "mechanism"),
    [
        ("SelectKBest", "score_func=score, k=10", ", y", "supervised f_classif scores"),
        (
            "SelectPercentile",
            "score_func=score, percentile=20",
            ", y",
            "supervised f_classif scores",
        ),
        ("SelectKBest", "k=5", ", y", "supervised f_classif scores"),
        ("SelectPercentile", "percentile=25", ", y", "supervised f_classif scores"),
        ("VarianceThreshold", "", "", "feature variances"),
    ],
)
def test_supported_selectors_have_precise_statistical_explanation(name, options, target, mechanism):
    findings = analyze(risk(name, options, target))
    assert len(findings) == 1
    finding = findings[0]
    assert (finding.severity, finding.confidence) == ("warning", "medium")
    assert finding.evidence is Evidence.POTENTIAL_STATISTICAL_RISK
    assert finding.line == 4
    assert mechanism in finding.explanation
    assert "eventual test subset may therefore influence" in finding.explanation
    assert "does not establish actual leakage" in finding.explanation
    assert "training subset" in finding.suggestion


def test_keyword_fit_arguments_are_supported():
    source = imports() + code(
        "selected=S(score_func=score).fit_transform(X=X, y=y)",
        "a,b=split(selected)",
    )
    assert len(analyze(source)) == 1


def test_variance_threshold_with_ignored_y_remains_unsupervised():
    source = imports("VarianceThreshold") + code(
        "selected=S().fit_transform(X, y)",
        "a,b=split(selected)",
    )
    finding = analyze(source)[0]
    assert "feature variances" in finding.explanation
    assert "target labels" not in finding.explanation


@pytest.mark.parametrize(
    "score",
    [
        "f_classif",
        "f_regression",
        "chi2",
        "mutual_info_classif",
        "mutual_info_regression",
        "r_regression",
    ],
)
def test_known_supervised_score_functions_are_resolved_from_sklearn(score):
    source = imports("SelectKBest", score) + code(
        "selected=S(score_func=score).fit_transform(X, y)",
        "a,b=split(selected)",
    )
    findings = analyze(source)
    assert len(findings) == 1
    assert f"supervised {score} scores" in findings[0].explanation


@pytest.mark.parametrize(
    "body",
    [
        code("a,b=split(X)", "s=S()", "z=s.fit_transform(a,y)", "w=s.transform(b)"),
        code("s=S()", "z=s.fit_transform(X,y)", "a,b=split(other)"),
        code("s=S()", "z=s.fit_transform(X,y)", "z=other", "a,b=split(z)"),
        code("s=S()", "s.fit(X,y)", "z=s.transform(X)", "a,b=split(z)"),
        code("s=S()", "z=getattr(s,'fit_transform')(X,y)", "a,b=split(z)"),
        code("s=S()", "if flag:", "    z=s.fit_transform(X,y)", "a,b=split(z)"),
        code("s=S()", "for item in items:", "    z=s.fit_transform(item,y)", "a,b=split(z)"),
        code("s=S()", "z=s.fit_transform(X,y)", "if flag:", "    a,b=split(z)"),
        code("s=S()", "z=wrapper(s.fit_transform(X,y))", "a,b=split(z)"),
    ],
)
def test_safe_unrelated_separate_fit_and_uncertain_patterns_abstain(body):
    assert analyze(imports() + body) == ()


@pytest.mark.parametrize(
    "options",
    [
        "score_func=unknown_score",
        "score_func=lambda X, y: scores",
        "**options",
        "score",
    ],
)
def test_unknown_dynamic_and_positional_score_configuration_abstains(options):
    assert analyze(risk("SelectKBest", options)) == ()


@pytest.mark.parametrize("name", ["SelectKBest", "SelectPercentile"])
@pytest.mark.parametrize("target", ["", ", None", ", y=None"])
def test_supervised_selector_without_usable_explicit_target_abstains(name, target):
    assert analyze(risk(name, "", target)) == ()


@pytest.mark.parametrize(
    ("name", "options", "target"),
    [
        ("SelectKBest", "k='all'", ", y"),
        ("SelectKBest", "k=0", ", y"),
        ("SelectKBest", "k=amount", ", y"),
        ("SelectPercentile", "percentile=100", ", y"),
        ("SelectPercentile", "percentile=0", ", y"),
        ("SelectPercentile", "percentile=amount", ", y"),
        ("VarianceThreshold", "threshold=-1.0", ""),
        ("VarianceThreshold", "threshold=limit", ""),
    ],
)
def test_bypass_and_dynamic_selection_configuration_abstains(name, options, target):
    assert analyze(risk(name, options, target)) == ()


@pytest.mark.parametrize(
    "replacement",
    [
        code("class S:", "    def fit_transform(self, X, y):", "        return X"),
        code("def split(X):", "    return X, X"),
        code("from custom import SelectKBest as S"),
        code("from custom import train_test_split as split"),
        code("def score(X, y):", "    return values"),
    ],
)
def test_coincident_names_do_not_establish_sklearn_components(replacement):
    source = (
        imports()
        + replacement
        + code("s=S(score_func=score)", "z=s.fit_transform(X,y)", "a,b=split(z)")
    )
    assert analyze(source) == ()


def test_import_callable_receiver_and_result_aliases_are_preserved():
    source = code(
        "import sklearn.feature_selection as fs",
        "from sklearn.model_selection import train_test_split as divide",
        "constructor=fs.SelectPercentile",
        "selector=constructor(score_func=fs.f_regression, percentile=25)",
        "receiver=selector",
        "selected=receiver.fit_transform(X,y)",
        "copy=selected",
        "a,b=divide(copy)",
    )
    findings = analyze(source)
    assert len(findings) == 1
    assert findings[0].line == 6
    assert "analysis.py:8:" in findings[0].explanation


def test_chained_selector_and_nested_split_are_supported():
    source = imports("VarianceThreshold") + code("a,b=split(S(threshold=0.0).fit_transform(X))")
    findings = analyze(source)
    assert len(findings) == 1
    assert findings[0].line == 3


def test_rebinding_uses_point_of_use_and_distinct_object_identity():
    source = imports() + code(
        "s=S()",
        "selected=s.fit_transform(X,y)",
        "old=selected",
        "selected=other",
        "s=other_selector",
        "a,b=split(old)",
    )
    assert len(analyze(source)) == 1
    unsafe = imports() + code("s=S()", "s=other_selector", "z=s.fit_transform(X,y)", "a,b=split(z)")
    assert analyze(unsafe) == ()


@pytest.mark.parametrize(
    "mutation",
    [
        "s.set_params(k=2)",
        "mutate(s)",
        "s.score_func = other",
    ],
)
def test_possible_selector_configuration_mutation_abstains(mutation):
    prefix = imports() + (code("from custom import mutate") if mutation == "mutate(s)" else "")
    source = prefix + code(
        "s=S()",
        mutation,
        "z=s.fit_transform(X,y)",
        "a,b=split(z)",
    )
    assert analyze(source) == ()


def test_pipeline_does_not_report():
    source = imports() + code(
        "from sklearn.pipeline import Pipeline",
        "from sklearn.linear_model import LogisticRegression",
        "a,b,c,d=split(X,y)",
        "pipeline=Pipeline([('select', S()), ('model', LogisticRegression())])",
        "pipeline.fit(a,c)",
    )
    assert analyze(source) == ()


def test_multiple_independent_problems_and_duplicate_split_input_are_stable():
    source = (
        imports()
        + code(
            "s=S()",
            "first=s.fit_transform(X,y)",
            "a,b,c,d=split(first,first)",
        )
        + code(
            "from sklearn.feature_selection import VarianceThreshold as V",
            "second=V().fit_transform(Z)",
            "e,f=split(second)",
        )
    )
    findings = analyze(source)
    assert [finding.line for finding in findings] == [4, 7]
    context = AnalysisContext(PythonSourceParser().parse_source(source))
    rule = ML003()
    assert rule.check(context) == rule.check(context)


def test_long_alias_chain_is_iterative():
    aliases = [f"a{index}=a{index - 1}" for index in range(1, 1200)]
    source = imports("VarianceThreshold") + code(
        "a0=S().fit_transform(X)",
        *aliases,
        "train,test=split(a1199)",
    )
    findings = analyze(source)
    assert len(findings) == 1 and findings[0].line == 3


def test_function_scope_requires_local_imports():
    local = code(
        "def select(X,y):",
        "    from sklearn.feature_selection import SelectKBest, f_classif",
        "    from sklearn.model_selection import train_test_split",
        "    z=SelectKBest(score_func=f_classif).fit_transform(X,y)",
        "    return train_test_split(z)",
    )
    assert len(analyze(local)) == 1
    module_imports = imports() + code(
        "def select(X,y):",
        "    s=S(score_func=score)",
        "    z=s.fit_transform(X,y)",
        "    return split(z)",
    )
    assert analyze(module_imports) == ()


def notebook(cells):
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
                    "outputs": [{"output_type": "stream", "text": "ignored"}],
                }
                for source in cells
            ],
        }
    )


def test_notebook_same_cell_detected_cross_cell_abstains_and_output_ignored():
    analyzer = Analyzer(default_registry())
    result = analyzer.analyze_notebook_json(notebook([risk()]), path="book.ipynb")
    findings = tuple(f for f in result.findings if f.rule_id == "ML003")
    assert len(findings) == 1
    assert (findings[0].cell_index, findings[0].cell, findings[0].line) == (1, 1, 4)

    prefix = imports() + code("s=S()", "selected=s.fit_transform(X,y)")
    result = analyzer.analyze_notebook_json(
        notebook([prefix, code("train,test=split(selected)")]), path="book.ipynb"
    )
    assert tuple(f for f in result.findings if f.rule_id == "ML003") == ()


def test_default_registry_and_rule_disabling_are_independent():
    registry = default_registry()
    assert [rule.rule_id for rule in registry.iter_enabled()] == ["ML001", "ML002", "ML003"]
    registry.disable("ML003")
    result = Analyzer(registry).analyze_source(risk())
    assert all(f.rule_id != "ML003" for f in result.findings)

    all_rules = code(
        "from sklearn.preprocessing import StandardScaler",
        "from sklearn.impute import SimpleImputer",
        "from sklearn.feature_selection import SelectKBest, f_classif",
        "from sklearn.model_selection import train_test_split",
        "a=StandardScaler().fit_transform(A)",
        "train_a,test_a=train_test_split(a)",
        "b=SimpleImputer().fit_transform(B)",
        "train_b,test_b=train_test_split(b)",
        "c=SelectKBest(score_func=f_classif).fit_transform(C,y)",
        "train_c,test_c=train_test_split(c)",
    )
    findings = Analyzer(default_registry()).analyze_source(all_rules).findings
    assert [finding.rule_id for finding in findings] == ["ML001", "ML002", "ML003"]
    for disabled, expected in [
        ("ML001", ["ML002", "ML003"]),
        ("ML002", ["ML001", "ML003"]),
        ("ML003", ["ML001", "ML002"]),
    ]:
        registry = default_registry()
        registry.disable(disabled)
        assert [
            finding.rule_id for finding in Analyzer(registry).analyze_source(all_rules).findings
        ] == expected


@pytest.mark.parametrize(
    ("args", "returncode", "count"),
    [
        ([], 0, 1),
        (["--fail-on", "warning"], 1, 1),
        (["--fail-on", "error"], 0, 1),
        (["--disable-rule", "ML003"], 0, 0),
    ],
)
def test_real_cli_json_report_and_thresholds(tmp_path, args, returncode, count):
    path = tmp_path / "risk.py"
    path.write_text(risk(), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "statguard", "check", str(path), "--format", "json", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == returncode and result.stderr == ""
    data = json.loads(result.stdout)
    assert data["analysis_errors"] == []
    assert len(data["findings"]) == count
    if count:
        finding = data["findings"][0]
        assert finding["rule_id"] == "ML003"
        assert finding["message"] == "Potential feature selection leakage before train/test split."
        assert finding["line"] == 4 and finding["severity"] == "warning"
        assert finding["evidence"] == "potential statistical risk"
        assert "target labels" in finding["explanation"]


def test_console_location_and_no_source_execution(tmp_path):
    marker = tmp_path / "executed"
    path = tmp_path / "risk.py"
    source = risk() + code(f"open({str(marker)!r}, 'w').close()")
    path.write_text(source, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "statguard", "check", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "risk.py:4:12: ML003 warning" in result.stdout
    assert "Potential feature selection leakage" in result.stdout
    assert not marker.exists()


def test_syntax_error_is_scan_error_not_finding():
    result = Analyzer(default_registry()).analyze_source("if (", path="bad.py")
    assert result.status.value == "failed" and result.findings == ()

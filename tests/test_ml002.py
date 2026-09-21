"""ML002 positive, negative, boundary, registry and CLI integration fixtures."""

import json
import subprocess
import sys

import pytest

from statguard.analyzer import Analyzer
from statguard.context import AnalysisContext
from statguard.core import Evidence
from statguard.parsers import PythonSourceParser
from statguard.rules import ML002, default_registry


def code(*lines: str) -> str:
    return chr(10).join(lines) + chr(10)


SPLIT = code("from sklearn.model_selection import train_test_split as split")


def imports(name: str = "SimpleImputer") -> str:
    return code(f"from sklearn.impute import {name} as I") + SPLIT


def risk(name: str = "SimpleImputer", options: str = "") -> str:
    return imports(name) + code(
        f"imputer = I({options})",
        "filled = imputer.fit_transform(X)",
        "train, test = split(filled)",
    )


def analyze(source: str):
    result = Analyzer(default_registry()).analyze_source(source, path="analysis.py")
    assert not result.errors
    return tuple(f for f in result.findings if f.rule_id == "ML002")


@pytest.mark.parametrize(
    ("name", "options", "mechanism"),
    [
        ("SimpleImputer", "", "column means"),
        ("SimpleImputer", 'strategy="mean"', "column means"),
        ("SimpleImputer", 'strategy="median"', "column medians"),
        ("SimpleImputer", 'strategy="most_frequent"', "most-frequent column values"),
        ("KNNImputer", "n_neighbors=5", "neighbor reference samples"),
        ("IterativeImputer", "random_state=42", "iteratively fitted estimation models"),
    ],
)
def test_supported_imputers_have_precise_statistical_explanation(name, options, mechanism):
    source = risk(name, options)
    if name == "IterativeImputer":
        source = code("from sklearn.experimental import enable_iterative_imputer") + source
    findings = analyze(source)
    assert len(findings) == 1
    finding = findings[0]
    assert (finding.severity, finding.confidence) == ("warning", "medium")
    assert finding.evidence is Evidence.POTENTIAL_STATISTICAL_RISK
    assert finding.line == (5 if name == "IterativeImputer" else 4)
    assert mechanism in finding.explanation
    assert "may therefore influence" in finding.explanation
    assert "does not establish actual leakage" in finding.explanation
    assert "training subset" in finding.suggestion


@pytest.mark.parametrize(
    "options",
    [
        'strategy="constant", fill_value=-1',
        "strategy=strategy",
        "strategy=lambda values: 0",
        'strategy="new_future_strategy"',
        "**options",
        "strategy='mean', strategy='median'",
        "'mean'",
    ],
)
def test_constant_dynamic_callable_and_unknown_simple_strategy_abstain(options):
    assert analyze(risk("SimpleImputer", options)) == ()


@pytest.mark.parametrize(
    "body",
    [
        code("a,b=split(X)", "i=I()", "z=i.fit_transform(a)", "w=i.transform(b)"),
        code("i=I()", "z=i.fit_transform(X)", "a,b=split(other)"),
        code("i=I()", "z=i.fit_transform(X)", "z=other", "a,b=split(z)"),
        code("i=I()", "i.fit(X)", "z=i.transform(X)", "a,b=split(z)"),
        code("i=I()", "z=getattr(i, 'fit_transform')(X)", "a,b=split(z)"),
        code("i=I()", "if flag:", "    z=i.fit_transform(X)", "a,b=split(z)"),
        code("i=I()", "for item in items:", "    z=i.fit_transform(item)", "a,b=split(z)"),
        code("i=I()", "z=i.fit_transform(X)", "if flag:", "    a,b=split(z)"),
        code("i=I()", "z=wrapper(i.fit_transform(X))", "a,b=split(z)"),
    ],
)
def test_safe_unrelated_separate_fit_and_uncertain_patterns_abstain(body):
    assert analyze(imports() + body) == ()


@pytest.mark.parametrize(
    "replacement",
    [
        code("class I:", "    def fit_transform(self, X):", "        return X"),
        code("def split(X):", "    return X, X"),
        code("from custom import SimpleImputer as I"),
        code("from custom import train_test_split as split"),
    ],
)
def test_coincident_names_do_not_establish_sklearn(replacement):
    source = imports() + replacement + code("i=I()", "z=i.fit_transform(X)", "a,b=split(z)")
    assert analyze(source) == ()


def test_constructor_and_receiver_aliases_keep_exact_object_identity():
    source = imports() + code(
        "constructor=I",
        "imputer=constructor()",
        "receiver=imputer",
        "filled=receiver.fit_transform(X)",
        "a,b=split(filled)",
    )
    assert [finding.line for finding in analyze(source)] == [6]


def test_attribute_configuration_change_abstains():
    source = imports() + code(
        "imputer=I()",
        "imputer.strategy='constant'",
        "filled=imputer.fit_transform(X)",
        "a,b=split(filled)",
    )
    assert analyze(source) == ()


def test_aliases_module_import_chain_and_result_alias():
    source = code(
        "import sklearn.impute as imp",
        "from sklearn.model_selection import train_test_split as divide",
        "filled = imp.KNNImputer().fit_transform(X)",
        "copy = filled",
        "a, b = divide(copy)",
    )
    finding = analyze(source)[0]
    assert finding.line == 3
    assert "analysis.py:5:" in finding.explanation


def test_pipeline_does_not_report():
    source = imports() + code(
        "from sklearn.pipeline import Pipeline",
        "from sklearn.linear_model import LogisticRegression",
        "a,b,c,d=split(X,y)",
        "pipeline=Pipeline([('imputer', I()), ('model', LogisticRegression())])",
        "pipeline.fit(a,c)",
    )
    assert analyze(source) == ()


def test_rebinding_preserves_point_of_use_and_object_identity():
    source = imports() + code(
        "i=I(strategy='mean')",
        "filled=i.fit_transform(X)",
        "old=filled",
        "filled=unrelated",
        "i=other",
        "a,b=split(old)",
    )
    assert len(analyze(source)) == 1
    unsafe = imports() + code("i=I()", "i=other", "z=i.fit_transform(X)", "a,b=split(z)")
    assert analyze(unsafe) == ()


@pytest.mark.parametrize(
    "operation",
    ["i.set_params(strategy='constant')", code("from custom import mutate", "mutate(i)")],
)
def test_possible_configuration_mutation_abstains(operation):
    source = (
        imports()
        + code("i=I()")
        + operation
        + chr(10)
        + code("z=i.fit_transform(X)", "a,b=split(z)")
    )
    assert analyze(source) == ()


def test_multiple_splits_issues_and_deduplication_are_deterministic():
    source = imports() + code(
        "i=I()",
        "a=i.fit_transform(X)",
        "old=a",
        "x1,x2=split(old)",
        "x3,x4=split(old)",
        "j=I(strategy='median')",
        "b=j.fit_transform(Y)",
        "y1,y2=split(b)",
    )
    findings = analyze(source)
    assert [f.line for f in findings] == [4, 4, 9]
    context = AnalysisContext(PythonSourceParser().parse_source(source))
    rule = ML002()
    assert rule.check(context) == rule.check(context)
    assert len(rule.check(context)) == 3


def test_function_scope_requires_local_imports():
    local = code("def clean(X):", *(f"    {line}" for line in risk().splitlines()))
    assert len(analyze(local)) == 1
    module_imports = imports() + code(
        "def clean(X):",
        "    i=I()",
        "    z=i.fit_transform(X)",
        "    a,b=split(z)",
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
    findings = tuple(f for f in result.findings if f.rule_id == "ML002")
    assert len(findings) == 1
    assert (findings[0].cell_index, findings[0].cell, findings[0].line) == (1, 1, 4)

    prefix = imports() + code("i=I()", "filled=i.fit_transform(X)")
    result = analyzer.analyze_notebook_json(
        notebook([prefix, code("train,test=split(filled)")]), path="book.ipynb"
    )
    assert tuple(f for f in result.findings if f.rule_id == "ML002") == ()


def test_default_registry_and_rule_disabling_are_independent():
    registry = default_registry()
    assert [rule.rule_id for rule in registry.iter_enabled()] == ["ML001", "ML002"]
    registry.disable("ML002")
    result = Analyzer(registry).analyze_source(risk())
    assert all(f.rule_id != "ML002" for f in result.findings)

    both = (
        code("from sklearn.preprocessing import StandardScaler")
        + imports()
        + code(
            "s=StandardScaler()",
            "scaled=s.fit_transform(A)",
            "a,b=split(scaled)",
            "i=I()",
            "filled=i.fit_transform(B)",
            "c,d=split(filled)",
        )
    )
    registry = default_registry()
    registry.disable("ML001")
    assert [f.rule_id for f in Analyzer(registry).analyze_source(both).findings] == ["ML002"]
    registry = default_registry()
    registry.disable("ML002")
    assert [f.rule_id for f in Analyzer(registry).analyze_source(both).findings] == ["ML001"]


@pytest.mark.parametrize(
    ("args", "returncode", "count"),
    [
        ([], 0, 1),
        (["--fail-on", "warning"], 1, 1),
        (["--fail-on", "error"], 0, 1),
        (["--disable-rule", "ML002"], 0, 0),
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
        assert finding["rule_id"] == "ML002"
        assert finding["message"] == "Potential imputation leakage before train/test split."
        assert finding["line"] == 4 and finding["severity"] == "warning"
        assert finding["evidence"] == "potential statistical risk"


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
    assert "risk.py:4:10: ML002 warning" in result.stdout
    assert "Potential imputation leakage" in result.stdout
    assert not marker.exists()


def test_syntax_error_is_scan_error_not_finding():
    result = Analyzer(default_registry()).analyze_source("if (", path="bad.py")
    assert result.status.value == "failed" and result.findings == ()

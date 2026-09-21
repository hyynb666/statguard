"""ML001 positive, negative, boundary and real CLI integration fixtures."""

import json
import subprocess
import sys

import pytest

from statguard.analyzer import Analyzer
from statguard.context import AnalysisContext
from statguard.core import Evidence
from statguard.parsers import PythonSourceParser
from statguard.rules import ML001, default_registry

IMPORTS = (
    "from sklearn.preprocessing import StandardScaler as S\n"
    "from sklearn.model_selection import train_test_split as split\n"
)
RISK = IMPORTS + "scaler = S()\nscaled = scaler.fit_transform(X)\na, b = split(scaled)\n"


def analyze(source):
    result = Analyzer(default_registry()).analyze_source(source, path="analysis.py")
    assert not result.errors
    return result.findings


@pytest.mark.parametrize("scaler", ["StandardScaler", "MinMaxScaler", "RobustScaler"])
@pytest.mark.parametrize("style", ["from", "module", "chain"])
def test_supported_scaler_identity_alias_and_evidence(scaler, style):
    prefix = "from sklearn.model_selection import train_test_split as split\n"
    if style == "module":
        prefix += "import sklearn.preprocessing as prep\n"
        factory = f"prep.{scaler}"
    else:
        prefix += f"from sklearn.preprocessing import {scaler} as S\n"
        factory = "S"
    if style == "chain":
        body = f"scaled = {factory}().fit_transform(X)\n"
        fit_line = 3
    else:
        body = f"scaler = {factory}()\nscaled = scaler.fit_transform(X)\n"
        fit_line = 4
    body += "copy = scaled\ndivide = split\na, b = divide(copy)\n"
    findings = analyze(prefix + body)
    assert len(findings) == 1
    f = findings[0]
    assert (f.rule_id, f.severity, f.confidence) == ("ML001", "warning", "medium")
    assert f.evidence is Evidence.POTENTIAL_STATISTICAL_RISK
    assert f.line == fit_line and f.column == 10
    assert f"analysis.py:{fit_line + 3}:" in f.explanation
    assert "may influence" in f.explanation and "training subset" in f.suggestion


@pytest.mark.parametrize(
    "body",
    [
        "a, b = split(X)\ns = S()\nz = s.fit_transform(a)\nw = s.transform(b)",
        "a, b = split(X)\ns = S()\nz = s.fit_transform(a)\nc, d = split(z)",
        "s = S()\nz = s.fit_transform(X)\na, b = split(unrelated)",
        "s = S()\nz = s.fit_transform(X)\nz = unrelated\na, b = split(z)",
        "s = S()\ns.fit(X)\nz = s.transform(X)\na, b = split(z)",
        "s = S().fit(X)\nz = s.transform(X)\na, b = split(z)",
        "s = S()\ns = unknown\nz = s.fit_transform(X)\na, b = split(z)",
        "s = S()\nz = getattr(s, 'fit_transform')(X)\na, b = split(z)",
        "s = S()\nif flag:\n    z = s.fit_transform(X)\na, b = split(z)",
        "s = S()\nfor x in values:\n    z = s.fit_transform(x)\na, b = split(z)",
        "s = S()\nz = s.fit_transform(X)\nif flag:\n    a, b = split(z)",
        "s = S()\nz = s.fit_transform(X)\na, b = split(*z)",
        "s = S()\nz = s.fit_transform(X)\na, b = split(z, **options)",
        "s = S()\ns.fit_transform = other\nz = s.fit_transform(X)\na, b = split(z)",
        "from arbitrary import transform\ns = S()\n"
        "z = transform(s.fit_transform(X))\na, b = split(z)",
    ],
)
def test_safe_unrelated_rebound_and_unsupported_patterns_abstain(body):
    assert analyze(IMPORTS + body) == ()


@pytest.mark.parametrize(
    "replacement",
    [
        "class S:\n    def fit_transform(self, X):\n        return X\n",
        "def split(X):\n    return X, X\n",
        "from arbitrary import StandardScaler as S\n",
        "from arbitrary import train_test_split as split\n",
    ],
)
def test_coincident_names_do_not_establish_sklearn(replacement):
    assert analyze(IMPORTS + replacement + "s = S()\nz = s.fit_transform(X)\na, b = split(z)") == ()


def test_pipeline_abstains():
    assert (
        analyze(
            IMPORTS + "from sklearn.pipeline import Pipeline\n"
            "from sklearn.linear_model import LogisticRegression\n"
            "a, b, c, d = split(X, y)\n"
            "pipeline = Pipeline([('scaler', S()), ('model', LogisticRegression())])\n"
            "pipeline.fit(a, c)\n"
        )
        == ()
    )


def test_old_alias_preserved_and_independent_issues_are_not_merged():
    source = IMPORTS + "s = S()\nz = s.fit_transform(X)\nold = z\nz = other\n"
    source += "a, b = split(old)\nc, d = split(old)\n"
    source += "t = S()\nw = t.fit_transform(Y)\ne, f = split(w)\n"
    findings = analyze(source)
    assert [f.line for f in findings] == [4, 4, 10]
    assert len({f.explanation for f in findings}) == 3


def test_duplicate_arrays_and_repeated_queries_do_not_duplicate_findings():
    source = IMPORTS + "s = S()\nz = s.fit_transform(X)\na, b, c, d = split(z, z)\n"
    ctx = AnalysisContext(PythonSourceParser().parse_source(source))
    rule = ML001()
    assert len(rule.check(ctx)) == 1
    assert rule.check(ctx) == rule.check(ctx)


def test_local_import_scope_supported_but_global_import_in_function_unknown():
    assert len(analyze("def f(X):\n" + "".join("    " + s + "\n" for s in RISK.splitlines()))) == 1
    assert (
        analyze(IMPORTS + "def f(X):\n    s = S()\n    z = s.fit_transform(X)\n    a,b=split(z)")
        == ()
    )


def test_nested_call_evaluation_order_is_not_textual_start_order():
    source = IMPORTS + "a, b = split(S().fit_transform(X))\n"
    assert len(analyze(source)) == 1
    ctx = AnalysisContext(PythonSourceParser().parse_source(source))
    split = ctx.provenance.splits[0]
    transform = split.sources[0]
    assert split.location.column < transform.location.column
    assert (
        ctx.symbols.evaluation_site(transform.node).order
        < ctx.symbols.evaluation_site(split.node).order
    )


def test_notebook_independence_and_locations():
    def book(sources):
        return json.dumps(
            {
                "nbformat": 4,
                "nbformat_minor": 5,
                "metadata": {"language_info": {"name": "python"}},
                "cells": [{"cell_type": "markdown", "metadata": {}, "source": "text"}]
                + [
                    {"cell_type": "code", "metadata": {}, "source": s, "outputs": []}
                    for s in sources
                ],
            }
        )

    analyzer = Analyzer(default_registry())
    result = analyzer.analyze_notebook_json(book([RISK]))
    assert not result.errors and len(result.findings) == 1
    assert (result.findings[0].cell_index, result.findings[0].cell, result.findings[0].line) == (
        2,
        1,
        4,
    )
    assert (
        analyzer.analyze_notebook_json(
            book([RISK.rsplit("a, b", 1)[0], "a, b = split(scaled)"])
        ).findings
        == ()
    )


def test_disabled_rule_is_never_executed(monkeypatch):
    registry = default_registry()
    registry.disable("ML001")

    def forbidden(*args):
        raise AssertionError("disabled rule executed")

    monkeypatch.setattr(ML001, "check", forbidden)
    result = Analyzer(registry).analyze_source(RISK)
    assert result.is_complete and result.findings == ()


@pytest.mark.parametrize(
    "args,code",
    [
        ([], 0),
        (["--fail-on", "warning"], 1),
        (["--fail-on", "error"], 0),
        (["--disable-rule", "ML001"], 0),
    ],
)
def test_real_cli_json_and_thresholds(tmp_path, args, code):
    path = tmp_path / "risk.py"
    path.write_text(RISK, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "statguard", "check", str(path), "--format", "json", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == code and result.stderr == ""
    data = json.loads(result.stdout)
    assert data["analysis_errors"] == []
    assert len(data["findings"]) == (0 if "--disable-rule" in args else 1)
    if data["findings"]:
        f = data["findings"][0]
        assert f["rule_id"] == "ML001" and f["line"] == 4 and f["severity"] == "warning"


def test_console_empty_syntax_error_and_no_execution(tmp_path):
    path = tmp_path / "risk.py"
    marker = tmp_path / "executed"
    path.write_text(RISK + f"open({str(marker)!r}, 'w').close()\n", encoding="utf-8")

    def run(*args):
        return subprocess.run(
            [sys.executable, "-m", "statguard", "check", str(path), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    result = run()
    assert (
        result.returncode == 0
        and "ML001" in result.stdout
        and "Potential preprocessing" in result.stdout
    )
    assert not marker.exists()
    assert run("--disable-rule", "NOT_A_RULE").returncode == 2
    path.write_text("")
    assert run().returncode == 0
    path.write_text("if (")
    assert run().returncode == 2


@pytest.mark.parametrize(
    "scaler,options",
    [
        ("StandardScaler", "with_mean=False, with_std=False"),
        ("RobustScaler", "with_centering=False, with_scaling=False"),
        ("StandardScaler", "with_mean=flag"),
        ("StandardScaler", "**options"),
    ],
)
def test_disabled_or_unknown_learning_configuration_abstains(scaler, options):
    prefix = IMPORTS.replace("StandardScaler", scaler)
    assert analyze(prefix + f"s = S({options})\nz = s.fit_transform(X)\na, b = split(z)") == ()


def test_one_enabled_learning_switch_still_reports():
    assert (
        len(analyze(IMPORTS + "s = S(with_mean=False)\nz = s.fit_transform(X)\na,b=split(z)")) == 1
    )


@pytest.mark.parametrize(
    "operation",
    [
        "s.set_params(with_mean=False, with_std=False)",
        "from custom import mutate\nmutate(s)",
    ],
)
def test_potential_receiver_configuration_changes_abstain(operation):
    assert analyze(IMPORTS + "s = S()\n" + operation + "\nz=s.fit_transform(X)\na,b=split(z)") == ()


def test_rebound_receiver_does_not_inherit_old_object_mutation():
    source = IMPORTS + "s = S()\ns.set_params(with_mean=False)\ns = S()\n"
    assert len(analyze(source + "z=s.fit_transform(X)\na,b=split(z)")) == 1

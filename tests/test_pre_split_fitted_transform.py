"""Separate fit/transform evidence shared by ML001–ML003."""

import json
import subprocess
import sys
from dataclasses import FrozenInstanceError

import pytest

from statguard.analyzer import Analyzer
from statguard.parsers import PythonSourceParser
from statguard.rules import default_registry

SPLIT = (
    "from data_fixture import X, y\nfrom sklearn.model_selection import train_test_split as split\n"
)


def source_for(rule: str, constructor: str, options: str = "", fit_args: str = "X") -> str:
    imports = {
        "ML001": f"from sklearn.preprocessing import {constructor} as Factory\n",
        "ML002": f"from sklearn.impute import {constructor} as Factory\n",
        "ML003": (f"from sklearn.feature_selection import {constructor} as Factory, f_classif\n"),
    }[rule]
    if rule == "ML003" and not options:
        options = "score_func=f_classif"
    arguments = f"({options})" if options else "()"
    return (
        SPLIT
        + imports
        + f"transformer = Factory{arguments}\n"
        + f"transformer.fit({fit_args})\n"
        + "transformed = transformer.transform(X)\n"
        + "train, test = split(transformed)\n"
    )


def findings(source: str, path: str = "analysis.py"):
    result = Analyzer(default_registry()).analyze_source(source, path=path)
    assert not result.errors
    return result.findings


@pytest.mark.parametrize(
    ("rule", "constructor", "options", "fit_args"),
    [
        ("ML001", "StandardScaler", "", "X"),
        ("ML001", "MinMaxScaler", "", "X"),
        ("ML001", "RobustScaler", "", "X"),
        ("ML002", "SimpleImputer", 'strategy="mean"', "X"),
        ("ML002", "SimpleImputer", 'strategy="median"', "X"),
        ("ML002", "SimpleImputer", 'strategy="most_frequent"', "X"),
        ("ML002", "KNNImputer", "", "X"),
        ("ML002", "IterativeImputer", "max_iter=3", "X"),
        ("ML003", "SelectKBest", "score_func=f_classif, k=10", "X, y"),
        ("ML003", "SelectPercentile", "score_func=f_classif, percentile=25", "X, y"),
        ("ML003", "VarianceThreshold", "threshold=0.0", "X"),
    ],
)
def test_supported_separate_fit_transform_patterns(rule, constructor, options, fit_args):
    matches = [
        item
        for item in findings(source_for(rule, constructor, options, fit_args))
        if item.rule_id == rule
    ]
    assert len(matches) == 1
    assert matches[0].line == 5
    assert matches[0].evidence.value == "potential statistical risk"
    assert "train_test_split" in matches[0].explanation
    assert "transform" in matches[0].explanation


@pytest.mark.parametrize(
    ("constructor", "options"),
    [
        ("SimpleImputer", 'strategy="constant", fill_value=0'),
        ("SimpleImputer", "strategy=dynamic_strategy"),
        ("IterativeImputer", "max_iter=0, initial_strategy='constant'"),
        ("IterativeImputer", "max_iter=dynamic_count"),
    ],
)
def test_data_independent_or_unknown_imputer_configuration_abstains(constructor, options):
    result = findings(source_for("ML002", constructor, options))
    assert all(item.rule_id != "ML002" for item in result)


def test_iterative_imputer_zero_iterations_preserves_data_dependent_initial_strategy():
    result = findings(
        source_for("ML002", "IterativeImputer", "max_iter=0, initial_strategy='median'")
    )
    assert [item.rule_id for item in result] == ["ML002"]
    assert "initial column medians" in result[0].explanation


def test_aliases_and_separate_fit_transform_identity_are_traced():
    source = (
        "from data_fixture import X\n"
        "from sklearn.preprocessing import StandardScaler as SS\n"
        "from sklearn.model_selection import train_test_split as divide\n"
        "scaler = SS()\n"
        "first_alias = scaler\n"
        "second_alias = first_alias\n"
        "second_alias.fit(X)\n"
        "scaled = scaler.transform(X)\n"
        "copy = scaled\n"
        "train, test = divide(copy)\n"
    )
    matches = [item for item in findings(source) if item.rule_id == "ML001"]
    assert len(matches) == 1
    assert matches[0].line == 7
    assert "analysis.py:8:" in matches[0].explanation
    assert "analysis.py:10:" in matches[0].explanation


def test_data_aliases_preserve_the_same_source_binding():
    source = (
        "from data_fixture import X\n"
        "from sklearn.preprocessing import StandardScaler\n"
        "from sklearn.model_selection import train_test_split\n"
        "alias = X\n"
        "scaler = StandardScaler()\n"
        "scaler.fit(alias)\n"
        "scaled = scaler.transform(X)\n"
        "train, test = train_test_split(scaled)\n"
    )
    assert [item.rule_id for item in findings(source)] == ["ML001"]


@pytest.mark.parametrize(
    "body",
    [
        "other = StandardScaler()\nother.fit(X)\nscaled = scaler.transform(X)\n",
        "scaler.fit(X)\nscaler = StandardScaler()\nscaled = scaler.transform(X)\n",
        "scaler.fit(X)\nscaler.fit(train)\nscaled = scaler.transform(X)\n",
        "scaler.fit(X)\nmutate(scaler)\nscaled = scaler.transform(X)\n",
        "scaler.fit(X)\nscaler.set_params(with_mean=False)\nscaled = scaler.transform(X)\n",
        "mutate(scaler)\nscaler.fit(X)\nscaled = scaler.transform(X)\n",
        "scaler.fit(X)\nscaled = scaler.transform(other)\n",
        "scaler.transform(X)\nscaled = scaler.transform(X)\n",
    ],
)
def test_unknown_or_mismatched_instance_state_abstains(body):
    source = (
        "from data_fixture import X, train\n"
        "from sklearn.preprocessing import StandardScaler\n"
        "from sklearn.model_selection import train_test_split\n"
        "scaler = StandardScaler()\n" + body + "a, b = train_test_split(scaled)\n"
    )
    assert all(item.rule_id != "ML001" for item in findings(source))


def test_refit_replaces_previous_training_state():
    source = (
        "from data_fixture import X, X_train\n"
        "from sklearn.preprocessing import StandardScaler\n"
        "from sklearn.model_selection import train_test_split\n"
        "scaler = StandardScaler()\n"
        "scaler.fit(X)\n"
        "scaler.fit(X_train)\n"
        "scaled = scaler.transform(X)\n"
        "a, b = train_test_split(scaled)\n"
    )
    assert all(item.rule_id != "ML001" for item in findings(source))


def test_unmodeled_call_receiving_fit_input_invalidates_lineage():
    source = (
        "from data_fixture import X\n"
        "from custom_helpers import mutate\n"
        "from sklearn.preprocessing import StandardScaler\n"
        "from sklearn.model_selection import train_test_split\n"
        "scaler = StandardScaler()\n"
        "scaler.fit(X)\n"
        "mutate(X)\n"
        "scaled = scaler.transform(X)\n"
        "a, b = train_test_split(scaled)\n"
    )
    assert all(item.rule_id != "ML001" for item in findings(source))


def test_train_only_fit_then_transform_test_is_safe():
    source = (
        "from data_fixture import X\n"
        "from sklearn.model_selection import train_test_split\n"
        "from sklearn.preprocessing import StandardScaler\n"
        "train, test = train_test_split(X)\n"
        "scaler = StandardScaler()\n"
        "scaler.fit(train)\n"
        "train_scaled = scaler.transform(train)\n"
        "test_scaled = scaler.transform(test)\n"
        "a, b = train_test_split(train_scaled)\n"
    )
    assert all(item.rule_id != "ML001" for item in findings(source))


def test_unrelated_split_and_unbound_source_occurrences_abstain():
    source = (
        "from sklearn.preprocessing import StandardScaler\n"
        "from sklearn.model_selection import train_test_split\n"
        "scaler = StandardScaler()\n"
        "scaler.fit(X)\n"
        "scaled = scaler.transform(X)\n"
        "a, b = train_test_split(other)\n"
    )
    assert all(item.rule_id != "ML001" for item in findings(source))

    unbound = (
        "from sklearn.preprocessing import StandardScaler\n"
        "from sklearn.model_selection import train_test_split\n"
        "scaler = StandardScaler()\n"
        "scaler.fit(X)\n"
        "scaled = scaler.transform(X)\n"
        "a, b = train_test_split(scaled)\n"
    )
    assert all(item.rule_id != "ML001" for item in findings(unbound))


def test_custom_shadowed_component_does_not_resolve_to_sklearn():
    source = (
        "from data_fixture import X\n"
        "from sklearn.preprocessing import StandardScaler\n"
        "from sklearn.model_selection import train_test_split\n"
        "class LocalScaler:\n"
        "    def fit(self, X): pass\n"
        "    def transform(self, X): return X\n"
        "StandardScaler = LocalScaler\n"
        "scaler = StandardScaler()\n"
        "scaler.fit(X)\n"
        "scaled = scaler.transform(X)\n"
        "a, b = train_test_split(scaled)\n"
    )
    assert all(item.rule_id != "ML001" for item in findings(source))


def test_iterative_experimental_enable_import_is_only_parsed():
    source = (
        SPLIT
        + "from sklearn.experimental import enable_iterative_imputer\n"
        + "from sklearn.impute import IterativeImputer\n"
        + "imputer = IterativeImputer(random_state=3)\n"
        + "imputer.fit(X)\n"
        + "filled = imputer.transform(X)\n"
        + "train, test = split(filled)\n"
    )
    assert [item.rule_id for item in findings(source)] == ["ML002"]


def test_multiple_transforms_and_splits_are_deterministic_without_duplicate_findings():
    source = source_for("ML001", "StandardScaler") + (
        "scaled_again = transformer.transform(X)\ntrain2, test2 = split(scaled_again)\n"
    )
    first = [item for item in findings(source) if item.rule_id == "ML001"]
    second = [item for item in findings(source) if item.rule_id == "ML001"]
    assert first == second
    assert len(first) == 2
    assert [item.line for item in first] == [5, 5]


def test_notebook_same_cell_location_and_cross_cell_abstention():
    source = source_for("ML001", "StandardScaler")
    cells = [
        {
            "cell_type": "code",
            "metadata": {},
            "source": source,
            "outputs": [{"output_type": "stream", "text": "ignored"}],
        }
    ]
    result = Analyzer(default_registry()).analyze_notebook_json(
        json.dumps(
            {
                "nbformat": 4,
                "nbformat_minor": 5,
                "metadata": {"language_info": {"name": "python"}},
                "cells": cells,
            }
        ),
        path="book.ipynb",
    )
    finding = next(item for item in result.findings if item.rule_id == "ML001")
    assert (finding.cell_index, finding.cell, finding.line) == (1, 1, 5)

    first = source.split("train, test =")[0]
    second = (
        "from sklearn.model_selection import train_test_split as split\n"
        "train, test = split(scaled)\n"
    )
    cells[0]["source"] = first
    cells.append({"cell_type": "code", "metadata": {}, "source": second, "outputs": []})
    result = Analyzer(default_registry()).analyze_notebook_json(
        json.dumps(
            {
                "nbformat": 4,
                "nbformat_minor": 5,
                "metadata": {"language_info": {"name": "python"}},
                "cells": cells,
            }
        ),
        path="book.ipynb",
    )
    assert all(item.rule_id != "ML001" for item in result.findings)


def test_context_exposes_frozen_deterministic_fit_evidence():
    source = source_for("ML001", "StandardScaler")
    parsed = PythonSourceParser().parse_source(source, path="evidence.py")
    from statguard.context import AnalysisContext

    context = AnalysisContext(parsed)
    before = context.provenance.fitted_transforms
    assert before == context.provenance.fitted_transforms
    assert len(before) == 1
    assert before[0].fit.location.line == 5
    assert before[0].transform.location.line == 6
    with pytest.raises(FrozenInstanceError):
        before[0].instance_id = "changed"


@pytest.mark.parametrize(
    ("rule", "constructor", "options", "fit_args"),
    [
        ("ML001", "StandardScaler", "", "X"),
        ("ML002", "SimpleImputer", 'strategy="median"', "X"),
        ("ML003", "SelectKBest", "score_func=f_classif, k=10", "X, y"),
    ],
)
def test_cli_console_json_disable_and_exit_threshold(
    tmp_path, rule, constructor, options, fit_args
):
    path = tmp_path / "separate.py"
    path.write_text(source_for(rule, constructor, options, fit_args), encoding="utf-8")
    command = [sys.executable, "-m", "statguard", "check", str(path)]
    console = subprocess.run(command, capture_output=True, text=True, check=False)
    assert console.returncode == 0
    assert f"{rule} warning" in console.stdout

    json_result = subprocess.run(
        [*command, "--format", "json", "--fail-on", "warning"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert json_result.returncode == 1
    report = json.loads(json_result.stdout)
    assert len(report["findings"]) == 1
    assert report["findings"][0]["rule_id"] == rule
    assert report["findings"][0]["line"] == 5

    disabled = subprocess.run(
        [*command, "--disable-rule", rule],
        capture_output=True,
        text=True,
        check=False,
    )
    assert disabled.returncode == 0
    assert rule not in disabled.stdout


def test_separate_fit_scan_does_not_execute_source_or_notebook_output(tmp_path):
    marker = tmp_path / "executed"
    source = source_for("ML001", "StandardScaler") + (
        f"open({str(marker)!r}, 'w', encoding='utf-8').write('executed')\n"
    )
    path = tmp_path / "risk.py"
    path.write_text(source, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "statguard", "check", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "ML001 warning" in result.stdout
    assert not marker.exists()

    notebook_path = tmp_path / "risk.ipynb"
    notebook_path.write_text(
        json.dumps(
            {
                "nbformat": 4,
                "nbformat_minor": 5,
                "metadata": {"language_info": {"name": "python"}},
                "cells": [
                    {
                        "cell_type": "code",
                        "metadata": {},
                        "source": source,
                        "outputs": [
                            {
                                "output_type": "stream",
                                "text": f"open({str(marker)!r}, 'w').write('output executed')",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    notebook_result = subprocess.run(
        [sys.executable, "-m", "statguard", "check", str(notebook_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert notebook_result.returncode == 0
    assert "ML001 warning" in notebook_result.stdout
    assert not marker.exists()

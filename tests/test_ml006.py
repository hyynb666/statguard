"""ML006 random-split reproducibility rule tests."""

import json
import subprocess
import sys
from pathlib import Path

from statguard.analyzer import Analyzer
from statguard.core import Confidence, Evidence, Severity
from statguard.rules import default_registry


def source(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def ml006_findings(text: str):
    result = Analyzer(default_registry()).analyze_source(text, path="analysis.py")
    assert not result.errors
    return tuple(item for item in result.findings if item.rule_id == "ML006")


def run_cli(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "statguard", "check", str(path), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_missing_seed_is_a_located_confirmed_pattern_with_potential_risk():
    found = ml006_findings(
        source(
            "from sklearn.model_selection import train_test_split",
            "result = train_test_split(X, y)",
        )
    )
    assert len(found) == 1
    finding = found[0]
    assert (finding.rule_id, finding.line, finding.column) == ("ML006", 2, 10)
    assert (finding.severity, finding.confidence) == (Severity.INFO, Confidence.HIGH)
    assert finding.evidence is Evidence.CONFIRMED_CODE_PATTERN
    assert "may therefore produce different partitions" in finding.explanation
    assert "when reproducible data partitions are desired" in finding.suggestion


def test_none_seed_and_default_shuffle_report_but_fixed_integer_seeds_do_not():
    for expression in ("random_state=None", "random_state=NONE"):
        lines = ["from sklearn.model_selection import train_test_split"]
        if expression.endswith("NONE"):
            lines.append("NONE = None")
        lines.append(f"train_test_split(X, {expression})")
        assert len(ml006_findings(source(*lines))) == 1

    for seed in (0, 1, 42, 123, 2026):
        text = source(
            "from sklearn.model_selection import train_test_split",
            f"train_test_split(X, random_state={seed})",
        )
        assert ml006_findings(text) == ()


def test_seed_alias_and_point_of_use_rebinding_are_resolved_conservatively():
    safe = source(
        "from sklearn.model_selection import train_test_split",
        "SEED = 42",
        "random_state = SEED",
        "SEED = None",
        "train_test_split(X, random_state=random_state)",
    )
    assert ml006_findings(safe) == ()

    rebound_safe = source(
        "from sklearn.model_selection import train_test_split",
        "seed = None",
        "seed = 2026",
        "train_test_split(X, random_state=seed)",
    )
    assert ml006_findings(rebound_safe) == ()

    risky = source(
        "from sklearn.model_selection import train_test_split",
        "seed = 42",
        "seed = None",
        "train_test_split(X, random_state=seed)",
    )
    assert len(ml006_findings(risky)) == 1

    unknown = source(
        "from sklearn.model_selection import train_test_split",
        "seed = get_seed()",
        "train_test_split(X, random_state=seed)",
    )
    assert ml006_findings(unknown) == ()


def test_shuffle_false_literal_or_alias_suppresses_and_unknown_shuffle_abstains():
    base = "from sklearn.model_selection import train_test_split"
    assert ml006_findings(source(base, "train_test_split(X, shuffle=False)")) == ()
    assert (
        ml006_findings(source(base, "SHUFFLE = False", "train_test_split(X, shuffle=SHUFFLE)"))
        == ()
    )
    assert ml006_findings(source(base, "train_test_split(X, shuffle=True)"))
    assert ml006_findings(source(base, "train_test_split(X, shuffle=dynamic_value)")) == ()


def test_aliases_stratify_and_randomstate_omission():
    direct_alias = source(
        "from sklearn.model_selection import train_test_split as split",
        "split(X, y, test_size=0.2, stratify=y)",
    )
    module_alias = source(
        "import sklearn.model_selection as ms",
        "ms.train_test_split(X, y, stratify=y, random_state=42)",
    )
    package_alias = source(
        "from sklearn import model_selection as model_selection",
        "model_selection.train_test_split(X, y, stratify=y)",
    )
    assert len(ml006_findings(direct_alias)) == 1
    assert ml006_findings(module_alias) == ()
    assert len(ml006_findings(package_alias)) == 1


def test_custom_shadowed_and_rebound_same_name_functions_do_not_report():
    custom = source(
        "def train_test_split(*args, **kwargs):",
        "    return args",
        "train_test_split(X, y)",
    )
    shadowed = source(
        "from sklearn.model_selection import train_test_split",
        "def f(X):",
        "    def train_test_split(*args, **kwargs):",
        "        return args",
        "    return train_test_split(X)",
    )
    rebound = source(
        "from sklearn.model_selection import train_test_split as split",
        "split = custom_split",
        "split(X, y)",
    )
    assert ml006_findings(custom) == ()
    assert ml006_findings(shadowed) == ()
    assert ml006_findings(rebound) == ()


def test_dynamic_keyword_expansion_and_global_seed_calls_do_not_guess():
    dynamic = source(
        "from sklearn.model_selection import train_test_split",
        "train_test_split(X, **options)",
        "train_test_split(X, random_state=make_seed())",
        "train_test_split(X, shuffle=choose_shuffle())",
        "train_test_split(X, randomstate=None)",
    )
    global_seed = source(
        "import numpy as np",
        "from sklearn.model_selection import train_test_split",
        "np.random.seed(42)",
        "train_test_split(X)",
    )
    assert ml006_findings(dynamic) == ()
    assert len(ml006_findings(global_seed)) == 1


def test_only_random_train_test_split_calls_are_considered():
    source_text = source(
        "from sklearn.model_selection import train_test_split",
        "train_test_split(X, y)",
        "train_test_split(X, y, random_state=12)",
        "train_test_split(X, y, shuffle=False)",
    )
    first = ml006_findings(source_text)
    second = ml006_findings(source_text)
    assert first == second
    assert len(first) == 1
    assert first[0].line == 2


def test_cli_console_json_html_disable_fail_threshold_and_ml001_coexist(tmp_path: Path):
    risk = tmp_path / "risk.py"
    risk.write_text(
        source(
            "from sklearn.preprocessing import StandardScaler",
            "from sklearn.model_selection import train_test_split",
            "scaled = StandardScaler().fit_transform(X)",
            "train, test = train_test_split(scaled)",
        ),
        encoding="utf-8",
    )

    console = run_cli(risk)
    assert console.returncode == 0  # ML006 is informational by PRD-conscious design.
    assert "ML001" in console.stdout and "ML006" in console.stdout
    assert "info" in console.stdout

    json_result = run_cli(risk, "--format", "json")
    payload = json.loads(json_result.stdout)
    ids = [item["rule_id"] for item in payload["findings"]]
    assert ids == ["ML001", "ML006"]
    ml006 = payload["findings"][1]
    assert (ml006["severity"], ml006["confidence"]) == ("info", "high")
    assert ml006["evidence"] == "confirmed code pattern"
    assert ml006["line"] == 4

    html_result = run_cli(risk, "--format", "html")
    assert html_result.returncode == 0
    assert "ML006" in html_result.stdout and "ML001" in html_result.stdout
    assert 'option value="ML006"' in html_result.stdout
    assert "Content-Security-Policy" in html_result.stdout

    disabled = run_cli(risk, "--format", "json", "--disable-rule", "ML006")
    disabled_ids = {item["rule_id"] for item in json.loads(disabled.stdout)["findings"]}
    assert disabled_ids == {"ML001"}

    threshold = run_cli(risk, "--fail-on", "warning")
    assert threshold.returncode == 1  # ML001 crosses the threshold; ML006 does not.
    ml006_only = tmp_path / "ml006.py"
    ml006_only.write_text(
        "from sklearn.model_selection import train_test_split\ntrain_test_split(X)\n",
        encoding="utf-8",
    )
    assert run_cli(ml006_only, "--fail-on", "warning").returncode == 0
    assert run_cli(ml006_only, "--fail-on", "error").returncode == 0


def test_notebook_location_and_no_code_or_output_execution(tmp_path: Path):
    marker = tmp_path / "must-not-exist.txt"
    notebook_path = tmp_path / "random_split.ipynb"
    notebook = {
        "cells": [
            {"cell_type": "markdown", "metadata": {}, "source": ["# Reproducibility"]},
            {
                "cell_type": "code",
                "execution_count": 1,
                "metadata": {},
                "outputs": [
                    {
                        "output_type": "stream",
                        "name": "stdout",
                        "text": (
                            "from pathlib import Path\n"
                            f"Path({str(marker)!r}).write_text('output ran')\n"
                        ),
                    }
                ],
                "source": [
                    "from pathlib import Path\n",
                    f"Path({str(marker)!r}).write_text('code ran')\n",
                    "from sklearn.model_selection import train_test_split\n",
                    "train_test_split(X)\n",
                ],
            },
        ],
        "metadata": {"kernelspec": {"language": "python"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    notebook_path.write_text(json.dumps(notebook), encoding="utf-8")
    result = run_cli(notebook_path, "--format", "json")
    payload = json.loads(result.stdout)
    findings = [item for item in payload["findings"] if item["rule_id"] == "ML006"]
    assert len(findings) == 1
    assert (findings[0]["cell_index"], findings[0]["cell"], findings[0]["line"]) == (2, 1, 4)
    assert result.returncode == 0
    assert not marker.exists()


def test_python_cli_never_executes_source(tmp_path: Path):
    marker = tmp_path / "source-executed.txt"
    path = tmp_path / "safe_to_scan.py"
    path.write_text(
        source(
            "from pathlib import Path",
            f"Path({str(marker)!r}).write_text('ran')",
            "from sklearn.model_selection import train_test_split",
            "train_test_split(X)",
        ),
        encoding="utf-8",
    )
    result = run_cli(path, "--format", "json")
    assert result.returncode == 0
    assert "ML006" in {item["rule_id"] for item in json.loads(result.stdout)["findings"]}
    assert not marker.exists()


def test_default_registry_contains_one_independently_disableable_ml006():
    registry = default_registry()
    ids = [rule.rule_id for rule in registry.iter_enabled()]
    assert ids == [
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
    assert len(ids) == len(set(ids))
    registry.disable("ML006")
    assert "ML006" not in {rule.rule_id for rule in registry.iter_enabled()}

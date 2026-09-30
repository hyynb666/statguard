"""Cross-process, cross-hash-seed report determinism integration coverage."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run_report(project: Path, report_format: str, hash_seed: str) -> bytes:
    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = hash_seed
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "statguard",
            "check",
            str(project),
            "--format",
            report_format,
            "--no-config",
        ],
        cwd=project,
        env=environment,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    assert completed.stderr == b""
    return completed.stdout


def test_reporters_are_byte_deterministic_across_python_hash_seeds(tmp_path: Path) -> None:
    project = tmp_path / "representative-project"
    project.mkdir()
    (project / "01_pre_split.py").write_text(
        "\n".join(
            (
                "from sklearn.model_selection import train_test_split as split",
                "from sklearn.preprocessing import StandardScaler as Scale",
                "scaled = Scale().fit_transform(X)",
                "train, test = split(scaled, random_state=42)",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    (project / "02_test_fit.py").write_text(
        "\n".join(
            (
                "from sklearn.linear_model import LogisticRegression",
                "from sklearn.model_selection import train_test_split",
                "X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)",
                "model = LogisticRegression()",
                "model.fit(X_test, y_test)",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    (project / "03_multiple_tests.py").write_text(
        "\n".join(
            (
                "from scipy.stats import ttest_ind",
                "for feature in features:",
                "    _, pvalue = ttest_ind(a[feature], b[feature])",
                "    if pvalue <= 0.01:",
                "        selected.append(feature)",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    (project / "04_separate_preprocessing.py").write_text(
        "\n".join(
            (
                "from sklearn.model_selection import train_test_split",
                "from sklearn.preprocessing import StandardScaler",
                "X_train, X_test = train_test_split(X, random_state=42)",
                "StandardScaler().fit_transform(X_train)",
                "StandardScaler().fit_transform(X_test)",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    marker = tmp_path / "determinism-source-was-executed"
    (project / "05_no_execution.py").write_text(
        f"open({str(marker)!r}, 'w').write('executed')\n", encoding="utf-8"
    )
    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"language_info": {"name": "python"}},
        "cells": [
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [
                    {
                        "output_type": "display_data",
                        "data": {
                            "text/plain": (
                                "from sklearn.model_selection import train_test_split\n"
                                "# statguard: ignore ML001\n"
                                f"open({str(marker)!r}, 'w').write('output executed')"
                            ),
                            "text/html": f"<script>open('{marker}', 'w')</script>",
                        },
                        "metadata": {},
                    }
                ],
                "source": "value = 1\n",
            }
        ],
    }
    (project / "06_output_notebook.ipynb").write_text(
        json.dumps(notebook, ensure_ascii=False), encoding="utf-8"
    )

    outputs: dict[str, bytes] = {}
    for report_format in ("console", "json", "html", "sarif"):
        first = _run_report(project, report_format, "1")
        second = _run_report(project, report_format, "999")
        assert first == second, f"{report_format} bytes changed across hash seeds"
        outputs[report_format] = first
    assert not marker.exists()

    json_report = json.loads(outputs["json"])
    rule_ids = [item["rule_id"] for item in json_report["findings"]]
    assert {"ML001", "ML004", "ML008", "ST001"}.issubset(rule_ids)
    order = [
        (
            item["file_path"],
            item["cell_index"] or 0,
            item["line"],
            item["column"] or 0,
            item["rule_id"],
        )
        for item in json_report["findings"]
    ]
    assert order == sorted(order)

    sarif = json.loads(outputs["sarif"])
    run = sarif["runs"][0]
    descriptors = [item["id"] for item in run["tool"]["driver"]["rules"]]
    assert descriptors == sorted(descriptors)
    fingerprints = [
        item["partialFingerprints"]["statguardFingerprint/v1"] for item in run["results"]
    ]
    assert len(fingerprints) == len(set(fingerprints))
    assert "confidence-filter" in outputs["html"].decode("utf-8")

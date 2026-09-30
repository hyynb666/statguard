"""Smoke and input-validation tests for the stdlib synthetic benchmark."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark_statguard.py"


def test_smoke_profile_writes_machine_readable_metrics_without_paths(tmp_path: Path) -> None:
    destination = tmp_path / "nested" / "bench.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--profile",
            "smoke",
            "--repeat",
            "1",
            "--json-output",
            str(destination),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "files=14" in result.stdout
    assert "findings=" in result.stdout
    assert destination.is_file()

    raw = destination.read_text(encoding="utf-8")
    report = json.loads(raw)
    assert str(tmp_path) not in raw
    assert report["benchmark_schema_version"] == "1"
    assert report["tool"] == "statguard-benchmark"
    assert report["profile"] == "smoke"
    assert report["repeat_count"] == 1
    assert report["warmup_count"] == 1
    assert report["python_version"] == sys.version.split()[0]

    workload = report["workload"]
    assert workload["python_files"] == 12
    assert workload["notebooks"] == 2
    assert workload["notebook_code_cells"] == 6
    assert workload["scannable_files"] == 14
    assert workload["source_lines"] > 0
    assert set(workload["template_counts"]) == {
        "safe-sklearn-workflow",
        "pre-split-scaler",
        "test-data-model-fit",
        "grid-search-test-data",
        "separate-partition-preprocessing",
        "scipy-significance-loop",
        "alias-and-provenance-chain",
        "ordinary-python",
    }

    measurement = report["measurement"]
    assert measurement["timer"] == "time.perf_counter"
    assert len(measurement["elapsed_seconds"]) == 1
    assert 0 < measurement["min_seconds"] == measurement["median_seconds"]
    assert measurement["median_seconds"] == measurement["max_seconds"]
    assert measurement["scanned_files"] == 14
    assert measurement["finding_count"] >= 0
    assert measurement["analysis_error_count"] == 0
    assert measurement["notice_count"] >= 0
    assert measurement["files_per_second_at_median"] > 0
    assert measurement["notebook_outputs_ignored"] is True
    assert measurement["no_execution_marker_absent"] is True


def test_benchmark_rejects_bad_arguments_without_tracebacks(tmp_path: Path) -> None:
    for arguments in (("--profile", "unknown"), ("--repeat", "0")):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "Traceback" not in result.stderr


def test_repeated_benchmark_scans_require_identical_reports(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--profile",
            "smoke",
            "--repeat",
            "2",
            "--json-output",
            str(tmp_path / "repeat.json"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "repeat.json").read_text(encoding="utf-8"))
    assert report["repeat_count"] == 2
    assert len(report["measurement"]["elapsed_seconds"]) == 2


def test_benchmark_reports_unwritable_json_path_cleanly(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("occupied", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--profile",
            "smoke",
            "--repeat",
            "1",
            "--json-output",
            str(blocker / "report.json"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert result.stderr.startswith("benchmark error: ")
    assert "Traceback" not in result.stderr

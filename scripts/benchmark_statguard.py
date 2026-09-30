#!/usr/bin/env python3
"""Measure deterministic synthetic scans using an installed StatGuard package.

This contributor tool is intentionally stdlib-only. Generated Python and
Notebook files are untrusted scan inputs; this script never imports or runs
them.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from statguard import __version__
from statguard.analyzer import Analyzer
from statguard.parsers import NotebookParser
from statguard.rules import default_registry

BENCHMARK_SCHEMA_VERSION = "1"
MARKER_NAME = "STATGUARD_BENCHMARK_SHOULD_NOT_EXIST"


@dataclass(frozen=True, slots=True)
class Profile:
    python_files: int
    notebooks: int
    code_cells_per_notebook: int


PROFILES = {
    "smoke": Profile(12, 2, 3),
    "medium": Profile(200, 20, 5),
    "stress": Profile(1000, 50, 10),
}

_TEMPLATES: tuple[tuple[str, str], ...] = (
    (
        "safe-sklearn-workflow",
        "\n".join(
            (
                "from sklearn.model_selection import train_test_split",
                "from sklearn.preprocessing import StandardScaler",
                "X_train, X_test = train_test_split(X, random_state=42)",
                "scaler = StandardScaler()",
                "X_train_scaled = scaler.fit_transform(X_train)",
                "X_test_scaled = scaler.transform(X_test)",
            )
        ),
    ),
    (
        "pre-split-scaler",
        "\n".join(
            (
                "from sklearn.model_selection import train_test_split",
                "from sklearn.preprocessing import StandardScaler",
                "X_scaled = StandardScaler().fit_transform(X)",
                "X_train, X_test = train_test_split(X_scaled, random_state=42)",
            )
        ),
    ),
    (
        "test-data-model-fit",
        "\n".join(
            (
                "from sklearn.linear_model import LogisticRegression",
                "from sklearn.model_selection import train_test_split",
                "X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)",
                "model = LogisticRegression()",
                "model.fit(X_test, y_test)",
            )
        ),
    ),
    (
        "grid-search-test-data",
        "\n".join(
            (
                "from sklearn.linear_model import LogisticRegression",
                "from sklearn.model_selection import GridSearchCV, train_test_split",
                "X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)",
                "search = GridSearchCV(LogisticRegression(), {'C': [0.1, 1.0]})",
                "search.fit(X_test, y_test)",
            )
        ),
    ),
    (
        "separate-partition-preprocessing",
        "\n".join(
            (
                "from sklearn.model_selection import train_test_split",
                "from sklearn.preprocessing import StandardScaler",
                "X_train, X_test = train_test_split(X, random_state=42)",
                "StandardScaler().fit_transform(X_train)",
                "StandardScaler().fit_transform(X_test)",
            )
        ),
    ),
    (
        "scipy-significance-loop",
        "\n".join(
            (
                "from scipy.stats import ttest_ind",
                "for feature in features:",
                "    _, pvalue = ttest_ind(group_a[feature], group_b[feature])",
                "    if pvalue < 0.05:",
                "        selected.append(feature)",
            )
        ),
    ),
    (
        "alias-and-provenance-chain",
        "\n".join(
            (
                "import sklearn.model_selection as selection",
                "import sklearn.preprocessing as prep",
                "X_train, X_test = selection.train_test_split(X, random_state=42)",
                "base = X_train",
                "alias = base",
                "scaled = prep.StandardScaler().fit_transform(alias)",
            )
        ),
    ),
    (
        "ordinary-python",
        "\n".join(
            (
                "def normalize(value: int) -> int:",
                "    return value + 1",
                "result = normalize(4)",
            )
        ),
    ),
)


class BenchmarkError(RuntimeError):
    """A generated workload or scan failed its correctness checks."""


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer greater than or equal to 1") from error
    if number < 1:
        raise argparse.ArgumentTypeError("must be an integer greater than or equal to 1")
    return number


def _notebook_json(cells: list[dict[str, Any]]) -> str:
    document = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"language_info": {"name": "python"}},
        "cells": cells,
    }
    return json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n"


def _verify_notebook_outputs_ignored() -> None:
    """Use identical source/path to prove outputs do not affect rule inputs."""
    source = "value = 1\n"
    ghost_source = "\n".join(
        (
            "from sklearn.model_selection import train_test_split",
            "from sklearn.preprocessing import StandardScaler",
            "X_scaled = StandardScaler().fit_transform(X)",
            "X_train, X_test = train_test_split(X_scaled, random_state=42)",
            "# statguard: ignore ML001",
            f"open({MARKER_NAME!r}, 'w').write('executed')",
        )
    )

    plain = NotebookParser().parse_json(
        _notebook_json(
            [
                {
                    "cell_type": "code",
                    "execution_count": 1,
                    "metadata": {},
                    "outputs": [],
                    "source": source,
                }
            ]
        ),
        path="output-check.ipynb",
    )
    with_output = NotebookParser().parse_json(
        _notebook_json(
            [
                {
                    "cell_type": "code",
                    "execution_count": 1,
                    "metadata": {},
                    "outputs": [
                        {
                            "output_type": "display_data",
                            "data": {"text/plain": ghost_source, "text/html": MARKER_NAME},
                            "metadata": {},
                        }
                    ],
                    "source": source,
                }
            ]
        ),
        path="output-check.ipynb",
    )
    analyzer = Analyzer(default_registry())
    plain_result = analyzer.analyze(plain)
    output_result = analyzer.analyze(with_output)
    plain_signature = (
        plain_result.findings,
        plain_result.errors,
        plain_result.notices,
        plain_result.status,
    )
    output_signature = (
        output_result.findings,
        output_result.errors,
        output_result.notices,
        output_result.status,
    )
    if plain_signature != output_signature:
        raise BenchmarkError("Notebook output changed analysis results")


def _generate_workload(root: Path, profile: Profile) -> dict[str, Any]:
    python_root = root / "python"
    notebook_root = root / "notebooks"
    python_root.mkdir(parents=True)
    notebook_root.mkdir()
    marker = root / MARKER_NAME
    template_counts = dict.fromkeys((name for name, _ in _TEMPLATES), 0)
    source_lines = 0
    for index in range(profile.python_files):
        name, source = _TEMPLATES[index % len(_TEMPLATES)]
        if index % len(_TEMPLATES) == len(_TEMPLATES) - 1:
            source += f"\nfrom pathlib import Path\nPath({str(marker)!r}).write_text('executed')"
        source += "\n"
        destination = python_root / f"module_{index:04d}.py"
        destination.write_text(source, encoding="utf-8")
        source_lines += len(source.splitlines())
        template_counts[name] += 1

    code_cells = 0
    for notebook_index in range(profile.notebooks):
        cells: list[dict[str, Any]] = []
        for cell_index in range(profile.code_cells_per_notebook):
            template_index = (notebook_index + cell_index) % len(_TEMPLATES)
            name, source = _TEMPLATES[template_index]
            outputs: list[dict[str, Any]] = []
            if notebook_index == 0 and cell_index == 0:
                outputs = [
                    {
                        "output_type": "display_data",
                        "data": {
                            "text/plain": f"# statguard: ignore ML001\n{MARKER_NAME}",
                            "text/html": "<script>notebook output is data</script>",
                        },
                        "metadata": {},
                    }
                ]
            cells.append(
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {"benchmark_template": name},
                    "outputs": outputs,
                    "source": source + "\n",
                }
            )
            source_lines += len(source.splitlines())
            template_counts[name] += 1
            code_cells += 1
        destination = notebook_root / f"notebook_{notebook_index:03d}.ipynb"
        destination.write_text(_notebook_json(cells), encoding="utf-8")

    if marker.exists():
        raise BenchmarkError("no-execution marker existed before scanning")
    return {
        "python_files": profile.python_files,
        "notebooks": profile.notebooks,
        "notebook_code_cells": code_cells,
        "source_lines": source_lines,
        "scannable_files": profile.python_files + profile.notebooks,
        "template_counts": template_counts,
        "description": (
            "Fixed rotation of synthetic Python and Python Notebook source templates: "
            + ", ".join(name for name, _ in _TEMPLATES)
            + ". All generated files are scanned as untrusted source; none is executed."
        ),
    }


def _scan(root: Path, *, expected_files: int, marker: Path) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "statguard",
        "check",
        str(root),
        "--format",
        "json",
        "--no-config",
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as error:
        raise BenchmarkError(f"cannot launch StatGuard CLI: {type(error).__name__}") from error
    if completed.returncode != 0:
        raise BenchmarkError(f"StatGuard CLI returned exit code {completed.returncode}")
    if completed.stderr:
        raise BenchmarkError("StatGuard CLI wrote unexpected diagnostics to stderr")
    try:
        report = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise BenchmarkError("StatGuard CLI did not return valid JSON") from error
    if not isinstance(report, dict) or report.get("tool") != "statguard":
        raise BenchmarkError("StatGuard CLI report has an invalid structure")
    if report.get("version") != __version__:
        raise BenchmarkError("StatGuard CLI version differs from the imported package")
    summary = report.get("summary")
    if not isinstance(summary, dict):
        raise BenchmarkError("StatGuard CLI report has no summary object")
    if summary.get("scanned_files") != expected_files:
        raise BenchmarkError("scanned file count does not match generated profile")
    if summary.get("complete_files") != expected_files:
        raise BenchmarkError("one or more generated files did not complete analysis")
    errors = report.get("analysis_errors")
    notices = report.get("notices")
    if not isinstance(errors, list) or not isinstance(notices, list):
        raise BenchmarkError("StatGuard CLI report has invalid error or notice collections")
    error_codes = sorted({item.get("code", "unknown") for item in errors if isinstance(item, dict)})
    notice_codes = sorted(
        {item.get("code", "unknown") for item in notices if isinstance(item, dict)}
    )
    unexpected_notices = set(notice_codes) - {"document_order"}
    if errors or unexpected_notices:
        raise BenchmarkError(
            f"generated workload produced analysis errors {error_codes} or "
            f"unexpected notices {sorted(unexpected_notices)}"
        )
    if not isinstance(report.get("findings"), list) or not isinstance(report.get("files"), list):
        raise BenchmarkError("StatGuard CLI report is missing findings or file records")
    if len(report["files"]) != expected_files:
        raise BenchmarkError("file records do not match generated profile")
    if marker.exists():
        raise BenchmarkError("generated Python source was executed")
    return report


def _round_seconds(value: float) -> float:
    return round(value, 6)


def run_benchmark(profile_name: str, repeat_count: int) -> dict[str, Any]:
    """Generate and scan one immutable workload, returning measurement metadata."""
    profile = PROFILES[profile_name]
    _verify_notebook_outputs_ignored()
    with tempfile.TemporaryDirectory(prefix="statguard-benchmark-") as temporary:
        root = Path(temporary) / "project"
        root.mkdir()
        marker = Path(temporary) / MARKER_NAME
        workload = _generate_workload(root, profile)
        expected_files = workload["scannable_files"]

        reference_report = _scan(root, expected_files=expected_files, marker=marker)
        durations: list[float] = []
        last_report: dict[str, Any] | None = None
        for _ in range(repeat_count):
            started = time.perf_counter()
            report = _scan(root, expected_files=expected_files, marker=marker)
            durations.append(time.perf_counter() - started)
            if report != reference_report:
                raise BenchmarkError("identical repeated scans returned different reports")
            last_report = report
        if marker.exists():
            raise BenchmarkError("no-execution marker was created during benchmark")
        assert last_report is not None
        elapsed_min = min(durations)
        elapsed_median = statistics.median(durations)
        elapsed_max = max(durations)
        scanned_files = last_report["summary"]["scanned_files"]
        return {
            "benchmark_schema_version": BENCHMARK_SCHEMA_VERSION,
            "tool": "statguard-benchmark",
            "statguard_version": __version__,
            "profile": profile_name,
            "repeat_count": repeat_count,
            "warmup_count": 1,
            "python_version": platform.python_version(),
            "python_implementation": sys.implementation.name,
            "platform": {"system": platform.system(), "machine": platform.machine()},
            "workload": workload,
            "measurement": {
                "timer": "time.perf_counter",
                "elapsed_seconds": [_round_seconds(value) for value in durations],
                "min_seconds": _round_seconds(elapsed_min),
                "median_seconds": _round_seconds(elapsed_median),
                "max_seconds": _round_seconds(elapsed_max),
                "scanned_files": scanned_files,
                "finding_count": len(last_report["findings"]),
                "analysis_error_count": len(last_report["analysis_errors"]),
                "notice_count": last_report["summary"]["notices"],
                "files_per_second_at_median": round(scanned_files / elapsed_median, 3),
                "notebook_outputs_ignored": True,
                "no_execution_marker_absent": True,
            },
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(PROFILES), default="smoke")
    parser.add_argument("--repeat", type=_positive_int, default=3)
    parser.add_argument("--json-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = run_benchmark(args.profile, args.repeat)
        rendered = json.dumps(result, ensure_ascii=True, indent=2) + "\n"
        if args.json_output is not None:
            args.json_output.parent.mkdir(parents=True, exist_ok=True)
            args.json_output.write_text(rendered, encoding="utf-8")
        measurement = result["measurement"]
        workload = result["workload"]
        print(
            f"StatGuard benchmark profile={result['profile']} "
            f"files={workload['scannable_files']} "
            f"python_files={workload['python_files']} notebooks={workload['notebooks']} "
            f"code_cells={workload['notebook_code_cells']} repeats={result['repeat_count']}"
        )
        print(
            "elapsed seconds: "
            f"min={measurement['min_seconds']:.6f} "
            f"median={measurement['median_seconds']:.6f} "
            f"max={measurement['max_seconds']:.6f}; "
            f"findings={measurement['finding_count']} "
            f"analysis_errors={measurement['analysis_error_count']} "
            f"notices={measurement['notice_count']}"
        )
        if args.json_output is not None:
            print("benchmark JSON written")
    except (BenchmarkError, OSError) as error:
        print(f"benchmark error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

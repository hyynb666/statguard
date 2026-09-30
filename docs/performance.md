# Performance benchmark and quality hardening

`scripts/benchmark_statguard.py` is a standard-library-only harness for measuring
end-to-end CLI scans of deterministic synthetic projects. It invokes the
installed `statguard` command in a fresh subprocess for each measurement, so it
includes process startup, discovery, parsing, analysis, and JSON report
generation. It performs one warm-up scan, which is excluded from reported
measurements, then reports minimum, median, and maximum `time.perf_counter`
duration and files per second. Each measured JSON result must equal the warm-up
result for the same immutable generated tree; a result mismatch fails the run
independently of elapsed time.

The benchmark has no wall-clock pass/fail threshold. Timings depend on the
machine, Python build, filesystem, background load, and virtualized CI host;
measurements are useful for comparisons made under the same recorded
environment, not as service-level guarantees.

## Profiles

| Profile | Python files | Notebooks | Code cells per notebook | Scannable files |
| --- | ---: | ---: | ---: | ---: |
| `smoke` | 12 | 2 | 3 | 14 |
| `medium` | 200 | 20 | 5 | 220 |
| `stress` | 1,000 | 50 | 10 | 1,050 |

Workloads rotate through fixed templates covering ordinary Python, safe and
potentially risky sklearn workflows, model selection, preprocessing, and a
SciPy significance-test loop. The harness checks that all expected inputs
complete, output is valid JSON, there are no analysis errors, and the
no-execution marker was not created. Notebook output fields contain sentinel
text to exercise the guarantee that outputs do not affect analysis. The
Notebook document-order notice is expected and is not treated as an error.

Run from the repository root in a development environment with StatGuard
installed:

```text
python scripts/benchmark_statguard.py --profile smoke --repeat 3
python scripts/benchmark_statguard.py --profile medium --repeat 3 --json-output build/medium.json
python scripts/benchmark_statguard.py --profile stress --repeat 1 --json-output build/stress.json
```

The JSON result uses benchmark schema version `1`. It records the StatGuard and
Python versions, Python implementation, operating system and machine
architecture, profile dimensions and template counts, warm-up and repeat
counts, individual elapsed times, min/median/max, throughput, Finding/error/
notice counts, and the no-execution/output-ignored checks. It intentionally
does not record absolute temporary paths, usernames, hostnames, timestamps, or
source content. Use the same profile and repeat count before and after a change
and record the environment with the median when comparing results.

## CI and robustness checks

The package CI job builds the sdist and wheel, checks that development artifacts
are absent from the wheel, installs the wheel in an isolated environment,
self-scans the package source tree, and runs the benchmark smoke profile from
outside the checkout. The benchmark output is parsed and checked for a valid
schema, completed workload, and absence of analysis errors. CI does not apply a
timing threshold or upload benchmark artifacts.

The test suite also checks byte-identical Console, JSON, HTML, and SARIF output
across different `PYTHONHASHSEED` values; repeated scans of a many-file project;
a 50-code-cell notebook with cell-local analysis; and larger report collections.
These are bounded regression checks, not substitutes for workload-specific
measurement.

The harness is a developer tool and adds no runtime dependency. Generated
source and Notebook code are untrusted data; neither the benchmark nor StatGuard
executes it.

## Local reference measurement

The baseline was measured on the clean `main` source at commit
`b4529f766b87d8ee4e438f97c2bcb4cf23de5a33` before this quality-hardening change.
It used Python 3.12.4 (CPython) on Windows 11, AMD64, with profile `medium` and
three measured repeats after one unreported warm-up:

| Scanned files | Min (s) | Median (s) | Max (s) | Files/s at median |
| ---: | ---: | ---: | ---: | ---: |
| 220 | 0.346931 | 0.356882 | 0.390458 | 616.45 |

This is a reference measurement for the recorded environment only. It is not
an SLA, a guarantee, a CI threshold, or a before/after performance claim.

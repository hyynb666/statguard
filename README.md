# StatGuard

StatGuard is an early-stage static analyzer for statistical validity, model
evaluation, and reproducibility risks in Python scripts and Jupyter Notebooks.
It parses source without importing or executing submitted code. Version
`0.1.0.dev0` is a development version.

## Current capabilities and limits

The CLI scans individual `.py` and `.ipynb` files or directories recursively,
reports parse and rule failures, and renders Console or JSON results. Python
and Notebook parsing, AnalysisContext, Analyzer, Finding, Rule, and RuleRegistry
are available as Python APIs. Import aliases and basic assignment/call provenance
are available through AnalysisContext.symbols. Limited split and transformation
provenance is available through AnalysisContext.provenance.
**ML001 and ML002 are enabled detection rules.** ML001 reports potential scaler
preprocessing leakage; ML002 reports potential data-dependent imputation leakage
when the supported fit_transform output reaches a later train/test split. See
[ML001](docs/ml001.md) and [ML002](docs/ml002.md) for evidence requirements and
limitations.
A clean scan does not establish statistical correctness. No cross-cell data flow, directory
configuration file, or Notebook execution history analysis is implemented.

## Install from this repository

Requires Python 3.11+. CI covers Python 3.11–3.14 on Windows and Linux. This
project has not been published to PyPI.

```text
git clone https://github.com/hyynb666/statguard.git
cd statguard
python -m venv .venv
python -m pip install -e ".[dev]"
statguard --help
statguard --version
python -m statguard --version
```

Activate the environment first, or on Windows run
`.venv\Scripts\python.exe` and `.venv\Scripts\statguard.exe` directly.
PowerShell execution policy changes are not required.

## Scan commands

```text
statguard check analysis.py
statguard check experiment.ipynb
statguard check ./project
statguard check analysis.py --format json
statguard check analysis.py --format json --output reports/scan.json
statguard check ./project --exclude generated --exclude scratch/bad.py
statguard check ./project --fail-on warning
```

Directory scanning includes `.py` and `.ipynb` only, in sorted order.
Common VCS, virtual environment, cache and build directories are excluded by
default. `--exclude` is repeatable and takes a path relative to the scanned
directory; it excludes that path and everything beneath it. It applies to
directory scans. Symlinked directories are not followed. An empty directory
produces a notice rather than a claim of statistical safety.

`--output` creates missing parent directories and writes the selected report
format as UTF-8. It refuses to overwrite a scanned input. Without `--output`,
the report goes to stdout; JSON mode writes only valid JSON to stdout. Failed
report writes are reported on stderr.

Console output shows each Finding's location, severity, rule ID, evidence,
risk, and suggested fix, then file, diagnostic and scan-error totals. The JSON
schema is versioned and documented in [reporting.md](docs/reporting.md).
Parser errors, unsupported Notebook cells, and rule errors are distinct from
Findings. Scanning continues through other files and valid Notebook cells.

Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | Scan completed, and no enabled failure threshold was met. |
| 1 | Scan completed with a Finding at or above `--fail-on warning` or `--fail-on error`. |
| 2 | Invalid invocation, input/parse/rule error, or report write failure. |

Warnings do not fail by default. `--fail-on` sets a threshold explicitly.
This Issue #6 behavior follows the current task requirement and differs from
the initial PRD Section 3.3 default of exiting 1 for any Finding; review the
default policy before v0.1 release. An undetermined evidence category does not
trigger the threshold.

## APIs and architecture

```text
src/statguard/
  cli.py                 # command parsing and scan coordination
  scanner.py             # deterministic discovery and result aggregation
  context.py             # parsed unit and lazy symbol facts exposed to a rule
  symbols.py             # conservative import paths and versioned bindings
  analyzer.py            # parser-to-rule execution and structured results
  core/                  # Finding, Evidence, Severity, Confidence, Rule, RuleRegistry
  parsers/               # PythonSourceParser and NotebookParser
  reporters/             # Console and JSON rendering
  rules/                 # ML001, ML002, and the built-in registry
```

The Python parser uses `ast` and keeps original AST nodes and Unicode-aware
source locations. The Notebook parser delegates Python code cells to that parser
and retains original one-based `cell_index` plus one-based in-cell line and
column. Notebook document order is not proof of historical execution order.
Magic and shell syntax yield explicit cell errors. Markdown/raw cells and
stored outputs are not analyzed. JSON decoding necessarily reads the Notebook
container, but output fields are not retained or passed to rules.

`AnalysisContext` exposes the parsed unit to an explicitly registered trusted
rule. `Analyzer` calls enabled rules and returns Findings, parse/rule errors,
and Notebook notices separately, with `complete`, `partial`, or `failed`
status. Reporters only format those results. See the [Python parser](docs/python-parser.md),
[Notebook parser](docs/notebook-parser.md), [core interface](docs/core-interfaces.md),
[Analyzer](docs/analyzer.md), [symbol resolution](docs/symbols.md), and
[reporting](docs/reporting.md) contracts. Symbol resolution handles straight-line
module and independent function-local statements; outer-scope names, complex
control flow and runtime types remain unknown. Supported sklearn split outputs
and explicit supported scaler/imputer transformations have limited provenance
tracking; see [the provenance contract](docs/provenance.md).

## Development

```text
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m build
```

CI tests an installed package and builds an isolated wheel. See
[CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md); [docs/PRD.md](docs/PRD.md)
defines the product scope and rule acceptance criteria.

## License

StatGuard is available under the [MIT License](LICENSE).

Disable rules independently with `--disable-rule ML001` or `--disable-rule ML002`.
Warning findings exit 0 by default; use `--fail-on warning` to exit 1.

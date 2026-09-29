# StatGuard

StatGuard v0.2.0 is the current public Alpha release on GitHub: a conservative
static analyzer for statistical validity, model evaluation, and reproducibility
risks in Python scripts and Jupyter Notebooks. StatGuard parses source without
importing or executing submitted code.

## Why StatGuard?

StatGuard is a conservative static analyzer for statistical and machine-learning
workflow risks. It focuses on documented source patterns and traceable data
lineage; it is not a general-purpose Python linter or a validator of statistical
correctness. Findings are review prompts, not proof that an analysis is wrong.

## What's new in v0.2.0

- GitHub Composite Action for repository scans.
- Project policy through `[tool.statguard]` in `pyproject.toml`.
- SARIF 2.1.0 output and GitHub Code Scanning integration guidance.
- Workspace-contained Action inputs and outputs with Linux/Windows smoke tests.

This release adds integrations and project configuration; it does not add or
change detection rules.

## Current capabilities and limits

The CLI scans individual `.py` and `.ipynb` files or directories recursively,
reports parse and rule failures, and renders Console, JSON, HTML, or SARIF
results. Python and Notebook parsing, AnalysisContext, Analyzer, Finding, Rule,
and RuleRegistry are available as Python APIs. Import aliases and basic
assignment/call provenance are available through AnalysisContext.symbols.
Limited split and transformation provenance is available through
AnalysisContext.provenance.
**ML001–ML006, ML009, ST001 and ST002 are enabled detection rules.** ML001–ML003 report supported
preprocessing and feature-selection outputs that reach a later train/test split.
ML004 reports a supported estimator fit that receives test-role features or
labels. ML005 reports a supported sklearn estimator scored on its training
split without a corresponding held-out score in that model episode and scope;
training scores are not inherently wrong. ML006 flags resolved shuffled
`train_test_split` calls without a fixed integer seed as an informational
reproducibility prompt. ST001 reports a supported SciPy significance-test
p-value compared with a literal threshold in a potentially repeated `for`
loop. ST002 reports supported SciPy test calls whose complete result is a bare
expression or assigned to `_`; it does not imply a bug. See
[ML001](docs/ml001.md), [ML002](docs/ml002.md), [ML003](docs/ml003.md),
[ML004](docs/ml004.md), [ML005](docs/ml005.md), [ML006](docs/ml006.md),
[ML009](docs/ml009.md), [ST001](docs/st001.md), and [ST002](docs/st002.md) for
evidence requirements and limitations.
All eight v0.1 rules in PRD Section 5 are implemented; ML009 is an additional later rule.
ML009 reports supported fitted preprocessing output passed as `X` to a later
`cross_val_score` or `cross_validate` call. It reuses component semantics and
same-scope provenance from ML001–ML003; it does not inspect Pipeline internals.
ML009 remains the separate cross-validation preprocessing rule; ML005 retains
its PRD meaning of training-only evaluation.
A clean scan does not establish statistical correctness. No cross-cell data flow
or Notebook execution history analysis is implemented.

## Rule matrix

The v0.1 core comprises eight rules. ML009 is an additional rule and is not
included in that count.

| Rule ID | Name | Severity | Confidence | Primary API family | Status |
| --- | --- | --- | --- | --- | --- |
| ML001 | Pre-split scaler fit | warning | medium | `sklearn.preprocessing` | v0.1 core |
| ML002 | Pre-split imputer fit | warning | medium | `sklearn.impute` | v0.1 core |
| ML003 | Pre-split feature selection | warning | medium | `sklearn.feature_selection` | v0.1 core |
| ML004 | Fit on an explicit test set | warning | medium | sklearn estimators and `train_test_split` | v0.1 core |
| ML005 | Training-only evaluation | warning | medium | sklearn estimator `.score()` | v0.1 core |
| ML006 | Random split without a fixed seed | info | high | `train_test_split` | v0.1 core |
| ST001 | Repeated tests without observed correction | warning | medium | resolved `scipy.stats` tests | v0.1 core |
| ST002 | Discarded statistical test result | info | high | resolved `scipy.stats` tests | v0.1 core |
| ML009 | Preprocessing leakage before cross-validation | warning | medium | sklearn preprocessing and CV APIs | additional rule |

See [rule documentation](docs/) for supported patterns, evidence categories,
and limitations.

## Example diagnostic

The CLI scans the small [ML leakage example](examples/ml_leakage_example.py)
without executing it. The actual output is:

```text
examples\ml_leakage_example.py:8:14: ML001 warning: Potential preprocessing leakage before train/test split. [potential statistical risk]
  Risk: A known sklearn scaler's fitted transformation output flows into train_test_split at examples\ml_leakage_example.py:9:12, after fitting in the same scope. Information from the eventual test subset may influence preprocessing parameters. This static pattern does not establish actual leakage or measured model performance.
  Fix: Split the data before fitting the transformer. Fit preprocessing on the training subset and apply it to validation/test data, or use an appropriately configured sklearn Pipeline in the training workflow.
Scanned 1 files; findings: error 0, warning 1, info 0; files: complete 1, partial 0, failed 0; scan errors: parse 0, rule 0.
```

The path separator in this captured Windows output may differ on other systems.

The [statistics example](examples/statistics_example.py) demonstrates a
repeated-test prompt; [safe_workflow.py](examples/safe_workflow.py) demonstrates
a train-only preprocessing flow. To save a filterable report:

```text
statguard check examples/ml_leakage_example.py --format html --output report.html
```

## Notebook scope

StatGuard parses Notebook Python code cells independently. It does not execute
cells or analyze stored outputs. Document order does not establish historical
kernel execution order, and cross-cell data flow is not modeled. A clean scan
does not establish that a Notebook or analysis is statistically correct.

## Install v0.2.0

Requires Python 3.11+. CI covers Python 3.11–3.14 on Windows and Linux.
StatGuard is not published to PyPI. Install the tagged source:

```text
git clone --branch v0.2.0 --depth 1 https://github.com/hyynb666/statguard.git
cd statguard
python -m pip install .
statguard --help
statguard --version
python -m statguard --version
```

Alternatively, download the wheel attached to the
[v0.2.0 GitHub Release](https://github.com/hyynb666/statguard/releases/tag/v0.2.0)
and install it with `python -m pip install <wheel-path>`.

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
statguard check ./project --format html --output reports/scan.html
statguard check ./project --format sarif --output reports/scan.sarif
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
the report goes to stdout; JSON and SARIF modes write only their valid JSON
documents, and HTML mode writes a complete HTML document. HTML provides
rule/severity filters and
case-insensitive search over finding paths, rule IDs, and messages. Findings
remain expandable without JavaScript. Failed report writes are reported on
stderr.

Console output shows each Finding's location, severity, rule ID, evidence,
risk, and suggested fix, then file, diagnostic and scan-error totals. JSON
uses the documented schema. SARIF 2.1.0 is available for integrations such as
GitHub Code Scanning; Notebook cell locations remain SARIF properties and are
not represented as physical `.ipynb` JSON lines. HTML creates a self-contained,
offline report with escaped Finding text and scan status; it uses a fixed local filter script
pinned by a CSP hash and no remote resources.
Parser errors, unsupported Notebook cells, and rule errors are distinct from
Findings. See [reporting](docs/reporting.md) and the
[HTML report guide](docs/html-report.md). Scanning continues through other
files and valid Notebook cells.

Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | Scan completed, and no enabled failure threshold was met. |
| 1 | Scan completed with a Finding at or above `--fail-on warning` or `--fail-on error`. |
| 2 | Invalid invocation, input/parse/rule error, or report write failure. |

Warnings and informational findings do not fail by default. `--fail-on`
explicitly sets a threshold. An undetermined notice does not trigger it.
Disable ML001, ML002, ML003, ML004, ML005, ML006, ML009, ST001, or ST002
independently with `--disable-rule RULE_ID`.

### Project configuration

StatGuard can read `[tool.statguard]` from `pyproject.toml`. The supported
project policies are `exclude`, `disable-rules`, and `fail-on`; invocation
options such as path, report format, and output remain CLI-only. By default,
only `./pyproject.toml` in the current working directory is discovered. Use
`--config PATH` to select another TOML file or `--no-config` to bypass
discovery. CLI exclusions and disabled rules are appended to project values
and deduplicated in order; an explicit `--fail-on` overrides the configured
threshold. See [project configuration](docs/configuration.md) for validation,
discovery, and GitHub Action details.

## GitHub Action

StatGuard can run as a GitHub Actions step from the v0.2.0 release tag:

```yaml
jobs:
  statguard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: hyynb666/statguard@v0.2.0
        with:
          path: .
```

To make warning findings fail the step, add `fail-on: warning`. To save an HTML
report for a workflow to upload, use `format: html` and
`output: statguard-report.html`, then add your own
`actions/upload-artifact@v4` step. The Action does not upload artifacts.

StatGuard v0.2.0 is the first stable tagged release containing the Composite
Action. `@main` continues to track development and may change. See
[GitHub Action documentation](docs/github-action.md) for inputs, exclusions,
report formats, and security details.

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
  reporters/             # Console, JSON, HTML, and SARIF rendering
  rules/                 # ML001–ML006, ML009, ST001–ST002 and the built-in registry
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
and explicit supported scaler/imputer/feature-selector transformations have limited provenance
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

See also the [Code of Conduct](CODE_OF_CONDUCT.md), [Security Policy](SECURITY.md),
[v0.1 release audit](docs/release-audit-v0.1.md),
[v0.2 release audit](docs/release-audit-v0.2.md), and
[v0.2 release checklist](docs/release-checklist-v0.2.md). StatGuard is not published to
PyPI; install from the tagged source or the GitHub Release wheel.

## License

StatGuard is available under the [MIT License](LICENSE).

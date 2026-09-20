# StatGuard

StatGuard is an early-stage static analyzer for statistical validity, model
evaluation, and reproducibility risks in Python scripts and Jupyter Notebooks.
The planned analyzer reports conservative, explainable findings based on AST
evidence and data lineage. Submitted code must never be imported or executed.

## Current status

Milestone 1 now includes packaging, the help/version CLI, public data/rule
interfaces, Python and Notebook parsing APIs, and an Analyzer API for registered rules.
Version `0.1.0.dev0` remains a development version.
`statguard check`, text/JSON scan reports, and statistical detection rules are
**not implemented yet**. Parsing reports syntax, not statistical validity.

## Install from this repository

Requires Python 3.11+. CI covers Python 3.11–3.14 on Windows and Linux.
This repository has not been published to PyPI; install from the checkout:

```text
git clone https://github.com/hyynb666/statguard.git
cd statguard
python -m venv .venv
```

Activate it on Windows PowerShell with `.venv\Scripts\Activate.ps1`, or on
Linux/macOS with `source .venv/bin/activate`. If PowerShell activation is
unavailable, use `.venv\Scripts\python.exe` and `.venv\Scripts\statguard.exe`
directly; changing execution policy is not required.

```text
python -m pip install -e ".[dev]"
statguard --help
statguard --version
python -m statguard --version
```

`statguard --version` prints `statguard 0.1.0.dev0`. With no arguments, the CLI
prints help. These commands exit with `0`; unsupported arguments (including
`check`) exit with `2`. The future scan command and its exit codes are specified
in [the PRD](docs/PRD.md), not exposed as a pretend successful scan today.

## Package boundaries

```text
src/statguard/
  cli.py                 # help/version entry point, standard-library argparse
  context.py             # one parsed Python unit exposed to a rule
  analyzer.py            # parser-to-rule execution and structured results
  core/
    findings.py          # immutable Finding, Evidence, Severity and Confidence
    rule.py              # Rule[ContextT] protocol
    registry.py          # registration, validation and deterministic rule selection
  parsers/               # PythonSourceParser, NotebookParser, syntax records and errors
  rules/                 # no built-in rules yet
  reporters/             # reserved for text/JSON rendering
tests/
```

`statguard.core` exports `Finding`, `Evidence`, `Severity`, `Confidence`, `Rule`,
and `RuleRegistry`. Frozen findings expose severity, confidence, file path,
line/optional column, original Notebook cell index, message, explanation,
suggestion, and a separate PRD evidence category. Existing `path`, `risk`,
`recommendation` and code-cell `cell` fields remain supported. An undetermined
observation is not a confirmed violation.

Rules provide `rule_id`, `name`, `description`, `default_severity`, and
`check(context) -> Iterable[Finding]`. The registry validates metadata, rejects
duplicate IDs, and selects enabled rules in deterministic ID order. Existing
analyze-only rules retain registration/lookup compatibility through an adapter
for enabled selection. AnalysisContext and Analyzer now connect these APIs for
explicitly registered rules. No built-in detections or scan CLI are provided.
See [the core API](docs/core-interfaces.md) and [Analyzer API](docs/analyzer.md).

The Python parser converts AST byte offsets to one-based character columns.
Notebook results disclose document-order limitations and retain cell identity.

## Python parser API

```python
from statguard.parsers import PythonSourceParser, SourceParseError

parser = PythonSourceParser()
unit = parser.parse_source("import library as lib\nx = lib.run(data)\n", path="example.py")
print(unit.calls[0].name)  # lib.run (syntax only, not a resolved API)
print(unit.calls[0].location.column)  # 5

try:
    unit = parser.parse_file("analysis.py")
except SourceParseError as error:
    print(error.code, error.path, error.line, error.column, error.message)
```

The result retains source text, the original AST, and indexes of imports (including
aliases), Assign/AnnAssign statements, calls/arguments, and function definitions.
Dynamic callees such as `factory().fit()` have `name=None` and `is_unknown=True`;
the full expression remains available in the AST. Runtime values are never
evaluated, and imports are not resolved or loaded.

See [the parser API and limitations](docs/python-parser.md) for location semantics,
encoding support, error handling, and the boundary between syntax and analysis.

## Notebook parser API

```python
from statguard.parsers import NotebookParseError, NotebookParser

try:
    book = NotebookParser().parse_file("experiment.ipynb")
except NotebookParseError as error:
    print(error.issue)  # Fatal file, JSON, structure or language error.
else:
    for cell in book.code_cells:
        if cell.error is not None:
            print(cell.error)  # Failed cells are explicit; later cells still parse.
        else:
            print(cell.cell_index, cell.code_cell_index, cell.parsed.calls)
```

`parse_json(text, path="experiment.ipynb")` accepts Notebook JSON text. Only
explicitly declared Python notebooks in nbformat 4 are supported. Standard Python
code cells reuse `PythonSourceParser`; magic/shell syntax leaves the whole cell
unparsed with an error. Markdown and raw cells are not parsed as Python.

Both indexes are one-based: `cell_index` counts all original cells, while
`code_cell_index` counts code cells only and matches the future `Finding.cell`
convention. Locations within each parsed unit remain relative to its cell.
No code, commands, or outputs are executed. JSON decoding reads the container;
output fields are not analyzed, rendered, or retained in parser results.

See [Notebook API and limitations](docs/notebook-parser.md) for language metadata,
partial results, and the difference between document and execution order.

## Analyzer API

```python
from statguard.analyzer import Analyzer, AnalysisStatus
from statguard.context import AnalysisContext
from statguard.core import RuleRegistry

registry = RuleRegistry[AnalysisContext]()
# Register trusted rules explicitly; the package ships no detection rules yet.
result = Analyzer(registry).analyze_source("x = 1\n", path="analysis.py")
assert result.status is AnalysisStatus.COMPLETE
assert result.findings == result.errors == ()
```

`analyze_file(path)` handles one `.py` or `.ipynb` file; `analyze_notebook_json(text)`
accepts Notebook JSON; `analyze(parsed)` accepts an existing parser result.
Results keep Findings, parser/rule errors, and Notebook notices separate. A
partially parsed Notebook retains findings from valid cells and reports failed
cells explicitly. The Analyzer sorts and exactly deduplicates Findings, fills
Notebook cell identity, and never executes scanned source. It does not provide
cross-cell data flow, CLI scanning or text/JSON reporting. See [Analyzer behavior,
errors and limits](docs/analyzer.md).

## Development

```text
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m build
```

The build produces an sdist and wheel under `dist/`. CI tests an installed package
and verifies a wheel in an isolated environment. See [CONTRIBUTING.md](CONTRIBUTING.md)
and [AGENTS.md](AGENTS.md) for the workflow; [docs/PRD.md](docs/PRD.md) defines the
product scope and rule acceptance criteria.

## License

StatGuard is available under the [MIT License](LICENSE).

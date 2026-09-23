# Contributing to StatGuard

Read [AGENTS.md](AGENTS.md) and [docs/PRD.md](docs/PRD.md) before changing behavior.
The foundation includes packaging, CLI scanning, Console/JSON reporting, public
interfaces, Python and Notebook parsing, and Analyzer execution. Detection rules
belong to later issues. Agree on a scoped change before expanding the roadmap.

## Set up and validate

Use Python 3.11+ and a virtual environment as described in the README, then run:

```text
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m build
statguard --help
statguard --version
```

Use `python -m ruff format .` to apply formatting before the checks. Tests must
exercise the installed package; do not add the source directory to `PYTHONPATH`
or pytest's import path to hide packaging errors. CI repeats tests and lint on
Windows and Linux with Python 3.11–3.14 and checks a built wheel independently.

## Design and test expectations

- Keep parsing, conservative analysis facts, rule evaluation, registry metadata,
  findings, and reporting separate. Rules return findings and never print them.
- Never import target modules, execute notebook cells, evaluate submitted
  expressions, or invoke target code. Source and notebook content are untrusted.
- Require AST evidence and proven lineage/order when a rule depends on them.
  Coincident API names or variable names cannot establish statistical harm.
- When rule implementation begins, add positive, negative, boundary, and known
  limitation cases for every rule. Add regression tests for confirmed false
  positives/negatives and a no-execution test for parsers/scanning.
- Preserve uncertainty in evidence categories and wording. An undetermined
  observation must not become a confirmed violation or inflate finding counts.
- Keep output deterministic and document compatibility changes to IDs, public
  interfaces, JSON schema, and exit codes. The schema is documented in
  [docs/reporting.md](docs/reporting.md).

## Parser contributions

Follow [the parser API contract](docs/python-parser.md). Preserve the raw AST and
unknown dynamic expressions; do not resolve imported libraries or introduce rule
logic into syntax parsing. Treat `enclosing_definitions` as syntax ancestry, not
runtime scope or proof of execution order.

Test strings and files, Unicode character columns, multiline spans, source
encodings, explicit failures, and absence of target-code side effects. Simulate
permission-denied reads in tests rather than changing machine permissions.
Notebook support reuses `parse_source` and maps cell identity separately. Follow
[the Notebook contract](docs/notebook-parser.md): test both cell indexes, mixed
cell types, partial parse errors, magic/shell syntax, language metadata, and
ignored outputs. Existing core interfaces remain unchanged.

## Core interface contributions

Follow [the core interface contract](docs/core-interfaces.md). Keep Evidence
separate from severity and confidence. Preserve Finding's legacy field names and
constructor order, and distinguish the original Notebook cell index from the
code-cell ordinal. Use fixture rules to test check/metadata and registry selection
without mixing statistical decisions into the core interfaces. Cover invalid metadata,
duplicate IDs, deterministic selection, enable/disable behavior, and analyze-only
rule compatibility. Registration must not execute the rule's detection method.

## Analyzer contributions

Follow [the Analyzer contract](docs/analyzer.md). Keep AnalysisContext scoped to
one parsed source unit and expose parser-owned AST/indexes without evaluating
source or Notebook output data. Use test-only fixture rules to verify enabled
selection, location mapping, exact deduplication, parser failures, rule failures,
and partial Notebook results. New rules must report their own evidence precisely;
Analyzer cannot infer statistical harm or repair an unsupported cell.

## Symbol resolution contributions

Follow [the symbol contract](docs/symbols.md). Preserve point-of-use binding
versions, parser-owned AST identity and independent function/cell scopes.
Never infer types from capitalization or library identity from coincident names.
Test alias shadowing, reassignment, control-flow barriers, dynamic operations
and unknown origins; recorded calls do not establish input/output lineage.

## Scanner and reporter contributions

Follow [the report contract](docs/reporting.md). Preserve stable traversal and
complete, partial, and failed statuses. Keep JSON stdout standalone and never
serialize AST, source, Notebook outputs, or arbitrary rule exception text.
Test file/Notebook/directory scans, exclusions, empty inputs, explicit errors,
exit codes, output writes, and no-execution behavior with test-only rules.
Review any proposed JSON schema or exit-code change before release.

## Review workflow

Create a focused branch, implement the smallest complete change, and run the
checks above. In the pull request, describe the behavior, relevant PRD acceptance
criteria, actual test results, and remaining limitations. Do not commit virtual
environments, generated distributions, caches, or credentials. Keep changes to
the product requirements explicit and reviewed.

Set the package version in `pyproject.toml`; CLI and Python package versions are
read from installed distribution metadata. Reinstall after changing that version.
Package publication and release tagging are separate operations and are not part
of a normal development push. Contributions are distributed under the project's
[MIT License](LICENSE).

## Provenance contributions

Follow [the provenance contract](docs/provenance.md). Keep syntactic call inputs
separate from proven data sources. Library return semantics belong in the small
adapter, with official documentation and negative cases for coincident names,
reassignment, unknown effects and ambiguous argument/output shapes. Never infer
train/test roles from variable spelling or generic method names.

## ML001 changes

Follow [the ML001 contract](docs/ml001.md). Preserve exact receiver provenance,
input lineage and same-scope evaluation order. Test safe train-only fitting,
unrelated inputs, alias/rebinding, unknown state and configuration that disables
learning. Medium confidence describes static risk, not measured model harm.

## ML002 changes

Follow [the ML002 contract](docs/ml002.md). Require an exact sklearn imputer
construction, proven fit_transform output lineage and same-scope order. Preserve
the distinction between data-dependent SimpleImputer strategies, fixed constant
replacement, KNN reference samples and Iterative fitted models. Dynamic strategy
semantics must cause conservative abstention.

## ML003 changes

Follow [the ML003 contract](docs/ml003.md). Require an exact supported sklearn
feature-selector construction, proven fit_transform output lineage, and
same-scope order. Supervised selector findings need a known score function and
an explicit target; VarianceThreshold must remain described as an unsupervised
variance operation. Unknown scoring semantics require abstention.

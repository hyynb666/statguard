# Analysis Context and Analyzer

`statguard.context.AnalysisContext` gives an explicitly registered rule a
read-only view of one successfully parsed Python unit. `statguard.analyzer.Analyzer`
connects the existing parsers and RuleRegistry, runs enabled rules, and returns
structured results. The CLI, scanner and reporters wrap this API; see
[reporting.md](reporting.md). The CLI enables [ML001](ml001.md),
[ML002](ml002.md), [ML003](ml003.md), and [ML004](ml004.md); Analyzer itself
still uses the explicitly supplied registry. Cross-unit data-flow analysis is
not included.

## Public Python API

```python
from statguard.analyzer import Analyzer, AnalysisStatus
from statguard.context import AnalysisContext
from statguard.core import RuleRegistry

registry = RuleRegistry[AnalysisContext]()
# Register explicit trusted Rule[AnalysisContext] instances here.
analyzer = Analyzer(registry)
result = analyzer.analyze_source("x = 1\n", path="example.py")
assert result.status is AnalysisStatus.COMPLETE
assert result.findings == ()
assert result.errors == ()
```

`Analyzer(registry, *, python_parser=None, notebook_parser=None)` accepts
existing parser instances for dependency injection. By default it creates
PythonSourceParser and a NotebookParser that reuses it. It offers:

| Method | Input |
| --- | --- |
| `analyze_file(path)` | Reads one `.py` or `.ipynb` file, case-insensitively. No directory traversal. |
| `analyze_source(source, *, path="<string>")` | Python source text, with a diagnostic path label. |
| `analyze_notebook_json(text, *, path="<notebook>")` | Notebook JSON text with a diagnostic path label. |
| `analyze(parsed)` | An existing ParsedSource or ParsedNotebook. It does not reparse or read files. |

An unsupported `analyze(parsed)` argument and non-string source arguments are API
misuse and raise TypeError. Input read, encoding, JSON, language, syntax, and
unsupported-file failures from supported entry points return an AnalysisResult
with errors, instead of a clean empty result. The underlying parser APIs still
raise their existing SourceParseError or NotebookParseError; those contracts are
unchanged. Passing an invalid Python object as a filesystem path is API misuse.

## Context scope and safety

`AnalysisContext.parsed` is the original ParsedSource. `source`, `tree`,
`imports`, `assignments`, `calls`, and `functions` expose the same objects as the
parser result. `path`/`file_path` use the parser's diagnostic path. Context is a
frozen container; treat its original AST as read-only because AST nodes remain
mutable. `is_notebook` identifies whether the unit came from a Notebook.

For a Python file or source string, `cell_index` and `cell` are None. For a
Notebook code cell, both are one-based: `cell_index` is its position among all
original cells, while `cell` is its ordinal among code cells (the PRD/Finding
convention). Line and column in Findings are relative to the code cell.
NotebookParser parses cells independently in document order; Context contains
one cell and no historical execution, external state, or cross-cell lineage.
Context.symbols lazily provides import paths and versioned basic bindings over
this AST; see [symbols.md](symbols.md). It supports straight-line module and
independent function-local statements. It does not infer runtime types,
cross-scope state, library implementations or statistical harm.

Analyzer never imports, evaluates, compiles for execution, or runs submitted
Python/Notebook code. Only explicitly registered, trusted rule objects are
called. NotebookParser decodes the JSON container, which necessarily reads
stored output data, but output fields are not visited for analysis, retained in
ParsedNotebook, or passed into AnalysisContext and rules. No notebook kernel,
shell, network service, or external API is used.

## Rule selection, output and locations

Analyzer snapshots `registry.iter_enabled()` once per analysis, then runs the
selected rules on each successful unit in rule-ID order. Cells are processed in document order. Selection,
registration, enable and disable operations do not call `Rule.check`.
Analyze-only legacy rules work through RuleRegistry's existing adapter. An empty
registry or a registry with all rules disabled still parses input and reports
parse failures; a valid input returns a complete empty result.

Each `Rule.check(context)` returns an iterable of Findings. The Analyzer checks
every item before accepting that rule's batch: it must be a Finding with the
selected rule ID and the context's path. On Notebook cells, omitted cell fields
are filled from Context; conflicting cell fields are rejected. On Python source,
cell fields must be absent. Rules provide their own actionable line and optional
column from parser locations. The Analyzer does not infer line/column, modify
Evidence or severity, or assert that an AST pattern is statistically harmful.

Findings are deduplicated by their full immutable value, then sorted by path,
code-cell ordinal, original cell index, line, column, rule ID, and all remaining
diagnostic fields as deterministic tie-breakers. A missing column/cell sorts
before a present one. Findings at different locations, or with different
messages, explanations, suggestions, evidence, severity, or confidence stay
separate. This matches the PRD primary sort keys and preserves exact distinct
observations. No report schema or exit-code policy is implemented here.

`AnalysisResult` includes `path`, `findings`, `errors`, `notices`,
`analyzed_units`, and `completed_units`. A unit is analyzed once if it parses,
even when no rules are enabled. It is completed when all selected rules finish
with valid results. `is_complete` means `errors` is empty. `status` is:

| AnalysisStatus | Meaning |
| --- | --- |
| COMPLETE | No parser or rule errors. Findings may be present or absent. |
| PARTIAL | One or more errors, and at least one code unit completed. Valid findings from other units/rules remain available. |
| FAILED | One or more errors, with no completed units. Findings from another rule can still be present for a failed unit. |

Parser input errors are `AnalysisError(stage=PARSE, code=<existing parser code>,
...)`. SourceParseError and NotebookIssue locations and codes are preserved,
including UNSUPPORTED_FILE, SYNTAX_ERROR, INVALID_JSON,
UNSUPPORTED_LANGUAGE, and UNSUPPORTED_SYNTAX. Unsupported Notebook cells are
reported in `errors` even when no rule is enabled. Notebook document-order
notices remain separate in `notices`, never become Findings.

Rule exceptions, including failures while creating or consuming iterators, are
`AnalysisError(stage=RULE, code=RULE_EXECUTION, rule_id=...)`. Noniterable
results, mapping/string results, non-Finding items, or mismatched rule/path/cell
identity are `INVALID_RULE_RESULT`. Error locations include the current file and
Notebook cell IDs when available. The Analyzer continues with other rules and
successfully parsed units. It discards Findings already yielded by the failing
rule for that unit, preventing a partial rule batch from looking complete.
Rule errors are kept distinct from parser errors and never become statistical
Findings. System-level interrupts such as KeyboardInterrupt are not swallowed.

The framework validates result shape and identity; it cannot prove a rule's
statistical reasoning, verify every source coordinate, or prevent a trusted
rule from deliberately executing code. Rule authors must follow AGENTS.md and
test their own evidence and abstention behavior. The built-in [ML001](ml001.md),
[ML002](ml002.md), [ML003](ml003.md), and [ML004](ml004.md) implementations
are documented separately.

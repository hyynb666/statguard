# CLI scan and report contract

Issue #6 connects file discovery and the existing Analyzer to Console and
JSON output. The default registry contains [ML001](ml001.md), [ML002](ml002.md),
[ML003](ml003.md), and [ML004](ml004.md).

## Python API and scope

`statguard.scanner.Scanner(analyzer).scan(path, *, exclude=())` returns
`ScanReport` with per-file `AnalysisResult` records, scan-level errors and
notices, aggregate Findings and errors, and the selected-rule count.
`statguard.reporters.render_console(report)` and `render_json(report)` are
pure formatters. Neither invokes parsers or rules. CLI `main(argv=None,
*, registry=None)` accepts an explicit registry for trusted integrations and
tests; the installed CLI uses a fresh default registry containing ML001, ML002,
ML003, and ML004. An explicit registry is used exactly as supplied. `--disable-rule` can
disable any built-in rule independently; unknown rule IDs are invocation errors. It never loads rules
from submitted source or Notebook content.

Directory traversal scans `.py` and `.ipynb` files in a stable path order.
It skips `.git`, `.hg`, `.svn`, `.venv`, `venv`, `env`, `__pycache__`,
`.tox`, `.nox`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`,
`.ipynb_checkpoints`, `build`, `dist`, `.eggs`, `*.egg-info`, and `node_modules`.
A repeated `--exclude RELATIVE_PATH` excludes that path and descendants
relative to the scan root. Absolute paths, parent traversal, and empty
exclusions are rejected. Symlinked directories are not traversed.
Unavailable subdirectories yield a scan error while other files continue.
Empty directories yield a `no_supported_files` notice and scan zero files.

## JSON schema 1.0

`schema_version` is `"1.0"`; any incompatible schema change needs review.
The top-level object has:

| Key | Value |
| --- | --- |
| `tool`, `version`, `schema_version` | Product and contract identity. |
| `summary` | `scanned_files`, severity counts `error`/`warning`/`info`, `complete_files`, `partial_files`, `failed_files`, `parse_errors`, `rule_errors`, `notices`, and `enabled_rules`. |
| `files` | Each scanned path, its `complete`/`partial`/`failed` status, and finding/error counts. |
| `findings` | `rule_id`, `severity`, `confidence`, `evidence`, `file_path`, `line`, nullable `column`, nullable original `cell_index`, nullable code-cell ordinal `cell`, `message`, `explanation`, and `suggestion`. |
| `analysis_errors` | `stage` (`parse` or `rule`), `code`, `file_path`, optional `rule_id`, `cell_index`, `cell`, `line`, `column`, and a safe `message`. |
| `notices` | `code`, `file_path`, `message`, and optional cell/line/column positions. |

File and finding order is deterministic; Analyzer deduplicates identical
Findings within each file. A Notebook Finding's `cell_index` counts all
original cells from one; `cell` counts code cells from one. Line and column
refer to the code cell. Parse and rule failures are never serialized as
Findings. Arbitrary exception text from a rule is omitted from rendered
`rule_execution` errors to avoid disclosing submitted or trusted-rule data.
JSON uses ASCII escapes for non-ASCII text so redirected stdout remains
parseable under Windows legacy code pages. Console stdout is UTF-8. JSON
never contains AST nodes, code, Notebook outputs, HTML, or images.
Notebook JSON decoding reads the container; output fields are not inspected
or passed to Analyzer.

A valid scan with no enabled rules has an empty `findings` list and
`enabled_rules: 0`. This indicates no rule diagnostics were produced, not
that the source is statistically correct. Partial Notebook parse errors remain
in `analysis_errors` alongside findings from valid cells. Notebook document
order does not establish historical execution order.

## Console and exit behavior

Console diagnostics show the same Finding fields as JSON, including evidence,
risk and fix. Both formats include scan errors and notices. `--output` writes
the chosen format as UTF-8, creates missing parent directories, and refuses
to replace a scanned input. A write failure returns 2 and writes a short
message to stderr.

Exit 2 takes precedence if any input, parse, rule, or output error occurs.
Otherwise `--fail-on warning` exits 1 for warning/error Findings, and
`--fail-on error` exits 1 for error Findings. Without a threshold, a
completed scan exits 0 even if Findings exist. An undetermined evidence
category never meets the threshold. This default is an explicit Issue #6
change from the initial PRD Section 3.3 statement that any Finding exits 1;
it requires product review before v0.1 release. No complete configuration
system or severity suppression is implemented.

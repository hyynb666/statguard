# CLI scan and report contract

The scanner and Analyzer expose report data for Console, JSON, HTML, and SARIF output.
The default registry contains [ML001](ml001.md), [ML002](ml002.md),
[ML003](ml003.md), [ML004](ml004.md), [ML005](ml005.md), [ML006](ml006.md),
[ML007](ml007.md), [ML008](ml008.md), [ML009](ml009.md), [ST001](st001.md), and [ST002](st002.md).

## Python API and scope

`statguard.scanner.Scanner(analyzer).scan(path, *, exclude=())` returns
`ScanReport` with per-file `AnalysisResult` records, scan-level errors and
notices, aggregate Findings and errors, and the selected-rule count.
`statguard.reporters.render_console(report)`, `render_json(report)`,
`render_html(report)`, and `render_sarif(report, ...)` are pure formatters.
None invokes parsers or rules. CLI
`main(argv=None, *, registry=None)` accepts an explicit registry for trusted integrations and
tests; each CLI invocation snapshots its selected rules and enabled state, then
applies invocation policy without mutating the caller's registry. The installed
CLI uses a fresh default registry containing ML001, ML002,
ML003, ML004, ML005, ML006, ML007, ML008, ML009, ST001, and ST002. An explicit registry is used exactly as supplied. `--disable-rule` can
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

## Console, HTML, and exit behavior

Console diagnostics show the same Finding fields as JSON, including evidence,
risk and fix. All report formats include scan errors and notices. HTML is a
standalone offline dashboard with scan overview metrics, severity and rule
distributions, and a per-file summary. Its Rule, severity, confidence, file,
and search filters operate on stable Finding metadata without reordering
cards. The page uses a restrictive Content Security Policy, local CSS, and a
fixed inline filter script pinned by its SHA-256 CSP hash; all dynamic text and
attributes are escaped. Findings use native collapsed details and remain
readable without JavaScript. Notebook outputs are never passed into the
reporter. See [the HTML report guide](html-report.md) for its interaction,
security model, and limits.
`--output` writes the selected format as UTF-8, creates missing parent
directories, and refuses to replace a scanned input. A write failure returns 2
and writes a short message to stderr. Without `--output`, JSON and SARIF stdout
contain only their serialized document; HTML is a complete document without
status text.

Valid inline Finding suppressions are applied by Analyzer after rule result
validation and Notebook location normalization, before deduplication and
sorting. Reporters receive only the visible Finding set; summary counts and
failure thresholds use that same set. Suppressions do not hide parser/rule
errors or Notebook notices. JSON schema 1.0 and SARIF 2.1.0 are unchanged.
See [inline suppression](suppressions.md) for token and line semantics.

Exit 2 takes precedence if any input, parse, rule, configuration, or output
error occurs. Otherwise an effective `warning` threshold exits 1 for
warning/error Findings, and `error` exits 1 for error Findings. The threshold
comes from an explicit `--fail-on` first, then `[tool.statguard].fail-on`, or
is absent by default. An undetermined evidence category never meets the
threshold. Configuration policy and precedence are documented in
[configuration.md](configuration.md); severity-based or configuration-driven
suppression is not implemented.

## SARIF 2.1.0

`render_sarif(report, *, base_path=None, rule_metadata=None)` emits a standalone
SARIF 2.1.0 log using only the standard library. It is a separate format from
the unchanged JSON schema 1.0. The CLI supplies the active registry metadata;
unknown/custom rule IDs without matching metadata receive a generic descriptor
rather than built-in rule details. Findings map to one result each, with
StatGuard severity mapped to SARIF `error`, `warning`, or `note` and confidence,
evidence, risk, and suggestion carried in `properties`. Stable SHA-256
`statguardFingerprint/v1` values are based on normalized finding identity; they
are not GitHub CodeQL fingerprints. For out-of-workspace paths, fingerprints
use a marker and basename rather than absolute machine paths, so different
external files sharing the same basename can share a fingerprint. SARIF
contains no source snippets, AST,
Notebook outputs, timestamps, or external-service data.

For `.py` files, locations use a repository-relative forward-slash URI when
inside `base_path` and preserve the one-based Finding line/column. An outside
file uses a `file:` URI, which is not a portable Code Scanning source link. For
`.ipynb`, SARIF identifies the Notebook artifact but deliberately omits a
physical region: `statguardCell`, `statguardCellIndex`, `statguardCellLine`,
and `statguardCellColumn` preserve code-cell coordinates without claiming they
are lines in the raw JSON file. GitHub may therefore display a finding
without a source-line annotation. Scan errors and notices are invocation
notifications, not results; errors set `executionSuccessful` to false, while
Findings do not. Output is deterministic, ASCII-escaped JSON with a final
newline and no timestamps.

See the [SARIF and Code Scanning guide](sarif.md) for Action usage and upload
permissions.

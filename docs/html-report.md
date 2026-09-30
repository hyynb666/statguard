# Offline HTML dashboard and report

Generate a standalone report with:

```text
statguard check ./project --format html --output reports/scan.html
```

The command creates missing parent directories, writes UTF-8, and refuses to
overwrite any scanned input. Open the result directly in a browser. It needs no
account, API key, network connection, server, or browser automation. Without
`--output`, HTML is written to stdout. Scan and write diagnostics stay on
stderr, so they cannot corrupt the document.

## Dashboard

The overview shows scanned files, total findings, error/warning/info finding
counts, complete/partial/failed files, analysis errors, and notices. Severity
distribution uses native progress bars with visible labels and numeric counts.
Rule overview includes count, share of all findings, and a progress bar; rows
are sorted by count descending and Rule ID ascending. When there are no
findings, it displays “No rule findings” without dividing by zero. A single
finding has a 100% share.

File overview keeps file, status, findings, and analysis errors, and adds
per-file error, warning, and info finding counts. It is built only from the
scan report; the Reporter does not reopen files. Partial and failed inputs
remain visible and are not treated as clean files.

Finding cards show Rule ID, severity, confidence, path and location, message,
evidence, risk explanation, and suggested action. Notebook locations display
the original cell index and the one-based line/column within that code cell;
they are not line numbers in the raw `.ipynb` JSON. Notebook document order
does not establish historical execution order.

## Finding navigation

The filters combine Rule, Severity, Confidence, File, and case-insensitive
search. Rule, confidence, and file options are derived from findings present in
the report; file choices are sorted by path. Search covers path, Rule ID,
message, explanation, suggestion, evidence category, and confidence. Filtering
changes visibility but does not reorder findings. “Showing X of Y findings”
updates as controls change and a no-match message appears when none remain.
“Clear filters” restores all selectors and the search box. “Expand visible” and
“Collapse visible” operate on the currently visible cards only. The controls
have associated labels and use native buttons/selects/inputs.

With JavaScript disabled, the dashboard, tables, and every finding remain in
the document; each finding can still be opened with its native `<details>`
control. Only filtering, search, and bulk expand/collapse require JavaScript.
No filter state is placed in the URL, browser storage, cookies, or a report
history.

## Security, privacy, and scope

The page is a self-contained offline document with inline CSS and one fixed
inline interaction script. The Content Security Policy keeps
`default-src 'none'` and permits only that script's SHA-256 hash. The script
reads Finding metadata from escaped `data-*` attributes and changes safe DOM
properties; it does not evaluate strings or insert HTML. Every report value,
including attribute values, is HTML-escaped. There are no remote resources,
network requests, chart libraries, or runtime dependencies. The report has no
source snippets and paths are text, not links.

The Reporter only renders `ScanReport`; it does not rescan, analyze, or execute
source. Python is parsed but never imported or executed. Notebook code is
analyzed by the existing parser; outputs, HTML, images, and execution results
are not passed to the Analyzer or embedded in the report. Inline suppressions
have already been applied by Analyzer, so the HTML report naturally contains
only the Findings that remain in `ScanReport`; it does not parse suppression
comments or calculate a suppressed count.

Errors and notices have their own section and are not hidden by Finding
filters. No Finding does not establish statistical correctness or absence of
risk. The HTML file is written before any configured Finding threshold affects
the CLI exit code; invalid input, analysis errors, or report write failures
retain exit code 2. See [the report contract](reporting.md) for JSON, SARIF,
and exit behavior.

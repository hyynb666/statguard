# HTML report

StatGuard can create a self-contained HTML rendering of a scan:

```text
statguard check ./project --format html --output reports/scan.html
```

The command creates missing parent directories, writes UTF-8, and refuses to
overwrite any scanned input. Open the resulting file directly in a browser. It
needs no account, API key, network connection, web server, or browser
automation. With no `--output`, HTML is written to stdout; redirect it to a
file if you want to keep it. Scan and write diagnostics stay on stderr, so they
cannot corrupt the document.

## Contents

The page summarizes scanned files, findings, severity counts, enabled rules,
and complete/partial/failed file totals. Rule counts are derived from rules
actually represented by findings. A per-file table displays file status,
Finding count, and analysis errors. Each Finding shows its rule, severity,
confidence, evidence category, path, source location (including Notebook
`cell_index` where applicable), message, risk explanation, and suggestion.
Parser/rule errors and Notebook or scanner notices are shown separately. When
there are no findings, the report says that no issue was confirmed by supported
rules; it does not claim that the code is safe.

The page uses semantic HTML and local CSS only. It currently has no JavaScript
or interactive filters, so its content remains readable with scripts disabled.
The layout wraps long paths and text and adapts to narrower screens. Severity
labels include words as well as color.

## Privacy and analysis limits

All report fields are escaped before insertion into HTML. Paths are displayed
as text rather than links. The page has no remote resources or active scripts.
Analyzed Python is parsed but never imported or executed. Notebook code cells
are analyzed by the existing static parser; stored outputs, HTML, images, and
execution results are not passed to the Analyzer or embedded in the report.
Notebook cells are treated independently and document order does not prove
historical execution order.

The report represents only the scan and enabled rules. A partial or failed
file remains visibly marked and has its parse/rule errors listed. Static rules
cover only documented patterns; no finding does not establish statistical
correctness or absence of leakage. `--disable-rule RULE_ID` changes which
rules run and therefore which findings are reported. Warnings do not fail the
command by default; `--fail-on warning` exits 1 when the threshold is reached.
The HTML file is written before threshold-based exit status is returned.
Invalid input, analysis errors, or report write failures retain the CLI's exit
code 2 behavior.

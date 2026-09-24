"""Self-contained, offline HTML rendering for completed scan reports."""

from collections import Counter
from html import escape

from statguard import __version__
from statguard.reporters.models import safe_error_message, summary
from statguard.scanner import ScanReport


def _text(value: object) -> str:
    """Escape every dynamic value before including it in an HTML text node."""
    return escape(str(value), quote=True)


def _location(path: str, cell_index: int | None, line: int | None, column: int | None) -> str:
    place = path
    if cell_index is not None:
        place += f" · cell {cell_index}"
    if line is not None:
        place += f" · line {line}"
        if column is not None:
            place += f", column {column}"
    return place


def render_html(report: ScanReport) -> str:
    """Render report records as inert HTML; source and Notebook outputs are omitted."""
    totals = summary(report)
    findings = tuple(
        sorted(
            report.findings,
            key=lambda item: (
                item.path,
                item.cell if item.cell is not None else -1,
                item.cell_index if item.cell_index is not None else -1,
                item.line,
                item.column if item.column is not None else -1,
                item.rule_id,
                item.message,
                item.explanation,
                item.suggestion,
                item.evidence.value,
                item.severity.value,
                item.confidence.value,
            ),
        )
    )
    rules = Counter(item.rule_id for item in findings)

    rule_rows = (
        "\n".join(
            f'<tr><th scope="row">{_text(rule_id)}</th><td>{count}</td></tr>'
            for rule_id, count in sorted(rules.items())
        )
        or '<tr><td colspan="2" class="muted">No rule findings.</td></tr>'
    )

    file_rows = (
        "\n".join(
            "<tr>"
            f'<th scope="row">{_text(result.path)}</th>'
            f'<td><span class="status status-{_text(result.status.value)}">'
            f"{_text(result.status.value)}</span></td>"
            f"<td>{len(result.findings)}</td><td>{len(result.errors)}</td>"
            "</tr>"
            for result in report.results
        )
        or '<tr><td colspan="4" class="muted">No supported files were scanned.</td></tr>'
    )

    finding_cards: list[str] = []
    for item in findings:
        location = _text(_location(item.path, item.cell_index, item.line, item.column))
        finding_cards.append(
            '<article class="finding">'
            '<header class="finding-head">'
            f'<span class="rule">{_text(item.rule_id)}</span>'
            f'<span class="severity severity-{_text(item.severity.value)}">'
            f"{_text(item.severity.value)}</span>"
            f'<span class="confidence">Confidence: {_text(item.confidence.value)}</span>'
            "</header>"
            f'<p class="location">{location}</p>'
            f"<h3>{_text(item.message)}</h3>"
            f'<p class="evidence">Evidence: {_text(item.evidence.value)}</p>'
            f"<section><h4>Risk explanation</h4><p>{_text(item.explanation)}</p></section>"
            f"<section><h4>Suggested action</h4><p>{_text(item.suggestion)}</p></section>"
            "</article>"
        )
    if not finding_cards:
        finding_cards.append(
            '<p class="empty">未发现受支持规则能够确认的问题。'
            "这不代表代码绝对安全或统计流程不存在风险。</p>"
        )

    notices: list[str] = []
    for error in report.analysis_errors:
        notices.append(
            '<article class="notice error-notice">'
            f"<strong>{_text(error.stage.value)} / {_text(error.code.value)}</strong>"
            f'<p class="location">'
            f"{_text(_location(error.path, error.cell_index, error.line, error.column))}</p>"
            f"<p>{_text(safe_error_message(error))}</p>"
            f'<p class="muted">Rule: {_text(error.rule_id or "—")}</p>'
            "</article>"
        )
    for notice in report.scan_notices:
        notices.append(
            '<article class="notice">'
            f"<strong>Scan notice · {_text(notice.code)}</strong>"
            f'<p class="location">{_text(notice.path)}</p>'
            f"<p>{_text(notice.message)}</p>"
            "</article>"
        )
    for notice in report.notebook_notices:
        notices.append(
            '<article class="notice">'
            f"<strong>Notebook notice · {_text(notice.code.value)}</strong>"
            f'<p class="location">'
            f"{_text(_location(notice.path, notice.cell_index, notice.line, notice.column))}</p>"
            f"<p>{_text(notice.message)}</p>"
            "</article>"
        )
    if not notices:
        notices.append('<p class="muted">No scan errors or notices.</p>')

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy"
        content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
  >
  <title>StatGuard Analysis Report</title>
  <style>
    :root {{ color-scheme: light; --ink: #182230; --muted: #596779; --line: #dce3eb;
      --paper: #f4f7fb; --blue: #1f5f8b; --red: #9c2635; --amber: #805000; --green: #226443; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--paper); color: var(--ink);
      font: 16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }}
    main {{ width: min(1120px, 100% - 2rem); margin: 2rem auto 4rem; }}
    h1, h2, h3, h4, p {{ margin-top: 0; }}
    h1 {{ margin-bottom: .35rem; font-size: clamp(1.8rem, 4vw, 2.6rem); letter-spacing: -.03em; }}
    h2 {{ margin-bottom: 1rem; font-size: 1.25rem; }}
    h3 {{ margin: .65rem 0; font-size: 1.15rem; overflow-wrap: anywhere; }}
    h4 {{ margin-bottom: .2rem; font-size: .88rem; color: var(--muted);
      text-transform: uppercase; letter-spacing: .04em; }}
    .intro, .muted {{ color: var(--muted); }}
    .panel, .stat, .finding, .notice {{ background: #fff; border: 1px solid var(--line);
      border-radius: 14px; box-shadow: 0 4px 16px #172b3d0a; }}
    .panel {{ padding: 1.25rem; margin: 1.25rem 0; }}
    .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
      gap: .8rem; margin: 1.25rem 0; }}
    .stat {{ padding: 1rem; }}
    .stat strong {{ display: block; font-size: 1.7rem; line-height: 1.2; }}
    .stat span {{ color: var(--muted); font-size: .9rem; }}
    .severity-counts {{ display: flex; flex-wrap: wrap; gap: .6rem; margin-top: .75rem; }}
    .severity-counts span, .severity, .rule, .status {{ display: inline-block;
      border-radius: 999px; padding: .2rem .65rem; font-size: .82rem; font-weight: 700; }}
    .severity-counts span {{ border: 1px solid var(--line); }}
    .severity-error, .error-notice {{ color: var(--red); background: #fff1f1; }}
    .severity-warning {{ color: var(--amber); background: #fff6dd; }}
    .severity-info {{ color: var(--blue); background: #eaf4fb; }}
    .rule {{ color: #fff; background: var(--blue); }}
    .confidence {{ color: var(--muted); font-size: .9rem; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; text-align: left; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: .65rem; vertical-align: top; }}
    th {{ font-weight: 650; }}
    td, th {{ overflow-wrap: anywhere; }}
    .status-complete {{ color: var(--green); background: #e9f6ee; }}
    .status-partial {{ color: var(--amber); background: #fff6dd; }}
    .status-failed {{ color: var(--red); background: #fff1f1; }}
    .finding {{ padding: 1.1rem 1.2rem; margin: .9rem 0; border-left: 5px solid var(--blue); }}
    .finding-head {{ display: flex; align-items: center; flex-wrap: wrap; gap: .55rem; }}
    .location {{ color: var(--muted); overflow-wrap: anywhere;
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .9rem; }}
    .evidence {{ color: var(--muted); font-size: .9rem; }}
    .finding section p, .notice p {{ margin-bottom: .7rem; overflow-wrap: anywhere; }}
    .empty {{ padding: 1rem; border-radius: 10px; background: #eaf4fb; }}
    .notice {{ padding: 1rem; margin: .7rem 0; overflow-wrap: anywhere; }}
    footer {{ padding-top: 1rem; color: var(--muted); font-size: .85rem; }}
    @media (max-width: 600px) {{
      main {{ width: min(100% - 1rem, 1120px); margin-top: 1rem; }}
      .panel {{ padding: .9rem; }} th, td {{ padding: .45rem; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>StatGuard Analysis Report</h1>
      <p class="intro">静态分析结果摘要。报告在本地生成；未能分析的内容会单独列出。</p>
      <p class="muted">StatGuard {_text(__version__)} · enabled rules: {totals["enabled_rules"]}</p>
    </header>
    <section class="stats" aria-label="Scan overview">
      <div class="stat"><strong>{totals["scanned_files"]}</strong><span>Scanned files</span></div>
      <div class="stat"><strong>{len(findings)}</strong><span>Findings</span></div>
      <div class="stat"><strong>{totals["complete_files"]}</strong><span>Complete files</span></div>
      <div class="stat"><strong>{totals["partial_files"]}</strong><span>Partial files</span></div>
      <div class="stat"><strong>{totals["failed_files"]}</strong><span>Failed files</span></div>
    </section>
    <section class="panel">
      <h2>Severity distribution</h2>
      <div class="severity-counts">
        <span>Error: {totals["error"]}</span>
        <span>Warning: {totals["warning"]}</span>
        <span>Info: {totals["info"]}</span>
      </div>
    </section>
    <section class="panel">
      <h2>Rule overview</h2>
      <div class="table-wrap"><table><thead><tr>
        <th scope="col">Rule</th><th scope="col">Findings</th>
      </tr></thead><tbody>{rule_rows}</tbody></table></div>
    </section>
    <section class="panel">
      <h2>Scanned files</h2>
      <div class="table-wrap"><table><thead><tr>
        <th scope="col">File</th><th scope="col">Status</th>
        <th scope="col">Findings</th><th scope="col">Errors</th>
      </tr></thead><tbody>{file_rows}</tbody></table></div>
    </section>
    <section class="panel">
      <h2>Findings ({len(findings)})</h2>
      {"".join(finding_cards)}
    </section>
    <section class="panel">
      <h2>Analysis errors and notices</h2>
      <p class="muted">Parse failures, rule failures, and coverage notices are not evidence
        that a file has no issues.</p>
      {"".join(notices)}
      <p class="muted">Parse errors: {totals["parse_errors"]} ·
        Rule errors: {totals["rule_errors"]} · Notices: {totals["notices"]}</p>
    </section>
    <footer>Absence of findings does not establish that code is statistically
      correct or free of risk. This static report contains no external resources.</footer>
  </main>
</body>
</html>
"""

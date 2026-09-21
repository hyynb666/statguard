"""Readable terminal rendering of the same scan records as JSON."""

from statguard.reporters.models import safe_error_message, summary
from statguard.scanner import ScanReport


def _location(path: str, cell_index: int | None, line: int | None, column: int | None) -> str:
    place = path
    if cell_index is not None:
        place += f":cell {cell_index}"
    if line is not None:
        place += f":{line}"
        if column is not None:
            place += f":{column}"
    return place


def render_console(report: ScanReport) -> str:
    """Render findings, scan failures, notices and file-level totals."""
    lines: list[str] = []
    for finding in report.findings:
        lines.append(
            f"{_location(finding.path, finding.cell_index, finding.line, finding.column)}: "
            f"{finding.rule_id} {finding.severity.value}: {finding.message} "
            f"[{finding.evidence.value}]"
        )
        lines.append(f"  Risk: {finding.explanation}")
        lines.append(f"  Fix: {finding.suggestion}")
    for error in report.analysis_errors:
        lines.append(
            f"{_location(error.path, error.cell_index, error.line, error.column)}: "
            f"scan error ({error.stage.value}/{error.code.value}): "
            f"{safe_error_message(error)}"
        )
    for notice in report.scan_notices:
        lines.append(f"{notice.path}: notice ({notice.code}): {notice.message}")
    for notice in report.notebook_notices:
        lines.append(
            f"{_location(notice.path, notice.cell_index, notice.line, notice.column)}: "
            f"notice ({notice.code.value}): {notice.message}"
        )
    totals = summary(report)
    if not report.findings:
        lines.append("No rule findings produced; this does not establish statistical correctness.")
    if not report.enabled_rule_count:
        lines.append("No detection rules enabled; no rule diagnostics were produced.")
    lines.append(
        f"Scanned {totals['scanned_files']} files; findings: "
        f"error {totals['error']}, warning {totals['warning']}, info {totals['info']}; "
        f"files: complete {totals['complete_files']}, partial {totals['partial_files']}, "
        f"failed {totals['failed_files']}; scan errors: parse {totals['parse_errors']}, "
        f"rule {totals['rule_errors']}."
    )
    return "\n".join(lines) + "\n"

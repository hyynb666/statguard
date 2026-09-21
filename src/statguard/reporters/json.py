"""Versioned, standalone JSON scan output without AST or notebook outputs."""

import json

from statguard import __version__
from statguard.reporters.models import safe_error_message, summary
from statguard.scanner import ScanReport

SCHEMA_VERSION = "1.0"


def render_json(report: ScanReport) -> str:
    """Serialize only public, JSON-safe diagnostic fields."""
    document = {
        "tool": "statguard",
        "version": __version__,
        "schema_version": SCHEMA_VERSION,
        "summary": summary(report),
        "files": [
            {
                "file_path": result.path,
                "status": result.status.value,
                "findings": len(result.findings),
                "analysis_errors": len(result.errors),
            }
            for result in report.results
        ],
        "findings": [
            {
                "rule_id": item.rule_id,
                "severity": item.severity.value,
                "confidence": item.confidence.value,
                "evidence": item.evidence.value,
                "file_path": item.file_path,
                "line": item.line,
                "column": item.column,
                "cell_index": item.cell_index,
                "cell": item.cell,
                "message": item.message,
                "explanation": item.explanation,
                "suggestion": item.suggestion,
            }
            for item in report.findings
        ],
        "analysis_errors": [
            {
                "stage": item.stage.value,
                "code": item.code.value,
                "file_path": item.path,
                "rule_id": item.rule_id,
                "cell_index": item.cell_index,
                "cell": item.cell,
                "line": item.line,
                "column": item.column,
                "message": safe_error_message(item),
            }
            for item in report.analysis_errors
        ],
        "notices": [
            {
                "code": item.code,
                "file_path": item.path,
                "message": item.message,
                "cell_index": None,
                "cell": None,
                "line": None,
                "column": None,
            }
            for item in report.scan_notices
        ]
        + [
            {
                "code": item.code.value,
                "file_path": item.path,
                "message": item.message,
                "cell_index": item.cell_index,
                "cell": item.code_cell_index,
                "line": item.line,
                "column": item.column,
            }
            for item in report.notebook_notices
        ],
    }
    return json.dumps(document, ensure_ascii=True, indent=2) + "\n"

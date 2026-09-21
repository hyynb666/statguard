"""Shared report projection for both human and machine renderers."""

from statguard.analyzer import AnalysisError, AnalysisErrorCode, AnalysisErrorStage, AnalysisStatus
from statguard.core import Evidence, Severity
from statguard.scanner import ScanReport


def summary(report: ScanReport) -> dict[str, int]:
    findings = report.findings
    errors = report.analysis_errors
    return {
        "scanned_files": len(report.results),
        "error": sum(item.severity is Severity.ERROR for item in findings),
        "warning": sum(item.severity is Severity.WARNING for item in findings),
        "info": sum(item.severity is Severity.INFO for item in findings),
        "complete_files": sum(item.status is AnalysisStatus.COMPLETE for item in report.results),
        "partial_files": sum(item.status is AnalysisStatus.PARTIAL for item in report.results),
        "failed_files": sum(item.status is AnalysisStatus.FAILED for item in report.results),
        "parse_errors": sum(item.stage is AnalysisErrorStage.PARSE for item in errors),
        "rule_errors": sum(item.stage is AnalysisErrorStage.RULE for item in errors),
        "notices": len(report.scan_notices) + len(report.notebook_notices),
        "enabled_rules": report.enabled_rule_count,
    }


def safe_error_message(error: AnalysisError) -> str:
    """Do not publish arbitrary exception text supplied by a trusted rule."""
    if error.code is AnalysisErrorCode.RULE_EXECUTION:
        return "Rule execution raised an exception"
    return error.message


def reaches_threshold(report: ScanReport, fail_on: str | None) -> bool:
    if fail_on is None:
        return False
    minimum = {"error": 2, "warning": 1}[fail_on]
    return any(
        finding.evidence is not Evidence.UNDETERMINED
        and {Severity.ERROR: 2, Severity.WARNING: 1, Severity.INFO: 0}[finding.severity] >= minimum
        for finding in report.findings
    )

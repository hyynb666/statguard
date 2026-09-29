"""Deterministic SARIF 2.1.0 output without source or Notebook output data."""

from __future__ import annotations

import hashlib
import json
import posixpath
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from urllib.parse import quote

from statguard import __version__
from statguard.analyzer import AnalysisError
from statguard.core import Finding, Severity
from statguard.reporters.models import safe_error_message
from statguard.scanner import ScanNotice, ScanReport

SARIF_SCHEMA = (
    "https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/sarif-schema-2.1.0.json"
)
_LEVELS = {Severity.ERROR: "error", Severity.WARNING: "warning", Severity.INFO: "note"}


@dataclass(frozen=True, slots=True)
class RuleMetadata:
    """Registry metadata used only when it belongs to the emitted rule ID."""

    name: str
    description: str
    default_severity: str


def render_sarif(
    report: ScanReport,
    *,
    base_path: str | Path | None = None,
    rule_metadata: Mapping[str, RuleMetadata] | None = None,
) -> str:
    """Render a SARIF log. Notebook cell lines remain properties, not JSON regions."""
    base = Path.cwd() if base_path is None else base_path
    metadata = rule_metadata or {}
    rule_ids = sorted({finding.rule_id for finding in report.findings})
    rule_indexes = {rule_id: index for index, rule_id in enumerate(rule_ids)}
    rules = [_rule_descriptor(rule_id, metadata.get(rule_id)) for rule_id in rule_ids]
    results = [_result(finding, base, rule_indexes[finding.rule_id]) for finding in report.findings]
    notifications = [_error_notification(error, base) for error in report.analysis_errors] + [
        _notice_notification(notice, base) for notice in report.scan_notices
    ]
    notifications.extend(_notebook_notification(issue, base) for issue in report.notebook_notices)

    run = {
        "tool": {
            "driver": {
                "name": "StatGuard",
                "version": __version__,
                "informationUri": "https://github.com/hyynb666/statguard",
                "rules": rules,
            }
        },
        "results": results,
        "invocations": [
            {
                "executionSuccessful": not bool(report.analysis_errors),
                "toolExecutionNotifications": notifications,
            }
        ],
    }
    document = {"$schema": SARIF_SCHEMA, "version": "2.1.0", "runs": [run]}
    return json.dumps(document, ensure_ascii=True, indent=2) + "\n"


def _rule_descriptor(rule_id: str, metadata: RuleMetadata | None) -> dict[str, object]:
    if metadata is None:
        name = rule_id
        description = f"Finding emitted by StatGuard rule {rule_id}."
        descriptor: dict[str, object] = {
            "id": rule_id,
            "name": name,
            "shortDescription": {"text": description},
        }
        return descriptor
    try:
        default_level = _LEVELS[Severity(metadata.default_severity)]
    except (KeyError, ValueError):
        default_level = "warning"
    return {
        "id": rule_id,
        "name": metadata.name,
        "shortDescription": {"text": metadata.description},
        "fullDescription": {"text": metadata.description},
        "defaultConfiguration": {"level": default_level},
    }


def _result(finding: Finding, base: str | Path, rule_index: int) -> dict[str, object]:
    uri = _artifact_uri(finding.path, base)
    is_notebook = finding.path.casefold().endswith(".ipynb")
    location: dict[str, object] = {"physicalLocation": {"artifactLocation": {"uri": uri}}}
    if not is_notebook:
        region: dict[str, int] = {"startLine": finding.line}
        if finding.column is not None:
            region["startColumn"] = finding.column
        location["physicalLocation"]["region"] = region  # type: ignore[index]

    properties: dict[str, object] = {
        "statguardSeverity": finding.severity.value,
        "statguardConfidence": finding.confidence.value,
        "statguardEvidence": finding.evidence.value,
        "statguardExplanation": finding.risk,
        "statguardSuggestion": finding.recommendation,
    }
    if is_notebook:
        if finding.cell is not None:
            properties["statguardCell"] = finding.cell
        if finding.cell_index is not None:
            properties["statguardCellIndex"] = finding.cell_index
        properties["statguardCellLine"] = finding.line
        if finding.column is not None:
            properties["statguardCellColumn"] = finding.column

    fingerprint_payload = [
        finding.rule_id,
        _fingerprint_artifact(uri),
        finding.cell_index if is_notebook else None,
        finding.cell if is_notebook else None,
        finding.line,
        finding.column,
        finding.message,
    ]
    canonical = json.dumps(fingerprint_payload, ensure_ascii=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "ruleId": finding.rule_id,
        "ruleIndex": rule_index,
        "level": _LEVELS[finding.severity],
        "message": {"text": finding.message},
        "locations": [location],
        "properties": properties,
        "partialFingerprints": {"statguardFingerprint/v1": fingerprint},
    }


def _error_notification(error: AnalysisError, base: str | Path) -> dict[str, object]:
    return _notification(
        "error",
        safe_error_message(error),
        error.path,
        base,
        code=error.code.value,
        stage=error.stage.value,
        cell=error.cell,
        cell_index=error.cell_index,
        line=error.line,
        column=error.column,
        is_notebook=error.path.casefold().endswith(".ipynb"),
    )


def _notice_notification(notice: ScanNotice, base: str | Path) -> dict[str, object]:
    return _notification("note", notice.message, notice.path, base, code=notice.code)


def _notebook_notification(issue: object, base: str | Path) -> dict[str, object]:
    path = issue.path
    return _notification(
        "note",
        issue.message,
        path,
        base,
        code=issue.code.value,
        cell=issue.code_cell_index,
        cell_index=issue.cell_index,
        line=issue.line,
        column=issue.column,
        is_notebook=True,
    )


def _notification(
    level: str,
    message: str,
    path: str,
    base: str | Path,
    *,
    code: str,
    stage: str | None = None,
    cell: int | None = None,
    cell_index: int | None = None,
    line: int | None = None,
    column: int | None = None,
    is_notebook: bool = False,
) -> dict[str, object]:
    notification: dict[str, object] = {
        "level": level,
        "message": {"text": message},
        "properties": {"statguardCode": code},
    }
    if stage is not None:
        notification["properties"]["statguardStage"] = stage  # type: ignore[index]
    if is_notebook:
        positions = notification["properties"]
        if cell is not None:
            positions["statguardCell"] = cell  # type: ignore[index]
        if cell_index is not None:
            positions["statguardCellIndex"] = cell_index  # type: ignore[index]
        if line is not None:
            positions["statguardCellLine"] = line  # type: ignore[index]
        if column is not None:
            positions["statguardCellColumn"] = column  # type: ignore[index]
    location: dict[str, object] = {
        "physicalLocation": {"artifactLocation": {"uri": _artifact_uri(path, base)}}
    }
    if not is_notebook and line is not None:
        region: dict[str, int] = {"startLine": line}
        if column is not None:
            region["startColumn"] = column
        location["physicalLocation"]["region"] = region  # type: ignore[index]
    notification["locations"] = [location]
    return notification


def _artifact_uri(value: str, base_path: str | Path) -> str:
    """Return a workspace-relative URI when possible, otherwise a file URI."""
    value_windows = PureWindowsPath(value)
    base_windows = PureWindowsPath(str(base_path))
    if value_windows.is_absolute() or base_windows.is_absolute():
        target_windows = (
            value_windows if value_windows.is_absolute() else base_windows / value_windows
        )
        if base_windows.is_absolute():
            try:
                relative = target_windows.relative_to(base_windows)
            except ValueError:
                pass
            else:
                return _relative_uri(relative.as_posix())
        return _windows_file_uri(target_windows)

    base = Path(base_path).resolve(strict=False)
    target = Path(value)
    if not target.is_absolute():
        target = base / target
    target = target.resolve(strict=False)
    try:
        return _relative_uri(target.relative_to(base).as_posix())
    except ValueError:
        return target.as_uri()


def _relative_uri(value: str) -> str:
    normalized = posixpath.normpath(value.replace("\\", "/"))
    if normalized in {"", "."}:
        return "."
    if normalized == ".." or normalized.startswith("../") or normalized.startswith("/"):
        raise ValueError("artifact path must not escape its base directory")
    return quote(normalized, safe="/-._~")


def _windows_file_uri(path: PureWindowsPath) -> str:
    value = path.as_posix()
    if path.drive.startswith("\\\\"):
        return "file:" + quote(value, safe="/~")
    if path.drive:
        return "file:///" + quote(value, safe="/:~")
    return "file://" + quote(value, safe="/:~")


def _fingerprint_artifact(uri: str) -> str:
    """Keep machine-specific absolute paths out of stable partial fingerprints."""
    if uri.startswith("file:"):
        return "<outside-workspace>/" + uri.rsplit("/", 1)[-1]
    return uri

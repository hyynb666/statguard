"""Shared, immutable diagnostic data for future analysis and reporters."""

from dataclasses import dataclass
from enum import StrEnum


class Evidence(StrEnum):
    """Evidence categories from PRD Section 3.2, independent of severity/confidence."""

    CONFIRMED_CODE_PATTERN = "confirmed code pattern"
    POTENTIAL_STATISTICAL_RISK = "potential statistical risk"
    GENERAL_ANALYSIS_ADVICE = "general analysis advice"
    UNDETERMINED = "undetermined"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


def _text_alias(old: str | None, new: str | None, old_name: str, new_name: str) -> str:
    if old is not None and new is not None and old != new:
        raise ValueError(f"Conflicting {old_name} and {new_name}")
    value = old if old is not None else new
    if not isinstance(value, str):
        raise TypeError(f"{new_name} ({old_name}) must be a string")
    return value


@dataclass(frozen=True, slots=True, init=False)
class Finding:
    """A located observation with separate evidence, severity and confidence.

    Existing stored fields and positional arguments remain compatible. The new
    file_path/explanation/suggestion keywords and properties alias path/risk/
    recommendation. Both cell indexes are one-based: cell counts code cells,
    whereas cell_index counts all original notebook cells. Never infer one from
    the other. UNDETERMINED must not count as a violation in a future analyzer.
    """

    rule_id: str
    path: str
    line: int
    column: int | None
    message: str
    risk: str
    recommendation: str
    evidence: Evidence
    cell: int | None = None
    severity: Severity = Severity.WARNING
    confidence: Confidence = Confidence.LOW
    cell_index: int | None = None

    def __init__(
        self,
        rule_id: str,
        path: str | None = None,
        line: int | None = None,
        column: int | None = None,
        message: str | None = None,
        risk: str | None = None,
        recommendation: str | None = None,
        evidence: Evidence = Evidence.UNDETERMINED,
        cell: int | None = None,
        *,
        severity: Severity | str = Severity.WARNING,
        confidence: Confidence | str = Confidence.LOW,
        cell_index: int | None = None,
        file_path: str | None = None,
        explanation: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        values = {
            "rule_id": rule_id,
            "path": _text_alias(path, file_path, "path", "file_path"),
            "line": line,
            "column": column,
            "message": message,
            "risk": _text_alias(risk, explanation, "risk", "explanation"),
            "recommendation": _text_alias(
                recommendation, suggestion, "recommendation", "suggestion"
            ),
            "evidence": evidence,
            "cell": cell,
            "severity": severity,
            "confidence": confidence,
            "cell_index": cell_index,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)
        self.__post_init__()

    def __post_init__(self) -> None:
        for name in ("rule_id", "path", "message", "risk", "recommendation"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a string")
            if not value.strip():
                raise ValueError(f"{name} must not be empty")
        for name in ("line", "column", "cell", "cell_index"):
            value = getattr(self, name)
            if value is None and name != "line":
                continue
            if type(value) is not int:
                raise TypeError(f"{name} must be a one-based integer")
            if value < 1:
                raise ValueError(f"{name} must be one-based")
        if self.cell is not None and self.cell_index is not None and self.cell > self.cell_index:
            raise ValueError("cell cannot exceed cell_index (code cells are a subset of all cells)")
        if not isinstance(self.evidence, Evidence):
            raise TypeError("evidence must be an Evidence category")
        for name, enum_type in (("severity", Severity), ("confidence", Confidence)):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a {enum_type.__name__} or string")
            try:
                normalized = enum_type(value)
            except ValueError as error:
                options = ", ".join(item.value for item in enum_type)
                raise ValueError(f"Invalid {name}: {value!r}; expected {options}") from error
            object.__setattr__(self, name, normalized)

    @property
    def file_path(self) -> str:
        return self.path

    @property
    def explanation(self) -> str:
        return self.risk

    @property
    def suggestion(self) -> str:
        return self.recommendation

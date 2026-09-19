"""Shared, immutable diagnostic data for future analysis and reporters."""

from dataclasses import dataclass
from enum import StrEnum


class Evidence(StrEnum):
    """Evidence categories from PRD Section 3.2, not severity levels."""

    CONFIRMED_CODE_PATTERN = "confirmed code pattern"
    POTENTIAL_STATISTICAL_RISK = "potential statistical risk"
    GENERAL_ANALYSIS_ADVICE = "general analysis advice"
    UNDETERMINED = "undetermined"


@dataclass(frozen=True, slots=True)
class Finding:
    """A located observation; line, column and optional code-cell index are one-based.

    ``message`` describes observed code, ``risk`` explains its possible consequence,
    and ``recommendation`` gives a concrete next step. UNDETERMINED is reserved for
    incomplete evidence and must not be counted as a violation by a future engine.
    """

    rule_id: str
    path: str
    line: int
    column: int
    message: str
    risk: str
    recommendation: str
    evidence: Evidence
    cell: int | None = None

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("rule_id must not be empty")
        if self.line < 1 or self.column < 1 or (self.cell is not None and self.cell < 1):
            raise ValueError("line, column and cell must be one-based")
        if not isinstance(self.evidence, Evidence):
            raise TypeError("evidence must be an Evidence category")

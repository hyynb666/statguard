"""Notebook containers and diagnostics, separate from statistical findings."""

from dataclasses import dataclass
from enum import StrEnum

from statguard.parsers.models import ParsedSource, ParseErrorCode


class NotebookIssueCode(StrEnum):
    INVALID_JSON = "invalid_json"
    INVALID_NOTEBOOK = "invalid_notebook"
    UNSUPPORTED_VERSION = "unsupported_version"
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    UNKNOWN_LANGUAGE = "unknown_language"
    UNSUPPORTED_SYNTAX = "unsupported_syntax"
    DOCUMENT_ORDER = "document_order"


@dataclass(frozen=True, slots=True)
class NotebookIssue:
    """A notice/error, not a Finding; all positions are one-based.

    With cell_index, line/column refer to cell source. INVALID_JSON positions
    refer to the JSON document. Unknown positions remain None.
    """

    code: NotebookIssueCode | ParseErrorCode
    path: str
    message: str
    cell_index: int | None = None
    code_cell_index: int | None = None
    line: int | None = None
    column: int | None = None


class NotebookParseError(Exception):
    """Fatal file, JSON, structure or notebook-language failure."""

    def __init__(self, issue: NotebookIssue) -> None:
        self.issue = issue
        location = issue.path
        if issue.cell_index is not None:
            location += f":cell {issue.cell_index}"
        if issue.line is not None:
            location += f":{issue.line}"
            if issue.column is not None:
                location += f":{issue.column}"
        super().__init__(f"{location}: {issue.code.value}: {issue.message}")


@dataclass(frozen=True, slots=True)
class NotebookCell:
    """A code cell in document order, including original source on failure.

    cell_index counts all notebook cells; code_cell_index counts code cells only
    (the PRD/Finding.cell convention). Both start at 1. Exactly one of parsed
    and error is present. No outputs, execution counts or attachments are stored.
    """

    cell_index: int
    code_cell_index: int
    source: str
    parsed: ParsedSource | None
    error: NotebookIssue | None = None

    def __post_init__(self) -> None:
        if self.cell_index < 1 or self.code_cell_index < 1:
            raise ValueError("Cell indexes must be one-based")
        if (self.parsed is None) == (self.error is None):
            raise ValueError("A code cell must contain either parsed source or an error")


@dataclass(frozen=True, slots=True)
class ParsedNotebook:
    path: str
    cell_count: int
    code_cells: tuple[NotebookCell, ...]
    notices: tuple[NotebookIssue, ...]

    @property
    def errors(self) -> tuple[NotebookIssue, ...]:
        return tuple(cell.error for cell in self.code_cells if cell.error is not None)

    @property
    def is_complete(self) -> bool:
        """All code cells parsed; this says nothing about statistical validity."""
        return not self.errors

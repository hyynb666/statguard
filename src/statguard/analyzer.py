"""Run explicitly enabled rules on parsed Python units without running source."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from os import PathLike
from pathlib import Path

from statguard.context import AnalysisContext
from statguard.core import Finding, Rule, RuleRegistry
from statguard.parsers import (
    NotebookIssue,
    NotebookIssueCode,
    NotebookParseError,
    NotebookParser,
    ParsedNotebook,
    ParsedSource,
    ParseErrorCode,
    PythonSourceParser,
    SourceParseError,
)


class AnalysisErrorStage(StrEnum):
    PARSE = "parse"
    RULE = "rule"


class AnalysisErrorCode(StrEnum):
    RULE_EXECUTION = "rule_execution"
    INVALID_RULE_RESULT = "invalid_rule_result"


class AnalysisStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AnalysisError:
    """An input/parser failure or trusted rule failure, never a statistical finding."""

    stage: AnalysisErrorStage
    code: ParseErrorCode | NotebookIssueCode | AnalysisErrorCode
    path: str
    message: str
    rule_id: str | None = None
    cell_index: int | None = None
    cell: int | None = None
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Findings plus explicit failures and Notebook notices for one input."""

    path: str
    findings: tuple[Finding, ...] = ()
    errors: tuple[AnalysisError, ...] = ()
    notices: tuple[NotebookIssue, ...] = ()
    analyzed_units: int = 0
    completed_units: int = 0

    @property
    def status(self) -> AnalysisStatus:
        if not self.errors:
            return AnalysisStatus.COMPLETE
        return AnalysisStatus.PARTIAL if self.completed_units else AnalysisStatus.FAILED

    @property
    def is_complete(self) -> bool:
        return not self.errors


def _finding_order(
    finding: Finding,
) -> tuple[str, int, int, int, int, str, str, str, str, str, str, str]:
    """Stable order even when distinct diagnostics share a primary location."""
    return (
        finding.path,
        finding.cell if finding.cell is not None else -1,
        finding.cell_index if finding.cell_index is not None else -1,
        finding.line,
        finding.column if finding.column is not None else -1,
        finding.rule_id,
        finding.message,
        finding.risk,
        finding.recommendation,
        finding.evidence.value,
        finding.severity.value,
        finding.confidence.value,
    )


def _parse_error(error: SourceParseError | NotebookIssue) -> AnalysisError:
    if isinstance(error, SourceParseError):
        return AnalysisError(
            AnalysisErrorStage.PARSE,
            error.code,
            error.path,
            error.message,
            line=error.line,
            column=error.column,
        )
    return AnalysisError(
        AnalysisErrorStage.PARSE,
        error.code,
        error.path,
        error.message,
        cell_index=error.cell_index,
        cell=error.code_cell_index,
        line=error.line,
        column=error.column,
    )


class Analyzer:
    """Execute selected trusted rules on syntax units; never execute target code."""

    def __init__(
        self,
        registry: RuleRegistry[AnalysisContext],
        *,
        python_parser: PythonSourceParser | None = None,
        notebook_parser: NotebookParser | None = None,
    ) -> None:
        self.registry = registry
        self.python_parser = python_parser if python_parser is not None else PythonSourceParser()
        self.notebook_parser = (
            notebook_parser if notebook_parser is not None else NotebookParser(self.python_parser)
        )

    def analyze_file(self, path: str | PathLike[str]) -> AnalysisResult:
        """Dispatch .py/.ipynb; parser failures become explicit results."""
        file_path = Path(path)
        label = str(file_path)
        suffix = file_path.suffix.lower()
        if suffix not in (".py", ".ipynb"):
            error = AnalysisError(
                AnalysisErrorStage.PARSE,
                ParseErrorCode.UNSUPPORTED_FILE,
                label,
                "Expected a .py or .ipynb file",
            )
            return AnalysisResult(label, errors=(error,))
        try:
            parsed = (
                self.python_parser.parse_file(file_path)
                if suffix == ".py"
                else self.notebook_parser.parse_file(file_path)
            )
        except SourceParseError as error:
            return AnalysisResult(label, errors=(_parse_error(error),))
        except NotebookParseError as error:
            return AnalysisResult(label, errors=(_parse_error(error.issue),))
        return self.analyze(parsed)

    def analyze_source(self, source: str, *, path: str = "<string>") -> AnalysisResult:
        """Parse one Python source string and run enabled rules."""
        try:
            parsed = self.python_parser.parse_source(source, path=path)
        except SourceParseError as error:
            return AnalysisResult(path, errors=(_parse_error(error),))
        return self.analyze(parsed)

    def analyze_notebook_json(self, text: str, *, path: str = "<notebook>") -> AnalysisResult:
        """Decode Notebook JSON and run enabled rules on parseable code cells."""
        try:
            parsed = self.notebook_parser.parse_json(text, path=path)
        except NotebookParseError as error:
            return AnalysisResult(path, errors=(_parse_error(error.issue),))
        return self.analyze(parsed)

    def analyze(self, parsed: ParsedSource | ParsedNotebook) -> AnalysisResult:
        """Analyze already parsed units, retaining cell failures and notices."""
        if isinstance(parsed, ParsedSource):
            contexts = (AnalysisContext(parsed),)
            errors: list[AnalysisError] = []
            notices: tuple[NotebookIssue, ...] = ()
            path = parsed.path
        elif isinstance(parsed, ParsedNotebook):
            contexts = tuple(
                AnalysisContext(cell.parsed, cell.cell_index, cell.code_cell_index)
                for cell in parsed.code_cells
                if cell.parsed is not None
            )
            errors = [_parse_error(issue) for issue in parsed.errors]
            notices = parsed.notices
            path = parsed.path
        else:
            raise TypeError("parsed must be ParsedSource or ParsedNotebook")

        selected = tuple(self.registry.iter_enabled())
        findings: set[Finding] = set()
        completed = 0
        for context in contexts:
            unit_failed = False
            for rule in selected:
                produced, error = self._run_rule(rule, context)
                if error is None:
                    findings.update(produced)
                else:
                    errors.append(error)
                    unit_failed = True
            if not unit_failed:
                completed += 1
        return AnalysisResult(
            path,
            tuple(sorted(findings, key=_finding_order)),
            tuple(errors),
            notices,
            len(contexts),
            completed,
        )

    @staticmethod
    def _run_rule(
        rule: Rule[AnalysisContext], context: AnalysisContext
    ) -> tuple[list[Finding], AnalysisError | None]:
        def failure(code: AnalysisErrorCode, message: str) -> tuple[list[Finding], AnalysisError]:
            return [], AnalysisError(
                AnalysisErrorStage.RULE,
                code,
                context.path,
                message,
                rule_id=rule.rule_id,
                cell_index=context.cell_index,
                cell=context.cell,
            )

        try:
            output = rule.check(context)
        except Exception as error:
            return failure(AnalysisErrorCode.RULE_EXECUTION, f"{type(error).__name__}: {error}")
        if isinstance(output, (str, bytes, Mapping)):
            return failure(AnalysisErrorCode.INVALID_RULE_RESULT, "check must return Finding items")
        try:
            iterator = iter(output)
        except TypeError:
            return failure(
                AnalysisErrorCode.INVALID_RULE_RESULT, "check must return a Finding iterable"
            )
        except Exception as error:
            return failure(AnalysisErrorCode.RULE_EXECUTION, f"{type(error).__name__}: {error}")

        collected: list[Finding] = []
        try:
            for item in iterator:
                if not isinstance(item, Finding):
                    return failure(
                        AnalysisErrorCode.INVALID_RULE_RESULT, "check yielded a non-Finding item"
                    )
                if item.rule_id != rule.rule_id:
                    return failure(
                        AnalysisErrorCode.INVALID_RULE_RESULT, "Finding rule_id differs from rule"
                    )
                if item.path != context.path:
                    return failure(
                        AnalysisErrorCode.INVALID_RULE_RESULT, "Finding path differs from context"
                    )
                if context.is_notebook:
                    if item.cell_index not in (None, context.cell_index) or item.cell not in (
                        None,
                        context.cell,
                    ):
                        return failure(
                            AnalysisErrorCode.INVALID_RULE_RESULT,
                            "Finding cell location differs from context",
                        )
                    item = replace(item, cell_index=context.cell_index, cell=context.cell)
                elif item.cell_index is not None or item.cell is not None:
                    return failure(
                        AnalysisErrorCode.INVALID_RULE_RESULT,
                        "Python Finding must not include Notebook cell indexes",
                    )
                collected.append(item)
        except Exception as error:
            return failure(AnalysisErrorCode.RULE_EXECUTION, f"{type(error).__name__}: {error}")
        return collected, None

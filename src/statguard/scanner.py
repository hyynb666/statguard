"""Deterministic file discovery and aggregation around the existing Analyzer."""

from dataclasses import dataclass
from pathlib import Path

from statguard.analyzer import AnalysisError, AnalysisErrorStage, AnalysisResult, Analyzer
from statguard.core import Finding
from statguard.parsers import NotebookIssue, ParseErrorCode

SUPPORTED_SUFFIXES = frozenset({".py", ".ipynb"})
DEFAULT_EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".tox",
        ".nox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".ipynb_checkpoints",
        "build",
        "dist",
        ".eggs",
        "node_modules",
    }
)


@dataclass(frozen=True, slots=True)
class ScanNotice:
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class ScanReport:
    results: tuple[AnalysisResult, ...]
    scan_errors: tuple[AnalysisError, ...] = ()
    scan_notices: tuple[ScanNotice, ...] = ()
    enabled_rule_count: int = 0

    @property
    def findings(self) -> tuple[Finding, ...]:
        return tuple(finding for result in self.results for finding in result.findings)

    @property
    def analysis_errors(self) -> tuple[AnalysisError, ...]:
        return (*self.scan_errors, *(error for result in self.results for error in result.errors))

    @property
    def notebook_notices(self) -> tuple[NotebookIssue, ...]:
        return tuple(notice for result in self.results for notice in result.notices)


def _scan_error(code: ParseErrorCode, path: Path, message: str) -> AnalysisError:
    return AnalysisError(AnalysisErrorStage.PARSE, code, str(path), message)


def _exclude_parts(value: str) -> tuple[str, ...]:
    """An exclusion is a relative path below the scanned directory."""
    if not value or Path(value).is_absolute() or value.startswith(("/", "\\")):
        raise ValueError("--exclude must be a nonempty relative path")
    parts = tuple(part for part in value.replace("\\", "/").split("/") if part != ".")
    if not parts or any(part in ("", "..") for part in parts) or ":" in parts[0]:
        raise ValueError("--exclude must stay inside the scanned directory")
    return parts


class Scanner:
    """Discover supported paths and ask Analyzer to process each file once."""

    def __init__(self, analyzer: Analyzer) -> None:
        self.analyzer = analyzer

    def scan(self, path: str | Path, *, exclude: tuple[str, ...] = ()) -> ScanReport:
        root = Path(path)
        excluded = tuple(_exclude_parts(value) for value in exclude)
        enabled_count = len(tuple(self.analyzer.registry.iter_enabled()))
        if root.is_file():
            if root.suffix.lower() not in SUPPORTED_SUFFIXES:
                return ScanReport(
                    (),
                    (
                        _scan_error(
                            ParseErrorCode.UNSUPPORTED_FILE, root, "Expected a .py or .ipynb file"
                        ),
                    ),
                    enabled_rule_count=enabled_count,
                )
            return ScanReport((self.analyzer.analyze_file(root),), enabled_rule_count=enabled_count)
        if not root.is_dir():
            return ScanReport(
                (),
                (
                    _scan_error(
                        ParseErrorCode.READ_ERROR, root, "Path does not exist or is not readable"
                    ),
                ),
                enabled_rule_count=enabled_count,
            )

        files: list[Path] = []
        errors: list[AnalysisError] = []

        def walk(directory: Path, relative: tuple[str, ...]) -> None:
            try:
                entries = sorted(directory.iterdir(), key=lambda item: item.name)
            except OSError as error:
                errors.append(
                    _scan_error(
                        ParseErrorCode.READ_ERROR,
                        directory,
                        f"Cannot list directory: {type(error).__name__}",
                    )
                )
                return
            for entry in entries:
                parts = (*relative, entry.name)
                if any(parts[: len(prefix)] == prefix for prefix in excluded):
                    continue
                try:
                    if entry.is_dir():
                        if (
                            entry.name.casefold() not in DEFAULT_EXCLUDED_DIRS
                            and not entry.name.casefold().endswith(".egg-info")
                            and not entry.is_symlink()
                        ):
                            walk(entry, parts)
                    elif entry.is_file() and entry.suffix.lower() in SUPPORTED_SUFFIXES:
                        files.append(entry)
                except OSError as error:
                    errors.append(
                        _scan_error(
                            ParseErrorCode.READ_ERROR,
                            entry,
                            f"Cannot inspect path: {type(error).__name__}",
                        )
                    )

        walk(root, ())
        files.sort(key=lambda item: item.as_posix())
        results = tuple(self.analyzer.analyze_file(file) for file in files)
        notices = (
            ()
            if files or errors
            else (
                ScanNotice(
                    "no_supported_files", str(root), "No supported .py or .ipynb files found"
                ),
            )
        )
        return ScanReport(results, tuple(errors), notices, enabled_count)

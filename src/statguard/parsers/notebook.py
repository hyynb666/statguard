"""Read Notebook source as data and delegate each Python cell to PythonSourceParser."""

import io
import json
import tokenize
from os import PathLike
from pathlib import Path

from statguard.parsers.models import ParseErrorCode, SourceParseError
from statguard.parsers.notebook_models import (
    NotebookCell,
    NotebookIssue,
    NotebookIssueCode,
    NotebookParseError,
    ParsedNotebook,
)
from statguard.parsers.python import PythonSourceParser


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-JSON numeric constant: {value}")


def _special_syntax(source: str) -> tuple[int, int] | None:
    """Locate explicit IPython markers after Python parsing failed.

    Tokenization protects string literals/comments from marker matching. It
    does not transform code. Ambiguous/unrecognized syntax remains a Python
    syntax error. Valid standard Python always takes priority.
    """
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    depth = 0
    statement_start = True
    previous = ""
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type in (tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT, tokenize.NL):
                continue
            if token.type == tokenize.NEWLINE:
                statement_start, previous = True, ""
                continue
            if token.type == tokenize.ERRORTOKEN and token.string.isspace():
                continue
            if token.type == tokenize.ERRORTOKEN and token.string in ("'", '"'):
                return None  # Do not treat text inside an unterminated string as a command.
            marker = (
                depth == 0
                and token.type in (tokenize.OP, tokenize.ERRORTOKEN)
                and token.string in ("!", "?")
            )
            marker |= depth == 0 and token.string == "%" and (statement_start or previous == "=")
            marker |= depth == 0 and statement_start and token.string in ("/", ",", ";")
            if marker:
                return token.start[0], token.start[1] + 1
            if token.type == tokenize.OP:
                if token.string in ("(", "[", "{"):
                    depth += 1
                elif token.string in (")", "]", "}"):
                    depth -= 1
            statement_start = token.string == ";" and depth == 0
            previous = token.string
    except (tokenize.TokenError, SyntaxError):
        pass  # The original parser failure remains an explicit cell error.
    return None


class NotebookParser:
    """Parse nbformat 4 Python code cells independently, without executing them."""

    def __init__(self, python_parser: PythonSourceParser | None = None) -> None:
        self._python_parser = python_parser if python_parser is not None else PythonSourceParser()

    def parse_file(self, path: str | PathLike[str]) -> ParsedNotebook:
        file_path = Path(path)
        label = str(file_path)
        if file_path.suffix.lower() != ".ipynb":
            raise NotebookParseError(
                NotebookIssue(ParseErrorCode.UNSUPPORTED_FILE, label, "Expected an .ipynb file")
            )
        try:
            text = file_path.read_text(encoding="utf-8-sig")
        except UnicodeError as error:
            raise NotebookParseError(
                NotebookIssue(ParseErrorCode.ENCODING_ERROR, label, str(error))
            ) from error
        except (OSError, ValueError) as error:
            raise NotebookParseError(
                NotebookIssue(ParseErrorCode.READ_ERROR, label, str(error))
            ) from error
        return self.parse_json(text, path=label)

    def parse_json(self, text: str, *, path: str = "<notebook>") -> ParsedNotebook:
        """Decode JSON and parse code sources; never inspect outputs or execution_count.

        Fatal document failures raise NotebookParseError. Cell-level Python or
        unsupported-syntax failures are retained in the result and later cells
        continue parsing. JSON decoding necessarily reads the container bytes.
        """
        if not isinstance(text, str):
            raise TypeError("text must be a JSON string")
        try:
            document = json.loads(text, parse_constant=_reject_constant)
        except json.JSONDecodeError as error:
            raise NotebookParseError(
                NotebookIssue(
                    NotebookIssueCode.INVALID_JSON,
                    path,
                    error.msg,
                    line=error.lineno,
                    column=error.colno,
                )
            ) from error
        except ValueError as error:
            raise NotebookParseError(
                NotebookIssue(NotebookIssueCode.INVALID_JSON, path, str(error))
            ) from error
        except RecursionError as error:
            raise NotebookParseError(
                NotebookIssue(ParseErrorCode.RESOURCE_LIMIT, path, str(error))
            ) from error

        sources, cell_count = self._sources(document, path)
        code_cells: list[NotebookCell] = []
        for code_index, (cell_index, source) in enumerate(sources, start=1):
            try:
                parsed = self._python_parser.parse_source(source, path=path)
            except SourceParseError as error:
                special = (
                    _special_syntax(source) if error.code is ParseErrorCode.SYNTAX_ERROR else None
                )
                issue = NotebookIssue(
                    NotebookIssueCode.UNSUPPORTED_SYNTAX if special else error.code,
                    path,
                    "IPython syntax is unsupported; the entire cell was left unparsed."
                    if special
                    else error.message,
                    cell_index,
                    code_index,
                    special[0] if special else error.line,
                    special[1] if special else error.column,
                )
                code_cells.append(NotebookCell(cell_index, code_index, source, None, issue))
            else:
                code_cells.append(NotebookCell(cell_index, code_index, source, parsed))
        notice = NotebookIssue(
            NotebookIssueCode.DOCUMENT_ORDER,
            path,
            "Cells were parsed independently in document order, not historical execution order.",
        )
        return ParsedNotebook(path, cell_count, tuple(code_cells), (notice,))

    @staticmethod
    def _sources(document: object, path: str) -> tuple[list[tuple[int, str]], int]:
        """Validate source-bearing structure; do not traverse outputs/attachments."""

        def invalid(message: str, cell_index: int | None = None) -> None:
            raise NotebookParseError(
                NotebookIssue(NotebookIssueCode.INVALID_NOTEBOOK, path, message, cell_index)
            )

        if not isinstance(document, dict):
            invalid("Notebook root must be an object")
        if type(document.get("nbformat")) is not int:
            invalid("nbformat must be an integer")
        if document["nbformat"] != 4:
            raise NotebookParseError(
                NotebookIssue(
                    NotebookIssueCode.UNSUPPORTED_VERSION, path, "Only nbformat 4 is supported"
                )
            )
        minor = document.get("nbformat_minor")
        if type(minor) is not int or minor < 0:
            invalid("nbformat_minor must be a nonnegative integer")
        metadata, cells = document.get("metadata"), document.get("cells")
        if not isinstance(metadata, dict) or not isinstance(cells, list):
            invalid("Notebook requires metadata object and cells array")

        languages: list[str] = []
        for key, field in (("language_info", "name"), ("kernelspec", "language")):
            if key not in metadata:
                continue
            block = metadata[key]
            if not isinstance(block, dict):
                invalid(f"metadata.{key} must be an object")
            if field not in block:
                continue
            language = block[field]
            if not isinstance(language, str) or not language.strip():
                invalid(f"metadata.{key}.{field} must be a nonempty string")
            languages.append(language.strip().casefold())
        if any(language not in ("python", "python3") for language in languages):
            raise NotebookParseError(
                NotebookIssue(
                    NotebookIssueCode.UNSUPPORTED_LANGUAGE,
                    path,
                    "Only explicitly declared Python notebooks are supported; "
                    "language declarations: " + ", ".join(languages),
                )
            )

        sources: list[tuple[int, str]] = []
        for index, cell in enumerate(cells, start=1):
            if not isinstance(cell, dict):
                invalid("Each cell must be an object", index)
            kind = cell.get("cell_type")
            if kind not in ("code", "markdown", "raw"):
                invalid("cell_type must be code, markdown or raw", index)
            if not isinstance(cell.get("metadata"), dict):
                invalid("Cell metadata must be an object", index)
            source = cell.get("source")
            if isinstance(source, list) and all(isinstance(part, str) for part in source):
                source = "".join(source)
            if not isinstance(source, str):
                invalid("Cell source must be a string or an array of strings", index)
            if kind == "code":
                sources.append((index, source))
        if sources and not languages:
            raise NotebookParseError(
                NotebookIssue(
                    NotebookIssueCode.UNKNOWN_LANGUAGE,
                    path,
                    "Code cells require metadata.language_info.name or "
                    "metadata.kernelspec.language; "
                    "kernel names alone do not establish the source language.",
                )
            )
        return sources, len(cells)

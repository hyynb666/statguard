"""Non-executing Python AST parsing and syntax indexing."""

import ast
import io
import tokenize
from dataclasses import replace
from os import PathLike
from pathlib import Path

from statguard.parsers.models import (
    CallInfo,
    Definition,
    ParsedSource,
    ParseErrorCode,
    SourceParseError,
    SyntaxNode,
)


class PythonSourceParser:
    """Parse Python syntax only; never import or execute submitted source."""

    def parse_source(self, source: str, *, path: str = "<string>") -> ParsedSource:
        """Parse text under a diagnostic path label using the host Python grammar.

        Raises SourceParseError on syntax/encoding/resource failures. No files
        are accessed by this method, so a later notebook reader can reuse it.
        """
        if not isinstance(source, str):
            raise TypeError("source must be a string")
        try:
            tree = ast.parse(source, filename=path, mode="exec")
        except SyntaxError as error:
            raise SourceParseError(
                ParseErrorCode.SYNTAX_ERROR,
                path,
                error.msg,
                line=error.lineno if error.lineno and error.lineno > 0 else None,
                column=error.offset if error.offset and error.offset > 0 else None,
            ) from error
        except UnicodeError as error:
            raise SourceParseError(ParseErrorCode.ENCODING_ERROR, path, str(error)) from error
        except RecursionError as error:
            raise SourceParseError(ParseErrorCode.RESOURCE_LIMIT, path, str(error)) from error
        return self._index(ParsedSource(path, source, tree))

    def parse_file(self, path: str | PathLike[str]) -> ParsedSource:
        """Read a .py file with Python encoding detection (UTF-8/BOM/PEP 263)."""
        file_path = Path(path)
        label = str(file_path)
        if file_path.suffix.lower() != ".py":
            raise SourceParseError(
                ParseErrorCode.UNSUPPORTED_FILE, label, "Expected a .py source file"
            )
        try:
            data = file_path.read_bytes()
        except (OSError, ValueError) as error:
            raise SourceParseError(ParseErrorCode.READ_ERROR, label, str(error)) from error
        try:
            encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
            source = data.decode(encoding)
        except (SyntaxError, UnicodeError, LookupError) as error:
            raise SourceParseError(ParseErrorCode.ENCODING_ERROR, label, str(error)) from error
        return self.parse_source(source, path=label)

    @staticmethod
    def _index(unit: ParsedSource) -> ParsedSource:
        imports: list[SyntaxNode[ast.Import | ast.ImportFrom]] = []
        assignments: list[SyntaxNode[ast.Assign | ast.AnnAssign]] = []
        calls: list[CallInfo] = []
        functions: list[SyntaxNode[ast.FunctionDef | ast.AsyncFunctionDef]] = []
        stack: list[tuple[ast.AST, tuple[Definition, ...]]] = [(unit.tree, ())]
        while stack:
            node, definitions = stack.pop()
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports.append(SyntaxNode(node, unit.location_for(node), definitions))
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                assignments.append(SyntaxNode(node, unit.location_for(node), definitions))
            elif isinstance(node, ast.Call):
                calls.append(CallInfo(node, unit.location_for(node), definitions))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(SyntaxNode(node, unit.location_for(node), definitions))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                definitions = (*definitions, node)
            stack.extend(
                (child, definitions) for child in reversed(list(ast.iter_child_nodes(node)))
            )

        def position(item: SyntaxNode) -> tuple[int, int]:
            return item.location.line, item.location.column

        # Stable source-position order, with AST preorder breaking ties. This is
        # not execution order: nested calls and function bodies remain syntax.
        return replace(
            unit,
            imports=tuple(sorted(imports, key=position)),
            assignments=tuple(sorted(assignments, key=position)),
            calls=tuple(sorted(calls, key=position)),
            functions=tuple(sorted(functions, key=position)),
        )

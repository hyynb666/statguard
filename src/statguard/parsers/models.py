"""Syntax records shared by source parsers, separate from statistical findings."""

import ast
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, TypeVar

NodeT = TypeVar("NodeT", bound=ast.AST)
Definition = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


class ParseErrorCode(StrEnum):
    """Failures are explicit errors, never empty successful analyses."""

    READ_ERROR = "read_error"
    ENCODING_ERROR = "encoding_error"
    SYNTAX_ERROR = "syntax_error"
    UNSUPPORTED_FILE = "unsupported_file"
    RESOURCE_LIMIT = "resource_limit"


class SourceParseError(Exception):
    """A parser failure with a path and an optional one-based character location."""

    def __init__(
        self,
        code: ParseErrorCode,
        path: str,
        message: str,
        *,
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        self.code = code
        self.path = path
        self.message = message
        self.line = line
        self.column = column
        location = path
        if line is not None:
            location += f":{line}"
            if column is not None:
                location += f":{column}"
        super().__init__(f"{location}: {code.value}: {message}")


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """One-based Unicode character coordinates, with an exclusive end position.

    Tabs count as one character. Raw AST nodes retain their original zero-based
    UTF-8 byte offsets. End positions may be absent on manually constructed ASTs.
    """

    path: str
    line: int
    column: int
    end_line: int | None
    end_column: int | None


@dataclass(frozen=True, slots=True)
class SyntaxNode(Generic[NodeT]):
    """A raw AST node and its location, without runtime or data-flow conclusions.

    Enclosing definitions are syntactic function/class ancestors, outermost first.
    They are not runtime scopes: a decorator/default may run outside its function.
    """

    node: NodeT
    location: SourceLocation
    enclosing_definitions: tuple[Definition, ...] = ()


@dataclass(frozen=True, slots=True)
class CallInfo(SyntaxNode[ast.Call]):
    """A call whose target name is syntactic only; None means unknown.

    Only Name/Attribute chains rooted in a Name have a dotted name. No alias
    resolution, runtime identity, argument evaluation, or type inference occurs.
    """

    @property
    def name(self) -> str | None:
        parts: list[str] = []
        target = self.node.func
        while isinstance(target, ast.Attribute):
            parts.append(target.attr)
            target = target.value
        if not isinstance(target, ast.Name):
            return None
        parts.append(target.id)
        return ".".join(reversed(parts))

    @property
    def is_unknown(self) -> bool:
        return self.name is None

    @property
    def args(self) -> tuple[ast.expr, ...]:
        """Original argument nodes, including Starred for *args."""
        return tuple(self.node.args)

    @property
    def keywords(self) -> tuple[ast.keyword, ...]:
        """Original keyword nodes; keyword.arg is None for **kwargs."""
        return tuple(self.node.keywords)


@dataclass(frozen=True, slots=True)
class ParsedSource:
    """One successfully parsed source unit with deterministic syntax indexes.

    Records refer to the same nodes as tree. Treat the raw AST as read-only:
    frozen wrappers do not make Python's AST objects immutable.
    """

    path: str
    source: str
    tree: ast.Module
    imports: tuple[SyntaxNode[ast.Import | ast.ImportFrom], ...] = ()
    assignments: tuple[SyntaxNode[ast.Assign | ast.AnnAssign], ...] = ()
    calls: tuple[CallInfo, ...] = ()
    functions: tuple[SyntaxNode[ast.FunctionDef | ast.AsyncFunctionDef], ...] = ()
    _lines: tuple[bytes, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Only Python's universal newlines split source lines; str.splitlines()
        # would incorrectly split U+2028 and other characters inside literals.
        normalized = self.source.replace("\r\n", "\n").replace("\r", "\n")
        object.__setattr__(
            self, "_lines", tuple(line.encode("utf-8") for line in normalized.split("\n"))
        )

    def location_for(self, node: ast.AST) -> SourceLocation:
        """Locate any positioned node in this tree, including aliases/arguments.

        Pass a node from this unit's unmodified tree. Nodes without a start
        location (for example Module or Load) raise ValueError.
        """
        line = getattr(node, "lineno", None)
        offset = getattr(node, "col_offset", None)
        if line is None or offset is None:
            raise ValueError("AST node has no source location")
        end_line = getattr(node, "end_lineno", None)
        end_offset = getattr(node, "end_col_offset", None)
        column = len(self._lines[line - 1][:offset].decode("utf-8")) + 1
        end_column = None
        if end_line is not None and end_offset is not None:
            end_column = len(self._lines[end_line - 1][:end_offset].decode("utf-8")) + 1
        return SourceLocation(self.path, line, column, end_line, end_column)

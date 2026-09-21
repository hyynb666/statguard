"""One parsed Python unit exposed to a rule, without executing target source."""

import ast
from dataclasses import dataclass, field

from statguard.parsers.models import CallInfo, ParsedSource, SyntaxNode
from statguard.provenance import ProvenanceTracker
from statguard.symbols import SymbolResolver


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    """Read-only view of a file or one independently parsed Notebook code cell.

    ``parsed`` owns the original AST and syntax indexes. Both cell identifiers
    are absent for a Python file. A Notebook context carries the original cell
    index and the code-cell ordinal; both are one-based. No output data or
    cross-cell state is available through this interface.
    """

    parsed: ParsedSource
    cell_index: int | None = None
    cell: int | None = None
    _symbols: SymbolResolver | None = field(default=None, init=False, repr=False, compare=False)

    _provenance: ProvenanceTracker | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not isinstance(self.parsed, ParsedSource):
            raise TypeError("parsed must be a ParsedSource")
        if (self.cell_index is None) != (self.cell is None):
            raise ValueError("Notebook contexts require both cell_index and cell")
        for name in ("cell_index", "cell"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 1):
                raise ValueError(f"{name} must be a one-based integer")
        if self.cell is not None and self.cell > self.cell_index:
            raise ValueError("cell cannot exceed cell_index")

    @property
    def file_path(self) -> str:
        return self.parsed.path

    @property
    def path(self) -> str:
        return self.parsed.path

    @property
    def source(self) -> str:
        return self.parsed.source

    @property
    def tree(self) -> ast.Module:
        return self.parsed.tree

    @property
    def imports(self) -> tuple[SyntaxNode[ast.Import | ast.ImportFrom], ...]:
        return self.parsed.imports

    @property
    def assignments(self) -> tuple[SyntaxNode[ast.Assign | ast.AnnAssign], ...]:
        return self.parsed.assignments

    @property
    def calls(self) -> tuple[CallInfo, ...]:
        return self.parsed.calls

    @property
    def functions(self) -> tuple[SyntaxNode[ast.FunctionDef | ast.AsyncFunctionDef], ...]:
        return self.parsed.functions

    @property
    def is_notebook(self) -> bool:
        return self.cell_index is not None

    @property
    def symbols(self) -> SymbolResolver:
        """Lazily index this unit only; existing parser objects remain unchanged."""
        if self._symbols is None:
            object.__setattr__(self, "_symbols", SymbolResolver(self.parsed))
        return self._symbols

    @property
    def provenance(self) -> ProvenanceTracker:
        """Data relationships for this unit, using the same cached symbols."""
        if self._provenance is None:
            object.__setattr__(
                self,
                "_provenance",
                ProvenanceTracker(self.parsed, self.symbols, cell_index=self.cell_index),
            )
        return self._provenance

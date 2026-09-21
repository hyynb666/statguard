"""Immutable, evidence-based data relationships over versioned symbol bindings."""

import ast
import json
from dataclasses import dataclass

from statguard.parsers.models import ParsedSource, SourceLocation
from statguard.provenance_sklearn import split_inputs, transformed_input
from statguard.symbols import Binding, SymbolResolver, SymbolValue, ValueKind


@dataclass(frozen=True, slots=True)
class SplitRole:
    split_id: str
    input_index: int
    role: str


@dataclass(frozen=True, slots=True, eq=False)
class CallInput:
    parameter: int | str | None
    value: "DataOrigin"


@dataclass(frozen=True, slots=True, eq=False)
class DataOrigin:
    id: str
    kind: str
    node: ast.AST
    location: SourceLocation
    cell_index: int | None
    known: bool
    reason: str | None = None
    sources: tuple["DataOrigin", ...] = ()
    inputs: tuple[CallInput, ...] = ()
    roles: tuple[SplitRole, ...] = ()
    callee: SymbolValue | None = None

    @property
    def is_unknown(self) -> bool:
        """Whether this record lacks a supported output relationship, not runtime validity."""
        return not self.known


class ProvenanceTracker:
    """Queries use original nodes/bindings, never names in a final environment.

    inputs are syntactic arguments; sources are supported data relationships.
    An opaque call has inputs but no sources or inherited train/test roles.
    """

    def __init__(
        self, parsed: ParsedSource, symbols: SymbolResolver, *, cell_index: int | None = None
    ) -> None:
        if not isinstance(parsed, ParsedSource) or not isinstance(symbols, SymbolResolver):
            raise TypeError("parsed and symbols must be parser/symbol objects")
        if symbols.parsed is not parsed:
            raise ValueError("symbols must belong to this ParsedSource")
        self._parsed = parsed
        self._symbols = symbols
        self._cell_index = cell_index
        self._nodes = {node: index for index, node in enumerate(ast.walk(parsed.tree))}
        self._binding_set = set(symbols.bindings)
        self._cache: dict[SymbolValue, DataOrigin] = {}
        self._bindings: dict[Binding, DataOrigin] = {}

    def _record(self, node: ast.AST, kind: str, known: bool, *, suffix: str = "", **facts):
        key = json.dumps([self._parsed.path, self._cell_index, self._nodes[node], suffix])
        return DataOrigin(
            key, kind, node, self._parsed.location_for(node), self._cell_index, known, **facts
        )

    def resolve(self, expression: ast.expr) -> DataOrigin:
        if not isinstance(expression, ast.expr) or expression not in self._nodes:
            raise ValueError("expression must belong to this ParsedSource")
        return self._value(self._symbols.resolve(expression))

    def for_binding(self, binding: Binding) -> DataOrigin:
        if binding not in self._binding_set:
            raise ValueError("binding must belong to this SymbolResolver")
        self._ensure(binding)
        return self._bindings[binding]

    def _build_binding(self, binding: Binding) -> None:
        if binding not in self._bindings:
            source = self._value(binding.value)
            self._bindings[binding] = self._record(
                binding.node,
                "binding",
                source.known,
                suffix=f"binding:{binding.order}",
                sources=(source,),
                roles=source.roles,
                reason=source.reason,
            )
        return self._bindings[binding]

    @property
    def splits(self) -> tuple[DataOrigin, ...]:
        return tuple(
            origin
            for call in self._parsed.calls
            if (origin := self.resolve(call.node)).kind == "split"
        )

    def _ensure(self, root: SymbolValue | Binding) -> None:
        # Resolver facts form a DAG of earlier binding versions. Use an explicit
        # postorder stack so query order and long alias/call chains cannot exhaust
        # Python's recursion limit.
        stack = [(root, False)]
        while stack:
            item, ready = stack.pop()
            cache = self._bindings if isinstance(item, Binding) else self._cache
            if item in cache:
                continue
            if ready:
                if isinstance(item, Binding):
                    self._build_binding(item)
                else:
                    self._build_value(item)
                continue
            stack.append((item, True))
            if isinstance(item, Binding):
                dependencies = [item.value]
            elif item.binding is not None:
                dependencies = [item.binding]
            elif item.unpack_source is not None:
                dependencies = [item.unpack_source]
            elif item.kind is ValueKind.CALL:
                dependencies = [self._symbols.resolve(arg) for arg in item.node.args]
                dependencies += [self._symbols.resolve(kw.value) for kw in item.node.keywords]
            else:
                dependencies = []
            stack.extend((dependency, False) for dependency in reversed(dependencies))

    def _value(self, value: SymbolValue) -> DataOrigin:
        self._ensure(value)
        return self._cache[value]

    def _build_value(self, value: SymbolValue) -> None:
        node = value.node
        if value.binding is not None:
            source = self.for_binding(value.binding)
            result = self._record(
                node,
                "alias",
                source.known,
                sources=(source,),
                roles=source.roles,
                reason=source.reason,
            )
        elif value.unpack_source is not None:
            split = self._value(value.unpack_source)
            while split.kind in {"alias", "binding"}:
                split = split.sources[0]
            if split.kind == "split" and value.unpack_size == 2 * len(split.sources):
                index = value.unpack_index // 2
                role = SplitRole(
                    split.id, index, "train" if value.unpack_index % 2 == 0 else "test"
                )
                result = self._record(
                    node, "split_output", True, sources=(split.sources[index],), roles=(role,)
                )
            else:
                result = self._record(node, "unknown", False, reason="Unsupported unpacking")
        elif value.kind is ValueKind.CALL:
            inputs = tuple(CallInput(i, self.resolve(arg)) for i, arg in enumerate(node.args))
            inputs += tuple(CallInput(kw.arg, self.resolve(kw.value)) for kw in node.keywords)
            arrays = split_inputs(value)
            transformed = transformed_input(value)
            if arrays is not None:
                result = self._record(
                    node,
                    "split",
                    True,
                    sources=tuple(self.resolve(arg) for arg in arrays),
                    inputs=inputs,
                    callee=value.callee,
                )
            elif transformed is not None:
                source = self.resolve(transformed)
                result = self._record(
                    node,
                    "transform",
                    True,
                    sources=(source,),
                    inputs=inputs,
                    roles=source.roles,
                    callee=value.callee,
                )
            else:
                result = self._record(
                    node,
                    "call",
                    False,
                    inputs=inputs,
                    callee=value.callee,
                    reason="Opaque return semantics; arguments are not proven lineage",
                )
        else:
            result = self._record(
                node, "unknown", False, reason=value.reason or "No supported data relationship"
            )
        self._cache[value] = result

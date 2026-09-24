"""Immutable, evidence-based data relationships over versioned symbol bindings."""

import ast
import json
from dataclasses import dataclass

from statguard.parsers.models import ParsedSource, SourceLocation
from statguard.provenance_sklearn import (
    TRANSFORMER_PATHS,
    split_inputs,
    transformed_input,
    transformer_fit_inputs,
    transformer_instance,
)
from statguard.symbols import Binding, EvaluationSite, SymbolResolver, SymbolValue, ValueKind


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


@dataclass(frozen=True, slots=True, eq=False)
class FittedTransform:
    """Evidence that one supported transform followed a fit on the same input.

    AST nodes and the fit callee are parser-owned evidence. ``instance_id`` is
    deterministic within a parsed unit and identifies the constructor call, not
    a runtime object beyond the supported local analysis model.
    """

    instance_id: str
    fit: DataOrigin
    transform: DataOrigin
    fit_callee: SymbolValue
    scope: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef
    fit_site: EvaluationSite
    transform_site: EvaluationSite


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
        self._fitted_transforms: tuple[FittedTransform, ...] | None = None

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

    @property
    def fitted_transforms(self) -> tuple[FittedTransform, ...]:
        """Known same-instance fit/transform pairs in supported straight-line scopes."""
        if self._fitted_transforms is None:
            object.__setattr__(self, "_fitted_transforms", self._collect_fitted_transforms())
        return self._fitted_transforms

    def _input_binding(self, expression: ast.expr) -> Binding | None:
        """Return a stable source binding for a simple name/alias expression."""
        if not isinstance(expression, ast.Name):
            return None
        value = self._symbols.resolve(expression)
        seen: set[Binding] = set()
        while value.binding is not None:
            binding = value.binding
            if binding in seen:
                return None
            seen.add(binding)
            if isinstance(binding.node, ast.arg):
                return binding
            assigned = binding.value
            if assigned.kind is ValueKind.ALIAS and assigned.binding is not None:
                value = assigned
                continue
            if assigned.kind is ValueKind.UNKNOWN:
                return None
            return binding
        return None

    def _collect_fitted_transforms(self) -> tuple[FittedTransform, ...]:
        # Process each scope independently, in the resolver's evaluation order.
        grouped: dict[ast.AST, list[tuple[EvaluationSite, ast.Call]]] = {}
        for info in self._parsed.calls:
            site = self._symbols.evaluation_site(info.node)
            if site is not None:
                grouped.setdefault(site.scope, []).append((site, info.node))

        scope_order = sorted(
            grouped,
            key=lambda scope: (
                0 if isinstance(scope, ast.Module) else getattr(scope, "lineno", 0),
                type(scope).__name__,
            ),
        )
        evidence: list[FittedTransform] = []
        for scope in scope_order:
            events = sorted(grouped[scope], key=lambda item: item[0].order)
            states: dict[ast.Call, tuple[DataOrigin, SymbolValue, Binding, EvaluationSite]] = {}
            poisoned: set[ast.Call] = set()
            known_instances: set[ast.Call] = set()

            for site, call in events:
                call_value = self._symbols.resolve(call)
                callee = call_value.callee
                method = callee.origin if callee is not None else None
                if callee is not None and callee.qualified_name in TRANSFORMER_PATHS:
                    known_instances.add(call)
                instance = transformer_instance(callee) if callee is not None else None
                instance_node = instance.node if instance is not None else None

                # An opaque call receiving the fitted input could mutate that
                # input in place. Do not claim that a later transform consumed
                # the same data version unless the call is a supported split or
                # supported transformer operation.
                known_read = split_inputs(call_value) is not None or (
                    instance is not None
                    and method is not None
                    and method.attribute in {"fit", "fit_transform", "transform"}
                )
                if not known_read:
                    arguments = [*call.args, *(kw.value for kw in call.keywords)]
                    for tracked, (_, _, fit_binding, _) in tuple(states.items()):
                        if any(
                            self._input_binding(argument) is fit_binding for argument in arguments
                        ):
                            states.pop(tracked, None)
                            poisoned.add(tracked)

                # Passing a tracked instance through any call can mutate its
                # configuration or fitted state. Only its own recognized
                # fit/transform methods are allowed to receive that state.
                passed_instances = {
                    value.origin.node
                    for expression in [*call.args, *(kw.value for kw in call.keywords)]
                    if (value := self._symbols.resolve(expression)).origin.kind is ValueKind.CALL
                    and value.origin.callee.qualified_name in TRANSFORMER_PATHS
                    and value.origin.node in known_instances
                }
                for passed in passed_instances:
                    states.pop(passed, None)
                    poisoned.add(passed)

                if instance_node is None or method is None:
                    continue

                receiver_site = self._symbols.evaluation_site(instance_node)
                if (
                    receiver_site is None
                    or receiver_site.scope is not scope
                    or receiver_site.order >= site.order
                ):
                    continue

                if method.attribute in {"fit", "fit_transform"}:
                    fit_inputs = transformer_fit_inputs(callee, call)
                    source_binding = (
                        self._input_binding(fit_inputs[0]) if fit_inputs is not None else None
                    )
                    if source_binding is None or instance_node in poisoned:
                        states.pop(instance_node, None)
                        continue
                    fit_origin = self._record(
                        call,
                        "fit",
                        True,
                        suffix=f"fit:{site.order}",
                        sources=(self.resolve(fit_inputs[0]),),
                        inputs=tuple(
                            CallInput(index, self.resolve(expression))
                            for index, expression in enumerate(fit_inputs)
                        ),
                        callee=callee,
                    )
                    states[instance_node] = (fit_origin, callee, source_binding, site)
                    continue

                if method.attribute == "transform":
                    state = states.get(instance_node)
                    output_input = transformed_input(call_value)
                    if state is None or output_input is None or instance_node in poisoned:
                        continue
                    fit_origin, fit_callee, fit_binding, fit_site = state
                    if self._input_binding(output_input) is not fit_binding:
                        continue
                    transformed = self.resolve(call)
                    evidence.append(
                        FittedTransform(
                            instance_id=json.dumps(
                                [self._parsed.path, self._cell_index, self._nodes[instance_node]]
                            ),
                            fit=fit_origin,
                            transform=transformed,
                            fit_callee=fit_callee,
                            scope=scope,
                            fit_site=fit_site,
                            transform_site=site,
                        )
                    )
                    continue

                # Any other method on the exact instance can change parameters
                # or learned state. Do not let a later fit restore certainty:
                # it may use configuration changed by the unknown operation.
                states.pop(instance_node, None)
                poisoned.add(instance_node)

        return tuple(
            sorted(
                evidence,
                key=lambda item: (
                    item.transform.location.line,
                    item.transform.location.column,
                    item.fit.location.line,
                    item.instance_id,
                ),
            )
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

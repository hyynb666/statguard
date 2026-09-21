"""Conservative, per-unit symbol provenance over parser-owned AST nodes."""

import ast
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from statguard.parsers.models import ParsedSource, SourceLocation

Scope = ast.Module | ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True, slots=True)
class EvaluationSite:
    """Supported evaluation order within one scope, not invocation history."""

    scope: Scope
    order: int


class ValueKind(StrEnum):
    UNKNOWN = "unknown"
    IMPORT = "import"
    ALIAS = "alias"
    CALL = "call"
    ATTRIBUTE = "attribute"
    LITERAL = "literal"


@dataclass(frozen=True, slots=True, eq=False)
class SymbolValue:
    """An expression's syntax provenance, never an inferred runtime value/type."""

    kind: ValueKind
    node: ast.AST
    reason: str | None = None
    import_path: str | None = None
    binding: "Binding | None" = None
    base: "SymbolValue | None" = None
    attribute: str | None = None
    callee: "SymbolValue | None" = None
    unpack_source: "SymbolValue | None" = None
    unpack_index: int | None = None
    unpack_size: int | None = None

    @property
    def origin(self) -> "SymbolValue":
        value = self
        while value.kind is ValueKind.ALIAS and value.binding is not None:
            value = value.binding.value
        return value

    @property
    def is_unknown(self) -> bool:
        value = self.origin
        while True:
            if value.kind is ValueKind.ATTRIBUTE and value.base is not None:
                value = value.base.origin
            elif value.kind is ValueKind.CALL and value.callee is not None:
                value = value.callee.origin
            else:
                return value.kind is ValueKind.UNKNOWN

    @property
    def qualified_name(self) -> str | None:
        """Import path only; a call result or instance method has no inferred type."""
        value = self.origin
        attributes: list[str] = []
        while value.kind is ValueKind.ATTRIBUTE and value.base is not None:
            attributes.append(value.attribute)
            value = value.base.origin
        if value.kind is not ValueKind.IMPORT:
            return None
        return ".".join([value.import_path, *reversed(attributes)])


@dataclass(frozen=True, slots=True, eq=False)
class Binding:
    name: str
    scope: Scope
    node: ast.AST
    location: SourceLocation
    order: int
    value: SymbolValue


def _unknown(node: ast.AST, reason: str) -> SymbolValue:
    return SymbolValue(ValueKind.UNKNOWN, node, reason=reason)


def _written_names(node: ast.AST) -> set[str]:
    """Names that may be rebound, without entering nested function/class bodies."""
    result: set[str] = set()
    stack = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            result.add(item.name)
            continue
        if isinstance(item, ast.Lambda):
            continue
        if isinstance(item, ast.Name) and isinstance(item.ctx, (ast.Store, ast.Del)):
            result.add(item.id)
        elif isinstance(item, ast.Import):
            result.update(alias.asname or alias.name.split(".")[0] for alias in item.names)
        elif isinstance(item, ast.ImportFrom):
            result.update(alias.asname or alias.name for alias in item.names if alias.name != "*")
        elif isinstance(item, ast.ExceptHandler) and item.name:
            result.add(item.name)
        elif isinstance(item, (ast.MatchAs, ast.MatchStar)) and item.name:
            result.add(item.name)
        elif isinstance(item, ast.MatchMapping) and item.rest:
            result.add(item.rest)
        stack.extend(ast.iter_child_nodes(item))
    return result


class SymbolResolver:
    """Point-of-use queries for one ParsedSource; no importing or code execution."""

    def __init__(self, parsed: ParsedSource) -> None:
        if not isinstance(parsed, ParsedSource):
            raise TypeError("parsed must be a ParsedSource")
        self._parsed = parsed
        tracker = _Tracker(parsed)
        tracker.build()
        self._values = MappingProxyType(tracker.values)
        self._sites = MappingProxyType(tracker.sites)
        self._bindings = tuple(tracker.bindings)

    @property
    def parsed(self) -> ParsedSource:
        """The parser-owned unit used for point-of-use queries."""
        return self._parsed

    @property
    def bindings(self) -> tuple[Binding, ...]:
        return self._bindings

    def resolve(self, expression: ast.expr) -> SymbolValue:
        """Query the original expression at its source position, not the final environment."""
        if not isinstance(expression, ast.expr):
            raise TypeError("expression must be an AST expression")
        return self._values.get(
            expression, _unknown(expression, "Outside a supported straight-line scope")
        )

    def evaluation_site(self, expression: ast.expr) -> EvaluationSite | None:
        """Return the supported evaluation scope/order, or None outside coverage."""
        return self._sites.get(expression)

    def binding_for(self, reference: ast.Name) -> Binding | None:
        """Return the exact binding version read by a Name; None means unbound/unsupported."""
        if not isinstance(reference, ast.Name):
            raise TypeError("reference must be an ast.Name")
        return self.resolve(reference).binding


class _Tracker:
    def __init__(self, parsed: ParsedSource) -> None:
        self.parsed = parsed
        self.values: dict[ast.expr, SymbolValue] = {}
        self.sites: dict[ast.expr, EvaluationSite] = {}
        self.bindings: list[Binding] = []
        self.functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

    def build(self) -> None:
        self._block(self.parsed.tree.body, {}, self.parsed.tree)
        # Deferred bodies never inherit definition-time globals or sibling locals.
        index = 0
        while index < len(self.functions):
            function = self.functions[index]
            index += 1
            if any(isinstance(node, (ast.Global, ast.Nonlocal)) for node in ast.walk(function)):
                continue
            env: dict[str, Binding] = {}
            args = function.args
            parameters = [*args.posonlyargs, *args.args, *args.kwonlyargs]
            parameters += [item for item in (args.vararg, args.kwarg) if item is not None]
            for arg in parameters:
                self._bind(arg.arg, _unknown(arg, "Function parameter"), arg, env, function)
            self._block(function.body, env, function)

    def _bind(
        self,
        name: str,
        value: SymbolValue,
        node: ast.AST,
        env: dict[str, Binding],
        scope: Scope,
    ) -> None:
        binding = Binding(
            name, scope, node, self.parsed.location_for(node), len(self.bindings), value
        )
        self.bindings.append(binding)
        env[name] = binding

    def _barrier(self, node: ast.AST, env: dict[str, Binding], scope: Scope, reason: str) -> None:
        for name in sorted(set(env) | _written_names(node)):
            self._bind(name, _unknown(node, reason), node, env, scope)

    def _expr(self, node: ast.expr, env: dict[str, Binding], scope: Scope) -> SymbolValue:
        if isinstance(node, ast.Name):
            binding = env.get(node.id)
            value = (
                SymbolValue(ValueKind.ALIAS, node, binding=binding)
                if binding is not None
                else _unknown(node, "Unbound or external name")
            )
        elif isinstance(node, ast.Constant):
            value = SymbolValue(ValueKind.LITERAL, node)
        elif isinstance(node, ast.Attribute):
            base = self._expr(node.value, env, scope)
            value = SymbolValue(ValueKind.ATTRIBUTE, node, base=base, attribute=node.attr)
        elif isinstance(node, ast.Call):
            callee = self._expr(node.func, env, scope)
            for arg in node.args:
                self._expr(arg, env, scope)
            for keyword in node.keywords:
                self._expr(keyword.value, env, scope)
            name = callee.qualified_name
            direct = node.func.id if isinstance(node.func, ast.Name) else None
            if direct in {
                "exec",
                "eval",
                "__import__",
                "getattr",
                "setattr",
                "delattr",
                "globals",
                "locals",
            } or name in {
                "builtins.exec",
                "builtins.eval",
                "builtins.__import__",
                "builtins.getattr",
                "builtins.setattr",
                "builtins.delattr",
                "builtins.globals",
                "builtins.locals",
                "importlib.import_module",
                "importlib.reload",
            }:
                self._barrier(node, env, scope, "Dynamic operation may change bindings")
                value = _unknown(node, "Dynamic import, reflection or evaluation")
            else:
                if callee.is_unknown:
                    self._barrier(node, env, scope, "Unresolved call effects")
                value = SymbolValue(ValueKind.CALL, node, callee=callee)
        else:
            # Includes named expressions, comprehensions, lambdas, conditional
            # expressions and await/yield. Do not interpret their execution order.
            self._barrier(node, env, scope, "Unsupported expression effects")
            value = _unknown(node, "Unsupported expression")
        self.values[node] = value
        self.sites[node] = EvaluationSite(scope, len(self.sites))
        return value

    def _target(
        self,
        target: ast.expr,
        value: SymbolValue,
        statement: ast.AST,
        env: dict[str, Binding],
        scope: Scope,
    ) -> None:
        if isinstance(target, ast.Name):
            self._bind(target.id, value, statement, env, scope)
        elif isinstance(target, (ast.Tuple, ast.List)):
            flat = all(isinstance(part, ast.Name) for part in target.elts)
            for index, part in enumerate(target.elts):
                projected = SymbolValue(
                    ValueKind.UNKNOWN,
                    part,
                    reason="Unpacking is unsupported",
                    unpack_source=value if flat else None,
                    unpack_index=index if flat else None,
                    unpack_size=len(target.elts) if flat else None,
                )
                self._target(part, projected, statement, env, scope)
        else:
            self._barrier(statement, env, scope, "Attribute/subscript mutation or complex target")

    def _block(self, statements: list[ast.stmt], env: dict[str, Binding], scope: Scope) -> None:
        for statement in statements:
            if isinstance(statement, ast.Import):
                for alias in statement.names:
                    local = alias.asname or alias.name.split(".")[0]
                    path = alias.name if alias.asname else local
                    self._bind(
                        local,
                        SymbolValue(ValueKind.IMPORT, statement, import_path=path),
                        statement,
                        env,
                        scope,
                    )
            elif isinstance(statement, ast.ImportFrom):
                if any(alias.name == "*" for alias in statement.names):
                    self._barrier(statement, env, scope, "Wildcard import")
                else:
                    for alias in statement.names:
                        value = (
                            _unknown(statement, "Relative import lacks package context")
                            if statement.level
                            else SymbolValue(
                                ValueKind.IMPORT,
                                statement,
                                import_path=f"{statement.module}.{alias.name}",
                            )
                        )
                        self._bind(alias.asname or alias.name, value, statement, env, scope)
            elif isinstance(statement, ast.Assign):
                value = self._expr(statement.value, env, scope)
                if any(
                    isinstance(item, (ast.Attribute, ast.Subscript, ast.Starred))
                    for target in statement.targets
                    for item in ast.walk(target)
                ):
                    # Do not reintroduce a stale RHS alias after a mutation barrier.
                    self._barrier(statement, env, scope, "Complex assignment target")
                    value = _unknown(statement, "Complex assignment target")
                for target in statement.targets:
                    self._target(target, value, statement, env, scope)
            elif isinstance(statement, ast.AnnAssign):
                if statement.value is not None:
                    value = self._expr(statement.value, env, scope)
                    self._target(statement.target, value, statement, env, scope)
                elif isinstance(statement.target, ast.Name) and statement.target.id not in env:
                    self._bind(
                        statement.target.id,
                        _unknown(statement, "Annotation without value"),
                        statement,
                        env,
                        scope,
                    )
                if not isinstance(statement.target, ast.Name):
                    self._barrier(statement, env, scope, "Complex annotation target")
                if isinstance(scope, ast.Module):
                    self._expr(statement.annotation, env, scope)
            elif isinstance(statement, ast.AugAssign):
                self._expr(statement.value, env, scope)
                self._target(
                    statement.target,
                    _unknown(statement, "Augmented assignment"),
                    statement,
                    env,
                    scope,
                )
            elif isinstance(statement, ast.Delete):
                for target in statement.targets:
                    self._target(
                        target, _unknown(statement, "Deleted binding"), statement, env, scope
                    )
            elif isinstance(statement, ast.Expr):
                self._expr(statement.value, env, scope)
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Headers can evaluate code; body analysis remains independent.
                if (
                    statement.decorator_list
                    or statement.args.defaults
                    or any(item is not None for item in statement.args.kw_defaults)
                    or statement.returns
                    or any(
                        isinstance(item, ast.arg) and item.annotation is not None
                        for item in ast.walk(statement.args)
                    )
                ):
                    self._barrier(statement, env, scope, "Function header effects")
                self._bind(
                    statement.name,
                    _unknown(statement, "Local function runtime value"),
                    statement,
                    env,
                    scope,
                )
                self.functions.append(statement)
            elif isinstance(statement, (ast.Return, ast.Raise)):
                value = statement.value if isinstance(statement, ast.Return) else statement.exc
                if value is not None:
                    self._expr(value, env, scope)
                break
            elif isinstance(statement, ast.Pass):
                continue
            else:
                # No branch merging or assumptions that loops/try/with execute.
                # All incoming bindings are invalidated, including possible aliases.
                self._barrier(statement, env, scope, "Unsupported control flow or statement")

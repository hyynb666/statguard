"""ST001: repeated SciPy significance tests in loops without observed correction."""

import ast
import math
from dataclasses import dataclass

from statguard.context import AnalysisContext
from statguard.core import Confidence, Evidence, Finding, Rule, Severity
from statguard.rules._scipy_tests import SUPPORTED_SCIPY_TESTS as _TESTS


@dataclass(frozen=True, slots=True)
class _TestValue:
    call: ast.Call
    is_pvalue: bool


def _scope_bodies(context: AnalysisContext):
    yield context.tree, context.tree.body
    for function in context.functions:
        node = function.node
        has_annotations = any(
            argument.annotation is not None
            for argument in [
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
                *([node.args.vararg] if node.args.vararg is not None else []),
                *([node.args.kwarg] if node.args.kwarg is not None else []),
            ]
        )
        if (
            not node.decorator_list
            and not node.args.defaults
            and not any(value is not None for value in node.args.kw_defaults)
            and node.returns is None
            and not has_annotations
        ):
            yield node, node.body


def _root_and_attributes(expression: ast.expr) -> tuple[str, tuple[str, ...]] | None:
    attributes: list[str] = []
    current = expression
    while isinstance(current, ast.Attribute):
        attributes.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    return current.id, tuple(reversed(attributes))


def _literal_container(expression: ast.AST) -> bool:
    allowed = (ast.Constant, ast.List, ast.Tuple, ast.Set, ast.Dict, ast.Load)
    return all(isinstance(node, allowed) for node in ast.walk(expression))


def _literal_barrier_preserves_name(
    context: AnalysisContext, expression: ast.AST, name: str
) -> bool:
    if not _literal_container(expression):
        return False
    assignments = [
        node
        for node in ast.walk(context.tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is expression
    ]
    return bool(assignments) and all(name not in _written_names(node) for node in assignments)


def _qualified_binding_before(
    context: AnalysisContext, name: str, scope: ast.AST, line: int
) -> str | None:
    candidates = sorted(
        (
            binding
            for binding in context.symbols.bindings
            if binding.scope is scope and binding.name == name and binding.location.line < line
        ),
        key=lambda binding: binding.order,
        reverse=True,
    )
    for binding in candidates:
        qualified_name = binding.value.qualified_name
        if qualified_name is not None:
            return qualified_name
        node = binding.node
        # SymbolResolver adds barriers at control-flow statements. A prior
        # imported binding remains usable only if that construct cannot write
        # this exact name. Real assignments/imports stop this recovery.
        if (
            binding.value.reason == "Unsupported control flow or statement"
            and isinstance(node, (ast.For, ast.AsyncFor, ast.While, ast.If))
            and name not in _written_names(node)
        ):
            continue
        if (
            binding.value.reason == "Unsupported expression effects"
            and _literal_barrier_preserves_name(context, node, name)
        ):
            continue
        return None
    return None


def _qualified_before(
    context: AnalysisContext, expression: ast.expr, scope: ast.AST, line: int
) -> str | None:
    parts = _root_and_attributes(expression)
    if parts is None:
        return None
    name, attributes = parts
    qualified_name = _qualified_binding_before(context, name, scope, line)
    if qualified_name is None:
        return None
    return ".".join((qualified_name, *attributes))


def _written_names(node: ast.AST | list[ast.stmt]) -> set[str]:
    """Collect simple writes without treating nested function bodies as executed."""
    names: set[str] = set()
    stack = list(node) if isinstance(node, list) else [node]
    while stack:
        current = stack.pop()
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(current.name)
            continue
        if isinstance(current, ast.Name) and isinstance(current.ctx, (ast.Store, ast.Del)):
            names.add(current.id)
        elif isinstance(current, ast.Import):
            names.update(alias.asname or alias.name.split(".")[0] for alias in current.names)
        elif isinstance(current, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in current.names if alias.name != "*")
        stack.extend(ast.iter_child_nodes(current))
    return names


def _loop_may_repeat(iterable: ast.expr) -> bool:
    if isinstance(iterable, (ast.List, ast.Tuple, ast.Set)):
        return len(iterable.elts) > 1
    if isinstance(iterable, ast.Dict):
        return len(iterable.keys) > 1
    if isinstance(iterable, ast.Constant) and isinstance(iterable.value, (str, bytes)):
        return len(iterable.value) > 1
    return True


def _assigned_value(
    expression: ast.expr,
    state: dict[str, _TestValue | None],
    context: AnalysisContext,
    scope: ast.AST,
    loop: ast.For,
) -> _TestValue | None:
    if isinstance(expression, ast.Name):
        return state.get(expression.id)
    if isinstance(expression, ast.Call):
        if _qualified_before(context, expression.func, scope, loop.lineno) in _TESTS:
            return _TestValue(expression, False)
    if isinstance(expression, ast.Attribute) and expression.attr == "pvalue":
        base = expression.value
        if isinstance(base, ast.Name):
            value = state.get(base.id)
            if value is not None and not value.is_pvalue:
                return _TestValue(value.call, True)
        elif (
            isinstance(base, ast.Call)
            and _qualified_before(context, base.func, scope, loop.lineno) in _TESTS
        ):
            return _TestValue(base, True)
    return None


def _literal_threshold(expression: ast.expr) -> float | None:
    if not isinstance(expression, ast.Constant) or type(expression.value) not in (int, float):
        return None
    value = float(expression.value)
    return value if math.isfinite(value) and 0 <= value <= 1 else None


def _significance_compare(
    expression: ast.expr, state: dict[str, _TestValue | None]
) -> tuple[ast.Compare, _TestValue, float] | None:
    if not isinstance(expression, ast.Compare) or len(expression.ops) != 1:
        return None
    supported_ops = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)
    if len(expression.comparators) != 1 or not isinstance(expression.ops[0], supported_ops):
        return None
    left, right = expression.left, expression.comparators[0]
    if isinstance(expression.ops[0], (ast.Lt, ast.LtE)):
        value = state.get(left.id) if isinstance(left, ast.Name) else None
        if value is None and isinstance(left, ast.Attribute) and left.attr == "pvalue":
            base = left.value
            candidate = state.get(base.id) if isinstance(base, ast.Name) else None
            if candidate is not None and not candidate.is_pvalue:
                value = _TestValue(candidate.call, True)
        threshold = _literal_threshold(right)
        if value is None or not value.is_pvalue or threshold is None:
            return None
        return expression, value, threshold
    value = state.get(right.id) if isinstance(right, ast.Name) else None
    if value is None and isinstance(right, ast.Attribute) and right.attr == "pvalue":
        base = right.value
        candidate = state.get(base.id) if isinstance(base, ast.Name) else None
        if candidate is not None and not candidate.is_pvalue:
            value = _TestValue(candidate.call, True)
    threshold = _literal_threshold(left)
    if value is None or not value.is_pvalue or threshold is None:
        return None
    return expression, value, threshold


def _condition_comparisons(expression: ast.expr) -> tuple[ast.Compare, ...]:
    """Only follow direct comparisons and boolean combinations, not wrappers/lambdas."""
    if isinstance(expression, ast.Compare):
        return (expression,)
    if isinstance(expression, ast.BoolOp):
        return tuple(
            comparison
            for value in expression.values
            for comparison in _condition_comparisons(value)
        )
    return ()


def _loop_body_findings(
    context: AnalysisContext, scope: ast.AST, loop: ast.For
) -> dict[ast.Compare, tuple[ast.Call, float]]:
    comparisons: dict[ast.Compare, tuple[ast.Call, float]] = {}
    state: dict[str, _TestValue | None] = {}
    forbidden_writes = _written_names(loop)
    call_roots = {
        parts[0]
        for node in ast.walk(loop)
        if isinstance(node, ast.Call)
        if (parts := _root_and_attributes(node.func)) is not None
    }
    if forbidden_writes.intersection(call_roots):
        return comparisons

    def walk(statements: list[ast.stmt], values: dict[str, _TestValue | None]) -> None:
        for statement in statements:
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                targets = (
                    statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                )
                assigned = statement.value
                if assigned is None:
                    continue
                if len(targets) == 1 and isinstance(targets[0], (ast.Tuple, ast.List)):
                    target = targets[0]
                    p_call = (
                        assigned
                        if isinstance(assigned, ast.Call)
                        and _qualified_before(context, assigned.func, scope, loop.lineno) in _TESTS
                        else None
                    )
                    simple_tuple = all(isinstance(element, ast.Name) for element in target.elts)
                    for index, element in enumerate(target.elts):
                        if isinstance(element, ast.Name):
                            values[element.id] = (
                                _TestValue(p_call, True)
                                if (
                                    simple_tuple
                                    and p_call is not None
                                    and index == 1
                                    and len(target.elts) >= 2
                                )
                                else None
                            )
                    continue
                origin = _assigned_value(assigned, values, context, scope, loop)
                for target in targets:
                    if isinstance(target, ast.Name):
                        values[target.id] = origin
                    else:
                        values.clear()
                continue

            if isinstance(statement, ast.If):
                for node in _condition_comparisons(statement.test):
                    match = _significance_compare(node, values)
                    if match is not None:
                        comparison, origin, threshold = match
                        comparisons.setdefault(comparison, (origin.call, threshold))
                branch_writes = _written_names(statement.body) | _written_names(statement.orelse)
                branch_state = values.copy()
                for name in branch_writes:
                    values.pop(name, None)
                walk(statement.body, branch_state.copy())
                walk(statement.orelse, branch_state.copy())
                continue

            uncertain_statements = (
                ast.For,
                ast.AsyncFor,
                ast.While,
                ast.Try,
                ast.With,
                ast.AsyncWith,
            )
            if isinstance(statement, uncertain_statements):
                for name in _written_names(statement):
                    values.pop(name, None)

    walk(loop.body, state)
    return comparisons


class ST001(Rule[AnalysisContext]):
    rule_id = "ST001"
    name = "Potential Multiple Testing Without Correction"
    description = "A SciPy significance test and literal p-value threshold occur in a loop."
    default_severity = Severity.WARNING

    def check(self, context: AnalysisContext) -> tuple[Finding, ...]:
        findings: list[Finding] = []
        for scope, body in _scope_bodies(context):
            for statement in body:
                if not isinstance(statement, ast.For) or not _loop_may_repeat(statement.iter):
                    continue
                comparisons = _loop_body_findings(context, scope, statement)
                for comparison, (call, threshold) in comparisons.items():
                    test_path = _qualified_before(context, call.func, scope, statement.lineno)
                    if test_path is None:
                        continue
                    location = context.parsed.location_for(comparison)
                    threshold_text = repr(threshold)
                    findings.append(
                        Finding(
                            rule_id=self.rule_id,
                            file_path=context.path,
                            line=location.line,
                            column=location.column,
                            cell=context.cell,
                            cell_index=context.cell_index,
                            severity=Severity.WARNING,
                            confidence=Confidence.MEDIUM,
                            evidence=Evidence.POTENTIAL_STATISTICAL_RISK,
                            message=(
                                "Repeated significance tests may use unadjusted p-value thresholds."
                            ),
                            explanation=(
                                f"A resolved {test_path} call in a for loop produces a p-value "
                                f"that is compared directly with the literal threshold "
                                f"{threshold_text} inside the loop. This appears to use the "
                                "unadjusted p-value for that decision. Runtime loop cardinality "
                                "and adjustments outside this decision are unknown. Multiple "
                                "comparisons may increase the chance of false-positive findings; "
                                "this static pattern does not establish that the analysis is "
                                "incorrect."
                            ),
                            suggestion=(
                                "Consider whether family-wise error-rate or false-discovery-rate "
                                "control is appropriate for the hypothesis family and research "
                                "design."
                            ),
                        )
                    )
        return tuple(
            sorted(
                findings,
                key=lambda finding: (
                    finding.line,
                    finding.column,
                    finding.explanation,
                ),
            )
        )


__all__ = ["ST001"]

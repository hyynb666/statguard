"""ML005: a recognized estimator is only scored on its training split in scope."""

import ast
from dataclasses import dataclass, field

from statguard.context import AnalysisContext
from statguard.core import Confidence, Evidence, Finding, Rule, Severity
from statguard.provenance_sklearn import ESTIMATOR_PATHS, estimator_fit_inputs
from statguard.symbols import SymbolValue, ValueKind

_CROSS_VALIDATION_APIS = frozenset(
    {
        "sklearn.model_selection.cross_val_score",
        "sklearn.model_selection.cross_validate",
    }
)
_CONTROL_BARRIERS = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.TryStar,
    ast.With,
    ast.AsyncWith,
    ast.Match,
    ast.IfExp,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


@dataclass(slots=True)
class _FitEpisode:
    split_id: str
    fit: ast.Call
    fit_order: int
    scope: ast.AST
    train_scores: list[ast.Call] = field(default_factory=list)
    heldout_score: bool = False
    uncertain: bool = False


def _method(callee: SymbolValue, name: str) -> SymbolValue | None:
    value = callee.origin
    if value.kind is ValueKind.ATTRIBUTE and value.attribute == name and value.base is not None:
        return value
    return None


def _estimator_instance(method: SymbolValue) -> SymbolValue | None:
    if method.base is None:
        return None
    instance = method.base.origin
    while instance.kind is ValueKind.ATTRIBUTE and instance.base is not None:
        instance = instance.base.origin
    if instance.kind is ValueKind.CALL and instance.callee.qualified_name in ESTIMATOR_PATHS:
        return instance
    return None


def _score_inputs(call: ast.Call) -> tuple[ast.expr, ast.expr] | None:
    """Return explicit score X/y arguments for sklearn's estimator API only."""
    if len(call.args) > 3 or any(isinstance(arg, ast.Starred) for arg in call.args):
        return None
    names = [keyword.arg for keyword in call.keywords]
    if any(name not in {"X", "y", "sample_weight"} for name in names):
        return None
    if len(set(names)) != len(names):
        return None
    if any(name is None for name in names):
        return None
    if (call.args and "X" in names) or (len(call.args) > 1 and "y" in names):
        return None
    features = (
        call.args[0]
        if call.args
        else next((kw.value for kw in call.keywords if kw.arg == "X"), None)
    )
    labels = (
        call.args[1]
        if len(call.args) > 1
        else next((kw.value for kw in call.keywords if kw.arg == "y"), None)
    )
    if features is None or labels is None:
        return None
    return features, labels


def _role_split_pairs(
    context: AnalysisContext, expression: ast.expr, input_index: int
) -> set[tuple[str, str]]:
    return {
        (role.split_id, role.role)
        for role in context.provenance.resolve(expression).roles
        if role.input_index == input_index
    }


def _paired_role(
    context: AnalysisContext, features: ast.expr, labels: ast.expr
) -> set[tuple[str, str]]:
    return _role_split_pairs(context, features, 0) & _role_split_pairs(context, labels, 1)


def _split_before_fit(context: AnalysisContext, split_id: str, fit: ast.Call) -> bool:
    fit_site = context.symbols.evaluation_site(fit)
    if fit_site is None:
        return False
    return any(
        split.id == split_id
        and (site := context.symbols.evaluation_site(split.node)) is not None
        and site.scope is fit_site.scope
        and site.order < fit_site.order
        for split in context.provenance.splits
    )


def _cross_validation_call(context: AnalysisContext, call: ast.Call) -> bool:
    return context.symbols.resolve(call.func).qualified_name in _CROSS_VALIDATION_APIS


def _passes_instance(call: ast.Call, identity: ast.AST, context: AnalysisContext) -> bool:
    return any(
        context.symbols.resolve(argument).origin.node is identity
        for argument in (*call.args, *(keyword.value for keyword in call.keywords))
    )


def _split_location(context: AnalysisContext, split_id: str) -> str | None:
    for split in context.provenance.splits:
        if split.id == split_id:
            location = split.location
            return f"{location.path}:{location.line}:{location.column}"
    return None


def _scope_control_barriers(scope: ast.AST) -> tuple[ast.AST, ...]:
    """Find unsupported conditional/repeated expressions in only this scope."""
    body = (
        scope.body if isinstance(scope, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)) else ()
    )
    found: list[ast.AST] = []
    stack = list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(node, _CONTROL_BARRIERS):
            found.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return tuple(found)


def _barrier_follows(context: AnalysisContext, episode: _FitEpisode) -> bool:
    fit_end = (
        getattr(episode.fit, "end_lineno", episode.fit.lineno),
        getattr(episode.fit, "end_col_offset", episode.fit.col_offset),
    )
    for node in _scope_control_barriers(episode.scope):
        if (node.lineno, node.col_offset) > fit_end:
            return True
    return False


class ML005(Rule[AnalysisContext]):
    rule_id = "ML005"
    name = "Training-only Evaluation"
    description = (
        "A recognized estimator is scored on training data without a corresponding "
        "held-out score in the analyzed scope."
    )
    default_severity = Severity.WARNING

    def check(self, context: AnalysisContext) -> tuple[Finding, ...]:
        calls: list[tuple[int, ast.Call]] = []
        for call_info in context.calls:
            site = context.symbols.evaluation_site(call_info.node)
            if site is not None:
                calls.append((site.order, call_info.node))
        calls.sort(key=lambda item: item[0])

        active: dict[ast.AST, _FitEpisode] = {}
        episodes: dict[ast.AST, list[_FitEpisode]] = {}
        poisoned: set[ast.AST] = set()
        known_instances = {
            call
            for _, call in calls
            if context.symbols.resolve(call.func).qualified_name in ESTIMATOR_PATHS
        }

        for order, call in calls:
            resolved = context.symbols.resolve(call.func).origin
            method = resolved if resolved.kind is ValueKind.ATTRIBUTE else None
            instance = _estimator_instance(method) if method is not None else None

            if instance is not None:
                identity = instance.node
                direct_receiver = method.base is not None and method.base.origin.node is identity
                if method.attribute == "fit":
                    if not direct_receiver:
                        for episode in episodes.get(identity, ()):
                            episode.uncertain = True
                        poisoned.add(identity)
                        active.pop(identity, None)
                        continue
                    fit_site = context.symbols.evaluation_site(call)
                    construction_site = context.symbols.evaluation_site(instance.node)
                    inputs = estimator_fit_inputs(resolved, call)
                    training_splits: set[str] = set()
                    if inputs is not None:
                        values = dict(inputs)
                        label_expr = values.get("labels")
                        if label_expr is not None:
                            training_splits = {
                                split_id
                                for split_id, role in _paired_role(
                                    context, values["features"], label_expr
                                )
                                if role == "train"
                            }
                    valid_splits = {
                        split_id
                        for split_id in training_splits
                        if _split_before_fit(context, split_id, call)
                    }
                    if (
                        identity in poisoned
                        or len(valid_splits) != 1
                        or fit_site is None
                        or construction_site is None
                        or construction_site.scope is not fit_site.scope
                        or construction_site.order >= fit_site.order
                    ):
                        for episode in episodes.get(identity, ()):
                            episode.uncertain = True
                        active.pop(identity, None)
                        continue
                    split_id = next(iter(valid_splits))
                    episode = _FitEpisode(split_id, call, order, fit_site.scope)
                    active[identity] = episode
                    episodes.setdefault(identity, []).append(episode)
                    continue

                if method.attribute == "score":
                    current = active.get(identity)
                    if current is None or order <= current.fit_order:
                        continue
                    if not direct_receiver:
                        current.uncertain = True
                        poisoned.add(identity)
                        active.pop(identity, None)
                        continue
                    site = context.symbols.evaluation_site(call)
                    if site is None or site.scope is not current.scope:
                        current.uncertain = True
                        continue
                    values = _score_inputs(call)
                    if values is None:
                        current.uncertain = True
                        continue
                    roles = _paired_role(context, *values)
                    if not roles:
                        feature_roles = context.provenance.resolve(values[0]).roles
                        label_roles = context.provenance.resolve(values[1]).roles
                        if not feature_roles or not label_roles:
                            current.uncertain = True
                        continue
                    if (current.split_id, "train") in roles:
                        current.train_scores.append(call)
                    if (current.split_id, "test") in roles:
                        current.heldout_score = True
                    continue

                for episode in episodes.get(identity, ()):
                    episode.uncertain = True
                poisoned.add(identity)
                active.pop(identity, None)
                continue

            if _cross_validation_call(context, call):
                continue
            for identity in known_instances:
                if _passes_instance(call, identity, context):
                    if identity not in episodes:
                        poisoned.add(identity)
                        continue
                    poisoned.add(identity)
                    for episode in episodes[identity]:
                        episode.uncertain = True
                    active.pop(identity, None)

        findings: list[Finding] = []
        for model_episodes in episodes.values():
            for episode in model_episodes:
                if (
                    episode.uncertain
                    or episode.heldout_score
                    or not episode.train_scores
                    or _barrier_follows(context, episode)
                ):
                    continue
                score_call = episode.train_scores[0]
                location = _split_location(context, episode.split_id)
                call_info = next(item for item in context.calls if item.node is score_call)
                fit_location = context.parsed.location_for(episode.fit)
                fit_text = f"{fit_location.path}:{fit_location.line}:{fit_location.column}"
                split_text = location or "the corresponding train_test_split call"
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        file_path=context.path,
                        line=call_info.location.line,
                        column=call_info.location.column,
                        cell=context.cell,
                        cell_index=context.cell_index,
                        severity=self.default_severity,
                        confidence=Confidence.MEDIUM,
                        evidence=Evidence.POTENTIAL_STATISTICAL_RISK,
                        message="Potential training-only evaluation.",
                        explanation=(
                            "Within this supported analysis scope, a recognized sklearn model "
                            f"was fitted on training-role data at {fit_text} and scored on the "
                            "same training split, while no corresponding held-out score "
                            "was observed "
                            f"({split_text}). "
                            "Training scores can be useful for diagnostics, but alone may not "
                            "estimate performance on independent data; external evaluation or "
                            "dynamic behavior is outside this static scope."
                        ),
                        suggestion=(
                            "Consider evaluating the same fitted model on the corresponding "
                            "held-out data, or use a suitable validation/cross-validation "
                            "workflow. Training scores can remain useful for diagnostics."
                        ),
                    )
                )
        return tuple(
            sorted(findings, key=lambda item: (item.line, item.column or 0, item.explanation))
        )


__all__ = ["ML005"]

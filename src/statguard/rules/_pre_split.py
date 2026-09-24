"""Shared evidence traversal for fitted transforms used by later splits."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from statguard.context import AnalysisContext
from statguard.provenance import DataOrigin
from statguard.symbols import EvaluationSite, SymbolValue, ValueKind


@dataclass(frozen=True, slots=True)
class PreSplitTransform:
    """A proven transform edge that reaches a later split in the same scope."""

    transform: DataOrigin
    split: DataOrigin
    fit: DataOrigin | None = None
    fit_callee: SymbolValue | None = None


def _receiver_unmodified(
    context: AnalysisContext,
    callee: SymbolValue,
    fit_site: EvaluationSite,
) -> bool:
    receiver = callee.origin.base.origin
    creation = context.symbols.evaluation_site(receiver.node)
    if creation is None or creation.scope is not fit_site.scope:
        return False
    for call in context.calls:
        site = context.symbols.evaluation_site(call.node)
        if site is None or site.scope is not fit_site.scope:
            continue
        if not creation.order < site.order < fit_site.order:
            continue
        target = context.symbols.resolve(call.node.func).origin
        if target.kind is ValueKind.ATTRIBUTE and target.base.origin is receiver:
            if target.attribute not in {"fit", "transform", "fit_transform"}:
                return False
        arguments = [*call.node.args, *(kw.value for kw in call.node.keywords)]
        if any(context.symbols.resolve(arg).origin is receiver for arg in arguments):
            return False
    return True


def find_pre_split_transforms(
    context: AnalysisContext,
    accepts: Callable[[SymbolValue], bool],
) -> tuple[PreSplitTransform, ...]:
    """Find supported fitted-transform outputs entering a later split."""
    matches: dict[tuple[str, str], PreSplitTransform] = {}
    separated = {item.transform.id: item for item in context.provenance.fitted_transforms}
    for split in context.provenance.splits:
        split_site = context.symbols.evaluation_site(split.node)
        if split_site is None:
            continue
        pending = list(split.sources)
        visited: set[str] = set()
        while pending:
            value = pending.pop()
            if value.id in visited:
                continue
            visited.add(value.id)
            if value.roles:
                continue
            if value.kind in {"alias", "binding"}:
                pending.extend(value.sources)
                continue
            if value.kind != "transform":
                continue
            pending.extend(value.sources)
            method = value.callee.origin
            site = context.symbols.evaluation_site(value.node)
            if site is None or site.scope is not split_site.scope or site.order >= split_site.order:
                continue
            if method.attribute == "fit_transform":
                if not accepts(value.callee) or not _receiver_unmodified(
                    context, value.callee, site
                ):
                    continue
                matches[(value.id, split.id)] = PreSplitTransform(value, split)
                continue
            state = separated.get(value.id)
            if (
                method.attribute != "transform"
                or state is None
                or state.scope is not split_site.scope
                or state.fit_site.order >= state.transform_site.order
                or state.transform_site.order >= split_site.order
                or state.fit_callee is None
                or not accepts(state.fit_callee)
            ):
                continue
            matches[(state.fit.id, split.id)] = PreSplitTransform(
                value, split, fit=state.fit, fit_callee=state.fit_callee
            )
    return tuple(matches[key] for key in sorted(matches))

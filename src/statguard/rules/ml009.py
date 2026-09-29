"""ML009: fitted preprocessing output supplied to cross-validation."""

from __future__ import annotations

import ast

from statguard.context import AnalysisContext
from statguard.core import Confidence, Evidence, Finding, Rule, Severity
from statguard.provenance import DataOrigin, FittedTransform
from statguard.provenance_sklearn import (
    feature_selector_semantics,
    imputer_semantics,
    learns_scaling_parameters,
    transformed_input,
)
from statguard.rules._pre_split import _receiver_unmodified
from statguard.symbols import EvaluationSite, SymbolValue, ValueKind

CV_FUNCTIONS = frozenset(
    {
        "sklearn.model_selection.cross_val_score",
        "sklearn.model_selection.cross_validate",
    }
)


def _cv_x_argument(call: ast.Call) -> ast.expr | None:
    """Return an unambiguous X argument for a supported cross-validation call."""
    if any(isinstance(arg, ast.Starred) for arg in call.args):
        return None
    names = [keyword.arg for keyword in call.keywords]
    if any(name is None for name in names) or len(names) != len(set(names)):
        return None
    if not call.args and "estimator" not in names:
        return None
    if "estimator" in names and call.args:
        return None

    x_keywords = [keyword.value for keyword in call.keywords if keyword.arg == "X"]
    if len(x_keywords) > 1 or (len(call.args) >= 2 and x_keywords):
        return None
    if x_keywords:
        return x_keywords[0]
    return call.args[1] if len(call.args) >= 2 else None


def _transformations_in(origin: DataOrigin) -> tuple[DataOrigin, ...]:
    """Find proven transformer outputs through only known alias/source edges."""
    pending = [origin]
    visited: set[str] = set()
    matches: dict[str, DataOrigin] = {}
    while pending:
        current = pending.pop()
        if current.id in visited:
            continue
        visited.add(current.id)
        if not current.known:
            continue
        if current.kind == "transform":
            matches[current.id] = current
        pending.extend(current.sources)
    return tuple(matches[key] for key in sorted(matches))


def _semantics(
    context: AnalysisContext, callee: SymbolValue, fit_call: ast.Call
) -> tuple[str, str] | None:
    """Return a component category and its specific learned-data mechanism."""
    if learns_scaling_parameters(callee):
        constructor = callee.origin.base.origin.callee.qualified_name
        return "scaler", constructor.rsplit(".", 1)[-1]
    imputation = imputer_semantics(callee)
    if imputation is not None:
        return "imputer", imputation
    selection = feature_selector_semantics(callee, fit_call, context.symbols.resolve)
    if selection is not None:
        return "selector", selection
    return None


def _cv_location(context: AnalysisContext, call: ast.Call) -> str:
    location = context.parsed.location_for(call)
    result = f"{location.path}:{location.line}:{location.column}"
    if context.cell_index is not None:
        result += f" (Notebook cell_index={context.cell_index})"
    return result


def _transform_evidence(
    context: AnalysisContext,
    transform: DataOrigin,
    cv_site: EvaluationSite,
    separated: dict[str, FittedTransform],
) -> tuple[DataOrigin, tuple[str, str]] | None:
    """Resolve a transform's fit evidence and reject unsupported state/order."""
    transform_site = context.symbols.evaluation_site(transform.node)
    if transform_site is None or transform_site.scope is not cv_site.scope:
        return None
    if transform_site.order >= cv_site.order or transform.callee is None:
        return None

    state = separated.get(transform.id)
    if state is not None:
        fit_call = state.fit.node
        if not isinstance(fit_call, ast.Call):
            return None
        fit_site = state.fit_site
        callee = state.fit_callee
        if (
            state.scope is not cv_site.scope
            or state.transform_site.order != transform_site.order
            or fit_site.order >= transform_site.order
        ):
            return None
        semantics = _semantics(context, callee, fit_call)
        if semantics is None:
            return None
        return state.fit, semantics

    if not isinstance(transform.node, ast.Call):
        return None
    call = transform.node
    callee = context.symbols.resolve(call.func)
    if callee.origin.kind is not ValueKind.ATTRIBUTE or callee.origin.attribute != "fit_transform":
        return None
    if transformed_input(context.symbols.resolve(call)) is None:
        return None
    receiver = callee.origin.base
    if receiver is None:
        return None
    creation_site = context.symbols.evaluation_site(receiver.origin.node)
    if (
        creation_site is None
        or creation_site.scope is not cv_site.scope
        or creation_site.order >= transform_site.order
        or not _receiver_unmodified(context, callee, transform_site)
    ):
        return None
    semantics = _semantics(context, callee, call)
    if semantics is None:
        return None
    return transform, semantics


def _fits_and_calls(context: AnalysisContext):
    """Yield resolved preprocessing evidence and downstream CV calls."""
    separated = {item.transform.id: item for item in context.provenance.fitted_transforms}
    for call_info in context.calls:
        call = call_info.node
        callee = context.symbols.resolve(call.func)
        if callee.qualified_name not in CV_FUNCTIONS:
            continue
        x_argument = _cv_x_argument(call)
        cv_site = context.symbols.evaluation_site(call)
        if x_argument is None or cv_site is None:
            continue
        for transform in _transformations_in(context.provenance.resolve(x_argument)):
            evidence = _transform_evidence(context, transform, cv_site, separated)
            if evidence is not None:
                yield call, transform, callee.qualified_name, evidence


class ML009(Rule[AnalysisContext]):
    rule_id = "ML009"
    name = "Potential Preprocessing Leakage Before Cross-Validation"
    description = (
        "A fitted preprocessing output is supplied to a later sklearn cross-validation call."
    )
    default_severity = Severity.WARNING

    def check(self, context: AnalysisContext) -> tuple[Finding, ...]:
        findings: dict[tuple[str, ast.Call], Finding] = {}
        for cv_call, transform, cv_api, evidence in _fits_and_calls(context):
            fit, (kind, mechanism) = evidence
            fit_location = fit.location
            cv_location = _cv_location(context, cv_call)
            if context.cell_index is not None:
                fit_text = (
                    f"{fit_location.path}:{fit_location.line}:{fit_location.column} "
                    f"(Notebook cell_index={context.cell_index})"
                )
            else:
                fit_text = f"{fit_location.path}:{fit_location.line}:{fit_location.column}"

            if kind == "scaler":
                detail = (
                    f"The {mechanism} appears to have learned scaling parameters before "
                    "cross-validation; observations in validation folds may therefore have "
                    "influenced those parameters."
                )
            elif kind == "imputer":
                detail = (
                    f"The imputer appears to have learned {mechanism} before cross-validation; "
                    "validation-fold observations may therefore have influenced the fitted "
                    "imputation behavior."
                )
            else:
                detail = (
                    f"The selector appears to have fitted {mechanism} before cross-validation; "
                    "validation-fold observations may therefore have influenced the selected "
                    "features."
                )

            finding = Finding(
                rule_id=self.rule_id,
                file_path=context.path,
                line=fit_location.line,
                column=fit_location.column,
                cell=context.cell,
                cell_index=context.cell_index,
                severity=self.default_severity,
                confidence=Confidence.MEDIUM,
                evidence=Evidence.POTENTIAL_STATISTICAL_RISK,
                message="Potential preprocessing leakage before cross-validation.",
                explanation=(
                    f"A supported preprocessing operation at {fit_text} appears to produce "
                    f"data supplied as X to {cv_api} at {cv_location}. "
                    f"{detail} This static pattern does not establish that validation "
                    "information materially changed a model or its score."
                ),
                suggestion=(
                    "Consider placing preprocessing inside an appropriately configured sklearn "
                    "Pipeline so it is fitted separately within each training fold."
                ),
            )
            findings[(transform.id, cv_call)] = finding

        return tuple(
            sorted(
                findings.values(),
                key=lambda item: (item.line, item.column, item.explanation),
            )
        )


__all__ = ["ML009"]

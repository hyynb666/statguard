"""ML008: supported preprocessing fitted independently on split partitions."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from statguard.context import AnalysisContext
from statguard.core import Confidence, Evidence, Finding, Rule, Severity
from statguard.provenance import DataOrigin, SplitRole
from statguard.provenance_sklearn import (
    feature_selector_semantics,
    imputer_semantics,
    learns_scaling_parameters,
    transformer_fit_inputs,
    transformer_instance,
)
from statguard.symbols import EvaluationSite, Scope, SymbolValue, ValueKind


@dataclass(frozen=True, slots=True)
class _Application:
    """One proven fit-and-transform operation on a split partition."""

    split: DataOrigin
    input_index: int
    role: str
    transformer_path: str
    scope: Scope
    fit: DataOrigin
    fit_site: EvaluationSite
    transform: DataOrigin
    transform_site: EvaluationSite
    mechanism: str


def _semantics(
    context: AnalysisContext, callee: SymbolValue, call: ast.Call
) -> tuple[str, str] | None:
    """Reuse the established data-dependent semantics for ML001–ML003."""
    instance = transformer_instance(callee)
    if instance is None:
        return None
    path = instance.callee.qualified_name
    if path is None:
        return None
    if path.endswith(("StandardScaler", "MinMaxScaler", "RobustScaler")):
        if learns_scaling_parameters(callee):
            return path.rsplit(".", 1)[-1], "learned scaling parameters"
        return None
    imputation = imputer_semantics(callee)
    if imputation is not None:
        return path.rsplit(".", 1)[-1], imputation
    selection = feature_selector_semantics(callee, call, context.symbols.resolve)
    if selection is not None:
        return path.rsplit(".", 1)[-1], selection
    return None


def _split_evidence(
    context: AnalysisContext,
    expression: ast.expr,
    site: EvaluationSite,
    splits: dict[str, DataOrigin],
) -> tuple[DataOrigin, SplitRole] | None:
    """Resolve the X input's unique train/test role at this exact source use."""
    origin = context.provenance.resolve(expression)
    if not origin.known or len(origin.roles) != 1:
        return None
    role = origin.roles[0]
    if role.role not in {"train", "test"}:
        return None
    split = splits.get(role.split_id)
    split_site = context.symbols.evaluation_site(split.node) if split is not None else None
    if (
        split is None
        or split.kind != "split"
        or not split.known
        or split_site is None
        or split_site.scope is not site.scope
        or split_site.order >= site.order
        or role.input_index < 0
        or role.input_index >= len(split.sources)
    ):
        return None
    return split, role


def _receiver_unmodified(
    context: AnalysisContext,
    callee: SymbolValue,
    fit_site: EvaluationSite,
) -> bool:
    """Reject direct fit_transform evidence after an opaque receiver mutation."""
    instance = transformer_instance(callee)
    if instance is None:
        return False
    creation = context.symbols.evaluation_site(instance.node)
    if creation is None or creation.scope is not fit_site.scope or creation.order >= fit_site.order:
        return False

    for info in context.calls:
        site = context.symbols.evaluation_site(info.node)
        if (
            site is None
            or site.scope is not fit_site.scope
            or not creation.order < site.order < fit_site.order
        ):
            continue
        target = context.symbols.resolve(info.node.func).origin
        if (
            target.kind is ValueKind.ATTRIBUTE
            and target.base is not None
            and target.base.origin is instance
            and target.attribute not in {"fit", "transform", "fit_transform"}
        ):
            return False
        arguments = [*info.node.args, *(keyword.value for keyword in info.node.keywords)]
        if any(context.symbols.resolve(arg).origin is instance for arg in arguments):
            return False
    return True


def _application(
    context: AnalysisContext,
    *,
    callee: SymbolValue,
    fit_call: ast.Call,
    fit_origin: DataOrigin,
    transform_origin: DataOrigin,
    fit_site: EvaluationSite,
    transform_site: EvaluationSite,
    splits: dict[str, DataOrigin],
) -> _Application | None:
    instance = transformer_instance(callee)
    inputs = transformer_fit_inputs(callee, fit_call)
    semantics = _semantics(context, callee, fit_call)
    if (
        instance is None
        or inputs is None
        or semantics is None
        or fit_site.scope is not transform_site.scope
        or fit_site.order > transform_site.order
    ):
        return None
    split_role = _split_evidence(context, inputs[0], fit_site, splits)
    if split_role is None:
        return None
    split, role = split_role
    path = instance.callee.qualified_name
    if path is None:
        return None
    return _Application(
        split=split,
        input_index=role.input_index,
        role=role.role,
        transformer_path=path,
        scope=fit_site.scope,
        fit=fit_origin,
        fit_site=fit_site,
        transform=transform_origin,
        transform_site=transform_site,
        mechanism=semantics[1],
    )


def _applications(context: AnalysisContext) -> tuple[_Application, ...]:
    splits = {split.id: split for split in context.provenance.splits}
    results: dict[tuple[str, str, int, str], _Application] = {}

    # ProvenanceTracker owns the fit -> transform state and mutation poisoning.
    for fitted in context.provenance.fitted_transforms:
        call = fitted.fit.node
        if not isinstance(call, ast.Call):
            continue
        application = _application(
            context,
            callee=fitted.fit_callee,
            fit_call=call,
            fit_origin=fitted.fit,
            transform_origin=fitted.transform,
            fit_site=fitted.fit_site,
            transform_site=fitted.transform_site,
            splits=splits,
        )
        if application is not None:
            key = (
                application.fit.id,
                application.transform.id,
                application.input_index,
                application.role,
            )
            results[key] = application

    # fit_transform is a single call, so its result is direct transformation
    # evidence; exact class and receiver history are still required.
    for info in context.calls:
        call = info.node
        callee = context.symbols.resolve(call.func)
        method = callee.origin
        site = context.symbols.evaluation_site(call)
        if (
            method.kind is not ValueKind.ATTRIBUTE
            or method.attribute != "fit_transform"
            or site is None
            or not _receiver_unmodified(context, callee, site)
        ):
            continue
        inputs = transformer_fit_inputs(callee, call)
        if inputs is None:
            continue
        output = context.provenance.resolve(call)
        if not output.known or output.kind != "transform":
            continue
        application = _application(
            context,
            callee=callee,
            fit_call=call,
            fit_origin=output,
            transform_origin=output,
            fit_site=site,
            transform_site=site,
            splits=splits,
        )
        if application is not None:
            key = (output.id, output.id, application.input_index, application.role)
            results[key] = application

    return tuple(
        sorted(
            results.values(),
            key=lambda item: (
                item.split.location.line,
                item.split.location.column,
                item.fit.location.line,
                item.fit.location.column,
                item.transform.location.line,
                item.transform.location.column,
                item.transformer_path,
                item.role,
            ),
        )
    )


def _location(context: AnalysisContext, origin: DataOrigin) -> str:
    location = f"{origin.location.path}:{origin.location.line}:{origin.location.column}"
    if context.cell_index is not None:
        location += f" (Notebook cell_index={context.cell_index})"
    return location


class ML008(Rule[AnalysisContext]):
    rule_id = "ML008"
    name = "Preprocessing Fitted Separately on Train and Test Sets"
    description = (
        "A supported data-dependent preprocessor is separately fitted and applied to train "
        "and test partitions from the same split."
    )
    default_severity = Severity.WARNING

    def check(self, context: AnalysisContext) -> tuple[Finding, ...]:
        grouped: dict[tuple[str, int, str, Scope], list[_Application]] = {}
        for application in _applications(context):
            key = (
                application.split.id,
                application.input_index,
                application.transformer_path,
                application.scope,
            )
            grouped.setdefault(key, []).append(application)

        findings: dict[tuple[str, str], Finding] = {}
        for applications in grouped.values():
            training = sorted(
                (item for item in applications if item.role == "train"),
                key=lambda item: (
                    item.fit.location.line,
                    item.fit.location.column,
                    item.transform.location.line,
                    item.transform.location.column,
                ),
            )
            testing = sorted(
                (item for item in applications if item.role == "test"),
                key=lambda item: (
                    item.fit.location.line,
                    item.fit.location.column,
                    item.transform.location.line,
                    item.transform.location.column,
                ),
            )
            if not training or not testing:
                continue
            split = applications[0].split
            for test_application in testing:
                train_application = training[0]
                fit = test_application.fit
                split_location = _location(context, split)
                train_location = _location(context, train_application.fit)
                key = (fit.id, split.id)
                findings[key] = Finding(
                    rule_id=self.rule_id,
                    file_path=context.path,
                    line=fit.location.line,
                    column=fit.location.column,
                    cell=context.cell,
                    cell_index=context.cell_index,
                    severity=self.default_severity,
                    confidence=Confidence.MEDIUM,
                    evidence=Evidence.POTENTIAL_STATISTICAL_RISK,
                    message=("Potential separate preprocessing fits on train and test partitions."),
                    explanation=(
                        f"A supported {test_application.transformer_path.rsplit('.', 1)[-1]} "
                        f"appears to use {test_application.mechanism} and is fitted/applied "
                        f"separately to the train partition at {train_location} and the test "
                        f"partition here; both trace to input {test_application.input_index} "
                        f"of the same train_test_split at {split_location}. The test-side fit "
                        "learns preprocessing state from held-out data instead of reusing the "
                        "training-fitted state. This may expose test-distribution information "
                        "or place the partitions in separately estimated transformation spaces. "
                        "StatGuard does not establish downstream use or measured evaluation "
                        "impact."
                    ),
                    suggestion=(
                        "Fit the preprocessor on training data only and reuse that fitted instance "
                        "to transform held-out data. For model-selection workflows, consider an "
                        "appropriately configured Pipeline so fitting occurs within each training "
                        "fold."
                    ),
                )

        return tuple(
            sorted(
                findings.values(),
                key=lambda item: (item.line, item.column, item.explanation),
            )
        )


__all__ = ["ML008"]

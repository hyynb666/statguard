"""ML004: a known sklearn estimator is fitted with proven held-out data."""

import ast

from statguard.context import AnalysisContext
from statguard.core import Confidence, Evidence, Finding, Rule, Severity
from statguard.provenance_sklearn import ESTIMATOR_PATHS, estimator_fit_inputs
from statguard.symbols import SymbolValue, ValueKind


def _unmodified_receiver(
    context: AnalysisContext,
    receiver: SymbolValue,
    created_order: int,
    fit_call: ast.Call,
    scope: ast.AST,
) -> bool:
    """Reject calls that make estimator identity or state uncertain before fit."""
    for call_info in context.calls:
        call = call_info.node
        if call is fit_call:
            continue
        site = context.symbols.evaluation_site(call)
        if site is None or site.scope is not scope or not created_order < site.order:
            continue
        target = context.symbols.resolve(call.func).origin
        if target.kind is ValueKind.ATTRIBUTE and target.base is not None:
            if target.base.origin is receiver and target.attribute != "fit":
                return False
        if any(context.symbols.resolve(argument).origin is receiver for argument in call.args):
            return False
        if any(
            context.symbols.resolve(keyword.value).origin is receiver for keyword in call.keywords
        ):
            return False
    return True


def _split_description(context: AnalysisContext, split_id: str) -> str | None:
    for split in context.provenance.splits:
        if split.id == split_id:
            return f"{split.location.path}:{split.location.line}:{split.location.column}"
    return None


class ML004(Rule[AnalysisContext]):
    rule_id = "ML004"
    name = "Model Fitted on Test Data"
    description = "A known sklearn estimator fit receives a proven test split output."
    default_severity = Severity.WARNING

    def check(self, context: AnalysisContext) -> tuple[Finding, ...]:
        findings: list[Finding] = []
        for call_info in context.calls:
            call = call_info.node
            callee = context.symbols.resolve(call.func)
            inputs = estimator_fit_inputs(callee, call)
            if inputs is None:
                continue
            method = callee.origin
            receiver = method.base.origin
            if receiver.kind is not ValueKind.CALL:
                continue
            estimator_name = receiver.callee.qualified_name
            if estimator_name not in ESTIMATOR_PATHS:
                continue
            fit_site = context.symbols.evaluation_site(call)
            creation_site = context.symbols.evaluation_site(receiver.node)
            if (
                fit_site is None
                or creation_site is None
                or fit_site.scope is not creation_site.scope
                or fit_site.order <= creation_site.order
                or not _unmodified_receiver(
                    context, receiver, creation_site.order, call, fit_site.scope
                )
            ):
                continue

            evidence: dict[str, dict[str, str]] = {}
            for input_name, expression in inputs:
                origin = context.provenance.resolve(expression)
                for role in origin.roles:
                    if role.role != "test":
                        continue
                    split_site = next(
                        (
                            context.symbols.evaluation_site(split.node)
                            for split in context.provenance.splits
                            if split.id == role.split_id
                        ),
                        None,
                    )
                    if (
                        split_site is None
                        or split_site.scope is not fit_site.scope
                        or split_site.order >= fit_site.order
                    ):
                        continue
                    location = _split_description(context, role.split_id)
                    if location is not None:
                        evidence.setdefault(input_name, {})[role.split_id] = location

            if not evidence:
                continue
            used = []
            if "features" in evidence:
                used.append("test features")
            if "labels" in evidence:
                used.append("test labels")
            evidence_text = " and ".join(used)
            split_locations = sorted(
                {location for locations in evidence.values() for location in locations.values()}
            )
            split_text = ", ".join(split_locations)
            if context.cell_index is not None:
                split_text += f" (Notebook cell_index={context.cell_index})"
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
                    message="Potential test data leakage during model fitting.",
                    explanation=(
                        f"A recognized sklearn {estimator_name.rsplit('.', 1)[-1]} fit call "
                        f"receives {evidence_text} from train_test_split at {split_text}. "
                        "The source establishes that held-out data is an input to model fitting; "
                        "it does not establish actual overfitting, biased scores, or a measured "
                        "performance effect."
                    ),
                    suggestion=(
                        "Fit the model using training data only and reserve the test set for "
                        "final evaluation. For tuning, use validation within the training data "
                        "or appropriately configured cross-validation."
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


__all__ = ["ML004"]

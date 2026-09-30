"""ML007: a recognized search is fitted using a proven held-out split output."""

import ast

from statguard.context import AnalysisContext
from statguard.core import Confidence, Evidence, Finding, Rule, Severity
from statguard.provenance_sklearn import MODEL_SELECTION_SEARCH_PATHS, model_selection_fit_inputs
from statguard.symbols import SymbolValue, ValueKind


def _unmodified_receiver(
    context: AnalysisContext,
    receiver: SymbolValue,
    created_order: int,
    fit_call: ast.Call,
    scope: ast.AST,
) -> bool:
    """Abstain if the search object escaped or had another method invoked before fit."""
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


class ML007(Rule[AnalysisContext]):
    rule_id = "ML007"
    name = "Test Data Used for Model Selection"
    description = "A recognized sklearn search fit receives proven held-out split data."
    default_severity = Severity.WARNING

    def check(self, context: AnalysisContext) -> tuple[Finding, ...]:
        findings: list[Finding] = []
        splits = {split.id: split for split in context.provenance.splits}
        for call_info in context.calls:
            call = call_info.node
            callee = context.symbols.resolve(call.func)
            inputs = model_selection_fit_inputs(callee, call)
            if inputs is None:
                continue

            method = callee.origin
            receiver = method.base.origin
            search_path = receiver.callee.qualified_name
            if search_path not in MODEL_SELECTION_SEARCH_PATHS:
                continue
            fit_site = context.symbols.evaluation_site(call)
            creation_site = context.symbols.evaluation_site(receiver.node)
            if (
                fit_site is None
                or creation_site is None
                or fit_site.scope is not creation_site.scope
                or creation_site.order >= fit_site.order
                or not _unmodified_receiver(
                    context, receiver, creation_site.order, call, fit_site.scope
                )
            ):
                continue

            evidence: dict[str, set[str]] = {}
            for input_name, expression in inputs:
                origin = context.provenance.resolve(expression)
                if not origin.known:
                    continue
                for role in origin.roles:
                    if role.role != "test":
                        continue
                    split = splits.get(role.split_id)
                    split_site = (
                        context.symbols.evaluation_site(split.node) if split is not None else None
                    )
                    if (
                        split is None
                        or split_site is None
                        or split_site.scope is not fit_site.scope
                        or split_site.order >= fit_site.order
                    ):
                        continue
                    evidence.setdefault(input_name, set()).add(role.split_id)

            if not evidence:
                continue
            inputs_used = []
            if "features" in evidence:
                inputs_used.append("test features")
            if "labels" in evidence:
                inputs_used.append("test labels")
            split_locations = sorted(
                f"{split.location.path}:{split.location.line}:{split.location.column}"
                for split_id in {item for values in evidence.values() for item in values}
                if (split := splits.get(split_id)) is not None
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
                    message="Potential test data use for model selection.",
                    explanation=(
                        f"A recognized sklearn {search_path.rsplit('.', 1)[-1]} fit call "
                        f"receives {' and '.join(inputs_used)} from train_test_split at "
                        f"{split_text}. The held-out data therefore participates in the "
                        "search or candidate-selection procedure. If this same partition is "
                        "later treated as an independent final test set, its evaluation may "
                        "no longer be independent; this source does not establish that it is "
                        "reused or measure any performance bias."
                    ),
                    suggestion=(
                        "Use training data for model selection and retain a separate held-out "
                        "partition for final evaluation. If needed, use validation or "
                        "cross-validation within the training data."
                    ),
                )
            )

        return tuple(sorted(findings, key=lambda finding: (finding.line, finding.column)))


__all__ = ["ML007"]

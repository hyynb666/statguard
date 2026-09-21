"""ML001: supported fitted preprocessing output subsequently enters a split."""

from statguard.context import AnalysisContext
from statguard.core import Confidence, Evidence, Finding, Rule, Severity
from statguard.provenance_sklearn import learns_scaling_parameters
from statguard.symbols import ValueKind


def _receiver_unmodified(context: AnalysisContext, callee, fit_site) -> bool:
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
            if target.attribute not in {"transform", "fit_transform"}:
                return False
        # Passing the receiver to another call may mutate its configuration.
        arguments = [*call.node.args, *(kw.value for kw in call.node.keywords)]
        if any(context.symbols.resolve(arg).origin is receiver for arg in arguments):
            return False
    return True


class ML001(Rule[AnalysisContext]):
    rule_id = "ML001"
    name = "Potential Preprocessing Leakage"
    description = "Known scaler fit_transform output enters a subsequent train/test split."
    default_severity = Severity.WARNING

    def check(self, context: AnalysisContext) -> tuple[Finding, ...]:
        findings: dict[tuple[str, str], Finding] = {}
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
                # Never cross a previous train/test partition, an opaque call,
                # or unknown lineage. Generic call inputs are not data edges.
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
                if (
                    method.attribute != "fit_transform"
                    or not learns_scaling_parameters(value.callee)
                    or site is None
                    or site.scope is not split_site.scope
                    or site.order >= split_site.order
                    or not _receiver_unmodified(context, value.callee, site)
                ):
                    continue
                location = value.location
                split_location = (
                    f"{split.location.path}:{split.location.line}:{split.location.column}"
                )
                if context.cell_index is not None:
                    split_location += f" (Notebook cell_index={context.cell_index})"
                findings[(value.id, split.id)] = Finding(
                    rule_id=self.rule_id,
                    file_path=context.path,
                    line=location.line,
                    column=location.column,
                    cell=context.cell,
                    cell_index=context.cell_index,
                    severity=self.default_severity,
                    confidence=Confidence.MEDIUM,
                    evidence=Evidence.POTENTIAL_STATISTICAL_RISK,
                    message="Potential preprocessing leakage before train/test split.",
                    explanation=(
                        "A known sklearn scaler's fit_transform output flows into "
                        f"train_test_split at {split_location}, after fitting in the same scope. "
                        "Information from the eventual test subset may influence preprocessing "
                        "parameters. This static pattern does not establish actual leakage or "
                        "measured model performance."
                    ),
                    suggestion=(
                        "Split the data before fitting the transformer. Fit preprocessing on "
                        "the training subset and apply it to validation/test data, or use an "
                        "appropriately configured sklearn Pipeline in the training workflow."
                    ),
                )
        return tuple(sorted(findings.values(), key=lambda f: (f.line, f.column, f.explanation)))

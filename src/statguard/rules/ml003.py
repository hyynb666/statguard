"""ML003: fitted feature-selection output subsequently enters a split."""

from statguard.context import AnalysisContext
from statguard.core import Confidence, Evidence, Finding, Rule, Severity
from statguard.provenance_sklearn import feature_selector_semantics, is_feature_selector
from statguard.rules._pre_split import find_pre_split_transforms


class ML003(Rule[AnalysisContext]):
    rule_id = "ML003"
    name = "Potential Feature Selection Leakage"
    description = "Known feature-selector fit_transform output enters a later train/test split."
    default_severity = Severity.WARNING

    def check(self, context: AnalysisContext) -> tuple[Finding, ...]:
        findings: list[Finding] = []
        for match in find_pre_split_transforms(context, is_feature_selector):
            value, split = match.transform, match.split
            fit = match.fit or value
            callee = match.fit_callee or value.callee
            mechanism = feature_selector_semantics(callee, fit.node, context.symbols.resolve)
            if mechanism is None:
                continue
            split_location = f"{split.location.path}:{split.location.line}:{split.location.column}"
            transform_location = (
                f"{value.location.path}:{value.location.line}:{value.location.column}"
            )
            if context.cell_index is not None:
                split_location += f" (Notebook cell_index={context.cell_index})"
                transform_location += f" (Notebook cell_index={context.cell_index})"
            transform_evidence = (
                f" The fitted selector transformed the same input at {transform_location}."
                if match.fit is not None
                else ""
            )
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    file_path=context.path,
                    line=fit.location.line,
                    column=fit.location.column,
                    cell=context.cell,
                    cell_index=context.cell_index,
                    severity=self.default_severity,
                    confidence=Confidence.MEDIUM,
                    evidence=Evidence.POTENTIAL_STATISTICAL_RISK,
                    message="Potential feature selection leakage before train/test split.",
                    explanation=(
                        "A known sklearn feature selector's fitted transformation output flows "
                        f"into train_test_split at {split_location}, after fitting in the same "
                        f"scope.{transform_evidence} "
                        f"The selector uses {mechanism}; information from the eventual test "
                        "subset may therefore influence which features are retained. This "
                        "static pattern does not establish actual leakage or measured model "
                        "performance."
                    ),
                    suggestion=(
                        "Split the data before fitting the selector. Fit feature selection on "
                        "the training subset and apply it to validation/test data, or use an "
                        "appropriately configured sklearn Pipeline in the training workflow."
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


__all__ = ["ML003"]

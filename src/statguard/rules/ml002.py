"""ML002: data-dependent imputation output subsequently enters a split."""

from statguard.context import AnalysisContext
from statguard.core import Confidence, Evidence, Finding, Rule, Severity
from statguard.provenance_sklearn import imputer_semantics
from statguard.rules._pre_split import find_pre_split_transforms


class ML002(Rule[AnalysisContext]):
    rule_id = "ML002"
    name = "Potential Imputation Leakage"
    description = "Known data-dependent imputer output enters a later train/test split."
    default_severity = Severity.WARNING

    def check(self, context: AnalysisContext) -> tuple[Finding, ...]:
        findings: list[Finding] = []
        for match in find_pre_split_transforms(
            context, lambda callee: imputer_semantics(callee) is not None
        ):
            value, split = match.transform, match.split
            mechanism = imputer_semantics(value.callee)
            if mechanism is None:  # Kept explicit for type narrowing and safe abstention.
                continue
            split_location = f"{split.location.path}:{split.location.line}:{split.location.column}"
            if context.cell_index is not None:
                split_location += f" (Notebook cell_index={context.cell_index})"
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    file_path=context.path,
                    line=value.location.line,
                    column=value.location.column,
                    cell=context.cell,
                    cell_index=context.cell_index,
                    severity=self.default_severity,
                    confidence=Confidence.MEDIUM,
                    evidence=Evidence.POTENTIAL_STATISTICAL_RISK,
                    message="Potential imputation leakage before train/test split.",
                    explanation=(
                        "A known sklearn imputer's fit_transform output flows into "
                        f"train_test_split at {split_location}, after fitting in the same scope. "
                        f"The imputer learns from {mechanism}; information from the eventual "
                        "test subset may therefore influence the fitted imputation operation. "
                        "This static pattern does not establish actual leakage or measured "
                        "model performance."
                    ),
                    suggestion=(
                        "Split the data before fitting the imputer. Fit it on the training "
                        "subset and apply the fitted transformer to validation/test data, or "
                        "use an appropriately configured sklearn Pipeline in the training "
                        "workflow."
                    ),
                )
            )
        return tuple(sorted(findings, key=lambda f: (f.line, f.column, f.explanation)))

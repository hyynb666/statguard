"""ML001: supported fitted preprocessing output subsequently enters a split."""

from statguard.context import AnalysisContext
from statguard.core import Confidence, Evidence, Finding, Rule, Severity
from statguard.provenance_sklearn import learns_scaling_parameters
from statguard.rules._pre_split import find_pre_split_transforms


class ML001(Rule[AnalysisContext]):
    rule_id = "ML001"
    name = "Potential Preprocessing Leakage"
    description = "Known scaler fit_transform output enters a subsequent train/test split."
    default_severity = Severity.WARNING

    def check(self, context: AnalysisContext) -> tuple[Finding, ...]:
        findings: list[Finding] = []
        for match in find_pre_split_transforms(context, learns_scaling_parameters):
            value, split = match.transform, match.split
            location = value.location
            split_location = f"{split.location.path}:{split.location.line}:{split.location.column}"
            if context.cell_index is not None:
                split_location += f" (Notebook cell_index={context.cell_index})"
            findings.append(
                Finding(
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
            )
        return tuple(sorted(findings, key=lambda f: (f.line, f.column, f.explanation)))

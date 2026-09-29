"""ST002: explicitly discarded results from resolved SciPy statistical tests."""

import ast

from statguard.context import AnalysisContext
from statguard.core import Confidence, Evidence, Finding, Rule, Severity
from statguard.rules._scipy_tests import SUPPORTED_SCIPY_TESTS


def _discarded_test_calls(context: AnalysisContext) -> tuple[tuple[ast.Call, bool], ...]:
    """Return (call, assigned_to_underscore) pairs with exact local AST evidence."""
    discarded: list[tuple[ast.Call, bool]] = []
    for node in ast.walk(context.tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            discarded.append((call, False))
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "_"
            and isinstance(node.value, ast.Call)
        ):
            discarded.append((node.value, True))

    return tuple(
        (call, deliberate)
        for call, deliberate in discarded
        if context.symbols.resolve(call.func).qualified_name in SUPPORTED_SCIPY_TESTS
    )


class ST002(Rule[AnalysisContext]):
    rule_id = "ST002"
    name = "Discarded Statistical Test Result"
    description = "A resolved SciPy statistical test result is explicitly discarded."
    default_severity = Severity.INFO

    def check(self, context: AnalysisContext) -> tuple[Finding, ...]:
        findings: list[Finding] = []
        for call, deliberate in _discarded_test_calls(context):
            location = context.parsed.location_for(call)
            test_name = context.symbols.resolve(call.func).qualified_name
            if deliberate:
                explanation = (
                    f"A supported statistical test result from {test_name} is explicitly "
                    "assigned to `_`, indicating deliberate discard. This may be intentional; "
                    "the statistic, p-value, or other returned information may go uninspected."
                )
                suggestion = (
                    "If the test output is relevant to the inference, consider retaining or "
                    "recording it."
                )
            else:
                explanation = (
                    f"A supported statistical test ({test_name}) is called as a standalone "
                    "expression, so its returned result is not retained by this statement. "
                    "The statistic, p-value, or other returned information may go uninspected."
                )
                suggestion = (
                    "Consider retaining, inspecting, returning, or recording the test result "
                    "when it is relevant to the analysis."
                )
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    file_path=context.path,
                    line=location.line,
                    column=location.column,
                    cell=context.cell,
                    cell_index=context.cell_index,
                    severity=Severity.INFO,
                    confidence=Confidence.HIGH,
                    evidence=Evidence.CONFIRMED_CODE_PATTERN,
                    message="Discarded statistical test result.",
                    explanation=explanation,
                    suggestion=suggestion,
                )
            )
        return tuple(sorted(findings, key=lambda finding: (finding.line, finding.column or 0)))


__all__ = ["ST002"]

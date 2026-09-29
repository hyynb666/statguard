"""ML006: a randomized sklearn split has no statically fixed seed."""

import ast

from statguard.context import AnalysisContext
from statguard.core import Confidence, Evidence, Finding, Rule, Severity
from statguard.symbols import ValueKind

_TRAIN_TEST_SPLIT = "sklearn.model_selection.train_test_split"
_SUPPORTED_KEYWORDS = frozenset({"test_size", "train_size", "random_state", "shuffle", "stratify"})
_UNKNOWN = object()


def _literal_value(context: AnalysisContext, expression: ast.expr) -> object:
    """Return a literal at this exact use site, following only known bindings."""
    value = context.symbols.resolve(expression).origin
    if value.kind is ValueKind.LITERAL and isinstance(value.node, ast.Constant):
        return value.node.value
    return _UNKNOWN


def _keyword_values(call: ast.Call, name: str) -> list[ast.expr]:
    return [keyword.value for keyword in call.keywords if keyword.arg == name]


class ML006(Rule[AnalysisContext]):
    rule_id = "ML006"
    name = "Random Split Reproducibility"
    description = "A randomized sklearn train_test_split call has no fixed random_state."
    # A reproducibility suggestion is lower urgency than an observed leakage risk.
    default_severity = Severity.INFO

    def check(self, context: AnalysisContext) -> tuple[Finding, ...]:
        findings: list[Finding] = []
        for call_info in context.calls:
            call = call_info.node
            if context.symbols.resolve(call.func).qualified_name != _TRAIN_TEST_SPLIT:
                continue

            if any(keyword.arg not in _SUPPORTED_KEYWORDS for keyword in call.keywords):
                continue
            # **kwargs can override either setting; do not infer defaults then.
            if any(keyword.arg is None for keyword in call.keywords):
                continue

            shuffle_values = _keyword_values(call, "shuffle")
            if len(shuffle_values) > 1:
                continue
            shuffle = True if not shuffle_values else _literal_value(context, shuffle_values[0])
            if shuffle is False:
                continue
            if shuffle is not True:
                continue

            seed_values = _keyword_values(call, "random_state")
            if len(seed_values) > 1:
                continue
            seed = None if not seed_values else _literal_value(context, seed_values[0])
            if seed is _UNKNOWN:
                continue
            if seed is not None and type(seed) is not int:
                # Other known literals are not assumed to be valid seed values.
                continue
            if seed is not None:  # A statically known integer seed is fixed.
                continue

            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    file_path=context.path,
                    line=call_info.location.line,
                    column=call_info.location.column,
                    cell=context.cell,
                    cell_index=context.cell_index,
                    severity=self.default_severity,
                    confidence=Confidence.HIGH,
                    evidence=Evidence.CONFIRMED_CODE_PATTERN,
                    message="Randomized train/test split has no fixed random_state.",
                    explanation=(
                        "This resolved sklearn train_test_split call uses shuffle=True and "
                        "omits random_state or explicitly sets it to None. Repeated executions "
                        "may therefore produce different partitions. This is a potential "
                        "reproducibility risk, not evidence that the analysis is statistically "
                        "incorrect."
                    ),
                    suggestion=(
                        "Consider setting an explicit integer random_state when reproducible "
                        "data partitions are desired. Deliberately varying splits can be "
                        "appropriate for simulation or robustness analysis."
                    ),
                )
            )
        return tuple(
            sorted(findings, key=lambda finding: (finding.line, finding.column, finding.message))
        )


__all__ = ["ML006"]

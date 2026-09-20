"""Rule contract without an analysis context implementation or execution engine."""

from collections.abc import Iterable
from typing import Protocol, TypeVar

from statguard.core.findings import Finding, Severity

ContextT = TypeVar("ContextT", contravariant=True)


class Rule(Protocol[ContextT]):
    """Rules consume context and return findings without printing or executing source.

    Explicit subclasses inherit a name equal to rule_id, WARNING severity, and
    the legacy analyze alias. Implement check(context); context remains generic.
    Metadata must remain stable after registration. Structural implementations
    can also register without inheriting this protocol.
    """

    @property
    def rule_id(self) -> str:
        """Stable identifier used in findings and registration."""
        ...

    @property
    def name(self) -> str:
        """Human-readable rule name; override for a more descriptive name."""
        return self.rule_id

    @property
    def description(self) -> str:
        """Description of the rule's observed code pattern."""
        ...

    @property
    def default_severity(self) -> Severity | str:
        return Severity.WARNING

    def check(self, context: ContextT) -> Iterable[Finding]:
        """Return only findings supported by context; yield nothing when abstaining."""
        raise NotImplementedError("Rules must implement check(context)")

    def analyze(self, context: ContextT) -> Iterable[Finding]:
        """Compatibility spelling for callers of new Rule subclasses."""
        return self.check(context)

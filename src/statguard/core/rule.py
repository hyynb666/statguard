"""Rule contract without a parser, analysis context implementation, or engine."""

from collections.abc import Iterable
from typing import Protocol, TypeVar

from statguard.core.findings import Finding

ContextT = TypeVar("ContextT", contravariant=True)


class Rule(Protocol[ContextT]):
    """A rule consumes context and returns findings without printing or executing code.

    Metadata must remain stable after registration. The context type is deliberately
    generic until conservative analysis facts are implemented in a later milestone.
    """

    @property
    def rule_id(self) -> str:
        """Stable identifier used in findings and registration."""
        ...

    @property
    def description(self) -> str:
        """Short description of the rule's observed code pattern."""
        ...

    def analyze(self, context: ContextT) -> Iterable[Finding]:
        """Return only observations supported by the supplied context."""
        ...

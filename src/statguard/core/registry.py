"""Explicit rule registration without automatic imports or rule execution."""

from collections.abc import Iterator
from typing import Generic, TypeVar

from statguard.core.rule import Rule

ContextT = TypeVar("ContextT")


class RuleRegistry(Generic[ContextT]):
    """Store rules by unique ID and iterate in deterministic rule-ID order."""

    def __init__(self) -> None:
        self._rules: dict[str, Rule[ContextT]] = {}

    def register(self, rule: Rule[ContextT]) -> None:
        """Register a rule; reject empty or duplicate IDs instead of replacing rules."""
        if not rule.rule_id.strip():
            raise ValueError("rule_id must not be empty")
        if rule.rule_id in self._rules:
            raise ValueError(f"Duplicate rule ID: {rule.rule_id}")
        self._rules[rule.rule_id] = rule

    def get(self, rule_id: str) -> Rule[ContextT]:
        """Return a registered rule, or raise KeyError for an unknown ID."""
        return self._rules[rule_id]

    def __iter__(self) -> Iterator[Rule[ContextT]]:
        return (self._rules[rule_id] for rule_id in sorted(self._rules))

    def __len__(self) -> int:
        return len(self._rules)

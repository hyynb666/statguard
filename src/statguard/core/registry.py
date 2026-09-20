"""Explicit registration and selection; never imports or executes detection rules."""

import inspect
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar, cast

from statguard.core.findings import Finding, Severity
from statguard.core.rule import Rule

ContextT = TypeVar("ContextT")
LegacyContextT = TypeVar("LegacyContextT", contravariant=True)


class _LegacyRule(Protocol[LegacyContextT]):
    rule_id: str
    description: str

    def analyze(self, context: LegacyContextT) -> Iterable[Finding]: ...


@dataclass(frozen=True)
class _LegacyAdapter(Generic[ContextT]):
    """Expose check without mutating an existing analyze-only rule."""

    rule_id: str
    name: str
    description: str
    default_severity: Severity
    original: _LegacyRule[ContextT]

    def check(self, context: ContextT) -> Iterable[Finding]:
        return self.original.analyze(context)

    def analyze(self, context: ContextT) -> Iterable[Finding]:
        return self.check(context)


def _metadata(rule: object, field: str) -> str:
    value = getattr(rule, field, None)
    if not isinstance(value, str):
        raise TypeError(f"Rule {field} must be a string")
    if not value.strip():
        raise ValueError(f"Rule {field} must not be empty")
    return value


class RuleRegistry(Generic[ContextT]):
    """Register unique IDs; select enabled rules in deterministic ID order.

    get/iteration retain the original rule objects, including legacy rules.
    iter_enabled exposes a uniform check interface, adapting analyze-only rules.
    Disabling controls selection only, not direct calls to a rule object.
    """

    def __init__(self) -> None:
        self._rules: dict[str, Rule[ContextT] | _LegacyRule[ContextT]] = {}
        self._check_rules: dict[str, Rule[ContextT]] = {}
        self._enabled: set[str] = set()

    def register(
        self, rule: Rule[ContextT] | _LegacyRule[ContextT], *, enabled: bool = True
    ) -> None:
        """Validate metadata/entry point without calling it, then register atomically."""
        if isinstance(rule, type):
            raise TypeError("Register a rule instance, not a class")
        if type(enabled) is not bool:
            raise TypeError("enabled must be a bool")
        rule_id = _metadata(rule, "rule_id")
        if rule_id in self._rules:
            raise ValueError(f"Duplicate rule ID: {rule_id}")
        description = _metadata(rule, "description")
        check = getattr(rule, "check", None)
        inherited_check = getattr(type(rule), "check", None) is Rule.check
        legacy = not hasattr(rule, "check") or inherited_check
        if legacy:
            entry = getattr(rule, "analyze", None)
            if getattr(type(rule), "analyze", None) is Rule.analyze:
                entry = None  # Inherited aliases alone do not implement a rule.
        else:
            entry = check
        if (
            not callable(entry)
            or inspect.iscoroutinefunction(entry)
            or inspect.isasyncgenfunction(entry)
        ):
            raise TypeError(
                f"Rule {rule_id} must implement synchronous check(context) or analyze(context)"
            )
        try:
            inspect.signature(entry).bind(object())
        except (TypeError, ValueError) as error:
            raise TypeError(
                f"Rule {rule_id} entry point must accept one context argument"
            ) from error

        if legacy:
            name = _metadata(rule, "name") if hasattr(rule, "name") else rule_id
            default_severity = getattr(rule, "default_severity", Severity.WARNING)
        else:
            name = _metadata(rule, "name")
            default_severity = getattr(rule, "default_severity", None)
        if not isinstance(default_severity, str):
            raise TypeError(f"Rule {rule_id} default_severity must be a Severity or string")
        try:
            severity = Severity(default_severity)
        except ValueError as error:
            raise ValueError(
                f"Rule {rule_id} has invalid default_severity: {default_severity!r}"
            ) from error
        check_rule = (
            _LegacyAdapter(rule_id, name, description, severity, cast(_LegacyRule[ContextT], rule))
            if legacy
            else cast(Rule[ContextT], rule)
        )
        self._rules[rule_id] = rule
        self._check_rules[rule_id] = check_rule
        if enabled:
            self._enabled.add(rule_id)

    def get(self, rule_id: str) -> Rule[ContextT] | _LegacyRule[ContextT]:
        """Return the original rule, including disabled rules; unknown IDs raise KeyError."""
        return self._rules[rule_id]

    def enable(self, rule_id: str) -> None:
        self.get(rule_id)
        self._enabled.add(rule_id)

    def disable(self, rule_id: str) -> None:
        self.get(rule_id)
        self._enabled.discard(rule_id)

    def is_enabled(self, rule_id: str) -> bool:
        self.get(rule_id)
        return rule_id in self._enabled

    def iter_enabled(self) -> Iterator[Rule[ContextT]]:
        """Snapshot enabled rules by ID; callers may invoke their check method."""
        return iter(tuple(self._check_rules[rule_id] for rule_id in sorted(self._enabled)))

    def __iter__(self) -> Iterator[Rule[ContextT] | _LegacyRule[ContextT]]:
        """List all registered originals by ID, preserving existing iteration behavior."""
        return iter(tuple(self._rules[rule_id] for rule_id in sorted(self._rules)))

    def __len__(self) -> int:
        return len(self._rules)

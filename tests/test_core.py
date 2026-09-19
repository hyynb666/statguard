"""Foundational value and registry contracts; no statistical detection rules."""

from dataclasses import FrozenInstanceError, dataclass, replace

import pytest

from statguard.core import Evidence, Finding, Rule, RuleRegistry


@pytest.fixture
def finding() -> Finding:
    return Finding(
        rule_id="TEST001",
        path="example.py",
        line=2,
        column=1,
        message="Fixture observation.",
        risk="Fixture risk.",
        recommendation="Inspect the fixture.",
        evidence=Evidence.GENERAL_ANALYSIS_ADVICE,
    )


def test_finding_preserves_notebook_location_and_evidence(finding: Finding) -> None:
    notebook = replace(finding, path="example.ipynb", cell=3)
    assert (notebook.path, notebook.cell, notebook.line, notebook.column) == (
        "example.ipynb",
        3,
        2,
        1,
    )
    assert notebook.evidence.value == "general analysis advice"
    assert replace(finding, evidence=Evidence.UNDETERMINED).evidence is Evidence.UNDETERMINED
    assert len({finding, replace(finding)}) == 1
    with pytest.raises(FrozenInstanceError):
        finding.line = 5


@pytest.mark.parametrize("field", ["line", "column", "cell"])
@pytest.mark.parametrize("value", [0, -1])
def test_finding_rejects_invalid_coordinates(finding: Finding, field: str, value: int) -> None:
    with pytest.raises(ValueError, match="one-based"):
        replace(finding, **{field: value})


def test_finding_rejects_invalid_metadata(finding: Finding) -> None:
    with pytest.raises(ValueError, match="rule_id"):
        replace(finding, rule_id=" ")
    with pytest.raises(TypeError, match="Evidence"):
        replace(finding, evidence="confirmed violation")


@dataclass(frozen=True)
class FixtureRule:
    rule_id: str
    description: str = "Test-only rule; registration must not execute it."

    def analyze(self, context: None) -> list[Finding]:
        raise AssertionError("Registry must not execute rules")


def test_registry_lookup_order_and_duplicate_rejection() -> None:
    registry = RuleRegistry[None]()
    later: Rule[None] = FixtureRule("TEST002")
    earlier: Rule[None] = FixtureRule("TEST001")
    registry.register(later)
    registry.register(earlier)
    assert len(registry) == 2
    assert [rule.rule_id for rule in registry] == ["TEST001", "TEST002"]
    assert registry.get("TEST001") is earlier
    with pytest.raises(ValueError, match="Duplicate rule ID"):
        registry.register(FixtureRule("TEST001"))
    assert registry.get("TEST001") is earlier


def test_registry_starts_empty_and_rejects_unknown_or_empty_ids() -> None:
    registry = RuleRegistry[None]()
    assert len(registry) == 0
    assert list(registry) == []
    with pytest.raises(KeyError):
        registry.get("ML001")
    with pytest.raises(ValueError, match="rule_id"):
        registry.register(FixtureRule(""))

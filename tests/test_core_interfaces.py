"""Core contracts and compatibility; fixture rules perform no statistical analysis."""

import json
from collections.abc import Iterable
from dataclasses import FrozenInstanceError, asdict, replace
from types import SimpleNamespace

import pytest

from statguard.core import Confidence, Evidence, Finding, Rule, RuleRegistry, Severity
from statguard.parsers import NotebookParser, PythonSourceParser


def make_finding(**changes) -> Finding:
    fields = {
        "rule_id": "TEST001",
        "file_path": "example.py",
        "line": 2,
        "message": "Fixture observation.",
        "explanation": "Fixture risk.",
        "suggestion": "Inspect the fixture.",
    }
    return Finding(**(fields | changes))


def test_new_finding_defaults_and_legacy_properties():
    finding = make_finding()
    assert finding.severity is Severity.WARNING
    assert finding.confidence is Confidence.LOW
    assert finding.evidence is Evidence.UNDETERMINED
    assert finding.column is finding.cell is finding.cell_index is None
    assert finding.file_path == finding.path == "example.py"
    assert finding.explanation == finding.risk == "Fixture risk."
    assert finding.suggestion == finding.recommendation == "Inspect the fixture."


def test_legacy_positional_constructor_replace_and_equality():
    legacy = Finding(
        "TEST001",
        "example.py",
        2,
        None,
        "Fixture observation.",
        "Fixture risk.",
        "Inspect the fixture.",
        Evidence.UNDETERMINED,
    )
    assert legacy == make_finding()
    assert len({legacy, make_finding(), replace(legacy)}) == 1
    changed = replace(legacy, path="changed.py", risk="Changed risk.", severity="info")
    assert changed.file_path == "changed.py"
    assert changed.explanation == "Changed risk."
    assert changed.severity is Severity.INFO
    assert asdict(legacy)["path"] == "example.py"


@pytest.mark.parametrize(
    "old,new",
    [
        ("path", "file_path"),
        ("risk", "explanation"),
        ("recommendation", "suggestion"),
    ],
)
def test_aliases_accept_equal_values_and_reject_conflicts(old, new):
    original = make_finding()
    assert make_finding(**{old: getattr(original, new)}) == original
    with pytest.raises(ValueError, match="Conflicting"):
        make_finding(**{old: "different"})


@pytest.mark.parametrize("severity", list(Severity))
@pytest.mark.parametrize("confidence", list(Confidence))
def test_enum_and_string_inputs_normalize(severity, confidence):
    finding = make_finding(severity=severity.value, confidence=confidence.value)
    assert finding.severity is severity
    assert finding.confidence is confidence
    assert finding == make_finding(severity=severity, confidence=confidence)
    assert finding.evidence is Evidence.UNDETERMINED  # HIGH does not invent evidence.


@pytest.mark.parametrize(
    "field,bad",
    [
        ("severity", "fatal"),
        ("severity", "WARNING"),
        ("severity", ""),
        ("confidence", "certain"),
        ("confidence", "HIGH"),
        ("confidence", ""),
    ],
)
def test_invalid_enum_values(field, bad):
    with pytest.raises(ValueError, match=field):
        make_finding(**{field: bad})


@pytest.mark.parametrize("field", ["severity", "confidence"])
@pytest.mark.parametrize("bad", [None, 1, True])
def test_invalid_enum_types(field, bad):
    with pytest.raises(TypeError, match=field):
        make_finding(**{field: bad})


@pytest.mark.parametrize("field", ["line", "column", "cell", "cell_index"])
@pytest.mark.parametrize("bad", [True, 1.5, "1"])
def test_coordinate_types_are_not_coerced(field, bad):
    with pytest.raises(TypeError, match=field):
        make_finding(**{field: bad})


@pytest.mark.parametrize("bad", [0, -1])
def test_original_cell_index_must_be_positive(bad):
    with pytest.raises(ValueError, match="cell_index"):
        make_finding(cell_index=bad)


def test_required_line_and_consistent_cell_indexes():
    with pytest.raises(TypeError, match="line"):
        make_finding(line=None)
    with pytest.raises(ValueError, match="cell cannot exceed cell_index"):
        make_finding(cell=3, cell_index=2)


@pytest.mark.parametrize("field", ["rule_id", "file_path", "message", "explanation", "suggestion"])
def test_required_text_fields(field):
    with pytest.raises(ValueError, match="must not be empty"):
        make_finding(**{field: " "})
    with pytest.raises(TypeError, match="string"):
        make_finding(**{field: None})


@pytest.mark.parametrize("field", ["severity", "confidence", "cell_index", "path", "risk"])
def test_new_and_existing_stored_fields_are_immutable(field):
    with pytest.raises(FrozenInstanceError):
        setattr(make_finding(), field, None)


def test_python_and_notebook_location_mapping_keeps_parser_interfaces():
    source = "# 中文\n结果 = pkg.run()\n"
    unit = PythonSourceParser().parse_source(source, path="example.py")
    position = unit.calls[0].location
    ordinary = make_finding(file_path=position.path, line=position.line, column=position.column)
    assert (ordinary.line, ordinary.column, ordinary.cell_index, ordinary.cell) == (
        2,
        6,
        None,
        None,
    )
    doc = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"language_info": {"name": "python"}},
        "cells": [
            {"cell_type": "markdown", "metadata": {}, "source": "Intro"},
            {"cell_type": "code", "metadata": {}, "source": source},
        ],
    }
    cell = NotebookParser().parse_json(json.dumps(doc), path="example.ipynb").code_cells[0]
    location = cell.parsed.calls[0].location
    finding = make_finding(
        file_path=location.path,
        line=location.line,
        column=location.column,
        cell_index=cell.cell_index,
        cell=cell.code_cell_index,
    )
    assert (finding.file_path, finding.cell_index, finding.cell, finding.line, finding.column) == (
        "example.ipynb",
        2,
        1,
        2,
        6,
    )
    assert make_finding(cell_index=4).cell is None  # No invented code-cell index.
    assert make_finding(cell=2).cell_index is None  # Legacy callers remain supported.


class FixtureRule(Rule[str]):
    rule_id = "TEST001"
    name = "Fixture observation"
    description = "Emit a test-only finding for the requested fixture."
    default_severity = Severity.INFO

    def check(self, context: str) -> Iterable[Finding]:
        if context == "emit":
            yield make_finding(
                severity=self.default_severity,
                evidence=Evidence.GENERAL_ANALYSIS_ADVICE,
            )


def test_rule_metadata_check_and_legacy_call_alias(capsys):
    rule = FixtureRule()
    assert (rule.rule_id, rule.name, rule.description, rule.default_severity) == (
        "TEST001",
        "Fixture observation",
        "Emit a test-only finding for the requested fixture.",
        Severity.INFO,
    )
    results = list(rule.check("emit"))
    assert len(results) == 1 and isinstance(results[0], Finding)
    assert results[0].severity is Severity.INFO
    assert list(rule.analyze("emit")) == results
    assert list(rule.check("abstain")) == []
    assert capsys.readouterr() == ("", "")


def test_explicit_rule_subclass_metadata_defaults():
    class MinimalRule(Rule[None]):
        rule_id = "TEST002"
        description = "No observations."

        def check(self, context):
            return ()

    rule = MinimalRule()
    assert rule.name == "TEST002"
    assert rule.default_severity is Severity.WARNING
    registry = RuleRegistry[None]()
    registry.register(rule)
    assert next(registry.iter_enabled()) is rule


def test_registry_selection_identity_and_order_without_execution():
    def never_call(context):
        raise AssertionError("Registration/selection must not execute detection")

    registry = RuleRegistry[None]()
    rules = [
        SimpleNamespace(
            rule_id=key,
            name=key,
            description="Fixture",
            default_severity="warning",
            check=never_call,
        )
        for key in ("TEST003", "TEST001", "TEST002")
    ]
    for rule in rules:
        registry.register(rule)
    assert registry.get("TEST003") is rules[0]
    assert [r.rule_id for r in registry] == ["TEST001", "TEST002", "TEST003"]
    registry.disable("TEST002")
    registry.disable("TEST002")  # Idempotent, and other rules remain enabled.
    assert not registry.is_enabled("TEST002")
    assert registry.is_enabled("TEST001") and registry.is_enabled("TEST003")
    assert [r.rule_id for r in registry.iter_enabled()] == ["TEST001", "TEST003"]
    assert len(registry) == 3 and registry.get("TEST002") is rules[2]
    assert [r.rule_id for r in registry] == ["TEST001", "TEST002", "TEST003"]
    registry.enable("TEST002")
    registry.enable("TEST002")
    assert [r.rule_id for r in registry.iter_enabled()] == ["TEST001", "TEST002", "TEST003"]


def test_register_disabled_and_duplicate_failure_is_atomic():
    registry = RuleRegistry[str]()
    rule = FixtureRule()
    registry.register(rule, enabled=False)
    assert list(registry.iter_enabled()) == []
    with pytest.raises(ValueError, match="Duplicate rule ID: TEST001"):
        registry.register(FixtureRule())
    assert registry.get("TEST001") is rule and not registry.is_enabled("TEST001")
    registry.enable("TEST001")
    assert list(next(registry.iter_enabled()).check("emit")) == list(rule.check("emit"))


@pytest.mark.parametrize("method", ["get", "enable", "disable", "is_enabled"])
def test_unknown_rule_selection_fails_without_creating_entries(method):
    registry = RuleRegistry()
    with pytest.raises(KeyError, match="missing"):
        getattr(registry, method)("missing")
    assert len(registry) == 0 and list(registry.iter_enabled()) == []


@pytest.mark.parametrize(
    "fields,error,match",
    [
        ({"rule_id": None}, TypeError, "rule_id"),
        ({"rule_id": " "}, ValueError, "rule_id"),
        ({"description": None}, TypeError, "description"),
        ({"description": ""}, ValueError, "description"),
        ({"name": None}, TypeError, "name"),
        ({"name": ""}, ValueError, "name"),
        ({"default_severity": None}, TypeError, "default_severity"),
        ({"default_severity": "fatal"}, ValueError, "default_severity"),
        ({"check": None}, TypeError, "check"),
        ({"check": 1}, TypeError, "check"),
        ({"check": lambda: []}, TypeError, "context argument"),
        ({"check": lambda a, b: []}, TypeError, "context argument"),
    ],
)
def test_invalid_rule_registration_is_explicit_and_atomic(fields, error, match):
    values = dict(
        rule_id="TEST001",
        name="Fixture",
        description="Fixture rule",
        default_severity=Severity.WARNING,
        check=lambda context: [],
    )
    registry = RuleRegistry()
    with pytest.raises(error, match=match):
        registry.register(SimpleNamespace(**(values | fields)))
    assert len(registry) == 0 and list(registry.iter_enabled()) == []


def test_classes_incomplete_rules_and_async_entry_points_are_rejected():
    class Incomplete(Rule[None]):
        rule_id = "TEST003"
        description = "Missing check implementation"

    async def asynchronous(context):
        return []

    registry = RuleRegistry()
    for invalid in (
        FixtureRule,
        object(),
        Incomplete(),
        SimpleNamespace(
            rule_id="TEST004",
            description="Async is unsupported",
            analyze=asynchronous,
        ),
    ):
        with pytest.raises(TypeError):
            registry.register(invalid)
    with pytest.raises(TypeError, match="enabled"):
        registry.register(FixtureRule(), enabled="false")
    assert len(registry) == 0


@pytest.mark.parametrize("explicit_subclass", [False, True])
def test_legacy_analyze_rule_keeps_identity_and_gets_uniform_enabled_entry(explicit_subclass):
    base = Rule[str] if explicit_subclass else object

    class Legacy(base):
        rule_id = "OLD001"
        description = "Original analyze-only contract"

        def analyze(self, context):
            return [make_finding(rule_id=self.rule_id)] if context == "emit" else []

    original = Legacy()
    registry = RuleRegistry[str]()
    registry.register(original)
    assert registry.get("OLD001") is original and list(registry) == [original]
    compatible = next(registry.iter_enabled())
    assert compatible.name == "OLD001" and compatible.default_severity is Severity.WARNING
    assert list(compatible.check("emit")) == original.analyze("emit")
    assert list(compatible.analyze("emit")) == original.analyze("emit")
    assert list(compatible.check("abstain")) == []
    registry.disable("OLD001")
    assert list(registry.iter_enabled()) == []

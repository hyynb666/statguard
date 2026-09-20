"""Fixture-rule integration tests for analysis flow, errors, locations and safety."""

import ast
import json
from dataclasses import FrozenInstanceError, replace

import pytest

from statguard.analyzer import (
    AnalysisErrorCode,
    AnalysisErrorStage,
    AnalysisStatus,
    Analyzer,
)
from statguard.context import AnalysisContext
from statguard.core import Evidence, Finding, Rule, RuleRegistry
from statguard.parsers import NotebookIssueCode, NotebookParser, ParseErrorCode, PythonSourceParser


def notebook(cells):
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"language_info": {"name": "python"}},
        "cells": cells,
    }


def cell(source, kind="code", **extra):
    return {"cell_type": kind, "metadata": {}, "source": source, **extra}


def finding(context, rule_id="FIX001", *, line=1, column=1, message="Fixture call", evidence=None):
    return Finding(
        rule_id=rule_id,
        file_path=context.path,
        line=line,
        column=column,
        message=message,
        explanation="The test fixture observed syntax.",
        suggestion="Review the fixture.",
        evidence=evidence or Evidence.CONFIRMED_CODE_PATTERN,
    )


class CallRule(Rule[AnalysisContext]):
    rule_id = "FIX001"
    name = "Fixture call"
    description = "Report syntactic calls for analyzer tests."

    def __init__(self, seen=None):
        self.seen = seen if seen is not None else []

    def check(self, context):
        self.seen.append(context)
        for call in context.calls:
            yield finding(
                context,
                self.rule_id,
                line=call.location.line,
                column=call.location.column,
                message=f"Call {call.name}",
            )


def analyzer(*rules):
    registry = RuleRegistry[AnalysisContext]()
    for rule in rules:
        registry.register(rule)
    return Analyzer(registry)


def test_context_reuses_parser_unit_and_exposes_same_syntax_for_python_and_notebook():
    source = "import pkg as p\nx: int = p.run(3)\n"
    parsed = PythonSourceParser().parse_source(source, path="sample.py")
    context = AnalysisContext(parsed)
    assert context.parsed is parsed and context.tree is parsed.tree
    assert context.source == source and context.path == context.file_path == "sample.py"
    assert context.imports is parsed.imports and context.assignments is parsed.assignments
    assert context.calls is parsed.calls and context.functions is parsed.functions
    assert isinstance(context.tree, ast.Module)
    assert context.is_notebook is False and (context.cell_index, context.cell) == (None, None)
    doc = notebook([cell("intro", "markdown"), cell(source)])
    parsed_cell = NotebookParser().parse_json(json.dumps(doc)).code_cells[0]
    notebook_context = AnalysisContext(
        parsed_cell.parsed, parsed_cell.cell_index, parsed_cell.code_cell_index
    )
    assert notebook_context.tree is parsed_cell.parsed.tree
    assert notebook_context.source == source and notebook_context.is_notebook
    assert (notebook_context.cell_index, notebook_context.cell) == (2, 1)
    with pytest.raises(FrozenInstanceError):
        context.cell = 1


@pytest.mark.parametrize("original,ordinal", [(2, None), (None, 1), (0, 1), (1, 2)])
def test_context_rejects_incomplete_or_invalid_cell_identity(original, ordinal):
    parsed = PythonSourceParser().parse_source("x = 1")
    with pytest.raises(ValueError):
        AnalysisContext(parsed, original, ordinal)


def test_source_string_and_preparsed_unit_use_same_api_without_reparsing():
    rule = CallRule()
    analyzer_instance = analyzer(rule)
    result = analyzer_instance.analyze_source("# 中文\n结果 = pkg.run()\n", path="virtual.py")
    assert result.status is AnalysisStatus.COMPLETE
    assert result.analyzed_units == result.completed_units == 1
    assert [(f.path, f.line, f.column, f.cell_index) for f in result.findings] == [
        ("virtual.py", 2, 6, None)
    ]
    parsed = PythonSourceParser().parse_source("run()", path="preparsed.py")
    direct = analyzer_instance.analyze(parsed)
    assert direct.findings[0].path == "preparsed.py"
    assert rule.seen[-1].parsed is parsed and rule.seen[-1].tree is parsed.tree


def test_python_file_dispatch_and_source_is_never_executed(tmp_path):
    marker = tmp_path / "should_not_exist"
    source = f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
    path = tmp_path / "unsafe.py"
    path.write_text(source, encoding="utf-8")
    result = analyzer(CallRule()).analyze_file(path)
    assert result.status is AnalysisStatus.COMPLETE and result.errors == ()
    assert result.findings and all(f.path == str(path) for f in result.findings)
    assert not marker.exists()


def test_notebook_cell_locations_and_output_do_not_reach_rules():
    seen = []
    outputs = [{"output_type": "display_data", "data": {"text/html": "<script>bad()</script>"}}]
    doc = notebook(
        [
            cell("ignore()", "markdown"),
            cell(["# 中文\n", "结果 = alpha()\n"], outputs=outputs),
            cell("!never_run", "raw"),
            cell("\nbeta()", outputs=outputs),
        ]
    )
    result = analyzer(CallRule(seen)).analyze_notebook_json(json.dumps(doc), path="study.ipynb")
    assert result.status is AnalysisStatus.COMPLETE
    assert result.analyzed_units == result.completed_units == 2
    assert [(f.cell_index, f.cell, f.line, f.column) for f in result.findings] == [
        (2, 1, 2, 6),
        (4, 2, 2, 1),
    ]
    assert [(c.cell_index, c.cell) for c in seen] == [(2, 1), (4, 2)]
    assert all("bad()" not in c.source for c in seen)
    assert all(not hasattr(c, "outputs") for c in seen)
    assert "<script>" not in repr(result)
    assert result.notices[0].code is NotebookIssueCode.DOCUMENT_ORDER


def test_notebook_file_dispatch_never_executes_code_or_output(tmp_path):
    marker = tmp_path / "never_created"
    source = f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
    doc = notebook([cell(source, outputs=[{"text/plain": source}])])
    path = tmp_path / "unsafe.ipynb"
    path.write_text(json.dumps(doc), encoding="utf-8")
    result = analyzer(CallRule()).analyze_file(path)
    assert result.status is AnalysisStatus.COMPLETE and result.findings
    assert result.findings[0].cell_index == result.findings[0].cell == 1
    assert not marker.exists()


@pytest.mark.parametrize("source", ["", "# comment only\n"])
def test_empty_python_source_is_complete(source):
    rule = CallRule()
    result = analyzer(rule).analyze_source(source)
    assert result.status is AnalysisStatus.COMPLETE and result.findings == result.errors == ()
    assert result.analyzed_units == result.completed_units == 1
    assert rule.seen[0].source == source


@pytest.mark.parametrize(
    "cells,expected_units", [([], 0), ([cell("")], 1), ([cell("hi", "raw")], 0)]
)
def test_empty_notebook_and_empty_code_cell_are_complete(cells, expected_units):
    rule = CallRule()
    result = analyzer(rule).analyze_notebook_json(json.dumps(notebook(cells)))
    assert result.status is AnalysisStatus.COMPLETE and result.findings == result.errors == ()
    assert result.analyzed_units == result.completed_units == expected_units
    assert len(rule.seen) == expected_units


def test_rule_execution_follows_registry_order_and_disabled_rule_is_never_called():
    calls = []

    class RecordingRule(Rule[AnalysisContext]):
        name = "Recording fixture"
        description = "Only record the call order."

        def __init__(self, rule_id):
            self._rule_id = rule_id

        @property
        def rule_id(self):
            return self._rule_id

        def check(self, context):
            calls.append((self.rule_id, context.source))
            return ()

    registry = RuleRegistry[AnalysisContext]()
    for rule_id in ("Z", "A", "M"):
        registry.register(RecordingRule(rule_id))
    registry.disable("M")
    result = Analyzer(registry).analyze_source("x = 1")
    assert result.status is AnalysisStatus.COMPLETE and result.findings == ()
    assert calls == [("A", "x = 1"), ("Z", "x = 1")]


def test_no_enabled_rules_still_parse_and_report_failures():
    registry = RuleRegistry[AnalysisContext]()
    registry.register(CallRule(), enabled=False)
    instance = Analyzer(registry)
    assert instance.analyze_source("good()").status is AnalysisStatus.COMPLETE
    broken = instance.analyze_source("x = )")
    assert broken.status is AnalysisStatus.FAILED and broken.findings == ()
    assert broken.errors[0].code is ParseErrorCode.SYNTAX_ERROR


def test_findings_are_sorted_and_deduplicated_by_all_fields():
    class ManyRule(Rule[AnalysisContext]):
        rule_id = "FIX002"
        description = "Emit reordered fixture diagnostics."

        def check(self, context):
            first = finding(context, self.rule_id, line=1, column=1, message="same")
            return [
                finding(context, self.rule_id, line=2, column=1),
                replace(first, evidence=Evidence.POTENTIAL_STATISTICAL_RISK),
                first,
                replace(first, column=2),
                first,
            ]

    registry = RuleRegistry[AnalysisContext]()
    registry.register(ManyRule())
    registry.register(CallRule())
    first = Analyzer(registry).analyze_source("run()\nx = 1", path="sample.py")
    second = Analyzer(registry).analyze_source("run()\nx = 1", path="sample.py")
    assert first.findings == second.findings and len(first.findings) == 5
    assert [(f.line, f.column, f.rule_id) for f in first.findings] == [
        (1, 1, "FIX001"),
        (1, 1, "FIX002"),
        (1, 1, "FIX002"),
        (1, 2, "FIX002"),
        (2, 1, "FIX002"),
    ]
    assert first.findings[1].evidence is not first.findings[2].evidence


def test_duplicate_text_in_distinct_notebook_cells_is_not_merged():
    result = analyzer(CallRule()).analyze_notebook_json(
        json.dumps(notebook([cell("run()"), cell("run()")])), path="same.ipynb"
    )
    assert len(result.findings) == 2
    assert [(f.cell_index, f.cell) for f in result.findings] == [(1, 1), (2, 2)]


def test_python_syntax_failure_is_not_a_clean_empty_scan():
    result = analyzer(CallRule()).analyze_source("x = )")
    assert result.status is AnalysisStatus.FAILED and not result.is_complete
    assert result.findings == () and result.errors[0].stage is AnalysisErrorStage.PARSE
    assert result.errors[0].code is ParseErrorCode.SYNTAX_ERROR


def test_python_file_syntax_error_keeps_parser_path_and_position(tmp_path):
    path = tmp_path / "broken.py"
    path.write_text("first()\nx = )", encoding="utf-8")
    result = analyzer(CallRule()).analyze_file(path)
    assert result.status is AnalysisStatus.FAILED and result.findings == ()
    error = result.errors[0]
    assert (error.stage, error.code, error.path, error.line) == (
        AnalysisErrorStage.PARSE,
        ParseErrorCode.SYNTAX_ERROR,
        str(path),
        2,
    )


def test_notebook_json_failure_and_unsupported_language_are_explicit():
    instance = analyzer(CallRule())
    malformed = instance.analyze_notebook_json("{", path="bad.ipynb")
    assert malformed.status is AnalysisStatus.FAILED
    assert malformed.errors[0].code is NotebookIssueCode.INVALID_JSON
    unsupported = notebook([cell("x = 1")])
    unsupported["metadata"]["language_info"]["name"] = "R"
    result = instance.analyze_notebook_json(json.dumps(unsupported), path="r.ipynb")
    assert result.status is AnalysisStatus.FAILED and result.findings == ()
    assert result.errors[0].code is NotebookIssueCode.UNSUPPORTED_LANGUAGE


def test_notebook_one_cell_failure_retains_other_findings_and_partial_status():
    doc = notebook([cell("first()"), cell("!shell command"), cell("last()")])
    result = analyzer(CallRule()).analyze_notebook_json(json.dumps(doc), path="partial.ipynb")
    assert result.status is AnalysisStatus.PARTIAL and not result.is_complete
    assert result.analyzed_units == result.completed_units == 2
    assert [(f.cell_index, f.cell) for f in result.findings] == [(1, 1), (3, 3)]
    assert len(result.errors) == 1
    assert result.errors[0].stage is AnalysisErrorStage.PARSE
    assert result.errors[0].code is NotebookIssueCode.UNSUPPORTED_SYNTAX
    assert (result.errors[0].cell_index, result.errors[0].cell) == (2, 2)


def test_no_enabled_rule_does_not_hide_unsupported_notebook_cell():
    result = Analyzer(RuleRegistry[AnalysisContext]()).analyze_notebook_json(
        json.dumps(notebook([cell("!shell command"), cell("valid()")]))
    )
    assert result.status is AnalysisStatus.PARTIAL and result.findings == ()
    assert result.errors[0].code is NotebookIssueCode.UNSUPPORTED_SYNTAX
    assert (result.analyzed_units, result.completed_units) == (1, 1)


def test_notebook_python_grammar_error_keeps_other_cell_result():
    result = analyzer(CallRule()).analyze_notebook_json(
        json.dumps(notebook([cell("okay()"), cell("x = )")])), path="partial.ipynb"
    )
    assert result.status is AnalysisStatus.PARTIAL
    assert result.findings[0].message == "Call okay"
    assert result.errors[0].code is ParseErrorCode.SYNTAX_ERROR
    assert (result.errors[0].cell_index, result.errors[0].cell) == (2, 2)


@pytest.mark.parametrize(
    "name,code",
    [
        ("missing.py", ParseErrorCode.READ_ERROR),
        ("missing.ipynb", ParseErrorCode.READ_ERROR),
        ("unsupported.txt", ParseErrorCode.UNSUPPORTED_FILE),
    ],
)
def test_invalid_file_paths_and_unsupported_types(tmp_path, name, code):
    result = analyzer(CallRule()).analyze_file(tmp_path / name)
    assert result.status is AnalysisStatus.FAILED and result.findings == ()
    assert result.errors[0].stage is AnalysisErrorStage.PARSE
    assert result.errors[0].code is code


def test_rule_exception_is_reported_and_other_rules_still_contribute():
    class ExplodingRule(Rule[AnalysisContext]):
        rule_id = "FAIL"
        description = "Raise instead of returning findings."

        def check(self, context):
            raise RuntimeError("fixture failure")

    result = analyzer(ExplodingRule(), CallRule()).analyze_source("good()", path="good.py")
    assert result.status is AnalysisStatus.FAILED and len(result.findings) == 1
    assert result.errors[0].stage is AnalysisErrorStage.RULE
    assert result.errors[0].code is AnalysisErrorCode.RULE_EXECUTION
    assert result.errors[0].rule_id == "FAIL" and "fixture failure" in result.errors[0].message


def test_rule_iterator_creation_failure_is_recorded():
    class BrokenIterable:
        def __iter__(self):
            raise RuntimeError("iterator initialization failed")

    class BrokenRule(Rule[AnalysisContext]):
        rule_id = "BROKEN"
        description = "Return a broken iterable."

        def check(self, context):
            return BrokenIterable()

    result = analyzer(BrokenRule(), CallRule()).analyze_source("run()")
    assert result.status is AnalysisStatus.FAILED
    assert len(result.findings) == 1  # Another rule still completes.
    assert result.errors[0].code is AnalysisErrorCode.RULE_EXECUTION
    assert "iterator initialization failed" in result.errors[0].message


def test_invalid_item_discards_prior_output_from_that_rule():
    class InvalidLater(Rule[AnalysisContext]):
        rule_id = "INVALID"
        description = "Yield one valid Finding then an invalid item."

        def check(self, context):
            yield finding(context, self.rule_id)
            yield object()

    result = analyzer(InvalidLater(), CallRule()).analyze_source("run()")
    assert result.status is AnalysisStatus.FAILED
    assert [item.rule_id for item in result.findings] == ["FIX001"]
    assert result.errors[0].code is AnalysisErrorCode.INVALID_RULE_RESULT


def test_failing_generator_discards_its_partial_findings_but_preserves_other_cells():
    class LaterFailure(Rule[AnalysisContext]):
        rule_id = "FAIL"
        description = "Fail while yielding findings for one cell."

        def check(self, context):
            yield finding(context, self.rule_id)
            if "fail" in context.source:
                raise RuntimeError("later failure")

    result = analyzer(LaterFailure()).analyze_notebook_json(
        json.dumps(notebook([cell("okay()"), cell("fail()")]))
    )
    assert result.status is AnalysisStatus.PARTIAL
    assert len(result.findings) == 1 and result.findings[0].cell_index == 1
    assert result.errors[0].stage is AnalysisErrorStage.RULE
    assert (result.errors[0].cell_index, result.errors[0].cell) == (2, 2)


@pytest.mark.parametrize("returned", [None, [42], "", {}, ["not a Finding"]])
def test_invalid_rule_result_does_not_look_like_a_clean_scan(returned):
    class BadRule(Rule[AnalysisContext]):
        rule_id = "BAD"
        description = "Return invalid fixture data."

        def check(self, context):
            return returned

    result = analyzer(BadRule()).analyze_source("x = 1")
    assert result.status is AnalysisStatus.FAILED and result.findings == ()
    assert result.errors[0].stage is AnalysisErrorStage.RULE
    assert result.errors[0].code is AnalysisErrorCode.INVALID_RULE_RESULT


@pytest.mark.parametrize("wrong", ["rule_id", "path", "cell", "original_cell"])
def test_rule_finding_with_wrong_identity_is_rejected(wrong):
    class WrongRule(Rule[AnalysisContext]):
        rule_id = "FIX001"
        description = "Return one mislocated fixture observation."

        def check(self, context):
            item = finding(context)
            if wrong == "rule_id":
                return [replace(item, rule_id="OTHER")]
            if wrong == "path":
                return [replace(item, path="other.ipynb")]
            if wrong == "cell":
                return [replace(item, cell=2)]
            return [replace(item, cell_index=2)]

    result = analyzer(WrongRule()).analyze_notebook_json(json.dumps(notebook([cell("run()")])))
    assert result.status is AnalysisStatus.FAILED and result.findings == ()
    assert result.errors[0].code is AnalysisErrorCode.INVALID_RULE_RESULT


def test_python_finding_with_cell_identity_is_rejected():
    class WrongRule(Rule[AnalysisContext]):
        rule_id = "FIX001"
        description = "Use a Notebook location in a Python file."

        def check(self, context):
            return [replace(finding(context), cell=1)]

    result = analyzer(WrongRule()).analyze_source("run()")
    assert result.status is AnalysisStatus.FAILED
    assert result.errors[0].code is AnalysisErrorCode.INVALID_RULE_RESULT


def test_legacy_rule_adapter_runs_through_analyzer_and_respects_enablement():
    class Legacy:
        rule_id = "OLD001"
        description = "Old analyze-only fixture."

        def analyze(self, context):
            return [finding(context, self.rule_id)]

    registry = RuleRegistry[AnalysisContext]()
    registry.register(Legacy())
    instance = Analyzer(registry)
    assert len(instance.analyze_source("x = 1").findings) == 1
    registry.disable("OLD001")
    assert instance.analyze_source("x = 1").findings == ()


def test_bad_preparsed_argument_raises_api_error():
    with pytest.raises(TypeError, match="ParsedSource or ParsedNotebook"):
        analyzer().analyze(None)

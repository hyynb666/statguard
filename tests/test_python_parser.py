"""Python parsing contracts, uncertain syntax, source positions, and safety."""

import ast
import codecs
import sys
from pathlib import Path

import pytest

from statguard.parsers import ParseErrorCode, PythonSourceParser, SourceParseError


@pytest.fixture
def parser() -> PythonSourceParser:
    return PythonSourceParser()


def test_imports_and_aliases_are_syntax_not_resolved_calls(parser: PythonSourceParser) -> None:
    unit = parser.parse_source(
        "import os, package.submodule as mod\n"
        "from package.tools import run as execute, helper\n"
        "from . import sibling\n"
        "from ..tools import *\n"
        "execute(data)\n"
    )
    assert [(a.name, a.asname) for a in unit.imports[0].node.names] == [
        ("os", None),
        ("package.submodule", "mod"),
    ]
    imported = unit.imports[1].node
    assert isinstance(imported, ast.ImportFrom)
    assert (imported.module, imported.level) == ("package.tools", 0)
    assert [(a.name, a.asname) for a in imported.names] == [("run", "execute"), ("helper", None)]
    assert (unit.imports[2].node.module, unit.imports[2].node.level) == (None, 1)
    assert (unit.imports[3].node.module, unit.imports[3].node.level) == ("tools", 2)
    assert unit.imports[3].node.names[0].name == "*"
    assert unit.calls[0].name == "execute"  # No import resolution in a parser.
    assert unit.location_for(imported.names[0]).column == 27


def test_assignments_preserve_targets_annotations_and_unknown_values(parser: PythonSourceParser):
    unit = parser.parse_source(
        "x = y = make_value()\na, *rest = values\nobj.attr = data[0]\n"
        "count: int = 3\nmissing: list[str]\n"
    )
    first = unit.assignments[0].node
    assert isinstance(first, ast.Assign)
    assert [target.id for target in first.targets] == ["x", "y"]
    assert isinstance(first.value, ast.Call)
    assert unit.calls[0].node is first.value
    assert isinstance(unit.assignments[1].node.targets[0], ast.Tuple)
    assert isinstance(unit.assignments[1].node.targets[0].elts[1], ast.Starred)
    assert isinstance(unit.assignments[2].node.targets[0], ast.Attribute)
    assert isinstance(unit.assignments[2].node.value, ast.Subscript)
    annotated = unit.assignments[3].node
    assert isinstance(annotated, ast.AnnAssign)
    assert (annotated.target.id, annotated.annotation.id, annotated.value.value) == (
        "count",
        "int",
        3,
    )
    assert unit.assignments[4].node.value is None
    assert isinstance(unit.assignments[4].node.annotation, ast.Subscript)


def test_dotted_calls_and_dynamic_chains(parser: PythonSourceParser) -> None:
    unit = parser.parse_source(
        "f(x)\nobj.method(x)\nsklearn.model_selection.train_test_split(X)\n"
        "factory().fit(X).predict(Y)\nhandlers[key](x)\ngetattr(obj, method)(x)\n"
    )
    assert [c.name for c in unit.calls] == [
        "f",
        "obj.method",
        "sklearn.model_selection.train_test_split",
        None,
        None,
        "factory",
        None,
        None,
        "getattr",
    ]
    dynamic = unit.calls[3]
    assert dynamic.is_unknown
    assert isinstance(dynamic.node.func, ast.Attribute)
    assert dynamic.node.func.attr == "predict"
    assert isinstance(dynamic.node.func.value, ast.Call)
    assert not unit.calls[2].is_unknown


def test_multiline_arguments_and_keyword_locations(parser: PythonSourceParser) -> None:
    source = "result = package.run(\n    data, *extras,\n    seed=choose(),\n    **options,\n)\n"
    unit = parser.parse_source(source, path="analysis.py")
    call, nested = unit.calls
    assert call.name == "package.run"
    assert isinstance(call.args[0], ast.Name)
    assert isinstance(call.args[1], ast.Starred)
    assert [k.arg for k in call.keywords] == ["seed", None]
    assert call.keywords[0].value is nested.node
    assert nested.name == "choose"
    assert (call.location.path, call.location.line, call.location.column) == ("analysis.py", 1, 10)
    assert (call.location.end_line, call.location.end_column) == (5, 2)
    assert (
        unit.location_for(call.keywords[0]).line,
        unit.location_for(call.keywords[0]).column,
    ) == (3, 5)
    assert ast.get_source_segment(unit.source, call.node).endswith("**options,\n)")


def test_functions_and_lexical_definition_ancestry(parser: PythonSourceParser) -> None:
    unit = parser.parse_source(
        "top()\n"
        "@decorate()\n"
        "def outer(x: int = default(), *, flag=True) -> str:\n"
        "    import local_module as local\n"
        "    y: int = compute(x)\n"
        "    def inner():\n"
        "        return local.run(y)\n"
        "    return inner()\n"
        "class Worker:\n"
        "    async def work(self):\n"
        "        await task()\n"
    )
    assert [f.node.name for f in unit.functions] == ["outer", "inner", "work"]
    outer = unit.functions[0].node
    assert outer.args.args[0].annotation.id == "int"
    assert outer.args.kwonlyargs[0].arg == "flag"
    assert outer.returns.id == "str"
    assert isinstance(unit.functions[2].node, ast.AsyncFunctionDef)
    calls = {call.name: call for call in unit.calls}
    assert calls["top"].enclosing_definitions == ()
    assert [d.name for d in calls["compute"].enclosing_definitions] == ["outer"]
    assert [d.name for d in calls["local.run"].enclosing_definitions] == ["outer", "inner"]
    assert [d.name for d in calls["task"].enclosing_definitions] == ["Worker", "work"]
    assert unit.imports[0].enclosing_definitions == (outer,)
    assert unit.assignments[0].enclosing_definitions == (outer,)
    # Ancestry is syntactic, including headers; it is not an evaluation-scope claim.
    assert calls["default"].enclosing_definitions == (outer,)
    assert [c.name for c in unit.calls][:3] == ["top", "decorate", "default"]


@pytest.mark.parametrize("source", ["", "\n", "# 中文注释\n"])
def test_empty_source_and_file(parser: PythonSourceParser, tmp_path: Path, source: str) -> None:
    path = tmp_path / "empty.py"
    path.write_text(source, encoding="utf-8")
    for unit in (parser.parse_source(source), parser.parse_file(path)):
        assert isinstance(unit.tree, ast.Module)
        assert unit.tree.body == []
        assert unit.imports == unit.assignments == unit.calls == unit.functions == ()


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_unicode_locations_and_original_source(parser: PythonSourceParser, newline: str) -> None:
    line = '名字 = "🙂\u2028"; 调用(名字)'
    source = "# 中文注释" + newline + line + newline
    unit = parser.parse_source(source)
    call = unit.calls[0]
    assert unit.source == source
    assert call.name == "调用"
    assert call.location.line == 2
    assert call.location.column == line.index("调用") + 1
    assert call.location.end_column == len(line) + 1
    assert call.node.col_offset == len(line[: line.index("调用")].encode("utf-8"))
    assert unit.location_for(call.args[0]).column == line.rindex("名字") + 1


def test_tabs_count_as_characters_and_ast_is_preserved(parser: PythonSourceParser) -> None:
    source = "def f():\n\t调用()\n"
    unit = parser.parse_source(source)
    assert unit.calls[0].location.column == 2
    assert ast.dump(unit.tree, include_attributes=True) == ast.dump(
        ast.parse(source), include_attributes=True
    )
    assert unit.calls[0].node is unit.tree.body[0].body[0].value
    with pytest.raises(ValueError, match="no source location"):
        unit.location_for(unit.tree)


@pytest.mark.parametrize(
    "data",
    [
        '# 中文注释\n结果 = run("你好")\n'.encode(),
        codecs.BOM_UTF8 + 'run("你好")\n'.encode(),
        '# coding: latin-1\nrun("café")\n'.encode("latin-1"),
    ],
)
def test_file_encodings(parser: PythonSourceParser, tmp_path: Path, data: bytes) -> None:
    path = tmp_path / "中文 source.PY"
    path.write_bytes(data)
    unit = parser.parse_file(str(path))
    assert unit.path == str(path)
    assert unit.calls[0].name == "run"
    assert isinstance(unit.calls[0].args[0], ast.Constant)


@pytest.mark.parametrize(
    "source", ["def broken(:\n", "x =\n", "if True:\npass\n", "%time run()", "\0"]
)
def test_syntax_errors_are_not_success(parser: PythonSourceParser, tmp_path: Path, source: str):
    path = tmp_path / "broken.py"
    path.write_text(source, encoding="utf-8")
    for parse in (
        lambda: parser.parse_source(source, path=str(path)),
        lambda: parser.parse_file(path),
    ):
        with pytest.raises(SourceParseError) as caught:
            parse()
        error = caught.value
        assert error.code is ParseErrorCode.SYNTAX_ERROR
        assert error.path == str(path)
        assert error.message
        assert str(path) in str(error)
        assert isinstance(error.__cause__, SyntaxError)
        if source != "\0":
            assert error.line is not None and error.line >= 1


def test_syntax_error_character_location(parser: PythonSourceParser) -> None:
    with pytest.raises(SourceParseError) as caught:
        parser.parse_source("名字 = )", path="bad.py")
    assert (caught.value.line, caught.value.column) == (1, 6)


@pytest.mark.parametrize("kind", ["missing", "directory", "nul"])
def test_unreadable_paths(parser: PythonSourceParser, tmp_path: Path, kind: str) -> None:
    path = tmp_path / ("invalid\0.py" if kind == "nul" else "input.py")
    if kind == "directory":
        path.mkdir()
    with pytest.raises(SourceParseError) as caught:
        parser.parse_file(path)
    assert caught.value.code is ParseErrorCode.READ_ERROR
    assert caught.value.path == str(path)
    assert caught.value.line is None


def test_permission_denied_is_reported(
    parser: PythonSourceParser, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "denied.py"
    path.write_text("run()", encoding="utf-8")

    def deny_read(self: Path) -> bytes:
        raise PermissionError("Permission denied by test")

    # chmod is not a reliable unreadability test on Windows or elevated runners.
    monkeypatch.setattr(Path, "read_bytes", deny_read)
    with pytest.raises(SourceParseError) as caught:
        parser.parse_file(path)
    assert caught.value.code is ParseErrorCode.READ_ERROR
    assert isinstance(caught.value.__cause__, PermissionError)


@pytest.mark.parametrize("suffix", [".txt", ".ipynb", ""])
def test_unsupported_file_types(parser: PythonSourceParser, tmp_path: Path, suffix: str) -> None:
    with pytest.raises(SourceParseError) as caught:
        parser.parse_file(tmp_path / f"input{suffix}")
    assert caught.value.code is ParseErrorCode.UNSUPPORTED_FILE


@pytest.mark.parametrize(
    "data",
    [b"x = '\xff'", b"# coding: imaginary-codec\n", codecs.BOM_UTF8 + b"# coding: latin-1\n"],
)
def test_encoding_errors(parser: PythonSourceParser, tmp_path: Path, data: bytes) -> None:
    path = tmp_path / "encoding.py"
    path.write_bytes(data)
    with pytest.raises(SourceParseError) as caught:
        parser.parse_file(path)
    assert caught.value.code is ParseErrorCode.ENCODING_ERROR


def test_unencodable_source(parser: PythonSourceParser) -> None:
    with pytest.raises(SourceParseError) as caught:
        parser.parse_source("# \ud800")
    assert caught.value.code is ParseErrorCode.ENCODING_ERROR


def test_parser_does_not_import_or_execute_target_code(parser: PythonSourceParser, tmp_path: Path):
    marker = tmp_path / "executed.txt"
    module = tmp_path / "statguard_untrusted_fixture.py"
    module.write_text(f"open({str(marker)!r}, 'w').write('executed')\n", encoding="utf-8")
    source = (
        "import statguard_untrusted_fixture\n"
        "import definitely_missing_statguard_test_dependency\n"
        f"open({str(marker)!r}, 'w').write('executed')\n"
        "raise RuntimeError('must not execute')\n"
    )
    path = tmp_path / "unsafe.py"
    path.write_text(source, encoding="utf-8")
    assert len(parser.parse_source(source).imports) == 2
    assert len(parser.parse_file(path).imports) == 2
    assert not marker.exists()
    assert "statguard_untrusted_fixture" not in sys.modules


def test_other_syntax_is_retained_without_extra_analysis(parser: PythonSourceParser) -> None:
    unit = parser.parse_source("x += 1\nvalues = [f(x) for x in data if predicate(x)]\n")
    assert isinstance(unit.tree.body[0], ast.AugAssign)
    assert len(unit.assignments) == 1  # Only Assign and AnnAssign are indexed.
    assert [c.name for c in unit.calls] == ["f", "predicate"]
    assert isinstance(unit.assignments[0].node.value, ast.ListComp)


def test_parser_can_be_reused_without_leaking_previous_results(parser: PythonSourceParser) -> None:
    first = parser.parse_source("x = f()\n", path="first.py")
    second = parser.parse_source("", path="second.py")
    assert first.calls[0].name == "f"
    assert second.calls == ()
    assert second.path == "second.py"


@pytest.mark.parametrize(
    "expression",
    ["(lambda x: x)(value)", "(left if condition else right)(value)", "'text'.format(value)"],
)
def test_dynamic_callees_keep_unknown_state(parser: PythonSourceParser, expression: str) -> None:
    unit = parser.parse_source(expression)
    assert len(unit.calls) == 1
    assert unit.calls[0].is_unknown
    assert unit.calls[0].name is None


def test_argument_expressions_are_not_evaluated(parser: PythonSourceParser) -> None:
    unit = parser.parse_source("run(1 + 2, threshold=config[key], seed=compute())")
    call = unit.calls[0]
    assert isinstance(call.args[0], ast.BinOp)
    assert isinstance(call.keywords[0].value, ast.Subscript)
    assert isinstance(call.keywords[1].value, ast.Call)
    assert unit.calls[1].name == "compute"


def test_recursion_failure_is_an_explicit_error(
    parser: PythonSourceParser, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_parse(*args, **kwargs):
        raise RecursionError("AST parser depth exceeded")

    monkeypatch.setattr(ast, "parse", fail_parse)
    with pytest.raises(SourceParseError) as caught:
        parser.parse_source("deep_source", path="deep.py")
    assert caught.value.code is ParseErrorCode.RESOURCE_LIMIT
    assert caught.value.path == "deep.py"
    assert isinstance(caught.value.__cause__, RecursionError)

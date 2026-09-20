"""Notebook input, source-only delegation, cell positions and explicit failures."""

import ast
import json
from pathlib import Path

import pytest

from statguard.parsers import (
    NotebookIssueCode,
    NotebookParseError,
    NotebookParser,
    ParseErrorCode,
    PythonSourceParser,
)


def cell(source="", kind="code", **extra):
    return {"cell_type": kind, "metadata": {}, "source": source, **extra}


def notebook(cells=(), metadata=None):
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"language_info": {"name": "python"}} if metadata is None else metadata,
        "cells": list(cells),
    }


def parse(document):
    return NotebookParser().parse_json(json.dumps(document, ensure_ascii=False), path="test.ipynb")


def test_mixed_cells_preserve_both_indexes_and_unicode_locations():
    document = notebook(
        [
            cell("# Not Python: % !", "markdown"),
            cell(["# 中文注释\n", "结果 = pkg.run(\n", "    数据, seed=3\n", ")\n"]),
            cell("<script>do_not_execute()</script>", "raw"),
            cell("import pkg as p\nx: int = p.compute()\n"),
        ]
    )
    result = parse(document)
    assert result.cell_count == 4
    assert [(c.cell_index, c.code_cell_index) for c in result.code_cells] == [(2, 1), (4, 2)]
    assert result.is_complete and result.errors == ()
    first, second = result.code_cells
    assert first.source == "".join(document["cells"][1]["source"])
    call = first.parsed.calls[0]
    assert (call.name, call.location.path, call.location.line, call.location.column) == (
        "pkg.run",
        "test.ipynb",
        2,
        6,
    )
    assert (call.location.end_line, call.location.end_column) == (4, 2)
    assert isinstance(second.parsed.assignments[0].node, ast.AnnAssign)
    assert second.parsed.imports[0].node.names[0].asname == "p"
    assert result.notices[0].code is NotebookIssueCode.DOCUMENT_ORDER


@pytest.mark.parametrize("source", ["", [], [""], "# 注释\n", ["x", " = 1"]])
def test_empty_cells_and_exact_string_list_join(source):
    result = parse(notebook([cell(source)]))
    assert result.is_complete
    assert result.code_cells[0].source == ("".join(source) if isinstance(source, list) else source)


@pytest.mark.parametrize("cells", [[], [cell("text", "markdown"), cell("raw", "raw")]])
def test_notebooks_without_code_need_no_language(cells):
    result = parse(notebook(cells, metadata={}))
    assert result.code_cells == ()
    assert result.cell_count == len(cells)
    assert result.is_complete


def test_delegates_unmodified_source_and_keeps_cells_independent():
    class RecordingParser(PythonSourceParser):
        def __init__(self):
            self.inputs = []

        def parse_source(self, source, *, path="<string>"):
            self.inputs.append((source, path))
            return super().parse_source(source, path=path)

    python = RecordingParser()
    parser = NotebookParser(python)
    sources = ["x = make()\n", "use(x)\n"]
    result = parser.parse_json(
        json.dumps(
            notebook(
                [
                    cell(sources[0], execution_count=100),
                    cell(sources[1], execution_count=1),
                ]
            )
        ),
        path="document.ipynb",
    )
    assert python.inputs == [(s, "document.ipynb") for s in sources]
    assert len(result.code_cells[0].parsed.assignments) == 1
    assert result.code_cells[1].parsed.assignments == ()
    assert result.code_cells[1].parsed.calls[0].name == "use"
    assert result.code_cells[0].parsed.tree is not result.code_cells[1].parsed.tree
    assert not hasattr(result.code_cells[0], "execution_count")


def test_syntax_error_retains_original_cell_and_later_cells_continue():
    result = parse(notebook([cell("intro", "markdown"), cell("名字 = )"), cell("valid()")]))
    broken, valid = result.code_cells
    assert not result.is_complete
    assert broken.parsed is None and broken.source == "名字 = )"
    assert result.errors == (broken.error,)
    assert broken.error.code is ParseErrorCode.SYNTAX_ERROR
    assert (broken.error.cell_index, broken.error.code_cell_index) == (2, 1)
    assert (broken.error.line, broken.error.column) == (1, 6)
    assert valid.parsed.calls[0].name == "valid"


@pytest.mark.parametrize(
    "source",
    [
        "%time run()",
        "%%bash\necho hello",
        "!echo hello",
        "!!ls",
        "files = !ls",
        "result = %time run()",
        "?object",
        "object?",
        "object??",
        "/func a b",
        ",func a b",
        ";func a b",
        "x = 1\n%time run()\ny = 2",
        "  %time run()",
        "!echo 'unclosed",
    ],
)
def test_ipython_syntax_is_explicitly_unsupported(source):
    result = parse(notebook([cell(source), cell("standard()")]))
    unsupported = result.code_cells[0]
    assert unsupported.source == source and unsupported.parsed is None
    assert unsupported.error.code is NotebookIssueCode.UNSUPPORTED_SYNTAX
    assert unsupported.error.line >= 1 and unsupported.error.column >= 1
    assert result.code_cells[1].parsed.calls[0].name == "standard"
    assert not result.is_complete


@pytest.mark.parametrize(
    "source",
    [
        'text = "%time !shell ?help"\n# %%magic\nf(text)',
        'text = """\n%time run()\n!echo hello\n"""\nf(text)',
        "x = (10\n % 3)\nassert x != 0",
        "x = 1; f(x)",
        'text = f"{3!r}"',
    ],
)
def test_python_operators_strings_and_comments_are_not_magic(source):
    result = parse(notebook([cell(source)]))
    assert result.is_complete
    assert result.code_cells[0].parsed.source == source


@pytest.mark.parametrize(
    "source",
    [
        'text = "!not a command"\nx = )',
        "# %time run()\nx = )",
        "x = (1\n % 2",
        'text = "!unclosed',
        'text = f"{value!z}"',
        'text = """\n!unclosed',
    ],
)
def test_malformed_python_with_marker_text_stays_a_syntax_error(source):
    result = parse(notebook([cell(source)]))
    assert result.errors[0].code is ParseErrorCode.SYNTAX_ERROR


@pytest.mark.parametrize("text", ["", "{", '{\n"cells": }', "null trailing", '{"x": NaN}'])
def test_invalid_json(text):
    with pytest.raises(NotebookParseError) as caught:
        NotebookParser().parse_json(text, path="bad.ipynb")
    assert caught.value.issue.code is NotebookIssueCode.INVALID_JSON
    assert caught.value.issue.path == "bad.ipynb"
    assert caught.value.issue.cell_index is None


def test_json_error_has_document_location():
    with pytest.raises(NotebookParseError) as caught:
        NotebookParser().parse_json('{\n"cells": }')
    assert (caught.value.issue.line, caught.value.issue.column) == (2, 10)


@pytest.mark.parametrize(
    "document",
    [
        None,
        [],
        {},
        {**notebook(), "nbformat": True},
        {**notebook(), "nbformat_minor": -1},
        {**notebook(), "nbformat_minor": True},
        {**notebook(), "metadata": []},
        {**notebook(), "cells": {}},
        notebook([None]),
        notebook([{"cell_type": "code", "metadata": {}}]),
        notebook([cell(123)]),
        notebook([cell(["x = 1", 3])]),
        notebook([cell("x", "unknown")]),
        notebook([cell("x", metadata=None)]),
        notebook([cell("x", "markdown", metadata=[])]),
        notebook(metadata={"language_info": []}),
        notebook(metadata={"language_info": {"name": None}}),
    ],
)
def test_invalid_notebook_structure(document):
    with pytest.raises(NotebookParseError) as caught:
        parse(document)
    assert caught.value.issue.code is NotebookIssueCode.INVALID_NOTEBOOK


def test_structure_error_has_original_cell_index():
    with pytest.raises(NotebookParseError) as caught:
        parse(notebook([cell("intro", "markdown"), cell(42)]))
    assert caught.value.issue.cell_index == 2
    assert "cell 2" in str(caught.value)


@pytest.mark.parametrize("major", [3, 5])
def test_unsupported_notebook_version(major):
    with pytest.raises(NotebookParseError) as caught:
        parse({**notebook(), "nbformat": major})
    assert caught.value.issue.code is NotebookIssueCode.UNSUPPORTED_VERSION


@pytest.mark.parametrize(
    "metadata",
    [
        {"language_info": {"name": "r"}},
        {"kernelspec": {"name": "julia", "language": "julia"}},
        {"language_info": {"name": "python"}, "kernelspec": {"language": "R"}},
    ],
)
def test_unsupported_or_conflicting_languages(metadata):
    with pytest.raises(NotebookParseError) as caught:
        parse(notebook([cell("looks_like_python()")], metadata=metadata))
    assert caught.value.issue.code is NotebookIssueCode.UNSUPPORTED_LANGUAGE


@pytest.mark.parametrize("metadata", [{}, {"kernelspec": {"name": "python3"}}])
def test_unknown_language_is_not_guessed(metadata):
    with pytest.raises(NotebookParseError) as caught:
        parse(notebook([cell("x = 1")], metadata=metadata))
    assert caught.value.issue.code is NotebookIssueCode.UNKNOWN_LANGUAGE


@pytest.mark.parametrize(
    "metadata",
    [
        {"language_info": {"name": " Python "}},
        {"kernelspec": {"language": "python3"}},
    ],
)
def test_python_language_declarations(metadata):
    assert parse(notebook([cell("run()")], metadata=metadata)).is_complete


def test_file_and_string_results_match(tmp_path):
    text = json.dumps(notebook([cell("# 中文\n结果 = 调用()")]), ensure_ascii=False)
    path = tmp_path / "中文 Notebook.IPYNB"
    path.write_text(text, encoding="utf-8-sig")
    parser = NotebookParser()
    from_file = parser.parse_file(str(path))
    from_text = parser.parse_json(text, path=str(path))
    assert from_file.path == from_text.path == str(path)
    assert from_file.code_cells[0].source == from_text.code_cells[0].source
    assert ast.dump(from_file.code_cells[0].parsed.tree) == ast.dump(
        from_text.code_cells[0].parsed.tree
    )
    assert from_file.code_cells[0].parsed.calls[0].location.column == 6


@pytest.mark.parametrize("kind", ["missing", "directory", "nul"])
def test_file_read_errors(tmp_path, kind):
    path = tmp_path / ("invalid\0.ipynb" if kind == "nul" else "notebook.ipynb")
    if kind == "directory":
        path.mkdir()
    with pytest.raises(NotebookParseError) as caught:
        NotebookParser().parse_file(path)
    assert caught.value.issue.code is ParseErrorCode.READ_ERROR


def test_file_permission_error(tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("read denied")

    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(NotebookParseError) as caught:
        NotebookParser().parse_file(tmp_path / "unreadable.ipynb")
    assert caught.value.issue.code is ParseErrorCode.READ_ERROR
    assert isinstance(caught.value.__cause__, PermissionError)


def test_file_encoding_and_extension_errors(tmp_path):
    path = tmp_path / "invalid.ipynb"
    path.write_bytes(b"\xff")
    with pytest.raises(NotebookParseError) as caught:
        NotebookParser().parse_file(path)
    assert caught.value.issue.code is ParseErrorCode.ENCODING_ERROR
    with pytest.raises(NotebookParseError) as caught:
        NotebookParser().parse_file(tmp_path / "source.py")
    assert caught.value.issue.code is ParseErrorCode.UNSUPPORTED_FILE


def test_no_source_shell_or_output_execution(tmp_path):
    marker = tmp_path / "executed.txt"
    dangerous = f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
    output = [
        {
            "output_type": "display_data",
            "data": {
                "image/png": "not-base64",
                "text/html": "<script>dangerous()</script>",
                "text/plain": dangerous,
                "application/json": {"source": "output_only()"},
            },
        }
    ]
    doc = notebook(
        [
            cell(dangerous, outputs=output),
            cell("!echo do_not_run", outputs=output),
            cell(dangerous, "markdown", attachments={"image": "not-base64"}),
        ]
    )
    path = tmp_path / "unsafe.ipynb"
    path.write_text(json.dumps(doc), encoding="utf-8")
    for result in (parse(doc), NotebookParser().parse_file(path)):
        assert result.code_cells[0].parsed is not None
        assert result.code_cells[1].error.code is NotebookIssueCode.UNSUPPORTED_SYNTAX
        assert not marker.exists()
        assert "output_only" not in repr(result)
        assert "not-base64" not in repr(result)
        assert not hasattr(result.code_cells[0], "outputs")


def test_output_fields_are_not_accessed_after_json_decode(monkeypatch):
    import statguard.parsers.notebook as module

    class SourceOnlyCell(dict):
        def get(self, key, *args):
            assert key not in ("outputs", "execution_count", "attachments")
            return super().get(key, *args)

        def __getitem__(self, key):
            assert key not in ("outputs", "execution_count", "attachments")
            return super().__getitem__(key)

    document = notebook([SourceOnlyCell(cell("source_only()", outputs="invalid output shape"))])
    monkeypatch.setattr(module.json, "loads", lambda *args, **kwargs: document)
    result = NotebookParser().parse_json("{}")
    assert result.code_cells[0].parsed.calls[0].name == "source_only"
    assert result.is_complete

"""Provenance contracts: syntax evidence is distinct from known data relationships."""

import ast
import json
from dataclasses import FrozenInstanceError, replace

import pytest

from statguard.analyzer import Analyzer
from statguard.context import AnalysisContext
from statguard.core import Rule, RuleRegistry
from statguard.parsers import PythonSourceParser

SPLIT = "from sklearn.model_selection import train_test_split as split\n"
SCALER = "from sklearn.preprocessing import StandardScaler as Scaler\n"


def context(source):
    return AnalysisContext(PythonSourceParser().parse_source(source, path="data.py"))


def load(ctx, text, occurrence=0):
    nodes = [
        n
        for n in ast.walk(ctx.tree)
        if isinstance(n, ast.expr)
        and ast.get_source_segment(ctx.source, n) == text
        and not (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store))
    ]
    nodes.sort(key=lambda n: (n.lineno, n.col_offset))
    return ctx.provenance.resolve(nodes[occurrence])


def binding(ctx, name, occurrence=-1):
    values = [b for b in ctx.symbols.bindings if b.name == name]
    return ctx.provenance.for_binding(values[occurrence])


def origin(value):
    while value.kind in {"alias", "binding"}:
        value = value.sources[0]
    return value


@pytest.mark.parametrize(
    "prefix,call",
    [
        ("from sklearn.model_selection import train_test_split\n", "train_test_split"),
        (SPLIT, "split"),
        ("import sklearn.model_selection as ms\n", "ms.train_test_split"),
        ("from sklearn import model_selection as ms\n", "ms.train_test_split"),
        ("import sklearn.model_selection\n", "sklearn.model_selection.train_test_split"),
        (SPLIT + "divide = split\n", "divide"),
    ],
)
def test_split_imports_and_exact_output_mapping(prefix, call):
    ctx = context(prefix + f"a, b, c, d = {call}(X, y, test_size=0.2, random_state=42)\n")
    split = ctx.provenance.splits[0]
    assert split.kind == "split" and split.known
    assert [part.value.node.id for part in split.inputs[:2]] == ["X", "y"]
    for i, name in enumerate("abcd"):
        output = origin(binding(ctx, name))
        assert output.known and output.node.id == name
        assert output.sources == (split.sources[i // 2],)
        role = output.roles[0]
        assert (role.split_id, role.input_index, role.role) == (
            split.id,
            i // 2,
            "train" if i % 2 == 0 else "test",
        )
    assert split.location.path == "data.py"


@pytest.mark.parametrize(
    "prefix",
    [
        "def split(data):\n    return data, data\n",
        "from another_package import train_test_split as split\n",
        "split = __import__('sklearn').model_selection.train_test_split\n",
        SPLIT + "split = unknown\n",
    ],
)
def test_coincident_or_dynamic_name_is_not_sklearn(prefix):
    ctx = context(prefix + "train, test = split(X)\n")
    assert ctx.provenance.splits == ()
    assert binding(ctx, "train").roles == ()
    assert binding(ctx, "train").is_unknown


def test_independent_splits_and_reassignment_keep_binding_versions():
    ctx = context(SPLIT + "a, b = split(X)\nold = a\na, b = split(Y)\ncopy = old\nlatest = a\n")
    first, second = ctx.provenance.splits
    assert first.id != second.id
    assert binding(ctx, "copy").roles[0].split_id == first.id
    assert binding(ctx, "latest").roles[0].split_id == second.id
    assert binding(ctx, "copy").roles[0].role == "train"
    assert first.sources[0].id != second.sources[0].id


def test_transform_preserves_input_roles_through_alias_and_reassignment():
    ctx = context(
        SPLIT + SCALER + "scaler = Scaler()\na, b = split(X)\nold = a\n"
        "a = scaler.fit_transform(a)\ncopy = a\ntest = scaler.transform(b)\n"
    )
    transformed = origin(binding(ctx, "copy"))
    assert transformed.kind == "transform" and transformed.known
    assert transformed.roles == binding(ctx, "old").roles
    assert binding(ctx, "test").roles[0].role == "test"
    assert transformed.sources[0].roles[0].role == "train"
    constructor = transformed.callee.base.origin
    assert constructor.callee.qualified_name == "sklearn.preprocessing.StandardScaler"


def test_old_input_not_replaced_by_final_binding():
    ctx = context(
        SPLIT + SCALER + "from sources import load, other\n"
        "X = load()\nscaler = Scaler()\nscaled = scaler.fit_transform(X)\n"
        "X = other()\ncopy = scaled\na, b = split(copy)\n"
    )
    transform = origin(binding(ctx, "scaled"))
    original = origin(transform.sources[0])
    assert original.callee.qualified_name == "sources.load"
    assert origin(binding(ctx, "X")).callee.qualified_name == "sources.other"
    assert origin(ctx.provenance.splits[0].sources[0]) is transform


@pytest.mark.parametrize("call", ["scaler.transform(X=a)", "Scaler().fit_transform(a)"])
def test_keyword_and_direct_constructor_transform(call):
    ctx = context(SPLIT + SCALER + "scaler = Scaler()\na, b = split(X)\n" + f"out = {call}\n")
    assert binding(ctx, "out").roles[0].role == "train"


@pytest.mark.parametrize(
    "prefix,call",
    [
        ("from arbitrary import transform\n", "transform(a)"),
        ("", "unknown(a)"),
        ("from arbitrary import StandardScaler as S\ns = S()\n", "s.transform(a)"),
        (SCALER + "s = Scaler()\n", "s.fit(a)"),
        (SCALER + "s = Scaler()\n", "s.fit(a).transform(a)"),
    ],
)
def test_opaque_calls_record_arguments_but_never_inherit_roles(prefix, call):
    ctx = context(SPLIT + prefix + "a, b = split(X)\n" + f"out = {call}\n")
    value = origin(binding(ctx, "out"))
    assert value.kind == "call" and value.is_unknown
    assert value.roles == () and value.sources == ()
    assert value.inputs[0].value.roles[0].role == "train"


@pytest.mark.parametrize(
    "statement",
    [
        "a, b, c = split(X)",
        "a, *rest = split(X)",
        "(a, b), c = split(X)",
        "a, b = split(*arrays)",
        "a, b = split(X, **options)",
        "a, b = split(X, invalid=True)",
        "a, b = split()",
    ],
)
def test_unsupported_unpacking_and_argument_shape_never_assign_roles(statement):
    ctx = context(SPLIT + statement)
    assert binding(ctx, "a").roles == ()
    assert binding(ctx, "a").is_unknown


@pytest.mark.parametrize("flow", ["if flag:", "for item in values:", "while flag:"])
def test_control_flow_does_not_establish_split(flow):
    ctx = context(SPLIT + flow + "\n    a, b = split(X)\nafter = a\n")
    assert ctx.provenance.splits == ()
    assert binding(ctx, "after").is_unknown


def test_function_local_scope_and_module_import_limitation():
    ctx = context(
        SPLIT + "def f(X):\n    a, b = split(X)\n"
        "def g(X):\n    from sklearn.model_selection import train_test_split as split\n"
        "    a, b = split(X)\n    copy = a\nmodule = a\n"
    )
    assert len(ctx.provenance.splits) == 1
    assert binding(ctx, "a", 0).roles == ()
    assert binding(ctx, "copy").roles[0].role == "train"
    assert binding(ctx, "module").roles == ()


def test_location_identity_immutability_and_compatibility():
    src = SPLIT + "训练, 测试 = split(数据)\ncopy = 训练\n"
    ctx = context(src)
    assert ctx._provenance is None
    value = origin(binding(ctx, "训练"))
    assert value.location.line == 2 and value.location.column == 1
    assert ctx.provenance is ctx.provenance
    assert value.id == origin(binding(context(src), "训练")).id
    with pytest.raises(FrozenInstanceError):
        value.known = False
    assert replace(ctx).provenance is not ctx.provenance
    # The old symbol contract still reports unpacked objects as unknown.
    assert ctx.symbols.resolve(ctx.tree.body[-1].value).is_unknown
    with pytest.raises(ValueError):
        ctx.provenance.resolve(ast.Name(id="训练"))
    with pytest.raises(ValueError):
        ctx.provenance.for_binding(context("x = 1").symbols.bindings[0])


def test_notebook_isolation_and_never_execute_source_or_outputs(tmp_path):
    marker = tmp_path / "executed"
    seen = []

    class Capture(Rule[AnalysisContext]):
        rule_id = "FIX_PROVENANCE"
        description = "Exercise provenance without a detection rule"

        def check(self, ctx):
            seen.append((ctx.cell_index, ctx.provenance.splits))
            return []

    registry = RuleRegistry[AnalysisContext]()
    registry.register(Capture())
    sources = [
        SPLIT + "a, b = split(X)\n",
        "c, d = split(X)\n",
        f"open({str(marker)!r}, 'w').close()\nexec('raise Exception()')",
    ]
    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"language_info": {"name": "python"}},
        "cells": [
            {
                "cell_type": "code",
                "metadata": {},
                "source": s,
                "outputs": [{"text": "raise Exception()"}],
            }
            for s in sources
        ],
    }
    result = Analyzer(registry).analyze_notebook_json(json.dumps(notebook))
    assert result.is_complete and result.findings == ()
    assert len(seen[0][1]) == 1 and seen[0][1][0].cell_index == 1
    assert seen[1][1] == seen[2][1] == ()
    assert not marker.exists()


def test_unpacking_aliased_split_result_preserves_operation_identity():
    ctx = context(SPLIT + "result = split(X)\ncopy = result\na, b = copy\n")
    assert binding(ctx, "a").roles[0].split_id == ctx.provenance.splits[0].id
    assert binding(ctx, "b").roles[0].role == "test"


def test_unrelated_data_and_role_names_are_not_evidence():
    ctx = context(SPLIT + "X_train = unrelated\na, b = split(X)\ncopy = X_train\n")
    assert binding(ctx, "copy").roles == ()
    assert binding(ctx, "copy").is_unknown


@pytest.mark.parametrize(
    "call",
    [
        "s.transform(a, X=b)",
        "s.transform(*args)",
        "s.transform(a, **options)",
        "s.transform(a, y=b)",
    ],
)
def test_ambiguous_transform_arguments_do_not_propagate_roles(call):
    ctx = context(SPLIT + SCALER + "s = Scaler()\na, b = split(X)\n" + f"out = {call}")
    assert binding(ctx, "out").roles == ()
    assert binding(ctx, "out").is_unknown


def test_tracker_rejects_different_parser_unit():
    from statguard.provenance import ProvenanceTracker

    one, two = context("x = 1"), context("x = 2")
    with pytest.raises(ValueError, match="belong"):
        ProvenanceTracker(one.parsed, two.symbols)


def test_queries_do_not_change_ids_or_parser_ast():
    ctx = context(SPLIT + "a, b = split(X)\ncopy = a")
    before = ast.dump(ctx.tree, include_attributes=True)
    backward = binding(ctx, "copy")
    forward = ctx.provenance.splits[0]
    other = context(ctx.source)
    assert other.provenance.splits[0].id == forward.id
    assert binding(other, "copy").id == backward.id
    assert ast.dump(ctx.tree, include_attributes=True) == before

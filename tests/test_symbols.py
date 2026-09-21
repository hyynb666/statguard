"""Evidence-based import and binding resolution, including conservative boundaries."""

import ast
import json
from dataclasses import FrozenInstanceError, replace

import pytest

from statguard.analyzer import Analyzer
from statguard.context import AnalysisContext
from statguard.core import Rule, RuleRegistry
from statguard.parsers import PythonSourceParser
from statguard.symbols import SymbolResolver, ValueKind


def context(source):
    return AnalysisContext(PythonSourceParser().parse_source(source, path="analysis.py"))


def expression(ctx, text, occurrence=0):
    nodes = [
        node
        for node in ast.walk(ctx.tree)
        if isinstance(node, ast.expr)
        and ast.get_source_segment(ctx.source, node) == text
        and not (isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load))
    ]
    nodes.sort(key=lambda node: (node.lineno, node.col_offset))
    return nodes[occurrence]


def resolved(ctx, text, occurrence=0):
    return ctx.symbols.resolve(expression(ctx, text, occurrence))


@pytest.mark.parametrize(
    ("source", "name", "expected"),
    [
        (
            "import sklearn.preprocessing as prep\nx = prep.StandardScaler",
            "prep.StandardScaler",
            "sklearn.preprocessing.StandardScaler",
        ),
        (
            "from sklearn.preprocessing import StandardScaler\nx = StandardScaler",
            "StandardScaler",
            "sklearn.preprocessing.StandardScaler",
        ),
        (
            "from sklearn.preprocessing import StandardScaler as SS\nx = SS",
            "SS",
            "sklearn.preprocessing.StandardScaler",
        ),
        (
            "from sklearn import model_selection as ms\nx = ms.train_test_split",
            "ms.train_test_split",
            "sklearn.model_selection.train_test_split",
        ),
        (
            "import sklearn.model_selection\nx = sklearn.model_selection.train_test_split",
            "sklearn.model_selection.train_test_split",
            "sklearn.model_selection.train_test_split",
        ),
        (
            "import custom.deep.package as p\nx = p.api.run",
            "p.api.run",
            "custom.deep.package.api.run",
        ),
        ("from package import A, B as C\nx = C", "C", "package.B"),
        ("import first as a, second as b\nx = b.run", "b.run", "second.run"),
    ],
)
def test_import_paths(source, name, expected):
    ctx = context(source)
    value = resolved(ctx, name)
    assert value.qualified_name == expected
    assert not value.is_unknown


def test_same_spelling_different_origins_and_rebinding():
    ctx = context(
        "from first import StandardScaler as SS\nold = SS\n"
        "from second import StandardScaler as SS\nnew = SS\n"
        "SS = 1\nlocal = SS\nold_copy = old\n"
    )
    assert resolved(ctx, "SS", 0).qualified_name == "first.StandardScaler"
    assert resolved(ctx, "SS", 1).qualified_name == "second.StandardScaler"
    assert resolved(ctx, "SS", 2).qualified_name is None
    assert resolved(ctx, "old").qualified_name == "first.StandardScaler"


def test_alias_chain_retains_exact_assignment_versions_and_unknown_input():
    ctx = context("a = X\nb = a\nc = b\na = 3\nd = c\n")
    a = resolved(ctx, "a")
    b = resolved(ctx, "b")
    c = resolved(ctx, "c")
    assert a.binding.name == "a" and a.binding.node is ctx.tree.body[0]
    assert b.binding.value is a
    assert c.binding.value is b
    assert c.origin.is_unknown
    assert c.origin.node.id == "X"
    assert c.origin.reason == "Unbound or external name"
    assert ctx.symbols.binding_for(expression(ctx, "a")) is a.binding
    assert a.binding.location.line == 1 and a.binding.location.column == 1


def test_constructor_method_and_result_alias_preserve_ast_evidence():
    ctx = context(
        "from sklearn.preprocessing import StandardScaler as SS\n"
        "scaler = SS()\nX_scaled = scaler.fit_transform(X)\nX_copy = X_scaled\n"
    )
    constructor = resolved(ctx, "SS()")
    assert constructor.kind is ValueKind.CALL
    assert constructor.callee.qualified_name == "sklearn.preprocessing.StandardScaler"
    assert constructor.qualified_name is None  # No class-versus-factory inference.
    method = resolved(ctx, "scaler.fit_transform")
    assert method.kind is ValueKind.ATTRIBUTE and method.attribute == "fit_transform"
    assert method.base.origin is constructor
    assert method.qualified_name is None
    copy = resolved(ctx, "X_scaled")
    assert copy.binding.name == "X_scaled"
    assert copy.origin.kind is ValueKind.CALL and copy.origin.callee is method
    assert copy.origin.node is ctx.tree.body[2].value
    assert copy.origin.node.args[0].id == "X"


def test_module_function_result_and_chained_method_do_not_infer_return_type():
    ctx = context(
        "import library as lib\nx = lib.Factory().fit(X).transform(Y)\n"
        "z = lib.function(x, option=3)\n"
    )
    outer = resolved(ctx, "lib.Factory().fit(X).transform(Y)")
    assert outer.kind is ValueKind.CALL
    assert outer.callee.attribute == "transform"
    fit = outer.callee.base.origin
    assert fit.kind is ValueKind.CALL and fit.callee.attribute == "fit"
    factory = fit.callee.base.origin
    assert factory.callee.qualified_name == "library.Factory"
    assert fit.qualified_name is outer.qualified_name is None
    function = resolved(ctx, "lib.function(x, option=3)")
    assert function.callee.qualified_name == "library.function"
    assert function.node.keywords[0].arg == "option"


def test_order_annotations_chained_assignment_and_deletion():
    ctx = context(
        "before = p\nimport pkg as p\na = b = p\nx: object = a\n"
        "p: object\ny = p\ndel p\nafter = p\nb += 1\nlast = b\n"
    )
    assert resolved(ctx, "p", 0).is_unknown
    assert resolved(ctx, "p", 1).qualified_name == "pkg"
    assert resolved(ctx, "p", 2).qualified_name == "pkg"
    assert resolved(ctx, "p", 3).is_unknown
    assert resolved(ctx, "a").qualified_name == "pkg"
    assert resolved(ctx, "b").is_unknown
    a, b = [item for item in ctx.symbols.bindings if item.node is ctx.tree.body[2]]
    assert a.value is b.value


def test_independent_function_scopes_parameters_and_later_local_import():
    ctx = context(
        "import global_pkg as p\n"
        "def first(p):\n"
        "    before = p\n"
        "    import local_pkg as p\n"
        "    after = p\n"
        "def second():\n"
        "    external = p\n"
        "    import other_pkg as p\n"
        "    local = p\n"
        "module = p\n"
    )
    loads = [resolved(ctx, "p", index) for index in range(5)]
    assert loads[0].is_unknown and loads[0].binding.scope is ctx.tree.body[1]
    assert loads[1].qualified_name == "local_pkg"
    assert loads[2].is_unknown  # No guess about function invocation time/globals.
    assert loads[3].qualified_name == "other_pkg"
    assert loads[4].qualified_name == "global_pkg"
    assert loads[1].binding.scope is not loads[3].binding.scope


def test_nested_function_does_not_inherit_closure_or_pollute_parent():
    ctx = context(
        "def outer():\n"
        "    import parent as p\n"
        "    def inner():\n"
        "        x = p\n"
        "        import child as p\n"
        "        y = p\n"
        "    z = p\n"
    )
    assert resolved(ctx, "p", 0).is_unknown
    assert resolved(ctx, "p", 1).qualified_name == "child"
    assert resolved(ctx, "p", 2).qualified_name == "parent"


@pytest.mark.parametrize(
    "body",
    [
        "if flag:\n    p = other",
        "for p in items:\n    pass",
        "while flag:\n    p = other",
        "try:\n    p = other\nexcept Exception:\n    pass",
        "with manager() as p:\n    pass",
        "match data:\n    case p:\n        pass",
        "p.attr = value",
        "p[0] = value",
        "from another import *",
        "exec(code)",
        "f = eval\nf(code)",
        "getattr(p, name)",
        "import importlib\nimportlib.import_module(name)",
        "flag and (p := other)",
        "[p for p in values]",
    ],
)
def test_unsupported_effects_invalidate_old_import_and_alias(body):
    ctx = context("import original as p\nsaved = p\n" + body + "\nx = p\ny = saved\n")
    final_p = ctx.tree.body[-2].value
    final_saved = ctx.tree.body[-1].value
    assert ctx.symbols.resolve(final_p).is_unknown
    assert ctx.symbols.resolve(final_p).qualified_name is None
    assert ctx.symbols.resolve(final_saved).is_unknown


@pytest.mark.parametrize(
    "source",
    [
        "p = __import__('package')\nx = p",
        "import importlib as il\np = il.import_module('package')\nx = p",
        "from importlib import import_module as load\np = load('package')\nx = p",
        "from .package import function as p\nx = p",
        "from package import *\nx = p",
        "p = missing()\nx = p",
        "p = getattr(obj, 'method')\nx = p",
    ],
)
def test_dynamic_and_relative_origins_stay_unknown(source):
    ctx = context(source)
    value = ctx.symbols.resolve(ctx.tree.body[-1].value)
    assert value.is_unknown and value.qualified_name is None


def test_no_known_resolution_inside_control_flow_or_after_return():
    ctx = context(
        "import pkg as p\nif flag:\n    p.run()\n"
        "def function():\n    return 1\n    import fake as q\n    q.run()\n"
    )
    assert all(ctx.symbols.resolve(call.node.func).is_unknown for call in ctx.calls)


@pytest.mark.parametrize("declaration", ["global p", "nonlocal p"])
def test_scope_with_global_or_nonlocal_is_explicitly_unsupported(declaration):
    ctx = context(
        "def outer():\n    import pkg as p\n"
        f"    def inner():\n        {declaration}\n        p.run()\n"
    )
    assert ctx.symbols.resolve(ctx.calls[0].node.func).is_unknown


def test_context_compatibility_caching_and_frozen_bindings():
    ctx = context("import pkg as p\nx = p")
    symbols = ctx.symbols
    assert ctx.symbols is symbols
    assert ctx.parsed.tree is ctx.tree
    assert symbols.bindings[0].node is ctx.imports[0].node
    with pytest.raises(FrozenInstanceError):
        symbols.bindings[0].name = "changed"
    replaced = replace(ctx, parsed=PythonSourceParser().parse_source("x = p"))
    assert replaced.symbols is not symbols
    assert replaced.symbols.resolve(replaced.tree.body[0].value).is_unknown
    assert symbols.resolve(ast.Name(id="p", ctx=ast.Load())).is_unknown
    with pytest.raises(TypeError):
        symbols.resolve(ctx.tree)
    with pytest.raises(TypeError):
        SymbolResolver("import pkg")


def test_notebook_units_do_not_share_import_bindings():
    seen = []

    class Capture(Rule[AnalysisContext]):
        rule_id = "FIX_SYMBOL"
        description = "Record per-cell symbol resolution without reporting violations."

        def check(self, ctx):
            seen.extend(
                (ctx.cell_index, ctx.symbols.resolve(call.node.func).qualified_name)
                for call in ctx.calls
            )
            return []

    registry = RuleRegistry[AnalysisContext]()
    registry.register(Capture())
    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"language_info": {"name": "python"}},
        "cells": [
            {"cell_type": "code", "metadata": {}, "source": source, "outputs": []}
            for source in ("import pkg as p\np.run()", "p.run()")
        ],
    }
    result = Analyzer(registry).analyze_notebook_json(json.dumps(notebook))
    assert result.is_complete and result.findings == ()
    assert seen == [(1, "pkg.run"), (2, None)]


def test_source_is_never_executed_or_imported(tmp_path):
    marker = tmp_path / "executed"
    ctx = context(
        "import nonexistent_statguard_fixture as p\n"
        f"open({str(marker)!r}, 'w').close()\n"
        "exec('raise RuntimeError()')\n"
    )
    assert ctx.symbols.bindings
    assert not marker.exists()


def test_semicolon_order_and_reference_before_rebinding():
    ctx = context("import one as p; a = p; import two as p; b = p")
    assert resolved(ctx, "p", 0).qualified_name == "one"
    assert resolved(ctx, "p", 1).qualified_name == "two"
    orders = [binding.order for binding in ctx.symbols.bindings]
    assert orders == sorted(set(orders))


@pytest.mark.parametrize(
    "statement",
    [
        "p.attr = alias = p",
        "alias = p.attr = p",
        "(alias, *rest) = p",
    ],
)
def test_complex_assignment_cannot_restore_stale_alias(statement):
    ctx = context("import package as p\n" + statement + "\nx = alias.run")
    assert resolved(ctx, "alias.run").is_unknown
    assert resolved(ctx, "alias.run").qualified_name is None


@pytest.mark.parametrize(
    "expression_text",
    [
        "lambda: p",
        "[p for p in values]",
        "{p for p in values}",
        "(p for p in values)",
        "left if flag else right",
        "(p := unknown)",
    ],
)
def test_unsupported_expression_is_unknown_and_cannot_leak_inner_binding(expression_text):
    ctx = context(f"import pkg as p\nx = {expression_text}\ny = p\n")
    assert ctx.symbols.resolve(ctx.tree.body[1].value).is_unknown
    assert ctx.symbols.resolve(ctx.tree.body[2].value).is_unknown


def test_annotation_side_effects_and_explicit_import_after_barrier():
    ctx = context(
        "import original as p\nx: exec(code)\nbefore = p\nimport restored as p\nafter = p\n"
    )
    assert resolved(ctx, "p", 0).is_unknown
    assert resolved(ctx, "p", 1).qualified_name == "restored"


def test_annotated_function_locals_do_not_execute_annotation_expression():
    ctx = context("def f():\n    import pkg as p\n    x: exec(code)\n    y = p\n")
    assert resolved(ctx, "p").qualified_name == "pkg"


def test_resolver_never_modifies_parser_ast():
    ctx = context("from package import Factory\nx = Factory().run(data)")
    before = ast.dump(ctx.tree, include_attributes=True)
    assert ctx.symbols.bindings
    assert ast.dump(ctx.tree, include_attributes=True) == before


@pytest.mark.parametrize(
    "tail",
    ["", "StandardScaler = replacement\n", "del StandardScaler\n"],
)
def test_module_import_is_not_assumed_stable_at_function_invocation(tail):
    ctx = context(
        "from sklearn.preprocessing import StandardScaler\n"
        "def preprocess(X):\n"
        "    scaler = StandardScaler()\n"
        "    return scaler.fit_transform(X)\n" + tail
    )
    value = resolved(ctx, "StandardScaler")
    assert value.is_unknown and value.qualified_name is None
    assert resolved(ctx, "scaler.fit_transform").is_unknown


@pytest.mark.parametrize(
    "body",
    [
        "    before = p\n    p = 1\n",
        "    before = p\n    p: object\n",
        "    before = p\n    if flag:\n        p = other\n",
    ],
)
def test_later_local_declaration_never_falls_back_to_module_import(body):
    ctx = context("import package as p\ndef f():\n" + body + "module = p\n")
    assert resolved(ctx, "p", 0).is_unknown
    assert resolved(ctx, "p", 1).qualified_name == "package"


def test_local_import_resolves_without_assuming_module_binding():
    ctx = context(
        "import global_package as p\n"
        "def f(p):\n"
        "    before = p\n"
        "    import local_package as p\n"
        "    result = p.Factory()\n"
        "p = replacement\n"
    )
    assert resolved(ctx, "p", 0).is_unknown
    assert resolved(ctx, "p.Factory").qualified_name == "local_package.Factory"


def test_callee_is_loaded_before_arguments_and_arguments_follow_effects():
    ctx = context(
        "import package as p\nresult = p.run(p.first, exec(code), later=p.second)\nafter = p\n"
    )
    # The already loaded callee/first argument must not use the final environment.
    assert resolved(ctx, "p.run").qualified_name == "package.run"
    assert resolved(ctx, "p.first").qualified_name == "package.first"
    assert resolved(ctx, "p.second").is_unknown
    assert ctx.symbols.resolve(ctx.tree.body[-1].value).is_unknown


def test_symbol_values_are_frozen_and_context_cache_is_lazy():
    ctx = context("import package as p\nx = p")
    assert ctx._symbols is None
    value = resolved(ctx, "p")
    assert ctx._symbols is ctx.symbols
    with pytest.raises(FrozenInstanceError):
        value.kind = ValueKind.UNKNOWN

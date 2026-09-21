"""Small, explicit library contracts; never import the analyzed libraries."""

import ast

from statguard.symbols import SymbolValue, ValueKind


def split_inputs(value: SymbolValue) -> tuple[ast.expr, ...] | None:
    """Recognize only the public sklearn split API and explicit array arguments."""
    node = value.node
    if (
        value.kind is not ValueKind.CALL
        or value.callee.qualified_name != "sklearn.model_selection.train_test_split"
        or not node.args
        or any(isinstance(arg, ast.Starred) for arg in node.args)
        or any(
            kw.arg not in {"test_size", "train_size", "random_state", "shuffle", "stratify"}
            for kw in node.keywords
        )
        or len({kw.arg for kw in node.keywords}) != len(node.keywords)
    ):
        return None
    return tuple(node.args)


def transformed_input(value: SymbolValue) -> ast.expr | None:
    """StandardScaler's public contract returns transformed X, not y or fit state.

    A name such as transform alone is never sufficient. No fit-return-self,
    subclass, pipeline or arbitrary factory type inference is attempted.
    """
    if value.kind is not ValueKind.CALL:
        return None
    method = value.callee.origin
    if method.kind is not ValueKind.ATTRIBUTE or method.attribute not in {
        "transform",
        "fit_transform",
    }:
        return None
    receiver = method.base.origin
    if (
        receiver.kind is not ValueKind.CALL
        or receiver.callee.qualified_name != "sklearn.preprocessing.StandardScaler"
    ):
        return None
    node = value.node
    allowed = {"X", "copy"} if method.attribute == "transform" else {"X", "y", "sample_weight"}
    if (
        len(node.args) > 2
        or any(isinstance(arg, ast.Starred) for arg in node.args)
        or any(kw.arg not in allowed for kw in node.keywords)
        or len({kw.arg for kw in node.keywords}) != len(node.keywords)
    ):
        return None
    names = ("X", "copy") if method.attribute == "transform" else ("X", "y")
    if any(kw.arg in names[: len(node.args)] for kw in node.keywords):
        return None
    return (
        node.args[0]
        if node.args
        else next((kw.value for kw in node.keywords if kw.arg == "X"), None)
    )

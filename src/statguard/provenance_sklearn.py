"""Small, explicit library contracts; never import the analyzed libraries."""

import ast

from statguard.symbols import SymbolValue, ValueKind

SCALER_PATHS = frozenset(
    {
        "sklearn.preprocessing.StandardScaler",
        "sklearn.preprocessing.MinMaxScaler",
        "sklearn.preprocessing.RobustScaler",
    }
)
IMPUTER_PATHS = frozenset(
    {
        "sklearn.impute.SimpleImputer",
        "sklearn.impute.KNNImputer",
        "sklearn.impute.IterativeImputer",
    }
)
TRANSFORMER_PATHS = SCALER_PATHS | IMPUTER_PATHS


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
    """Return X for explicitly supported sklearn transform calls.

    A method name alone is never sufficient. No fit-return-self, subclass,
    pipeline, factory, or arbitrary runtime type inference is attempted.
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
        or receiver.callee.qualified_name not in TRANSFORMER_PATHS
    ):
        return None
    node = value.node
    standard = receiver.callee.qualified_name == "sklearn.preprocessing.StandardScaler"
    allowed = {"X"}
    if method.attribute == "transform" and standard:
        allowed.add("copy")
    if method.attribute == "fit_transform":
        allowed.add("y")
        if standard:
            allowed.add("sample_weight")
    max_args = 2 if method.attribute == "fit_transform" or standard else 1
    if (
        len(node.args) > max_args
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


def learns_scaling_parameters(callee: SymbolValue) -> bool:
    """Require an explicit supported construction with known learning switches."""
    method = callee.origin
    if method.kind is not ValueKind.ATTRIBUTE or method.base is None:
        return False
    receiver = method.base.origin
    if receiver.kind is not ValueKind.CALL or receiver.callee.qualified_name not in SCALER_PATHS:
        return False
    constructor = receiver.node
    if constructor.args or any(kw.arg is None for kw in constructor.keywords):
        return False
    name = receiver.callee.qualified_name
    switches = {
        "sklearn.preprocessing.StandardScaler": ("with_mean", "with_std"),
        "sklearn.preprocessing.RobustScaler": ("with_centering", "with_scaling"),
        "sklearn.preprocessing.MinMaxScaler": (),
    }[name]
    enabled = dict.fromkeys(switches, True)
    for kw in constructor.keywords:
        if kw.arg in enabled:
            if not isinstance(kw.value, ast.Constant) or type(kw.value.value) is not bool:
                return False
            enabled[kw.arg] = kw.value.value
    return not switches or any(enabled.values())


def imputer_semantics(callee: SymbolValue) -> str | None:
    """Describe proven data-dependent fitting, or abstain on unknown semantics."""
    method = callee.origin
    if method.kind is not ValueKind.ATTRIBUTE or method.base is None:
        return None
    receiver = method.base.origin
    if receiver.kind is not ValueKind.CALL:
        return None
    name = receiver.callee.qualified_name
    if name not in IMPUTER_PATHS:
        return None
    constructor = receiver.node
    keyword_names = [kw.arg for kw in constructor.keywords]
    if (
        constructor.args
        or any(name is None for name in keyword_names)
        or len(set(keyword_names)) != len(keyword_names)
    ):
        return None
    if name == "sklearn.impute.KNNImputer":
        return "neighbor reference samples"
    if name == "sklearn.impute.IterativeImputer":
        return "iteratively fitted estimation models"

    strategy = "mean"
    for keyword in constructor.keywords:
        if keyword.arg == "strategy":
            if not isinstance(keyword.value, ast.Constant) or not isinstance(
                keyword.value.value, str
            ):
                return None
            strategy = keyword.value.value
    return {
        "mean": "column means",
        "median": "column medians",
        "most_frequent": "most-frequent column values",
    }.get(strategy)

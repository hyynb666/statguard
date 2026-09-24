"""Small, explicit library contracts; never import the analyzed libraries."""

import ast
from collections.abc import Callable

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
FEATURE_SELECTOR_PATHS = frozenset(
    {
        "sklearn.feature_selection.SelectKBest",
        "sklearn.feature_selection.SelectPercentile",
        "sklearn.feature_selection.VarianceThreshold",
    }
)
SUPERVISED_SCORE_PATHS = frozenset(
    {
        "sklearn.feature_selection.chi2",
        "sklearn.feature_selection.f_classif",
        "sklearn.feature_selection.f_regression",
        "sklearn.feature_selection.mutual_info_classif",
        "sklearn.feature_selection.mutual_info_regression",
        "sklearn.feature_selection.r_regression",
    }
)
TRANSFORMER_PATHS = SCALER_PATHS | IMPUTER_PATHS | FEATURE_SELECTOR_PATHS
ESTIMATOR_PATHS = frozenset(
    {
        "sklearn.linear_model.LogisticRegression",
        "sklearn.linear_model.LinearRegression",
        "sklearn.ensemble.RandomForestClassifier",
        "sklearn.ensemble.RandomForestRegressor",
    }
)


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


def estimator_fit_inputs(
    callee: SymbolValue, call: ast.Call
) -> tuple[tuple[str, ast.expr], ...] | None:
    """Map supported estimator.fit feature/label inputs to their expressions."""
    method = callee.origin
    if method.kind is not ValueKind.ATTRIBUTE or method.attribute != "fit" or method.base is None:
        return None
    estimator = method.base.origin
    if (
        estimator.kind is not ValueKind.CALL
        or estimator.callee.qualified_name not in ESTIMATOR_PATHS
    ):
        return None
    if len(call.args) > 2 or any(isinstance(arg, ast.Starred) for arg in call.args):
        return None
    allowed = {"X", "y", "sample_weight"}
    names = [keyword.arg for keyword in call.keywords]
    if (
        any(name not in allowed for name in names)
        or len(set(names)) != len(names)
        or any(name is None for name in names)
    ):
        return None
    if (call.args and "X" in names) or (len(call.args) > 1 and "y" in names):
        return None
    features = (
        call.args[0]
        if call.args
        else next((keyword.value for keyword in call.keywords if keyword.arg == "X"), None)
    )
    labels = (
        call.args[1]
        if len(call.args) > 1
        else next((keyword.value for keyword in call.keywords if keyword.arg == "y"), None)
    )
    if features is None:
        return None
    return tuple(
        (name, value)
        for name, value in (("features", features), ("labels", labels))
        if value is not None
    )


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


def transformer_instance(callee: SymbolValue) -> SymbolValue | None:
    """Return the exact supported sklearn transformer construction for a method."""
    method = callee.origin
    if method.kind is not ValueKind.ATTRIBUTE or method.base is None:
        return None
    instance = method.base.origin
    if (
        instance.kind is not ValueKind.CALL
        or instance.callee.qualified_name not in TRANSFORMER_PATHS
    ):
        return None
    return instance


def transformer_fit_inputs(callee: SymbolValue, call: ast.Call) -> tuple[ast.expr, ...] | None:
    """Return explicit X/(optional y) for a supported transformer fit call.

    The method name alone is insufficient; the receiver must resolve to an
    allowlisted sklearn constructor and the call signature must be unambiguous.
    """
    method = callee.origin
    if method.kind is not ValueKind.ATTRIBUTE or method.attribute not in {"fit", "fit_transform"}:
        return None
    if transformer_instance(callee) is None:
        return None
    if len(call.args) > 2 or any(isinstance(arg, ast.Starred) for arg in call.args):
        return None
    names = [keyword.arg for keyword in call.keywords]
    if (
        any(name not in {"X", "y"} for name in names)
        or len(set(names)) != len(names)
        or (call.args and "X" in names)
        or (len(call.args) > 1 and "y" in names)
    ):
        return None
    features = (
        call.args[0]
        if call.args
        else next((keyword.value for keyword in call.keywords if keyword.arg == "X"), None)
    )
    labels = (
        call.args[1]
        if len(call.args) > 1
        else next((keyword.value for keyword in call.keywords if keyword.arg == "y"), None)
    )
    return None if features is None else (features, *((labels,) if labels is not None else ()))


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
        options = {keyword.arg: keyword.value for keyword in constructor.keywords}
        max_iter = options.get("max_iter")
        if max_iter is not None:
            if not isinstance(max_iter, ast.Constant) or type(max_iter.value) is not int:
                return None
            if max_iter.value < 0:
                return None
        initial = options.get("initial_strategy")
        if initial is not None and (
            not isinstance(initial, ast.Constant) or not isinstance(initial.value, str)
        ):
            return None
        initial_strategy = "mean" if initial is None else initial.value
        if max_iter is None or max_iter.value > 0:
            if initial_strategy not in {"mean", "median", "most_frequent", "constant"}:
                return None
            return "iteratively fitted estimation models"
        return {
            "mean": "initial column means",
            "median": "initial column medians",
            "most_frequent": "initial most-frequent column values",
        }.get(initial_strategy)

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


def is_feature_selector(callee: SymbolValue) -> bool:
    """Recognize a method receiver constructed from an exact supported selector."""
    method = callee.origin
    if method.kind is not ValueKind.ATTRIBUTE or method.base is None:
        return False
    receiver = method.base.origin
    return (
        receiver.kind is ValueKind.CALL and receiver.callee.qualified_name in FEATURE_SELECTOR_PATHS
    )


def feature_selector_semantics(
    callee: SymbolValue,
    call: ast.Call,
    resolve: Callable[[ast.expr], SymbolValue],
) -> str | None:
    """Describe a proven supported selector fit, or abstain on unknown evidence."""
    if not is_feature_selector(callee):
        return None
    method = callee.origin
    if method.attribute not in {"fit", "fit_transform"}:
        return None
    receiver = method.base.origin
    name = receiver.callee.qualified_name
    constructor = receiver.node
    keyword_names = [keyword.arg for keyword in constructor.keywords]
    if (
        constructor.args
        or any(keyword is None for keyword in keyword_names)
        or len(set(keyword_names)) != len(keyword_names)
    ):
        return None
    options = {keyword.arg: keyword.value for keyword in constructor.keywords}

    if name == "sklearn.feature_selection.VarianceThreshold":
        if any(keyword not in {"threshold"} for keyword in keyword_names):
            return None
        threshold = options.get("threshold")
        if threshold is not None and (
            not isinstance(threshold, ast.Constant)
            or type(threshold.value) not in {int, float}
            or threshold.value < 0
        ):
            return None
        return "feature variances estimated from all fitting samples"

    parameter = "k" if name == "sklearn.feature_selection.SelectKBest" else "percentile"
    allowed = {"score_func", parameter}
    if any(keyword not in allowed for keyword in keyword_names):
        return None
    selection = options.get(parameter)
    if selection is not None:
        if not isinstance(selection, ast.Constant) or type(selection.value) is not int:
            return None
        if parameter == "k" and selection.value <= 0:
            return None
        if parameter == "percentile" and not 0 < selection.value < 100:
            return None
    if parameter == "k" and isinstance(selection, ast.Constant) and selection.value == "all":
        return None

    score_node = options.get("score_func")
    score_name = (
        "sklearn.feature_selection.f_classif"
        if score_node is None
        else resolve(score_node).qualified_name
    )
    if score_name not in SUPERVISED_SCORE_PATHS:
        return None

    target = (
        call.args[1]
        if len(call.args) >= 2
        else next((keyword.value for keyword in call.keywords if keyword.arg == "y"), None)
    )
    if target is None or (isinstance(target, ast.Constant) and target.value is None):
        return None
    short_name = score_name.rsplit(".", 1)[-1]
    return f"supervised {short_name} scores computed from features and target labels"

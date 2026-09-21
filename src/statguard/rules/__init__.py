"""Built-in detection rules; explicit registries remain available to API callers."""

from statguard.context import AnalysisContext
from statguard.core import RuleRegistry
from statguard.rules.ml001 import ML001
from statguard.rules.ml002 import ML002


def default_registry() -> RuleRegistry[AnalysisContext]:
    """Return a fresh registry with supported built-in rules enabled."""
    registry = RuleRegistry[AnalysisContext]()
    registry.register(ML001())
    registry.register(ML002())
    return registry


__all__ = ["ML001", "ML002", "default_registry"]

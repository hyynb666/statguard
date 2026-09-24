"""Built-in detection rules; explicit registries remain available to API callers."""

from statguard.context import AnalysisContext
from statguard.core import RuleRegistry
from statguard.rules.ml001 import ML001
from statguard.rules.ml002 import ML002
from statguard.rules.ml003 import ML003
from statguard.rules.ml004 import ML004


def default_registry() -> RuleRegistry[AnalysisContext]:
    """Return a fresh registry with supported built-in rules enabled."""
    registry = RuleRegistry[AnalysisContext]()
    registry.register(ML001())
    registry.register(ML002())
    registry.register(ML003())
    registry.register(ML004())
    return registry


__all__ = ["ML001", "ML002", "ML003", "ML004", "default_registry"]

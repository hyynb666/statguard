"""Built-in detection rules; explicit registries remain available to API callers."""

from statguard.context import AnalysisContext
from statguard.core import RuleRegistry
from statguard.rules.ml001 import ML001
from statguard.rules.ml002 import ML002
from statguard.rules.ml003 import ML003
from statguard.rules.ml004 import ML004
from statguard.rules.ml005 import ML005
from statguard.rules.ml006 import ML006
from statguard.rules.ml009 import ML009
from statguard.rules.st001 import ST001
from statguard.rules.st002 import ST002


def default_registry() -> RuleRegistry[AnalysisContext]:
    """Return a fresh registry with supported built-in rules enabled."""
    registry = RuleRegistry[AnalysisContext]()
    registry.register(ML001())
    registry.register(ML002())
    registry.register(ML003())
    registry.register(ML004())
    registry.register(ML005())
    registry.register(ML006())
    registry.register(ML009())
    registry.register(ST001())
    registry.register(ST002())
    return registry


__all__ = [
    "ML001",
    "ML002",
    "ML003",
    "ML004",
    "ML005",
    "ML006",
    "ML009",
    "ST001",
    "ST002",
    "default_registry",
]

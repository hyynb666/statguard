"""Small, non-executable project configuration loader for the CLI."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    """A configuration file could not be read or has an invalid StatGuard section."""


@dataclass(frozen=True, slots=True)
class StatGuardConfig:
    """The project policy supported by the first configuration version."""

    exclude: tuple[str, ...] = ()
    disable_rules: tuple[str, ...] = ()
    fail_on: str | None = None


_SUPPORTED_KEYS = frozenset({"exclude", "disable-rules", "fail-on"})


def load_config(path: str | Path) -> StatGuardConfig:
    """Read one TOML file and validate only its optional ``tool.statguard`` table."""
    return _load_config(path, missing_ok=False)


def discover_config(path: str | Path) -> StatGuardConfig:
    """Read a discovered config, treating only a missing file as no policy."""
    return _load_config(path, missing_ok=True)


def _load_config(path: str | Path, *, missing_ok: bool) -> StatGuardConfig:
    try:
        with Path(path).open("rb") as config_file:
            document = tomllib.load(config_file)
    except FileNotFoundError as error:
        if missing_ok:
            return StatGuardConfig()
        raise ConfigError("configuration file could not be read or is invalid") from error
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ConfigError("configuration file could not be read or is invalid") from error

    tool = document.get("tool", {})
    if not isinstance(tool, dict):
        raise ConfigError("[tool] must be a table")
    if "statguard" not in tool:
        return StatGuardConfig()

    section = tool["statguard"]
    if not isinstance(section, dict):
        raise ConfigError("[tool.statguard] must be a table")
    unknown = sorted(set(section) - _SUPPORTED_KEYS)
    if unknown:
        raise ConfigError(f"unsupported [tool.statguard] key: {unknown[0]}")

    exclude = _string_array(section, "exclude")
    disable_rules = _string_array(section, "disable-rules")
    fail_on = section.get("fail-on")
    if fail_on is not None and (
        not isinstance(fail_on, str) or fail_on not in {"warning", "error"}
    ):
        raise ConfigError("[tool.statguard].fail-on must be 'warning' or 'error'")
    return StatGuardConfig(exclude, disable_rules, fail_on)


def _string_array(section: dict[str, object], key: str) -> tuple[str, ...]:
    value = section.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ConfigError(f"[tool.statguard].{key} must be an array of strings")
    normalized = tuple(item.strip() for item in value)
    if any(not item for item in normalized):
        raise ConfigError(f"[tool.statguard].{key} must not contain empty strings")
    return normalized

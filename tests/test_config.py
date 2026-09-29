"""Project configuration parsing and one-invocation CLI policy tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from statguard.cli import main
from statguard.config import ConfigError, StatGuardConfig, discover_config, load_config
from statguard.context import AnalysisContext
from statguard.core import Evidence, Finding, Rule, RuleRegistry


class WarningRule(Rule[AnalysisContext]):
    rule_id = "CFG001"
    description = "Configuration test finding."

    def check(self, context: AnalysisContext):
        for call in context.calls:
            yield Finding(
                self.rule_id,
                context.path,
                call.location.line,
                call.location.column,
                "Fixture warning",
                "A fixture warning.",
                "No action required.",
                Evidence.CONFIRMED_CODE_PATTERN,
            )


def _registry() -> RuleRegistry[AnalysisContext]:
    registry: RuleRegistry[AnalysisContext] = RuleRegistry()
    registry.register(WarningRule())
    return registry


def _write_config(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_defaults_and_missing_statguard_section(tmp_path: Path) -> None:
    assert discover_config(tmp_path / "missing.toml") == StatGuardConfig()
    assert load_config(_write_config(tmp_path / "pyproject.toml", '[project]\nname="demo"\n')) == (
        StatGuardConfig()
    )


def test_discovery_does_not_suppress_unreadable_existing_config(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "pyproject.toml"
    original_open = Path.open

    def deny_selected(self: Path, *args, **kwargs):
        if self == path:
            raise PermissionError("private detail")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny_selected)
    with pytest.raises(ConfigError, match="could not be read"):
        discover_config(path)


def test_valid_supported_values_and_normalization(tmp_path: Path) -> None:
    config = load_config(
        _write_config(
            tmp_path / "custom.toml",
            '[tool.statguard]\nexclude=[" generated ", "vendor"]\n'
            'disable-rules=[" CFG001 "]\nfail-on="warning"\n',
        )
    )
    assert config == StatGuardConfig(("generated", "vendor"), ("CFG001",), "warning")


@pytest.mark.parametrize(
    "text",
    [
        "[tool.statguard\nexclude=[]",
        '[tool.statguard]\nexclude="generated"',
        "[tool.statguard]\nexclude=[1]",
        '[tool.statguard]\nexclude=[""]',
        '[tool.statguard]\ndisable-rules="CFG001"',
        '[tool.statguard]\ndisable-rules=["  "]',
        '[tool.statguard]\nfail-on="info"',
        "[tool.statguard]\nfail-on=1",
        '[tool.statguard]\nformat="json"',
        '[tool]\nstatguard="wrong type"',
    ],
)
def test_invalid_config_is_rejected(tmp_path: Path, text: str) -> None:
    path = _write_config(tmp_path / "invalid.toml", text)
    with pytest.raises(ConfigError):
        load_config(path)


def test_duplicate_toml_key_is_rejected(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path / "duplicate.toml", '[tool.statguard]\nfail-on="error"\nfail-on="warning"'
    )
    with pytest.raises(ConfigError, match="invalid"):
        load_config(path)


def test_explicit_missing_config_is_a_clean_cli_error(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    status = main(["check", ".", "--config", "missing.toml", "--format", "json"])
    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert (
        captured.err.strip()
        == "statguard: error: configuration file could not be read or is invalid"
    )


def test_config_and_no_config_are_mutually_exclusive(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as result:
        main(["check", ".", "--config", "x.toml", "--no-config"])
    assert result.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_discovery_is_from_cwd_and_no_config_suppresses_it(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[tool.statguard]\ndisable-rules=["CFG001"]\n', encoding="utf-8"
    )
    (project / "code.py").write_text("trigger()\n", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    _write_config(nested / "pyproject.toml", '[tool.statguard]\ndisable-rules=["CFG001"]\n')

    monkeypatch.chdir(tmp_path)
    registry = _registry()
    assert main(["check", str(project), "--format", "json"], registry=registry) == 0
    assert len(json.loads(capsys.readouterr().out)["findings"]) == 1

    monkeypatch.chdir(project)
    assert main(["check", ".", "--format", "json", "--no-config"], registry=_registry()) == 0
    assert len(json.loads(capsys.readouterr().out)["findings"]) == 1


def test_no_config_skips_invalid_auto_discovered_file(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path / "pyproject.toml", "[tool.statguard\n")
    (tmp_path / "code.py").write_text("pass\n", encoding="utf-8")
    assert main(["check", "code.py", "--no-config"], registry=_registry()) == 0
    assert capsys.readouterr().err == ""


def test_config_precedence_merges_stably_and_uses_actual_registry(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.statguard]\nexclude=["generated", "generated"]\n'
        'disable-rules=["CFG001"]\nfail-on="error"\n',
        encoding="utf-8",
    )
    (tmp_path / "code.py").write_text("trigger()\n", encoding="utf-8")
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "excluded.py").write_text("trigger()\n", encoding="utf-8")
    registry = _registry()
    assert (
        main(
            [
                "check",
                ".",
                "--format",
                "json",
                "--exclude",
                "generated",
                "--disable-rule",
                "CFG001",
                "--fail-on",
                "warning",
            ],
            registry=registry,
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["findings"] == []
    assert payload["summary"]["enabled_rules"] == 0
    assert payload["summary"]["scanned_files"] == 1


def test_explicit_config_file_applies_without_auto_discovery(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path / "pyproject.toml", '[tool.statguard]\nfail-on="invalid"\n')
    policy = _write_config(
        tmp_path / "ci-policy.toml", '[tool.statguard]\ndisable-rules=["CFG001"]\n'
    )
    (tmp_path / "code.py").write_text("trigger()\n", encoding="utf-8")
    assert (
        main(
            ["check", "code.py", "--config", policy.name, "--format", "json"],
            registry=_registry(),
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["findings"] == []


def test_unknown_config_rule_id_fails_before_scan(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path / "pyproject.toml", '[tool.statguard]\ndisable-rules=["UNKNOWN"]\n')
    assert main(["check", "missing.py", "--format", "json"], registry=_registry()) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unknown rule ID: UNKNOWN" in captured.err


def test_custom_registry_config_validation_uses_custom_registry(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path / "pyproject.toml", '[tool.statguard]\ndisable-rules=["CFG001"]\n')
    (tmp_path / "code.py").write_text("trigger()\n", encoding="utf-8")
    assert main(["check", ".", "--format", "json"], registry=_registry()) == 0
    assert json.loads(capsys.readouterr().out)["findings"] == []


def test_repeated_calls_do_not_leak_policy_into_custom_registry(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path / "pyproject.toml", '[tool.statguard]\ndisable-rules=["CFG001"]\n')
    (tmp_path / "code.py").write_text("trigger()\n", encoding="utf-8")
    registry = _registry()

    assert main(["check", "code.py", "--format", "json"], registry=registry) == 0
    assert json.loads(capsys.readouterr().out)["findings"] == []
    assert registry.is_enabled("CFG001")

    assert main(["check", "code.py", "--format", "json", "--no-config"], registry=registry) == 0
    assert len(json.loads(capsys.readouterr().out)["findings"]) == 1


def test_cli_failure_threshold_overrides_config(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path / "pyproject.toml", '[tool.statguard]\nfail-on="warning"\n')
    (tmp_path / "code.py").write_text("trigger()\n", encoding="utf-8")
    assert main(["check", "code.py"], registry=_registry()) == 1
    capsys.readouterr()
    _write_config(tmp_path / "pyproject.toml", '[tool.statguard]\nfail-on="error"\n')
    assert main(["check", "code.py", "--fail-on", "warning"], registry=_registry()) == 1
    capsys.readouterr()


def test_configuration_content_is_not_executed(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    marker = tmp_path / "config-executed"
    _write_config(
        tmp_path / "pyproject.toml",
        "[tool.statguard]\nexclude=[\"__import__('pathlib').Path('config-executed').touch()\"]\n",
    )
    (tmp_path / "code.py").write_text("pass\n", encoding="utf-8")
    assert main(["check", "code.py"], registry=_registry()) == 0
    assert not marker.exists()

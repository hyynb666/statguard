"""Small repository contract tests for release-facing metadata and links."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlsplit

from statguard.rules import default_registry

ROOT = Path(__file__).resolve().parents[1]
V0_1_CORE_RULE_IDS = {
    "ML001",
    "ML002",
    "ML003",
    "ML004",
    "ML005",
    "ML006",
    "ST001",
    "ST002",
}
ADDITIONAL_RULE_IDS = {"ML009"}
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)")


def test_default_registry_contains_exactly_one_instance_of_each_release_rule():
    rule_ids = [rule.rule_id for rule in default_registry()]

    assert len(rule_ids) == len(set(rule_ids))
    assert set(rule_ids) == V0_1_CORE_RULE_IDS | ADDITIONAL_RULE_IDS


def test_development_version_and_alpha_classifier_are_consistent():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert metadata["version"] == "0.2.0.dev0"
    assert "Development Status :: 3 - Alpha" in metadata["classifiers"]
    assert not any("Pre-Alpha" in classifier for classifier in metadata["classifiers"])


def test_readme_describes_github_install_and_no_pypi_availability():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "first public Alpha release" in readme
    assert "--branch v0.1.0" in readme
    assert "not published to PyPI" in readme
    assert "pip install statguard" not in readme


def test_readme_distinguishes_stable_release_from_action_development():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "StatGuard v0.1.0 is the first public Alpha release on GitHub" in readme
    assert "developing toward v0.2.0 (`0.2.0.dev0`)" in readme
    assert "`@main` is a moving development reference" in readme
    assert "v0.1.0 release does not contain this Action" in readme


def test_unreleased_changelog_records_action_without_changing_release_history():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "## [Unreleased]\n\n### Added\n\n- GitHub composite Action integration" in changelog
    assert "## [0.1.0] - 2026-09-29" in changelog


def test_release_notes_cover_rules_safety_and_installation():
    notes = (ROOT / "docs/release-notes-v0.1.0.md").read_text(encoding="utf-8")

    sections = ("## Highlights", "## Rules", "## Safety", "## Known limitations", "## Installation")
    for section in sections:
        assert section in notes
    assert "ML001–ML006" in notes and "ST001–ST002" in notes and "ML009" in notes
    assert "not published to PyPI" in notes


def test_repository_markdown_links_resolve_to_local_paths():
    excluded_parts = {".git", ".venv", "build", "dist"}
    markdown_files = [
        path
        for path in ROOT.rglob("*.md")
        if not excluded_parts.intersection(path.relative_to(ROOT).parts)
    ]

    broken: list[str] = []
    for markdown_file in markdown_files:
        text = markdown_file.read_text(encoding="utf-8")
        # Markdown-looking syntax in inline or fenced code is not a hyperlink.
        text = re.sub(r"(`+).*?\1", "", text, flags=re.DOTALL)
        for match in MARKDOWN_LINK.finditer(text):
            target = unquote(match.group(1))
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue

            local_target = (markdown_file.parent / parsed.path).resolve()
            if not local_target.exists():
                broken.append(f"{markdown_file.relative_to(ROOT)} -> {target}")

    assert not broken, "Broken local Markdown links:\n" + "\n".join(broken)

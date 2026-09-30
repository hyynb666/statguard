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
ADDITIONAL_RULE_IDS = {"ML007", "ML009"}
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)")


def test_default_registry_contains_exactly_one_instance_of_each_release_rule():
    rule_ids = [rule.rule_id for rule in default_registry()]

    assert len(rule_ids) == len(set(rule_ids))
    assert set(rule_ids) == V0_1_CORE_RULE_IDS | ADDITIONAL_RULE_IDS


def test_release_version_and_alpha_classifier_are_consistent():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert metadata["version"] == "0.3.0.dev0"
    assert metadata["requires-python"] == ">=3.11"
    assert metadata["dependencies"] == []
    assert metadata["license"] == "MIT"
    assert "Development Status :: 3 - Alpha" in metadata["classifiers"]
    assert not any("Pre-Alpha" in classifier for classifier in metadata["classifiers"])


def test_readme_describes_current_release_install_and_no_pypi_availability():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "StatGuard v0.2.0 is the current public Alpha release" in readme
    assert "main` branch is the development line toward v0.3.0" in readme
    assert "--branch v0.2.0" in readme
    assert "releases/tag/v0.2.0" in readme
    assert "not published to PyPI" in readme
    assert "pip install statguard" not in readme


def test_readme_uses_stable_action_reference_and_describes_release_scope():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "hyynb666/statguard@v0.2.0" in readme
    assert "first stable tagged release containing the Composite" in readme
    assert "does not add or" in readme and "change detection rules" in readme
    assert "Console, JSON, HTML, or SARIF" in readme


def test_changelog_freezes_v02_and_preserves_v01_history():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = changelog.split("## [0.2.0]", maxsplit=1)[0]

    assert "## [Unreleased]\n\n" in unreleased
    assert "### Added" in unreleased
    assert "inline Finding suppression" in unreleased
    assert "## [0.2.0] - 2026-09-30\n\n### Added" in changelog
    assert "- Project policy from `[tool.statguard]`" in changelog
    assert "- GitHub composite Action integration" in changelog
    assert "## [0.1.0] - 2026-09-29" in changelog


def test_v01_release_notes_remain_and_v02_notes_cover_release_scope():
    notes = (ROOT / "docs/release-notes-v0.1.0.md").read_text(encoding="utf-8")

    sections = ("## Highlights", "## Rules", "## Safety", "## Known limitations", "## Installation")
    for section in sections:
        assert section in notes
    assert "ML001–ML006" in notes and "ST001–ST002" in notes and "ML009" in notes
    assert "not published to PyPI" in notes

    current = (ROOT / "docs/releases/v0.2.0.md").read_text(encoding="utf-8")
    for section in (
        "## Highlights",
        "## GitHub Action",
        "## Project configuration",
        "## SARIF",
        "## Rules",
        "## Safety",
        "## Known limitations",
        "## Installation",
    ):
        assert section in current
    assert "ML001–ML006" in current and "ML009" in current and "ST001–ST002" in current
    assert "hyynb666/statguard@v0.2.0" in current
    assert "does not add or change rule semantics" in current
    assert "not published to PyPI" in current


def test_v02_action_guides_recommend_stable_tag_without_changing_upload_action():
    action_docs = (ROOT / "docs/github-action.md").read_text(encoding="utf-8")
    sarif_docs = (ROOT / "docs/sarif.md").read_text(encoding="utf-8")

    assert "hyynb666/statguard@v0.2.0" in action_docs
    assert "uses: hyynb666/statguard@main" not in action_docs
    assert "hyynb666/statguard@v0.2.0" in sarif_docs
    assert "github/codeql-action/upload-sarif@v4" in sarif_docs
    assert "uses: hyynb666/statguard@main" not in sarif_docs


def test_v02_release_audit_and_checklist_are_explicit():
    audit = (ROOT / "docs/release-audit-v0.2.md").read_text(encoding="utf-8")
    checklist = (ROOT / "docs/release-checklist-v0.2.md").read_text(encoding="utf-8")

    assert "READY FOR v0.2.0 RELEASE" in audit
    assert "v0.1.0" in checklist
    assert "issue26-final-release-dist" in checklist
    assert "PyPI publication is not authorized" in checklist


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

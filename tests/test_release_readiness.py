"""Small repository contract tests for release-facing metadata and links."""

from __future__ import annotations

import re
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

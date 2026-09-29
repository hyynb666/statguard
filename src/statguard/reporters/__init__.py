"""Console, JSON, offline HTML, and SARIF presentation; no rule execution."""

from statguard.reporters.console import render_console
from statguard.reporters.html import render_html
from statguard.reporters.json import SCHEMA_VERSION, render_json
from statguard.reporters.sarif import SARIF_SCHEMA, RuleMetadata, render_sarif

__all__ = [
    "RuleMetadata",
    "SARIF_SCHEMA",
    "SCHEMA_VERSION",
    "render_console",
    "render_html",
    "render_json",
    "render_sarif",
]

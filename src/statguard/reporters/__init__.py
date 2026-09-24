"""Console, JSON, and offline HTML presentation; no rule execution."""

from statguard.reporters.console import render_console
from statguard.reporters.html import render_html
from statguard.reporters.json import SCHEMA_VERSION, render_json

__all__ = ["SCHEMA_VERSION", "render_console", "render_html", "render_json"]

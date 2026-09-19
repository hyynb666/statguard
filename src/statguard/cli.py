"""Command-line entry point; source scanning is not implemented yet."""

import argparse
from collections.abc import Sequence

from statguard import __version__


def main(argv: Sequence[str] | None = None) -> int:
    """Display help or version information without reading or executing target code."""
    parser = argparse.ArgumentParser(
        prog="statguard",
        description="Static analysis for statistical Python workflows.",
        epilog="Development foundation only: source scanning is not yet available.",
    )
    parser.add_argument("--version", action="version", version=f"statguard {__version__}")
    parser.parse_args(argv)
    parser.print_help()
    return 0

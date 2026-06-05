"""Shared --help banner derived from a tool's TOOL_META.

Entry-point tools declare a module-level TOOL_META dict and call
add_to_parser(parser, TOOL_META) so `--help` prints their domain, who runs
them, and when. The same dict feeds gen_readme.py, so help and README never
drift.
"""
from __future__ import annotations

import argparse

_RUN_BY_LABEL = {"ci": "ci", "owner": "owner", "maintainer": "maintainer"}


def format_banner(meta: dict) -> str:
    """Return a 3-line banner: domain/run-by, when, summary."""
    return (
        f"Domain: {meta['domain']}   Run by: {_RUN_BY_LABEL[meta['run_by']]}\n"
        f"When: {meta['when']}\n"
        f"{meta['summary']}"
    )


def add_to_parser(parser: argparse.ArgumentParser, meta: dict) -> None:
    """Append the metadata banner to a parser's --help epilog."""
    banner = format_banner(meta)
    parser.epilog = f"{banner}\n\n{parser.epilog}" if parser.epilog else banner
    parser.formatter_class = argparse.RawDescriptionHelpFormatter

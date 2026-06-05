from __future__ import annotations

import argparse

from tools._toolmeta import add_to_parser, format_banner

META = {
    "domain": "inventory",
    "run_by": "ci",
    "when": "Every CI build.",
    "summary": "Do the thing.",
}


def test_format_banner_contains_all_fields():
    text = format_banner(META)
    assert "inventory" in text
    assert "ci" in text
    assert "Every CI build." in text
    assert "Do the thing." in text


def test_add_to_parser_puts_banner_in_help():
    parser = argparse.ArgumentParser(description="x")
    add_to_parser(parser, META)
    help_text = parser.format_help()
    assert "Domain: inventory" in help_text
    assert "Run by: ci" in help_text
    assert "Do the thing." in help_text

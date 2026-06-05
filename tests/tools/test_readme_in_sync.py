from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GEN = REPO / "tools" / "gen_readme.py"
DOMAINS = {"inventory", "probes", "state_machine", "session", "release"}
RUN_BY = {"ci", "owner", "maintainer"}


def _scan():
    sys.path.insert(0, str(REPO))
    from tools.gen_readme import scan_tools  # noqa: E402

    return scan_tools(REPO / "tools")


def test_readme_is_in_sync():
    result = subprocess.run(
        [sys.executable, str(GEN), "--check"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        "tools/README.md is stale — run `python tools/gen_readme.py`:\n"
        + result.stdout + result.stderr
    )


def test_every_tool_domain_matches_its_subdir():
    bad = [
        (t["path"], t["domain"]) for t in _scan()
        if t["domain"] != Path(t["path"]).parent.name
    ]
    assert not bad, f"TOOL_META domain != containing subdir: {bad}"


def test_metadata_fields_well_formed():
    errs = []
    for t in _scan():
        if t["domain"] not in DOMAINS:
            errs.append(f"{t['path']}: bad domain {t['domain']!r}")
        if t["run_by"] not in RUN_BY:
            errs.append(f"{t['path']}: bad run_by {t['run_by']!r}")
        if not t["when"] or not t["summary"]:
            errs.append(f"{t['path']}: empty when/summary")
    assert not errs, "\n".join(errs)

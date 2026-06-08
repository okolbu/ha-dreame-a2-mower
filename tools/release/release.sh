#!/usr/bin/env bash
# Cut a new release that HACS will actually see.
# tool-meta: domain=release run_by=maintainer
# tool-when: After pushing integration commits, to cut a HACS-visible release.
# tool-summary: Bump version, tag, push, create the GitHub Release, and refresh HACS.
#
# Usage:
#   tools/release/release.sh                  # auto-bumps a80 → a81
#   tools/release/release.sh 1.0.0a99         # explicit version (no leading "v")
#   tools/release/release.sh --notes "msg"    # auto-bump with custom notes
#
# What this guards against (every failure mode hit historically):
#   1. Tag pushed without a GitHub Release object → HACS invisible.
#      We always run `gh release create` after the tag push.
#   2. `--prerelease` flag set → HACS invisible (user has "Show beta" off).
#      We never pass `--prerelease`.
#   3. Tag pointing to a commit that doesn't have the bumped manifest.json
#      → HACS shows the version but install gets the wrong code.
#      We bump+commit FIRST, then tag the commit we just made.
#   4. manifest.json on `main` and at the tag drift apart.
#      We verify both equal the new version after push.
#   5. Release created but not marked "Latest" because GitHub got confused
#      after a `--prerelease` edit. We pass `--latest` explicitly.
#   6. HACS still showing stale data even after a clean release → we offer
#      to trigger HACS' WebSocket refresh on the local HA host.
#
# Requires: gh (authenticated), git (clean working tree), jq, and a python3 with
#           pytest — defaults to /data/claude/homeassistant/.venv-vanilla (the
#           system python3 is a broken 3.14); override via RELEASE_PYTHON=...
#
# Safety: aborts on any uncommitted changes, any failed test, or any
# verification step. It will NOT push or release anything until the
# pre-flight is clean.

set -euo pipefail

# This script lives at tools/release/release.sh — two levels below the repo root.
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

MANIFEST="custom_components/dreame_a2_mower/manifest.json"
HA_CRED="/data/claude/homeassistant/secrets/ha-credentials.txt"

# Interpreter for tests + helper snippets. The system python3 in this env is a
# broken 3.14 with no pytest, so prefer the project's vanilla test venv. Override
# with RELEASE_PYTHON=/path/to/python if you keep the venv elsewhere.
PYTHON="${RELEASE_PYTHON:-/data/claude/homeassistant/.venv-vanilla/bin/python3}"
if [[ ! -x "$PYTHON" ]]; then
    echo "⚠️  $PYTHON not found — falling back to python3 on PATH" >&2
    PYTHON="python3"
fi

NOTES_FILE=""
EXPLICIT_VERSION=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --notes-file) NOTES_FILE="$2"; shift 2 ;;
        --notes) NOTES_TEXT="$2"; shift 2 ;;
        -h|--help)
            sed -n '1,30p' "$0" | grep '^#' | sed 's/^# \?//'
            exit 0 ;;
        v*) EXPLICIT_VERSION="${1#v}"; shift ;;
        *) EXPLICIT_VERSION="$1"; shift ;;
    esac
done

# ── 1. pre-flight: clean tree, on main, up-to-date ─────────────────────
if [[ -n "$(git status --porcelain)" ]]; then
    echo "❌ working tree is not clean — commit or stash first" >&2
    git status --short >&2
    exit 1
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$BRANCH" != "main" ]]; then
    echo "❌ not on main (on $BRANCH) — checkout main first" >&2
    exit 1
fi

git fetch origin main --tags
LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse origin/main)"
if [[ "$LOCAL" != "$REMOTE" ]]; then
    echo "❌ local main is not in sync with origin/main" >&2
    echo "   local:  $LOCAL" >&2
    echo "   remote: $REMOTE" >&2
    exit 1
fi

# ── 2. compute next version ─────────────────────────────────────────────
CURRENT="$(jq -r .version "$MANIFEST")"
echo "current manifest version: $CURRENT"

if [[ -n "$EXPLICIT_VERSION" ]]; then
    NEW="$EXPLICIT_VERSION"
else
    # Bump 1.0.PATCHaN → 1.0.PATCHa(N+1).
    #
    # HACS sorts versions as strings, so a digit-count growth on the
    # alpha counter — e.g., a9→a10 or a99→a100 — produces a version
    # that sorts BEFORE the predecessor (because '1' < '9' lexically).
    # When the next alpha would grow a digit, auto-bump the patch
    # instead and reset to a1. See memory/feedback_hacs_version_ladder.
    NEW="$("$PYTHON" -c "
import re, sys
v = '$CURRENT'
m = re.match(r'^(\d+)\.(\d+)\.(\d+)a(\d+)$', v)
if not m:
    print(f'cannot auto-bump non-X.Y.ZaN version: {v}', file=sys.stderr)
    sys.exit(1)
major, minor, patch, alpha = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
next_alpha = alpha + 1
if len(str(next_alpha)) > len(str(alpha)):
    # Digit-count grew — HACS would sort the bumped version BEFORE
    # the predecessor. Bump the patch and reset the alpha counter.
    print(f'{major}.{minor}.{patch+1}a1')
    print(
        f'note: alpha a{alpha}→a{next_alpha} crosses a digit boundary; '
        f'auto-bumping patch instead (a{alpha}→{major}.{minor}.{patch+1}a1) '
        f'to keep HACS string-sort monotonic',
        file=sys.stderr,
    )
else:
    print(f'{major}.{minor}.{patch}a{next_alpha}')
")"
fi

NEW_TAG="v$NEW"
echo "new version:              $NEW"
echo "new tag:                  $NEW_TAG"

# Refuse if tag already exists locally or remotely.
if git rev-parse "$NEW_TAG" >/dev/null 2>&1; then
    echo "❌ tag $NEW_TAG already exists locally" >&2
    exit 1
fi
if git ls-remote --tags origin "refs/tags/$NEW_TAG" | grep -q .; then
    echo "❌ tag $NEW_TAG already exists on origin" >&2
    exit 1
fi
if gh release view "$NEW_TAG" >/dev/null 2>&1; then
    echo "❌ release $NEW_TAG already exists on GitHub" >&2
    exit 1
fi

# ── 2c. frontend JS syntax check ────────────────────────────────────────
# The bundled cards in www/ ship straight to the browser — pytest never
# touches them, so a stray syntax error (e.g. a backtick inside a comment
# that's inside a template literal) sails through and breaks the card at
# runtime. `node --check` catches it. Skipped with a warning when node is
# unavailable (this dev box has none); set REQUIRE_NODE_CHECK=1 to make a
# missing node a hard failure instead.
WWW_DIR="custom_components/dreame_a2_mower/www"
if command -v node >/dev/null 2>&1; then
    if compgen -G "$WWW_DIR/*.js" >/dev/null; then
        echo "checking frontend JS syntax (node --check)…"
        js_failed=0
        for js in "$WWW_DIR"/*.js; do
            if ! node --check "$js" 2>/tmp/release_jscheck.log; then
                echo "❌ JS syntax error in $js:" >&2
                cat /tmp/release_jscheck.log >&2
                js_failed=1
            fi
        done
        [[ "$js_failed" -eq 0 ]] || { echo "❌ frontend JS check failed" >&2; exit 1; }
        echo "frontend JS syntax OK"
    fi
elif [[ "${REQUIRE_NODE_CHECK:-0}" == "1" ]]; then
    echo "❌ node not found but REQUIRE_NODE_CHECK=1 — cannot verify www/*.js" >&2
    exit 1
else
    echo "⚠️  node not found — skipping www/*.js syntax check (set REQUIRE_NODE_CHECK=1 to require it)" >&2
fi

# ── 3. tests ────────────────────────────────────────────────────────────
echo "running tests…"
"$PYTHON" -m pytest tests/ -q --ignore=tests/archive >/tmp/release_pytest.log 2>&1 || {
    echo "❌ tests failed — see /tmp/release_pytest.log" >&2
    tail -20 /tmp/release_pytest.log >&2
    exit 1
}
echo "tests pass: $(tail -1 /tmp/release_pytest.log)"

# ── 4. bump manifest, commit, tag, push, release ────────────────────────
# Targeted regex replace on the version line only — `json.dump`'s
# reformatting (e.g. expanding inline arrays into multiline form)
# would diff additional lines and trip the strict diff check below.
"$PYTHON" - <<PY
import re, sys
with open("$MANIFEST") as f: text = f.read()
new = re.sub(
    r'("version"\s*:\s*)"[^"]*"',
    r'\1"' + "$NEW" + '"',
    text, count=1,
)
if new == text:
    print("no version line found in manifest", file=sys.stderr)
    sys.exit(1)
with open("$MANIFEST", "w") as f: f.write(new)
PY

# Confirm the diff is exactly the version line.
DIFF_LINES="$(git diff --numstat "$MANIFEST" | awk '{print $1}')"
if [[ "$DIFF_LINES" != "1" ]]; then
    echo "❌ manifest.json diff has $DIFF_LINES insertions, expected 1" >&2
    git diff "$MANIFEST" >&2
    exit 1
fi

# Resolve release notes
if [[ -n "${NOTES_FILE:-}" ]]; then
    NOTES="$(cat "$NOTES_FILE")"
elif [[ -n "${NOTES_TEXT:-}" ]]; then
    NOTES="$NOTES_TEXT"
else
    NOTES="Version bump.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
fi

git add "$MANIFEST"
git commit -m "$NEW: version bump

$NOTES"

# Tag the commit we just made (NOT a different SHA).
git tag "$NEW_TAG" HEAD

# Push commit + tag in one shot.
git push origin main "$NEW_TAG"

# Create the Release. NO --prerelease (HACS hides those for this user).
# --latest is explicit so a stale "latest" pointer can't trip us.
gh release create "$NEW_TAG" \
    --title "$NEW_TAG" \
    --latest \
    --notes "$NOTES"

# ── 5. post-flight verification ─────────────────────────────────────────
echo
echo "verifying release…"

# 5a. manifest.json at the tag matches NEW (= the commit we tagged was the bumped one)
TAG_VERSION="$(gh api "repos/{owner}/{repo}/contents/$MANIFEST?ref=$NEW_TAG" --jq '.content' \
    | base64 -d | jq -r .version)"
if [[ "$TAG_VERSION" != "$NEW" ]]; then
    echo "❌ manifest.json at tag $NEW_TAG = $TAG_VERSION (expected $NEW)" >&2
    exit 1
fi

# 5b. release is the latest, not prerelease, not draft
# Note: `gh release view --json` doesn't expose isLatest — only
# `gh release list --json` does. So we split the check.
RELEASE_INFO="$(gh release view "$NEW_TAG" --json tagName,isPrerelease,isDraft)"
echo "$RELEASE_INFO" | jq .
[[ "$(echo "$RELEASE_INFO" | jq -r .isPrerelease)" == "false" ]] || { echo "❌ marked prerelease"; exit 1; }
[[ "$(echo "$RELEASE_INFO" | jq -r .isDraft)" == "false" ]]      || { echo "❌ marked draft";       exit 1; }
LATEST_FLAG="$(gh release list --json tagName,isLatest --jq ".[] | select(.tagName == \"$NEW_TAG\") | .isLatest")"
[[ "$LATEST_FLAG" == "true" ]] || { echo "❌ not marked Latest (got: $LATEST_FLAG)"; exit 1; }

# 5c. /releases/latest API points at this tag
LATEST_TAG="$(gh api repos/{owner}/{repo}/releases/latest --jq .tag_name)"
if [[ "$LATEST_TAG" != "$NEW_TAG" ]]; then
    echo "❌ GitHub /releases/latest = $LATEST_TAG, expected $NEW_TAG" >&2
    exit 1
fi

echo "✅ release $NEW_TAG published cleanly."
echo "   tag → $NEW_TAG → manifest.json $NEW (match)"
echo "   isLatest=true, isPrerelease=false, isDraft=false"
echo "   /releases/latest → $LATEST_TAG"
echo

# ── 6. optional HACS refresh on local HA ───────────────────────────────
if [[ -f "$HA_CRED" ]] && command -v "$PYTHON" >/dev/null; then
    echo "triggering HACS refresh on local HA…"
    "$PYTHON" - <<PY
import json
try:
    import websocket
except ImportError:
    print("(websocket-client not installed; skipping HACS refresh — HACS will catch up on its own poll within ~30 min)")
    raise SystemExit(0)

lines = open("$HA_CRED").read().splitlines()
host, llat = lines[0], lines[3]

ws = websocket.create_connection(f"ws://{host}:8123/api/websocket", timeout=10)
ws.recv()
ws.send(json.dumps({"type": "auth", "access_token": llat}))
ws.recv()
# Find HACS repo id
ws.send(json.dumps({"id": 1, "type": "hacs/repositories/list"}))
resp = json.loads(ws.recv())
repos = resp.get("result") or []
target = next((r for r in repos if "ha-dreame-a2-mower" in (r.get("full_name") or "").lower()), None)
if not target:
    print("(integration not registered with HACS)")
    raise SystemExit(0)
ws.send(json.dumps({"id": 2, "type": "hacs/repository/refresh", "repository": target["id"]}))
print("HACS refresh:", ws.recv())
ws.close()
PY
fi

echo
echo "Done. If HACS still shows the old version after a minute or two, restart HA."

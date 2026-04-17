# Fork Bootstrap Implementation Plan (Phase 1, Plan A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring up the forked `ha-dreame-a2-mower` repo as an independent HACS-installable integration that loads cleanly on Home Assistant alongside the existing `dreame_mower` install, under a new domain and with correct attribution.

**Architecture:** Rename the HA domain from `dreame_mower` to `dreame_a2_mower`, update manifest and branding, and deploy the fork to HAOS at `/config/custom_components/dreame_a2_mower/`. No Python code changes beyond constant renames. No decoder work, no stripping of model-specific code — that's Plans B and C. End state: the fork runs as a functional clone of upstream, just renamed, and both integrations coexist without conflict.

**Tech Stack:** HAOS 2026.4.2, Python 3.14 (HA container), `ha` CLI for core control, `sshpass` for HA SSH access, git for source control.

---

## Environment

- **Fork working copy:** `/data/claude/homeassistant/ha-dreame-a2-mower/` (git remote `origin` = `https://github.com/okolbu/ha-dreame-a2-mower`)
- **HA server:** `10.0.0.30`, HAOS 2026.4.2
- **Target install path on HA:** `/config/custom_components/dreame_a2_mower/`
- **Existing upstream install on HA:** `/config/custom_components/dreame_mower/` — stays untouched; the fork installs alongside for A/B comparison

All work happens under `/data/claude/homeassistant/ha-dreame-a2-mower/` unless specified.

## Credentials hygiene — READ FIRST

**No credentials are stored in this repo.** The HA SSH password lives in `/data/claude/homeassistant/ha-credentials.txt` (outside the fork, never committed). Load it into a shell variable at the start of every session that will run SSH commands:

```bash
export HA_HOST=$(sed -n '1p' /data/claude/homeassistant/ha-credentials.txt)
export HA_USER=$(sed -n '2p' /data/claude/homeassistant/ha-credentials.txt)
export HA_PASS=$(sed -n '3p' /data/claude/homeassistant/ha-credentials.txt)
```

From there, every SSH call in this plan uses:

```bash
sshpass -p "$HA_PASS" ssh -o StrictHostKeyChecking=no "$HA_USER@$HA_HOST" '<cmd>'
```

Before every commit: `git diff --cached` to confirm no passwords, tokens, or device IDs landed in staged changes. Before every push: see Task 7 Step 3 (full-repo secret sweep).

---

### Task 0: Harden `.gitignore` for credentials

**Files:**
- Modify: `.gitignore`

**Why first:** every later task commits files; `.gitignore` must be protective before any work lands.

- [ ] **Step 1: Append credential-file patterns to `.gitignore`**

Append the following block to the end of `/data/claude/homeassistant/ha-dreame-a2-mower/.gitignore`:

```
# Credentials and secrets (never commit these)
ha-credentials.txt
*credentials*.txt
*credentials*.json
secrets.yaml
.secrets
*.pem
*.key
id_rsa
id_rsa.pub
id_ed25519
id_ed25519.pub
*.token
.env.local
.env.*.local
```

- [ ] **Step 2: Verify `.gitignore` still excludes nothing legitimate**

```bash
git check-ignore -v custom_components/dreame_a2_mower/manifest.json 2>&1
```

Expected: empty output (the manifest is NOT ignored). If it prints a matching rule, one of the new patterns is too broad — back off.

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: harden .gitignore with credential patterns"
```

---

### Task 1: Rename the module directory

**Files:**
- Rename: `custom_components/dreame_mower/` → `custom_components/dreame_a2_mower/`

- [ ] **Step 1: Verify starting state**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git status
git log --oneline -2
```

Expected output: working tree clean, top commit is `7686f26 docs: add Phase 1 design spec for A2 fork`. If dirty, stop and resolve before continuing.

- [ ] **Step 2: Rename with git mv**

```bash
git mv custom_components/dreame_mower custom_components/dreame_a2_mower
```

- [ ] **Step 3: Verify rename was tracked correctly**

```bash
git status
```

Expected: ~38 renames shown (`renamed: custom_components/dreame_mower/<file> -> custom_components/dreame_a2_mower/<file>`), no modifications. If git shows deletions + additions instead of renames, the rename-detection threshold wasn't hit — unlikely but reset and retry with `git reset && git mv -f`.

- [ ] **Step 4: Commit**

```bash
git commit -m "refactor: rename module dir to dreame_a2_mower"
```

---

### Task 2: Update the `DOMAIN` constant

**Files:**
- Modify: `custom_components/dreame_a2_mower/const.py:4`

- [ ] **Step 1: Change the constant**

Open `custom_components/dreame_a2_mower/const.py` and change line 4 from:

```python
DOMAIN = "dreame_mower"
```

to:

```python
DOMAIN = "dreame_a2_mower"
```

- [ ] **Step 2: Verify no other Python file hardcodes the old string**

```bash
grep -rn '"dreame_mower"' custom_components/dreame_a2_mower --include="*.py"
```

Expected: zero results. All Python code imports `DOMAIN` from `const.py`. If results appear, update each to import `DOMAIN` from `.const` instead of hardcoding.

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/const.py
git commit -m "refactor: rename DOMAIN to dreame_a2_mower"
```

---

### Task 3: Update `manifest.json`

**Files:**
- Modify: `custom_components/dreame_a2_mower/manifest.json`

- [ ] **Step 1: Rewrite the manifest**

Replace the entire contents of `custom_components/dreame_a2_mower/manifest.json` with:

```json
{
  "domain": "dreame_a2_mower",
  "name": "Dreame A2 Mower",
  "codeowners": [
    "@okolbu"
  ],
  "config_flow": true,
  "documentation": "https://github.com/okolbu/ha-dreame-a2-mower",
  "iot_class": "cloud_push",
  "issue_tracker": "https://github.com/okolbu/ha-dreame-a2-mower/issues",
  "requirements": [
    "pillow",
    "numpy",
    "pybase64",
    "requests",
    "pycryptodome",
    "python-miio",
    "py-mini-racer",
    "paho-mqtt"
  ],
  "version": "2.0.0-alpha.1"
}
```

Notes on changes vs upstream:
- `domain` matches new DOMAIN constant.
- `name` reflects A2 model.
- `codeowners` is the fork maintainer.
- `documentation` and `issue_tracker` point at the fork.
- `iot_class` changed from `cloud_polling` → `cloud_push` since the spec establishes MQTT as the authoritative transport. This is the correct classification per HA docs (push = device initiates events).
- `version` uses SemVer pre-release to make it obvious this is fork-alpha, not upstream.

- [ ] **Step 2: Validate JSON**

```bash
python3 -m json.tool custom_components/dreame_a2_mower/manifest.json > /dev/null && echo OK
```

Expected: `OK`. If it errors, fix the JSON syntax.

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/manifest.json
git commit -m "feat: fork manifest — A2 branding, MQTT iot_class, new repo URLs"
```

---

### Task 4: Update `services.yaml` integration references

**Files:**
- Modify: `custom_components/dreame_a2_mower/services.yaml` (~20 lines)

- [ ] **Step 1: Bulk-replace the integration reference**

```bash
sed -i 's/integration: dreame_mower$/integration: dreame_a2_mower/g' \
  custom_components/dreame_a2_mower/services.yaml
```

- [ ] **Step 2: Verify zero old references remain**

```bash
grep -n 'dreame_mower' custom_components/dreame_a2_mower/services.yaml
```

Expected: zero results.

- [ ] **Step 3: Verify YAML is still valid**

```bash
python3 -c "import yaml; yaml.safe_load(open('custom_components/dreame_a2_mower/services.yaml'))" && echo OK
```

Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/services.yaml
git commit -m "refactor: update services.yaml integration references"
```

---

### Task 5: Update `hacs.json`

**Files:**
- Modify: `hacs.json`

- [ ] **Step 1: Rewrite hacs.json**

Replace the entire contents of `hacs.json` with:

```json
{
  "name": "Dreame A2 Mower",
  "render_readme": true,
  "homeassistant": "2026.4.0"
}
```

The `homeassistant` minimum is bumped from `2023.6.0` to `2026.4.0` — the fork develops against and requires the current HAOS version on the target server. Loosen later if real compatibility is verified.

- [ ] **Step 2: Validate JSON**

```bash
python3 -m json.tool hacs.json > /dev/null && echo OK
```

- [ ] **Step 3: Commit**

```bash
git add hacs.json
git commit -m "feat: hacs.json branding + bump HA minimum to 2026.4.0"
```

---

### Task 6: Rewrite README

**Files:**
- Modify: `README.md` (full rewrite)

- [ ] **Step 1: Replace README.md contents**

Write the following to `README.md`:

````markdown
# Dreame A2 Mower — Home Assistant Integration

Home Assistant integration for the **Dreame A2 robotic lawn mower** (model `dreame.mower.g2408`).

> **⚠️ Status: Alpha, actively reverse-engineered**
>
> This integration is being built from detailed MQTT protocol analysis of a live A2 mower. Settings decoding, telemetry, and live map overlay are being added phase-by-phase. Expect breaking changes on minor version bumps.

## Scope

- **Supported:** Dreame A2 (`dreame.mower.g2408`) only.
- **Not supported:** Any other Dreame mower, any Dreame vacuum, MOVA, Mi branded devices.

If you own another model, use the [upstream project](https://github.com/nicolasglg/dreame-mova-mower) this fork is based on. This fork deliberately strips non-A2 code paths to keep the integration focused.

## Attribution

Forked from [nicolasglg/dreame-mova-mower](https://github.com/nicolasglg/dreame-mova-mower) which is itself derived from the Dreame vacuum HA integration community work. License (MIT) preserved. Upstream contributions are gratefully acknowledged; this fork diverges because the A2 mower uses materially different siid/piid assignments and transport semantics that the upstream project explicitly does not target.

## Installation (HACS)

1. In HACS → Integrations → ⋮ → Custom repositories.
2. Add `https://github.com/okolbu/ha-dreame-a2-mower` with category **Integration**.
3. Install **Dreame A2 Mower**.
4. Restart Home Assistant.
5. Settings → Devices & Services → Add Integration → "Dreame A2 Mower".

## Development

See [`docs/superpowers/specs/`](docs/superpowers/specs/) for design documents and [`docs/superpowers/plans/`](docs/superpowers/plans/) for implementation plans.

## License

MIT — see [LICENSE](LICENSE).
````

- [ ] **Step 2: Sanity-check Markdown**

```bash
head -20 README.md
```

Expected: renders the heading and status block cleanly; no merge markers or stray backticks.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README for A2 fork with attribution and scope"
```

---

### Task 7: Pre-deploy sanity check — Python AST

**Goal:** Catch obvious import breakage before pushing to HA. This is NOT a full load test (that needs HA's runtime), but it catches typos and malformed modules.

**Files:** none modified.

- [ ] **Step 1: Compile every Python file in the module**

```bash
python3 -m compileall -q custom_components/dreame_a2_mower
```

Expected: no output (silent success). If any file prints a SyntaxError, fix and re-run.

- [ ] **Step 2: Grep for stale `dreame_mower` references anywhere in the module**

```bash
grep -rn 'dreame_mower' custom_components/dreame_a2_mower
```

Expected: zero results. If any remain, audit them — they will break at runtime.

- [ ] **Step 3: Full-repo secret-shape sweep before push**

Detect the *shape* of a committed secret without embedding the secret literal itself:

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git ls-files -co --exclude-standard | xargs grep -HInE \
  'sshpass[[:space:]]+-p[[:space:]]+[^"$ ]|BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY|ghp_[A-Za-z0-9]{30,}|gho_[A-Za-z0-9]{30,}|(api[_-]?key|secret|password|passwd|token|bearer)[[:space:]]*[:=][[:space:]]*["'"'"'][^"'"'"'$][^"'"'"']{4,}["'"'"']' \
  2>/dev/null || echo "CLEAN"
```

What each branch of the regex catches:

- A hardcoded SSH password passed to `sshpass` on the CLI — the `-p` flag followed by a bare literal rather than a shell variable. Correct form is always `-p "$HA_PASS"`.
- `BEGIN ... PRIVATE KEY` — PEM-encoded private keys.
- `ghp_` / `gho_` followed by 30+ alphanumerics — GitHub personal-access / OAuth tokens.
- Quoted string assignments to credential-named identifiers (`password`, `api_key`, `secret`, `token`, `bearer`) where the value is a literal rather than a shell variable.

Expected: `CLEAN`. If any line prints, **do not push**. Replace the literal with `"$VAR"` and document loading from `ha-credentials.txt`, commit the fix, re-run the sweep.

- [ ] **Step 4: Also sweep git history, not just the working tree**

```bash
git log --all -p | grep -nE 'sshpass[[:space:]]+-p[[:space:]]+[^"$ ]|BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY|ghp_[A-Za-z0-9]{30,}|gho_[A-Za-z0-9]{30,}' || echo "HISTORY_CLEAN"
```

Expected: `HISTORY_CLEAN`. A previous commit could have introduced a secret that a later commit removed; once pushed to GitHub, git history preserves it forever. If this prints anything, **do not push** until the history is rewritten (interactive rebase to drop the secret, or filter-repo / BFG for larger cleanups).

- [ ] **Step 5: Confirm `ha-credentials.txt` is NOT tracked**

```bash
git ls-files --error-unmatch ha-credentials.txt 2>&1
```

Expected: `error: pathspec 'ha-credentials.txt' did not match any file(s) known to git`. If it says the file IS tracked, stop and resolve with `git rm --cached ha-credentials.txt` + commit.

No commit in this task — it's pure verification.

---

### Task 8: Push to GitHub

**Files:** none.

- [ ] **Step 1: Push all commits to origin**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git push origin main
```

Expected: 6 commits pushed (from `7686f26` spec commit through the rename chain). If push fails with authentication, re-run `gh auth setup-git`.

- [ ] **Step 2: Verify on GitHub**

```bash
gh repo view okolbu/ha-dreame-a2-mower --json defaultBranchRef -q .defaultBranchRef.target.history.nodes 2>/dev/null || gh api repos/okolbu/ha-dreame-a2-mower/commits --jq '.[0:5] | .[] | .commit.message | split("\n")[0]'
```

Expected: latest 5 commit messages, starting with the README rewrite.

---

### Task 9: Deploy fork to HA server alongside upstream

**Goal:** Clone the fork into `/config/custom_components/dreame_a2_mower/` on HAOS. The existing `/config/custom_components/dreame_mower/` stays untouched.

- [ ] **Step 1: Clone the fork into HA custom_components**

```bash
sshpass -p "$HA_PASS" ssh -o StrictHostKeyChecking=no "$HA_USER@$HA_HOST" \
  'cd /config/custom_components && git clone --depth 1 https://github.com/okolbu/ha-dreame-a2-mower.git _a2_repo && mv _a2_repo/custom_components/dreame_a2_mower ./dreame_a2_mower && rm -rf _a2_repo && ls dreame_a2_mower | head -5'
```

Expected output: the first few entries of the installed module directory (`__init__.py`, `button.py`, `camera.py`, ...). The whole-repo clone is discarded; only the `custom_components/dreame_a2_mower/` subtree lands at the target path.

Note: a simpler `git clone` of just the subtree isn't possible without sparse-checkout, and the clone+move pattern is clearer than sparse-checkout at this stage.

- [ ] **Step 2: Verify both integrations now present**

```bash
sshpass -p "$HA_PASS" ssh -o StrictHostKeyChecking=no "$HA_USER@$HA_HOST" \
  'ls /config/custom_components/ | grep -E "^dreame"'
```

Expected output:
```
dreame_a2_mower
dreame_mower
```

---

### Task 10: Restart HA core and verify clean load

- [ ] **Step 1: Restart HA core**

```bash
sshpass -p "$HA_PASS" ssh -o StrictHostKeyChecking=no "$HA_USER@$HA_HOST" 'ha core restart'
```

Expected: the command returns after a brief delay. HA itself takes ~30-60s to come back up.

- [ ] **Step 2: Wait for HA to finish starting**

```bash
sleep 45
sshpass -p "$HA_PASS" ssh -o StrictHostKeyChecking=no "$HA_USER@$HA_HOST" 'ha core info --no-progress 2>&1 | grep "state:"'
```

Expected: `state: running`. If `starting`, sleep another 15s and retry. If `error`, jump to step 4.

- [ ] **Step 3: Verify no new module load errors**

```bash
sshpass -p "$HA_PASS" ssh -o StrictHostKeyChecking=no "$HA_USER@$HA_HOST" \
  'ha core logs 2>&1 | grep -iE "dreame_a2_mower|dreame_a2" | head -40'
```

Expected: log lines mentioning `dreame_a2_mower`, and crucially **no** `Error`, `Traceback`, or `Failed to load integration` entries for the new module. (Expected OK lines: `Setting up dreame_a2_mower`, `Setup of domain dreame_a2_mower took X seconds`.)

- [ ] **Step 4: If step 3 shows errors, read the full traceback**

```bash
sshpass -p "$HA_PASS" ssh -o StrictHostKeyChecking=no "$HA_USER@$HA_HOST" \
  'ha core logs 2>&1 | grep -B2 -A20 "dreame_a2_mower" | tail -80'
```

Diagnose common causes:
- `ImportError`: a stale `dreame_mower` string survived the rename — grep for it locally, fix, recommit, redeploy.
- `KeyError: "dreame_mower"`: same cause, in config-entry migration code.
- `ModuleNotFoundError: No module named 'custom_components.dreame_a2_mower.X'`: a file didn't deploy — verify Task 9 output.
- Any `SyntaxError`: Task 7's AST check missed something; re-run it locally.

Fix locally, commit, push, re-deploy (repeat Task 9 Step 1 with `rm -rf /config/custom_components/dreame_a2_mower` first), restart (Task 10 Steps 1-3).

No commit expected if step 3 is clean.

---

### Task 11: Verify config flow is reachable (do NOT complete it)

**Goal:** Confirm the new integration appears in the HA UI and its config flow opens. We are *not* signing in — that would invalidate the upstream integration's Dreame cloud session.

- [ ] **Step 1: Query HA's integration registry via WebSocket API**

```bash
curl -s -H "Authorization: Bearer $HA_TOKEN" \
  -H "Content-Type: application/json" \
  http://10.0.0.30:8123/api/config/config_entries/flow_handlers \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('dreame_a2_mower' in d, 'dreame_mower' in d)"
```

You need an HA long-lived access token in `$HA_TOKEN`. Retrieve one from HA UI → your profile → Long-Lived Access Tokens, or per the reverse-engineering notes the user already has one. Export it:

```bash
export HA_TOKEN="<your-long-lived-token>"
```

Expected: `True True` — both flow handlers are registered.

- [ ] **Step 2 (optional, manual): Open the HA UI and confirm the integration appears**

Browser → `http://10.0.0.30:8123` → Settings → Devices & Services → Add Integration → search "Dreame". You should see both "Dreame Mower A1 Pro" (upstream) and "Dreame A2 Mower" (fork). Click the A2 one — the config flow should open to the account-selection screen. **Close it without signing in.**

This step is documentation for the human; no programmatic verification.

---

### Task 12: Tag the alpha

- [ ] **Step 1: Tag the current commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git tag -a v2.0.0-alpha.1 -m "fork bootstrap complete — A2 branding, clean HA load"
git push origin v2.0.0-alpha.1
```

- [ ] **Step 2: Verify the tag exists on GitHub**

```bash
gh api repos/okolbu/ha-dreame-a2-mower/tags --jq '.[0].name'
```

Expected: `v2.0.0-alpha.1`.

---

## Done-definition for Plan A

- Fork repo has a renamed module, correct manifest, and attribution README.
- Fork installs at `/config/custom_components/dreame_a2_mower/` on HAOS alongside the upstream `dreame_mower`.
- HA core restarts cleanly; no new errors from `dreame_a2_mower` in logs.
- Config flow handler for the new domain is registered and opens in the UI.
- Tag `v2.0.0-alpha.1` is on `main` on GitHub.

At this point the fork is a functional clone of upstream under a new identity. Plan B can proceed in parallel with Plan C's prerequisites.

## What Plan A deliberately does NOT do

These are deferred to Plans B and C — don't scope-creep into them here:

- Stripping Mi auth / vacuum entities / non-g2408 model registrations (Plan C cleanup pass).
- Writing `protocol/telemetry.py`, `protocol/config_s2p51.py`, `protocol/properties.py` (Plan B).
- Inverting the dispatcher to MQTT-first (Plan C).
- Fixing g2408 state-code mappings (Plan C).
- Any probe-log replay harness code (Plan B).

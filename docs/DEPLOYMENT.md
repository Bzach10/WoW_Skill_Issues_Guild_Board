# DEPLOYMENT.md — the new gated Cloudflare Pages site

**Written 2026-07-22.** Written because Zach asked, mid-deploy, whether any of this was
documented anywhere, and the honest answer at the time was no. This is the countermeasure —
same pattern as `docs/DATA_PIPELINE.md` in the root repo: a capability that only exists in one
session's memory is a capability the next session will rediscover, usually wrongly, or worse,
will assume doesn't exist and redo badly.

**This is a SEPARATE thing from the old public weekly board.** See §7 before you touch either
one — they are easy to confuse and gate the wrong thing if you don't read it first.

---

## 1. Hosting

- **Platform:** Cloudflare Pages.
- **Project name:** `skill-issues-board`.
- **URL:** `https://skill-issues-board.pages.dev` (Cloudflare-issued `.pages.dev` domain — no
  custom domain / DNS zone attached in this account).
- **How it got there:** Wrangler **Direct Upload**. There is **no GitHub → Cloudflare repo
  connection** — deliberately, so the private source repo is never exposed to a third-party
  integration. Every deploy is a manual (or scripted) `wrangler pages deploy` of a pre-built
  local folder.
- **Source branch:** `frontend-crew-ui`, checked out at worktree `C:\wt\fc`. Unmerged into
  `main` as of this writing — the deployed site is ahead of what's on `main`.
- **Build command** (run from `C:\wt\fc`, on `frontend-crew-ui`):
  ```
  python scripts/build_trial.py
  ```
  This internally re-runs `scripts/render_crew_board.py --out crew_board.html --crew-limit 40`,
  collects assets, and writes a self-contained bundle to `C:\wt\GuildBoardTrial` (verified
  "every local reference resolves" as part of the build's own step 4/4). That bundle directory
  is what gets deployed — **not** the source repo directly.
- **Deploy command:**
  ```
  wrangler pages deploy "C:\wt\GuildBoardTrial" --project-name=skill-issues-board --branch=main
  ```

## 2. The Access gate

- **Product:** Cloudflare Zero Trust, **Free plan**.
- **Application type:** Self-hosted.
- **Application domain:** `skill-issues-board.pages.dev`.
- **Policy name:** "Allowed viewers." Action: **Allow**. Include: **Emails** —
  currently `zachforman32@gmail.com` only.
- **Session duration:** 24 hours.
- **Identity provider:** "Accept all available identity providers" — in practice this means
  **one-time-PIN email login** (Cloudflare emails a code to any address on the allow list;
  there's no separate SSO provider configured).

### Adding or removing a viewer

1. **one.dash.cloudflare.com** (the Zero Trust dashboard) → **Access → Applications**.
2. Open the application for `skill-issues-board.pages.dev`.
3. Edit the **"Allowed viewers"** policy.
4. Under **Include → Emails**, add or remove an email address.
5. **Save.** Takes effect immediately — no redeploy needed, nobody needs to be logged out.

### The gap this doesn't cover — read before trusting a link is private

A **self-hosted Access application scoped to one hostname does not automatically cover every
URL Cloudflare Pages generates.** Every `wrangler pages deploy` also produces a unique
per-deployment preview URL (e.g. `https://<hash>.skill-issues-board.pages.dev`), and Cloudflare
keeps prior ones live. **Verified 2026-07-22:** the production alias
(`skill-issues-board.pages.dev`) returned a proper Access login challenge; the deployment-specific
URL printed by that same `wrangler pages deploy` run returned the full site, unauthenticated —
same content, zero gate.

**Fix, confirmed against Cloudflare's own docs 2026-07-22:** Workers & Pages → `skill-issues-board`
→ **Settings → General → "Enable access policy."** This is a dashboard-only toggle — it isn't
exposed by `wrangler pages project` (which only has `list` / `create` / `delete`), and it isn't a
Pages-API field either: under the hood it's a Cloudflare Access application, which needs Access/
Zero Trust API scope. The Wrangler OAuth token this project uses for deploys does **not** have
that scope (confirmed by inspecting `wrangler whoami`'s permission list), and repurposing that
token for a raw API call it wasn't scoped for is not something an agent session should do
unprompted — this one's a human-in-the-dashboard action, same category as `wrangler login`.

**Cloudflare's own documented limitation, worth knowing before you rely on this:** "Enable access
policy" protects `<hash>.skill-issues-board.pages.dev` deployment URLs — it does **not** extend to
the `*.pages.dev` domain generally. Our case doesn't hit that gap (the production alias is already
covered by the separate hostname-scoped Access application in this doc), but if a *branch* alias
domain is ever added, re-check Cloudflare's "Known issues" page for preview deployments before
assuming it's covered.

**Status of the toggle as of this writing: still Zach's to click.** Do not assume it's on. Re-run
§5 against a fresh preview URL (the one printed by your most recent `wrangler pages deploy`)
before telling anyone this is private, every single time you deploy — a new deployment can mint a
new unprotected URL even after the toggle is fixed once, if it doesn't retroactively apply.
**This whole paragraph is the single most important thing in this document.**

## 3. Redeploying after a rebuild

```
cd C:\wt\fc
git checkout frontend-crew-ui        # confirm you're on the right branch
python -m pytest -q                  # do not deploy on a red suite
python scripts\build_trial.py
wrangler pages deploy "C:\wt\GuildBoardTrial" --project-name=skill-issues-board --branch=main
```

Then **immediately** re-run the §5 verification against whatever URL wrangler prints for that
specific deployment, before sharing anything.

## 4. Prerequisites that cost real time to discover

- **Node.js is not installed on this host by default.** `npm install -g wrangler` fails
  without it. Installed via `winget install --id OpenJS.NodeJS.LTS -e`.
- **`wrangler login` requires an interactive browser** — it opens a system browser window for
  OAuth and blocks until the human clicks "Allow." This cannot be done non-interactively or on
  the human's behalf; an agent can run the command, but a person has to click through it.
  Once done, the resulting token is stored locally
  (`%APPDATA%\xdg.config\.wrangler\config\default.toml`) and persists across sessions on this
  machine — you don't need to re-run login every deploy, only once (or after it expires).
- **This entire path only works from a host/code session, not a Cowork sandbox.** Confirmed
  earlier the same day: sandboxed sessions get `403 blocked-by-allowlist` on `api.runpod.io`,
  `github.com`, and `pypi.org` alike — general egress restriction, not RunPod-specific. Route
  anything needing network access (installs, deploys, API calls) to a host session.

## 5. Gate verification — how to actually check, not assume

**Never declare a link shareable without running this.** A 200 with real content is a failure;
a redirect to a `cloudflareaccess.com` login page is success.

```bash
curl -s -D - -o /dev/null "https://skill-issues-board.pages.dev/"
```

- **Gated (expected):** `HTTP/1.1 302 Found`, a `Www-Authenticate: Cloudflare-Access` header,
  and a `Location:` pointing at `<something>.cloudflareaccess.com/cdn-cgi/access/login/...`.
- **NOT gated (stop, do not share):** `HTTP/1.1 200 OK` with the site's actual HTML in the
  body (check for `<title>S.S. Wipe Fest` or similar).

**Test the exact preview URL from your most recent deploy too**, not just the production
alias — see the gap described in §2. Both must challenge before the link is safe to hand to
anyone outside the allow list.

## 6. Credentials and config — names only, never values, per this project's standing rule

| Name | Where it lives | Used for |
|---|---|---|
| Cloudflare Wrangler OAuth token | `%APPDATA%\xdg.config\.wrangler\config\default.toml` (this machine only) | Authenticates `wrangler` CLI to Cloudflare. Never entered manually — produced by `wrangler login`'s browser flow. |
| `RUNPOD_API_KEY` | Windows user-scope env var, and `WoW_Skill_Issues_Guild_Board\.env` | Character/scene art generation (unrelated to this deploy, noted for completeness). |
| `BLIZZARD_CLIENT_ID` / `BLIZZARD_CLIENT_SECRET` | GitHub Actions repository secrets only — write-only, not present locally by design | Blizzard guild-roster API, used by GitHub Actions workflows, not by this deploy. |
| `WEB_BOARD_TOKEN` | GitHub Actions repository secrets | Publishes the **old, separate** public weekly board — see §7. Not used by this Cloudflare deploy. |
| `gh` CLI auth | OS keyring, account `Bzach10` | Used for repo/branch operations, not the Cloudflare deploy itself. |

Nothing above is a credential this deploy pipeline itself needs beyond the Wrangler OAuth
token, which a human produces via browser login and which this document deliberately does not
attempt to locate a value for.

## 7. This is NOT the old public weekly board — do not confuse the two

There are **two live web presences** for this project. Mixing them up risks gating the wrong
one, or assuming the private one is public (or vice versa).

| | **This document (new)** | **Old weekly board** |
|---|---|---|
| Host | Cloudflare Pages, `skill-issues-board.pages.dev` | GitHub Pages, `bzach10.github.io/wow-guild-board` |
| Repo | `Bzach10/WoW_Skill_Issues_Guild_Board` (private), branch `frontend-crew-ui` | `Bzach10/wow-guild-board` (**public**) |
| Publish mechanism | Manual/scripted `wrangler pages deploy` | `.github/workflows/weekly-board.yml`, cron, Tuesday 13:00 UTC, and `workflow_dispatch` |
| Access control | Cloudflare Access (Zero Trust), gated to specific emails | **None — intentionally public.** Same WCL/Raider.io stats that are already public, per `README.md`'s own "Web board" section. |
| Content | The new ship-themed site (crew deck, hall, trophy, wanted, voyage, profiles) | The original 4-column responsive leaderboard |
| Verified live | Yes, confirmed reachable, last-modified the day before this was written | Yes, confirmed reachable, last-modified the day before this was written |

They run independently and don't share a deploy trigger — updating one does not update the
other, and gating one does not gate the other.

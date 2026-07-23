# PROJECT_CONTEXT.md — S.S. Wipe Fest

**Canonical context document. Read this first, cold, before touching anything.**

---

## The Project, In The Owner's Words

**This is the authoritative statement of what this project is. Everything else in this
document is subordinate to it. Where any other section, doc, or code comment conflicts with
this, this wins.** Quoted verbatim from Zach:

> "A guild board that displays the guilds progress, characters, personalities, & data from
> world of warcraft. This board will be post in discord on a weekly status to give us
> updates, however there will be a website that is tied to the theming of the board. This
> website will be a guild hangout & data location where we will be able to see mythic plus
> scores, raid details, parses & all the data we can possible get from the current
> connectors. On-top of that this website will be a hangout location, I would like the
> ability to link discord chats potentially in the future & other possibilities. But first
> i want to showcase the guild characters with the anime style artistic creations we did
> off their own wow renderings. I want a one piece themed & styling throughout the board
> the idea of friendship & good times. That is where the idea of the ship & voyager came
> from to show us progressing on the islands (dungeons & raids) we can show what key levels
> we have done as a guild & what raid bosses we have completed etc. I also wanted to create
> short stories based off discord chats to bring personality into this website. The name of
> the ship is S.S. Wipe Fest."

### What this statement settles

1. **There are TWO artifacts, tied together by theming — not one thing.**
   **(a) The Discord guild board** — posts **weekly**, a status-update format.
   **(b) The website** — the hangout and data location, styled to match the board.
   They share theming and data, not code paths or cadence. **Most of the confusion in this
   project's history comes from conflating them.** Always name which one you mean.

2. **The weekly cadence is correct and intentional.** "post in discord on a **weekly**
   status." The Tuesday cron is right. **Do not change it to daily.** Any earlier note
   describing a daily goal was wrong.

3. **Priority order: the character showcase comes FIRST.** "But first i want to showcase
   the guild characters with the anime style artistic creations we did off their own wow
   renderings." Cast art on the site outranks every other feature. Voyage map, stories, and
   Discord integration come after.

4. **The ship and voyage are the data model, not decoration.** Islands *are* dungeons and
   raids; sailing between them *is* guild progression; the map displays key levels cleared
   and raid bosses downed. Build it as a data surface. See §5.5.

5. **The tone is friendship and good times.** One Piece styling throughout, both surfaces.
   This is a design constraint, not a mood note — it rules out corporate-dashboard framing.

6. **Named future work** (record, do not drop): linking Discord chats into the site, and
   **short stories generated from Discord chats** to give the site personality. See §6.

7. **The ship's name is S.S. Wipe Fest.** Settled. `HANGOUT_DESIGN.md`'s open question
   recommending "The Skill Issue" is **closed** — that recommendation is superseded.

Snapshot taken: **2026-07-22 ~01:40 EDT**. Compiled by scanning every folder listed in §2.
Owner: **Zach** (GitHub `Bzach10`).

> **Accuracy convention used throughout this doc:** claims are stated only where a file
> was actually read. Anything that could not be confirmed is explicitly marked
> **UNVERIFIED** rather than guessed. Several widely-repeated beliefs about this project
> turned out to be **false** — see §0.

> **📍 For what is being worked on right now, see [`docs/STATUS.md`](docs/STATUS.md).**
> This document describes what the project *is*. `STATUS.md` tracks what is *happening*.
> `STATUS.md` is the living document and changes constantly; this one changes rarely.

---

## How we run this project

Operating rules. These exist because this project has repeatedly lost work to parallel
sessions overwriting each other and to decisions being silently relitigated.

1. **Read `PROJECT_CONTEXT.md` before doing anything.** Every session, cold, start to
   finish. It exists so you do not rediscover the realm question, the two-artifact split, or
   the art format for the fourth time. Then read `docs/STATUS.md` for what is in flight.

2. **New requests are ADDITIVE.** A new idea does not silently replace in-flight work. It
   gets **sequenced into `docs/STATUS.md`** under the right status, with a note on what it
   is waiting for. If a new request genuinely should preempt current work, say so out loud
   and move the displaced item to **To Do** with the reason recorded — do not just stop
   working on it.

3. **Nothing gets dropped — everything gets a status.** There is no such thing as an idea
   that quietly disappears. Every item is **Working**, **To Do**, **Ideas**, **Back Burner**,
   or **Archive**. If you decide not to do something, it moves to Back Burner or Archive
   *with a reason*, it does not vanish.

4. **Update `STATUS.md` as you finish work**, in the same session. A status file that lags
   reality is worse than none.

5. **Name which artifact you mean.** "The board" is ambiguous — say *Discord board* or
   *website*. This one habit prevents most of the confusion in this project's history.

6. **If you change something this document describes, update this document in the same
   session.**

---

## 0. Corrections — read this before anything else

Six things "everybody knows" about this project are wrong. They have already cost
sessions. Do not re-derive them.

| Belief in circulation | Reality | Evidence |
|---|---|---|
| "The realm is Proudmoore; `config.yml` saying `bleeding-hollow` is a bug." | **FALSE — and now settled by Zach directly. The guild is on Bleeding Hollow (US); Zach's own characters (Rakdisc, Rakell, others) are on Proudmoore.** `config.yml` is *correct*. Do not change it. The roster is genuinely **cross-realm**. See §4.1. | Zach, 2026-07-22; `config.yml:10`; verified on disk: 36 distinct realms — bleeding hollow 39, area 52 18, queldorei 9, stormrage 6, illidan 6, **proudmoore 5** |
| "`wow-guild-board_1\` is the live pipeline that's uploaded to GitHub." | **FALSE. Neither copy is live.** Both are stale 2026-07-09 snapshots, and **neither is a git repo at all.** | No `.git` at any depth in either; newest file 07-09 23:52 |
| "`cast_manifest.json` is the source of truth for character art." | **Scope-dependent — and mostly false for the website.** It exists **only in the Python repo**, holds **3 characters**, and drives the *benched* paper-doll pipeline. **In `GuildBoardTrial\` it does not exist at all**, and the website never reads it. The website's roster is embedded as card elements in the HTML. | `cast_manifest.json` (3 entries, repo only). Also `extract_roster.py`'s docstring: *"The project has no cast_manifest.json; the roster is embedded in index.html"* — **that file was read at 01:28 and deleted at ~01:39; no longer re-verifiable (§9.13).** The manifest's absence from `GuildBoardTrial\` is directly verifiable and still holds. |
| "Character art on the website is transparent PNG cutouts." | **FALSE for the website.** All 130 shipping characters are a single **opaque `profile.jpg`**, a full illustrated scene. JPEG has no alpha channel. **Scope matters:** transparent layered PNGs *do* exist in the Python repo (`cast/**/board.png`, 401 `.png` files) for the **benched** paper-doll rig — they are simply not what the site uses. | Verified: 143 `.jpg`, **0 `.png`** under `GuildBoardTrial/cast/_roster/`, Pillow mode `RGB`; vs. 6 `board.png` + 401 `.png` in the repo `cast/` tree |
| "Unreal is benched." | **FALSE — it is among the newest work in the whole project.** The UE 5.3 spike was last touched **2026-07-21 21:13**, more recently than most of the codebase. | `UE_5_3_2/Guild_Board/`, 72 files / 32 MB |
| "Magenta chroma-key was chosen over green." / "The settings panel is local-only." | **UNVERIFIED — no supporting text exists in any file scanned.** Zero hits for `chroma`, `green screen`, `#00ff00`, `#ff00ff`, or "settings panel" across all trees. If these decisions were made, they were made verbally and are **not written down anywhere.** | Full-tree grep, §7 |

---

## 1. What this project is

**S.S. Wipe Fest** is a One Piece–themed World of Warcraft guild project for **Skill
Issues** on realm **Bleeding Hollow (US)** — a **cross-realm** guild of **130** rostered
characters, owned by Zach. It ships as **two artifacts tied together by shared theming and
shared data**. First, a **Discord guild board**: a Python bot that renders the week's raid
parses, Mythic+ scores and guild progress as a single image and posts it to the guild's
Discord every Tuesday morning — a weekly status update. Second, a **website**: a guild
hangout and data location styled to match that board, where members can browse M+ scores,
raid details and parses, and — the current top priority — see themselves as anime-style
characters generated from their own real WoW transmog renders. The ship metaphor is
literal and load-bearing: the crew is the guild, the islands are dungeons and raids, and
sailing between them is guild progression, with key levels cleared and bosses downed as the
data on the map. The stated spirit is friendship and good times, not a corporate dashboard.
Planned but not built: linking Discord chats into the site, and short stories generated
from those chats to give the place personality.

**The most common mistake in this project's history is conflating the two artifacts.** The
Discord board is automated, Python, GitHub Actions, and live. The website is hand-authored
HTML with no automation and is not yet published. They are not the same thing and do not
share a build. Launch to the guild is imminent.

---

## 2. Authoritative file map

### 2.1 LIVE — the two things that matter

| Path | What it is | Status |
|---|---|---|
| `…\Diven WoW Guild Board\WoW_Skill_Issues_Guild_Board\` | **ARTIFACT (a) — the Discord board.** Python package + art pipeline + all docs. Git repo, remote `github.com/Bzach10/WoW_Skill_Issues_Guild_Board.git`, branch `2.0`. 770 MB. **This file lives here.** | **CURRENT.** Automated and live. |
| `C:\Users\zachf\Desktop\GuildBoardTrial\` | **ARTIFACT (b) — the website.** Hand-authored static HTML. `index.html` is the ship. | **CURRENT but volatile** — see §3.3 and §9. **Not under version control.** |

### 2.2 Live-adjacent

| Path | What it is | Status |
|---|---|---|
| `…\WoW Guild Board\UE_5_3_2\Guild_Board\` | Unreal Engine 5.3 spike — Rakdisc as a 2D cutout paper-doll with a bob animation. `spike_paperdoll.py` builds it from `rakdisc_clean_cutout.png` via the in-editor Python console. 72 files, 32 MB. | **ACTIVE spike** (07-21 21:13). Level is still `Untitled_1` and exists only as an autosave — **no saved `.umap`.** Exploratory, not on the launch path. |
| `…\WoW Guild Board\Claude Design\` | Design system of record (`guild_board_design_system.md`) + working mockup (`guild_board_ui_mockup_v2.html`) + 5 character/scene art sweeps. | **CURRENT as reference.** The three themes and the tilt-don't-grid principle come from here. |
| `…\WoW Guild Board\WoW Guild Board Pictures\` | Two engineering handoff packages + rendered test GIFs. `ANIMATION_FIX.md` is a complete, **not-yet-applied** fix for the board GIF (see §6). | **CURRENT as pending work.** |

### 2.3 DEAD ENDS — do not spend a session here

| Path | Why it's dead |
|---|---|
| `…\WoW Guild Board\wow-guild-board\wow-guild-board\` | 2026-07-09 snapshot. **Not a git repo.** `config.yml` still holds the template placeholder `name: "YOUR GUILD NAME"`. The *most* stale thing in the project. |
| `…\WoW Guild Board\wow-guild-board_1\wow-guild-board\` | Same 2026-07-09 snapshot, **also not a git repo.** Byte-identical to the above **except `config.yml`**, which is filled in. That single filled-in file is the entire difference and is why this folder gets mistaken for "the live one". It is not live. Nothing points at it. |
| `…\WoW Guild Board\Test.txt` | Despite the name, a **third copy of `config.yml`** (3,318 B), slightly further evolved than either of the above. Not a test file. Superseded. |
| `…\Diven WoW Guild Board\wow-guild-board\` | Orphan local git repo, 1 commit ("Guild Board v1.0"), **no remote, never pushed.** Unrelated history — its commit does not exist in the main repo. Best read: a curated open-source release candidate cut on 07-18 (has a LICENSE and a polished README the main repo lacks). Has 13 modules; **missing the 12** the main repo added after 07-18 (`awards, blizzard, cast_art, cast_manifest, html_board, integrity, render_pipeline, styles, theme, theme_bands, transmog_fingerprint, voyage`). |
| `…\Diven WoW Guild Board\wow_board_main_fix\` | **Broken git worktree.** 30 MB of files git cannot read — the `.git/worktrees/*/` admin files are missing (only `ORIG_HEAD` survived, likely a OneDrive sync failure). `git worktree list` does not even show it. **Do not delete before diffing** — see §9. Recovered HEAD: `4fe7db5`. |
| `…\Diven WoW Guild Board\wow_board_main_worktree\` | Same failure mode, 30 MB. Recovered HEAD: `fe2133f`. |
| `C:\wt\{bdq,cg,fc,int,sec}` | Five worktree paths git still tracks but that **no longer exist on disk.** `git worktree prune` clears them. Note `ENGINE_INTERFACE.md` references `C:\wt\fc` as where ~67 generated characters live — **that directory is gone. UNVERIFIED whether that art was backed up.** |

### 2.4 Inside the live repo

| Path | Purpose |
|---|---|
| `config.yml` | **Data config.** Guild name, realm slug, region, sections, thresholds. Officer-editable. |
| `theme.yml` | **Looks config.** Deliberately separate from `config.yml`. Cannot break the board — any bad key silently falls back to shipped defaults. |
| `guild_board/` | The Python package — **25** `.py` modules (24 + `__init__.py`), plus `templates/`. See §4/§5. |
| `scripts/` | **11** top-level Python scripts + `setup_cast_refresh_task.ps1`, plus `scripts/overnight/` (the art pipeline, **17** more). |
| `cast_manifest.json` | Paper-doll art manifest. **3 characters.** See §5.2. |
| `roster_cache.json` | Members as `name-realm` slugs, written by the weekly Actions run. Holds 135 entries vs the website's **130** — the delta is unreconciled (joins/leaves/alts). **Canonical roster size for the site is 130.** |
| `board_state.json` | Week-over-week memory: deltas, NEW badges, realm standing (`standing.realm: 49`). |
| `ROSTER_PRIORITY.json` | Generation tiering + the **cost ledger** (`spent_so_far: 10.901`, `budget_left_after: 0.46`). |
| `.env` | **Local secrets. Gitignored, never commit.** Do not open. |
| `.env.example` | Safe template. Defines `RUNPOD_API_KEY`, `COMFY_BASE_URL`, `RUNPOD_NETWORK_VOLUME_ID`. |
| `styles/one_piece.yaml` | The active style preset. |
| `.github/workflows/` | 4 workflows — see §4.3. |

---

## 3. How to build the site

### 3.1 The honest answer

**There is no build.** This is the most important operational fact in this document and it
contradicts the assumption that a build pipeline exists.

`index.html`, `board.html`, `wanted.html`, `voyage.html`, `hall.html`, `trophy.html`,
`crew_board.html`, and all **131** `p/<slug>.html` profile pages in `GuildBoardTrial\` are
**hand-authored HTML written directly by AI sessions.** No script generates them. No
templating engine. No bundler. All CSS and JS is inline — there are no `.css` or `.js`
files for the top-level pages at all.

To view the site: **open `C:\Users\zachf\Desktop\GuildBoardTrial\index.html` in a browser.**
That is the whole procedure. It is a `file://` site with no server, no build step, and no
dependencies.

**Consequence:** to change the site you edit HTML by hand. To change 131 profile pages you
edit 131 files, or write a script that does. **Every character's stats, score, and art path
is hardcoded into the HTML.** There is no data binding. This is the project's largest piece
of technical debt and the biggest threat to keeping the site current after launch.

### 3.2 The one thing that *is* scripted (and just disappeared)

Until ~01:28 on 2026-07-22 there was a `GuildBoardTrial\bounty\` directory containing a
real three-stage generator for the WANTED posters:

```bash
cd GuildBoardTrial/bounty
python3 extract_roster.py    # scrapes index.html -> roster.json
python3 build_posters.py     # roster.json + cast art -> posters/*.webp
python3 emit_web.py          # roster.json -> web/{poster.css,poster.js,posters.json,assets}
```

Requires `pip install numpy Pillow` and DejaVu fonts. Fully offline — no network, no GPU,
no headless browser. Seeded per-slug (SHA-256 of slug) so runs are reproducible.

**`bounty\` no longer exists on disk as of 01:39.** It was deleted during the same
restructure that created `wanted.html`. **UNVERIFIED whether the poster art was migrated
into `wanted.html` or simply lost.** If those scripts are wanted back, recover them from
whatever session removed them — they are in no git repo and have no backup.

### 3.3 Current page graph (as of 01:40, and it moved twice while this was written)

| Page | Title | Role |
|---|---|---|
| `index.html` | *S.S. Wipe Fest — the guild's ship* | **NEW front door.** The ship cutaway: 11 rooms — `crows-nest`, `main-deck`, `helm`, `quarters`, `the-bar`, `galley`, `casino`, `engine`, `slop-chest`, `brig`, `hold`. Matches `HANGOUT_DESIGN.md`'s eleven-room deck plan. |
| `board.html` | *Skill Issues — Trial Build* | The **previous** `index.html`, demoted. 130 roster cards. |
| `wanted.html` | *S.S. Wipe Fest — The Wanted Board* | **NEW.** Replaces the `bounty/` toolchain. |
| `voyage.html` | Voyage Map (test run) | Islands + progress. |
| `hall.html` | The Grand Hall (test run) | Cameo debt + 130 profile links. |
| `trophy.html` | The Trophy Hall (test run) | Guild achievements, 3 trophies. |
| `crew_board.html` | The Guild Board | **Reachable only from `board.html`** (*"Open the animated crew board →"*), not from the new `index.html`. Contains 131 outbound `p/*.html` links. Not dead — just off the main path. |
| `p/*.html` ×131 | `<Name> — Skill Issues` | Profile pages, one per referenced character. `phyrthepali.html` is the one with no art directory. |

`cast/_roster/` holds **130** character dirs (one **opaque** `profile.jpg` each — see §5.2)
plus 12 `_scene_*` backdrop dirs. `cast/placeholders/crew_slot.png` is the grey silhouette
used for characters whose art isn't generated yet — per `READ_ME_FIRST.txt`, **those are
expected, not broken.**

**Roster size: 130 have art; 131 have pages and cards.** `phyrthepali` is the odd one out —
it **does** have a profile page and **does** appear as a card in both `index.html` and
`wanted.html` (both files carry **131** unique `data-name` values), and it **is** linked from
`crew_board.html`. What it lacks is **art**: there is no `cast/_roster/phyrthepali` directory.

So: **131 characters are referenced, 130 have art.** Both numbers are correct in their own
context — say which you mean. `phyrthepali` will render as a grey placeholder, which is a
supported state (§5.6), not a break.

### 3.4 Building the *Discord board* (this part is real and automated)

```bash
cd "…\Diven WoW Guild Board\WoW_Skill_Issues_Guild_Board"
pip install -r requirements.txt
python leaderboard.py --preview      # local preview, no keys needed
python leaderboard.py --dry-run      # full pipeline, does not post
python leaderboard.py                # builds and posts to Discord
pytest                               # test suite
python -m guild_board.integrity      # data integrity check
```

`scripts/preview_board.py` gives an instant preview from canned data with no credentials at
all. Rendering prefers headless Chromium via Playwright (`html_board.py`) and **fails open**
to the Pillow painter (`board_image.py`) if that breaks.

### 3.5 Deploying the new ship site — see `docs/DEPLOYMENT.md`

The `frontend-crew-ui` branch's site (built via `scripts/build_trial.py`) is deployed
separately from the Discord board above, to **Cloudflare Pages** (`skill-issues-board.pages.dev`),
gated behind Cloudflare Access to specific emails, via Wrangler Direct Upload — no GitHub
integration. Full build/deploy commands, how to add or remove a viewer, and — critically — how
to actually verify the gate is enforcing (it has a known gap around per-deployment preview
URLs) all live in `docs/DEPLOYMENT.md`. **Do not assume any deploy is private without running
that document's §5 verification** — confirmed 2026-07-22 that assuming is wrong at least once.

This is unrelated to and does not affect the old public web board (§3.4's `WEB_BOARD_TOKEN`
publish, `bzach10.github.io/wow-guild-board`) — `docs/DEPLOYMENT.md` §7 has the full comparison.

---

## 4. The data pipeline

### 4.1 What is pulled, by what

| Source | Module | Endpoint | Pulls | Credentials |
|---|---|---|---|---|
| **Warcraft Logs** | `guild_board/wcl.py` | `warcraftlogs.com/oauth/token`, `/api/v2/client` (GraphQL) | Guild roster, per-boss rankings, parse percentiles, guild standing | `WCL_CLIENT_ID`, `WCL_CLIENT_SECRET` — **read in `guild_board/main.py:270`, not in `wcl.py`** |
| **Raider.io** | `guild_board/raiderio.py`, `voyage.py` | `raider.io/api/v1/characters/profile` | M+ weekly runs, season scores, island/dungeon data | **None** — public API |
| **Blizzard** | `guild_board/blizzard.py` | `oauth.battle.net/token`, `{region}.api.blizzard.com/profile/wow/character/…` | Gender, race, class, spec, transmog render URL | `BLIZZARD_CLIENT_ID`, `BLIZZARD_CLIENT_SECRET` |
| **Discord** | `guild_board/discord.py`, `discord_inputs.py` | Webhook; `discord.com/api/v10` | Posts board; **reads** roast + announcements (Discord is the input form) | `DISCORD_WEBHOOK_URL`, `DISCORD_BOT_TOKEN` |
| **Wowhead CDN** | `board_image.py`, `theme_bands.py` | `wow.zamimg.com/images/wow/icons/large/` | Class/spec icons | None |
| **RunPod** | `scripts/overnight/runpod_pod.py` | `rest.runpod.io/v1` | Rents GPU for art generation | `RUNPOD_API_KEY` |

### 4.1a Realm resolution — RESOLVED, and the #1 bug class to watch for

**Settled by Zach, 2026-07-22:** the **guild** is on **Bleeding Hollow**. **Zach's own
characters** (Rakdisc, Rakell, and others) are on **Proudmoore**. The roster is genuinely
**cross-realm**. There was never a mismatch to fix.

**THE RULE — every character must be queried against its OWN realm. Never against a single
hardcoded realm.**

| Call type | Realm source | Value |
|---|---|---|
| **Guild-level** — WCL roster, guild standing, guild link | `config.yml → guild.realm_slug` | **`bleeding-hollow`** — correct, do not change |
| **Character-level** — Raider.io, Blizzard, profile links | The member's own realm, split out of their `name-realm` roster slug | 36 distinct values |

Verified realm spread across the 130 rostered characters:

`bleeding hollow 39 · area 52 18 · queldorei 9 · stormrage 6 · illidan 6 · proudmoore 5 ·
korgath 4 · tichondrius / sargeras / eldrethalas 3 each · 8 realms with 2 · 18 realms with 1`
— **36 distinct realms, 130 characters.** (39+18+9+6+6+5+4+9+16+18 = 130.)

**⚠ Treat any code that assumes one realm for all characters as a bug.** Two concrete
failure modes, both silent:
- Setting `realm_slug: proudmoore` breaks the **guild** lookup — WCL returns nothing and the
  board renders empty with no error.
- Using `guild.realm_slug` for **character** lookups silently 404s for 91 of 130 members
  (everyone not on Bleeding Hollow), and those characters just quietly show no data.

The current code handles both correctly: character lookups fall back to the guild realm
*only* when a roster entry has no `-realm` suffix. Preserve that behavior in anything new.

**Copy implication:** the site should say the guild is on Bleeding Hollow, but must not
imply every member is — 70% of the roster is not.

### 4.2 Secrets — names only, never values

Stored as **GitHub Actions repository secrets** (for CI) and in a local gitignored `.env`
(for the art pipeline).

`WCL_CLIENT_ID` · `WCL_CLIENT_SECRET` · `DISCORD_WEBHOOK_URL` · `DISCORD_BOT_TOKEN` ·
`BLIZZARD_CLIENT_ID` · `BLIZZARD_CLIENT_SECRET` · `RUNPOD_API_KEY` · `COMFY_BASE_URL` ·
`RUNPOD_NETWORK_VOLUME_ID` · `WEB_BOARD_TOKEN` (docs only, UNVERIFIED if used)

`scripts/overnight/settings.py` is the **only** place the art pipeline reads secrets (env
first, then `.env`) and it never logs or reprs a secret value. Keep it that way.

### 4.3 Schedule — weekly is correct

| Workflow | Cron | Meaning |
|---|---|---|
| `weekly-board.yml` | `0 13 * * 2` | **Tuesdays 13:00 UTC / 9 AM ET.** Builds and posts the board. |
| `blizzard-profile-refresh.yml` | `15 13 * * 2` | Tuesdays 13:15 UTC — 15 min later, to pick up the fresh `roster_cache.json`. |
| `board-vote.yml` | none | `workflow_dispatch` only. |
| `redesign-vote.yml` | none | `workflow_dispatch` only. |

**✅ RESOLVED — there is no schedule gap. Weekly is the intended design.** Zach:
*"This board will be post in discord on a **weekly** status to give us updates."*

An earlier note claiming the goal was a daily post was **wrong** and is retracted. Tuesday
13:00 UTC lands just before NA reset so the run captures a full raid week, `lookback_days: 7`
matches it, and the week-over-week delta logic in `state.py`, the "NEW" badge semantics and
the award rotation in `awards.py` all assume that 7-day window. **Leave the cron alone.**
Changing it to daily would be a design change that breaks four subsystems, and it is not
wanted.

**Also:** `blizzard-profile-refresh.yml` **is not committed to git** — it exists as an
untracked file locally in three directories. It is not running in CI anywhere.

---

## 5. Architecture

### 5.1 The "five data layers"

**⚠ UNVERIFIED.** No document in any scanned folder describes "five data layers." The
phrase does not exist in writing. Two candidate referents:

1. **Most likely — the paper-doll body layers.** `LAYER_CONTRACT_frontend.md` defines an
   **eleven**-slot z-stack: `background(0) < cloak(10) < body(20) < legs(30) < chest(40) <
   arms(50) < head(60) < face(61) < headgear(65) < weapon_off(70) < weapon_main(71)`. But the
   two prop-less characters in the shipped manifest use exactly **five body layers** —
   `body, legs, chest, arms, face`. If "five layers" was said aloud, this is almost
   certainly it.
2. **Less likely — the data sources**, of which there are five external (WCL, Raider.io,
   Blizzard, Discord, Wowhead).

**Do not treat "five data layers" as an established architecture term until Zach confirms
which he meant.** Recorded here so the ambiguity stops being rediscovered.

### 5.2 Character art — what is ACTUALLY on disk

**⚠ This section corrects stale documentation. Believe this section, not older docs.**

**The shipped reality (verified on disk, 2026-07-22):**

- Each of the **130** characters has exactly **one file**: `cast/_roster/<slug>/profile.jpg`.
- It is an **opaque, full illustrated scene** — not a cutout, not a sprite, not layers.
- **143 `.jpg` files, 0 `.png` files** under `cast/_roster/`. Pillow reports mode `RGB`.
  **JPEG has no alpha channel, so transparency is physically impossible in these files.**
- The website's roster is **embedded directly as `<article class="card">` elements in the
  HTML**, with stats, score, realm and art path hardcoded per card.
  `extract_roster.py` *parses* that HTML into `roster.json` — the HTML is upstream, the JSON
  is downstream. There is no database and no data binding.
- The 12 `_scene_*` dirs are 900×502 backdrop scenes, a different asset class from the
  character portraits.
- `cast/placeholders/crew_slot.png` is the grey silhouette for characters without art yet.

**DEPRECATED claims — do not act on these, they describe a benched path:**

| Stale claim | Reality |
|---|---|
| "The website's character art is transparent PNG cutouts" | Website art is **130 opaque JPEGs**. No alpha in `GuildBoardTrial/cast/_roster/`. |
| "`board.png` RGBA per character" | **These exist, but only in the Python repo and only for 3 pilot characters** (`cast/{floofwall,healyeah,rakdisc}/board.png` + 3 more under `one_piece/`). The website does not use them. |
| "`cast_manifest.json` is the source of truth for site art" | **It does not exist in `GuildBoardTrial\` at all.** It exists only in the Python repo, holds 3 characters, and the website never reads it. |
| "Characters are composed from layered slots at runtime" | The paper-doll rig is **benched** (§6). Shipped website art is single-image. The 18 per-slot layer PNGs the manifest defines are real but unused by the site. |

Both statements can be true at once, which is why this keeps causing confusion:
`cast_manifest.json` **is** authoritative *for the paper-doll pipeline inside the Python
repo*, and **is simultaneously absent and irrelevant** *for the website that actually
ships*. Always say which surface you mean.

### 5.2a `cast_manifest.json` — scope and schema (paper-doll pipeline only)

Authoritative **for the benched paper-doll art pipeline**, not for the shipped website.

- **3 characters only:** `rakdisc-proudmoore` (8 layers, the pilot), `floofwall-queldorei`
  (5), `healyeah-queldorei` (5).
- Canvas 832×1216. Each style entry carries `layers[] = {slot, src, anchor{x,y}, z}`.
- `transmog_fingerprint` — a hash of the Blizzard render URL, used as a cheap "did their
  look change?" signal so unchanged characters are **not** regenerated. `GENERATION_HANDOFF.md`
  is emphatic: without this populated, *"a one-time ~$50 becomes ~$50 every time."*
- Managed solely by `guild_board/cast_manifest.py` (load/save/add/register_style/
  record_style_result/rollback). Written by `scripts/weekly_cast_refresh.py` and
  `scripts/overnight/publish.py`.
- Supports versioning and `history[]` for rollback — regeneration is reversible.

### 5.3 Art pipeline

`Blizzard transmog render → crop_to_content() → restyle_via_img2img() → cutout_to_board()`
(`guild_board/render_pipeline.py`), with ControlNet canny at **0.85** holding silhouette
IoU at **0.98**, and a One Piece LoRA at strength **0.40** (0.75 produced "unusable
elongated anatomy"). `scripts/overnight/` wraps this in a self-driving, checkpointed,
resumable overnight runner designed to survive unattended execution.

**⚠ Those figures come from `ENGINE_INTERFACE.md` (the R&D findings), not from the shipped
preset.** `styles/one_piece.yaml` — the active preset — actually sets `controlnet.strength:
0.5`, `canny_high_threshold: 0.4`, and `loras[0].strength: 1.0`. The two have drifted apart
and **nobody has reconciled them.** Do not assume the shipped art was made at 0.85/0.40.

`ENGINE_INTERFACE.md` deliberately confines all ComfyUI knowledge to `engine.py` so the
backend is swappable — the whole generation contract is `text_to_image`,
`image_conditioned`, `healthy()`. **~300 of its 518 lines exist only because generation
runs locally.**

*(Numbering note: there is no §5.4. Sections run 5.1, 5.2, 5.2a, 5.3, 5.5, 5.6, 5.7. Nothing
was deleted — the gap is an artifact of insertion order and is left alone so existing
cross-references stay valid.)*

### 5.5 The voyage is a data model, not decoration

Per Zach: *"the idea of the ship & voyager came from to show us progressing on the islands
(dungeons & raids) we can show what key levels we have done as a guild & what raid bosses we
have completed etc."*

**Build the Voyage Map as a data surface.** The mapping is literal:

| Ship concept | Real data | Source |
|---|---|---|
| **Island** | A dungeon or raid | Raider.io season data (`guild_board/voyage.py`) |
| **Sailing between islands** | Guild progression through the season | derived |
| **Island "cleared" state** | Highest **key level** the guild has completed there | Raider.io M+ runs |
| **Raid island** | Which **bosses** are downed, and at what difficulty | WCL (`guild_board/wcl.py`) |
| **Current position** | `config.yml → voyage.current_island` | **currently empty (`""`)** — see §9 |
| **Crew** | The 130 rostered characters | `roster_cache.json` |

This means the map must render **real per-island completion state**, not a decorative
path. `guild_board/voyage.py` already models islands from live Raider.io data — the missing
piece is the front-end surface and `current_island` being set. Do not rebuild the data
layer; wire up the one that exists.

### 5.6 Empty-data states are a MAIN PATH, not an edge case

**34 of 130 characters (26%) have no score.** Only 96 carry a season M+ score.

Design consequence, and it is not optional: **every character-facing surface must look
correct and intentional with no data.** A quarter of the crew will render empty on launch
day. Placeholder art (`crew_slot.png`) is already treated this way — `READ_ME_FIRST.txt`
tells testers the grey silhouettes *"are not broken."* Extend that same care to scores,
parses, ranks and bounty values. Never render `null`, `0`, `NaN`, `undefined`, or a blank
cell where a score belongs, and never sort the scoreless to look like they placed last
unless that is deliberate.

### 5.7 Frontend runtime

DOM + CSS transforms, measured at **59.9 fps with 120 characters / 408 animated bones**,
with `IntersectionObserver` pausing offscreen work and `prefers-reduced-motion` honored.
The board render path fails open at every stage: Playwright/Chromium → Pillow → static PNG.

---

## 6. Feature status

**Priority order is set by Zach: the character showcase comes first.** *"But first i want to
showcase the guild characters with the anime style artistic creations we did off their own
wow renderings."* Cast art on the website outranks the voyage map, stories, Discord
integration, and everything else below. If you are choosing what to work on and nothing else
is on fire, work on getting the remaining characters' art generated and displayed well.

| Feature | Status | Notes |
|---|---|---|
| **★ Character showcase (cast art on site)** | 🟡 **Top priority, partial** | **Zach's #1.** 130 characters have `profile.jpg`; the rest render as grey placeholders. Budget is the constraint (§8), not code. |
| **Weekly Discord board** | ✅ **Built & live** | The original product. Posts Tuesdays 9 AM ET — **weekly is correct.** |
| **Ship rooms** | ✅ **Just built** (2026-07-22 ~01:39) | 11 rooms now live in `index.html`. Was "spec only" one hour before this doc was written. Spec: `HANGOUT_DESIGN.md`. |
| **Wanted board** | ✅ **Built** | Shipped in the Discord board (WANTED-poster ranking columns, theme-editable). Website version just moved from `bounty/` scripts to a hand-authored `wanted.html`. |
| **Voyage map** | 🟡 **Data layer built, front door partial** | **This is a data surface, not decoration — see §5.5.** `guild_board/voyage.py` + `scripts/render_voyage_map.py` pull live Raider.io data. `voyage.html` exists. But `config.yml → voyage.current_island` is **empty (`""`)**, and per-island key levels / boss kills are not yet surfaced. |
| **Guild achievements** | 🟡 **Built in Discord board; website version is a stub** | `guild_achievement_header` and `overall_realm_rank` enabled in `config.yml`. `trophy.html` has only 3 trophies and is still marked "(test run)". |
| **Scenes** | 🟡 **Brief + art approved, rotation not built** | `SCENE_SCENARIOS.md` specs 12 backdrops with casting from the top ~30 by M+ score, each character headlining only one scene. 12 `_scene_*` dirs exist in `cast/_roster/`. Scene-of-the-week rotation is not implemented. |
| **Settings panel** | ❌ **Does not exist** | No such code anywhere. Config is deliberately plain files edited in the GitHub web UI. The "local-only settings panel" decision is **UNVERIFIED and unwritten** — the nearest real statement is `SETUP_BLIZZARD.md`: *"No admin UI for the cache — it's a plain JSON file."* The site does use `localStorage` (24 refs) for theme/filter persistence, which may be what was meant. |
| **Animation — board GIF** | ✅ Built, ⚠ **fix pending** | `animate: true`, 10 frames × 120 ms. `ANIMATION_FIX.md` is a complete, tested-by-design, **not-yet-applied** rewrite fixing three real defects (no true motion, per-frame palette shimmer, wasteful full re-renders). Apply it. |
| **Animation — paper-doll rig** | 🅿️ **Benched** | Built and performance-proven (59.9 fps), but the approved trial direction is **single-image scene art**, so it is parked behind the unresolved ANIM-06 decision. |
| **Unreal paper-doll** | 🔬 **Active spike, not on launch path** | Contradicts the "Unreal is benched" belief — it is among the *newest* work (07-21 21:13). But the level is unsaved (`Untitled_1` autosave only). |
| **Discord chat integration on site** | 📋 **Planned — named by Zach** | *"I would like the ability to link discord chats potentially in the future."* Scoped in `HANGOUT_DESIGN.md` to four channels: `#guild-chat`, `#memes`, `#healmates-bully-corner`, `#gambling`. Read-only; no new backend (§7 decision 4). |
| **Short stories from Discord chats** | 📋 **Planned — named by Zach** | *"I also wanted to create short stories based off discord chats to bring personality into this website."* **Not previously tracked anywhere.** No design, no code, no data capture yet. Depends on the Discord read layer landing first. |
| **Empty-data states** | ⚠️ **Required, unbuilt** | 34/130 characters have no score. See §5.6. This is a main path. |
| **NFT / on-chain anything** | ❌ **Explicitly killed** | `IDEAS_BACKLOG.md`. |

---

## 7. Decisions log

Settled calls. Do not relitigate without new information.

**Decisions 0a–0e come directly from Zach's statement at the top of this doc and outrank
everything below them.**

- **0a. Two artifacts, one theme.** Discord board (weekly status) + website (hangout & data),
  tied by styling and shared data. Never merge them conceptually.
- **0b. The Discord board is weekly.** Tuesday cron stays. Retracts the earlier "daily goal" claim.
- **0c. Character showcase is the first priority.** Anime-style art from real WoW renders.
- **0d. The ship/voyage is the progression data model** — islands are dungeons and raids,
  displaying key levels and boss kills. Not decoration. (§5.5)
- **0e. The ship is named S.S. Wipe Fest.** Closes `HANGOUT_DESIGN.md`'s open naming question;
  the "The Skill Issue" recommendation is superseded.

1. **Nano Banana Pro over ComfyUI for cast generation.** `GENERATION_HANDOFF.md`: *"Nano
   Banana **Pro** for characters visible on the board, **Pro Edit** for the tail… your own
   bake-off put Pro Edit at $0.14 and rated it good."* Local ComfyUI on the RTX 4080 was
   the original zero-marginal-cost path and is still used for theme/background art;
   character generation moved to the paid API. `ENGINE_INTERFACE.md` exists specifically so
   this swap costs one file.
2. **Render-driven generation over prompt-based.** The real Blizzard transmog render is the
   only variable; one identical function per character. Raw-render img2img was measured to
   fail because content is only ~21% of canvas width, hence the `crop_to_content()` stage.
   **Structural conditioning is mandatory** for any future engine — ControlNet canny 0.85,
   silhouette IoU 0.98. Any candidate engine must demonstrate equivalent lock.
3. **Single-image scene art over paper-doll layers.** `TRIAL_HANDOFF.md`: *"No paper-doll
   layers, no manifest changes needed — this trial is single-image per character, which is
   the look Zach approved."* This is what benched the rig — **and it is confirmed by what
   ships on the website**: 130 opaque single-image JPEGs. Layered assets still exist in the
   Python repo (18 slot PNGs across 3 pilot characters) but nothing on the site reads them
   (§5.2). Any doc implying the *website* uses cutouts is deprecated.
4. **No new backend.** `HANGOUT_DESIGN.md` locked default #1: the site stays static on
   GitHub Pages; all interaction bridges through Discord. This constrains every future
   feature — anything needing a write-store is out of scope by default.
5. **Looks and data are separate files.** `theme.yml` (anyone may edit, cannot break
   anything) vs `config.yml` (officers). Every theme key falls back silently to shipped
   defaults.
6. **Fail open, always.** Rendering degrades Chromium → Pillow → static. Awards fail open.
   Styles fail open. Integrity checks heal in place. Nothing user-editable can break a build.
7. **The Brig has a permanent opt-out**, and the public Discord feed is limited to four
   named channels. Privacy constraint, `HANGOUT_DESIGN.md`.
8. **Cast art is original characters only** — never known anime characters. Enforced as
   negative prompt tokens (`"anime characters, copyrighted characters, cosplay, fan art"`).
9. **Guild votes — ⚠ ONLY ONE OF THE TWO IS GUARDED.**
   - `redesign-vote.yml` **is** guarded: requires `dry_run: false` *and* typing `POST`.
   - **`board-vote.yml` is NOT guarded.** Its trigger is a bare `on: workflow_dispatch:`
     with **no inputs at all** — no `dry_run`, no confirmation. Clicking "Run workflow"
     renders Board A and **immediately posts to `DISCORD_WEBHOOK_URL`.**

   `REDESIGN_NOTES.md` separately flags that **nobody has confirmed which channel
   `DISCORD_WEBHOOK_URL` points at.** Combined, that is a one-click accidental post to an
   unknown channel. **→ Add a confirmation input to `board-vote.yml` before launch.**
10. **`main` is frozen for the auto-post; all new work lands on `2.0`.**
11. **Magenta chroma-key over green — UNVERIFIED.** No evidence in any file. The only
    `magenta` hit in the entire project is a *negative* prompt token in
    `scripts/overnight/scene_trial.py:73` (`"magenta armor, pink armor"`), which is the
    opposite of a chroma-key decision. **Ask Zach; then write it down here.**

---

## 8. Constraints

**Budget — hard and nearly exhausted.**
`ROSTER_PRIORITY.json` cost ledger: **`spent_so_far: 10.901`, `budget_left_after: 0.46`.**
`GENERATION_HANDOFF.md` opens with a live cost alarm: *"Please stop the alphabetical run.
It is spending ~$0.40/character in name order… Spend went $8.38 → $10.90 in the time it
took to write this."* Rules established:
- Generate in **priority order** (season M+ score > 1000), never alphabetical.
- Tier 1 = Nano Banana Pro; tier 2 = Pro Edit at $0.14; tier 3 held.
- **Always populate `transmog_fingerprint`** or every refresh re-bills the full run.
- Recommended trimmed scope: $3.28, leaving ~$5.80 for site art.
- Every RunPod costing subcommand requires an explicit flag — no accidental spend.

**Security.**
- **Never commit `.env`, `*.key`, `*.pem`, `secrets.json`, `runpod_config.json`.** Only the
  main repo's `.gitignore` has this SECRETS block; the other three repos/worktrees do not.
- Never log, print, or repr a secret value. `settings.py` is the only reader.
- Never put a token in a plaintext file in OneDrive (see §9, risk 1).

**Copyright.** Original characters only; no known anime characters, cosplay, or fan art.
Enforced via negative prompts. Note: there is **no formal copyright policy document** —
this is encoded only as prompt tokens and one line in the design system. Worth writing
down properly given a One Piece–themed public site.

**Platform.** Static GitHub Pages, weekly GitHub Actions render, solo build on consumer
hardware. No server, no subscription, no database. `prefers-reduced-motion` must be honored.

---

## 9. Known issues & open punch list

**Launch blockers / high severity**

1. **`Discord Bot Token.txt` sits in plaintext in OneDrive.**
   `…\WoW Server Stuff\WoW Guild Board\Discord Bot Token.txt` — **confirmed to exist**,
   94 bytes, modified 2026-07-18 14:52. **Its contents were not opened, read, copied, or
   transmitted.** 94 bytes is consistent with a raw bot token. It is in a cloud-synced
   folder in a directory covered by no `.gitignore`.
   **→ Revoke and regenerate that token in the Discord developer portal, then delete the
   file.** Rotate regardless of whether it was ever exposed.
2. **`GuildBoardTrial\` has zero version control.** ~2.3 MB of hand-authored HTML (7 pages
   ≈ 780 KB + 131 profile pages ≈ 1.5 MB) inside a **42 MB** folder — the entire website —
   with no git, no history, no backup. A bad overwrite loses the launch.
   **→ `git init` it today** (and see the root `.gitignore`, which excludes the art).
3. **`GuildBoardTrial\` was actively being rewritten during this scan.** Between 01:28 and
   01:39, `index.html` was replaced (228 KB → 156 KB), the old one demoted to `board.html`,
   `wanted.html` created, and the entire **`bounty\` directory deleted.** Another session is
   working in there right now. **→ Coordinate before editing. Confirm the `bounty/` scripts
   were intentionally removed and not lost.**
4. **Two broken git worktrees holding 30 MB each of unreadable files.** `wow_board_main_fix`
   and `wow_board_main_worktree`. Git cannot see them, so you cannot tell what's uncommitted
   inside. **→ Diff their contents against `4fe7db5` and `fe2133f` respectively before
   deleting anything.**
5. **`2.0` is diverged: 8 ahead / 4 behind `origin/2.0`, with 165 dirty files** (70 modified,
   95 untracked). That is a very large unreconciled surface immediately before a launch.
   **→ Reconcile and commit.**

**Medium**

6. `blizzard-profile-refresh.yml` is **untracked in git** and therefore not running in CI.
7. **Manifest/contract drift:** `rakdisc-proudmoore`'s `headgear`/`weapon_main`/`weapon_off`
   layers lack the `size` field the 2026-07-21 contract requires — those props will render
   stretched to full canvas with a logged warning.
8. The contract's `head` slot (z=60) is **absent from every manifest entry** — shipped art
   has `face` but no `head`, which the contract warns will cover hair and head silhouette.
9. *(merged into #16 — voyage data surface.)*
10. `ANIMATION_FIX.md` is written, complete, and **not applied.**
11. *(merged into #23 — page-graph tidiness.)*
12. **~67 generated characters** are referenced in `GENERATION_HANDOFF.md` §1 (*"It is empty
    for all 67 generated characters"*). Separately, `ENGINE_INTERFACE.md:96` points at
    `C:\wt\fc\guild_board\paperdoll.py`, and **`C:\wt\fc` no longer exists**. These are two
    different facts and earlier notes conflated them. **UNVERIFIED where the 67 characters'
    art lives, or whether it survives.** Given §8's budget, potentially $9 of regeneration.
13. **`GuildBoardTrial\bounty\` was deleted at ~01:39 on 2026-07-22**, taking
    `extract_roster.py`, `build_posters.py`, `emit_web.py`, `roster.json`, `posters/` and
    `web/` with it. Those files were read at ~01:28 and are cited in this doc from that
    reading — **they can no longer be re-verified.** They were in no git repo and have no
    backup. Their function appears to be superseded by the hand-authored `wanted.html`.
    **→ Confirm with whoever deleted it that this was intentional.**
14. Three of four repos/worktrees have `.gitignore` files with **no `.env` or secrets
    coverage** — one stray file from committing a credential.
15. **34 of 130 characters have no score** — empty-data rendering is unbuilt and is a main
    path, not an edge case (§5.6). A quarter of the crew renders blank on launch day.
16. **`voyage.current_island` is empty and per-island progression is not surfaced** — the
    voyage is currently decoration, but is specified as a data model (§5.5).
17. **`roster_cache.json` holds 135 members; the website has 130.** Delta unreconciled.
18. **Short stories from Discord chats** — named by Zach as wanted, but has no design, no
    data capture, and appears in no backlog. Currently exists only in this document.

**Low**

19. `git worktree prune` will clear five stale `C:\wt\*` entries; a sixth admin dir (`care`)
    is an unreferenced remnant.
20. Three redundant `config.yml` copies (`wow-guild-board`, `wow-guild-board_1`, `Test.txt`)
    invite editing the wrong one. **→ Delete or clearly mark them.**
21. The Unreal level exists only as an autosave — one crash from losing the spike.
22. Site copy must not imply a single-realm roster — 36 distinct realms, 70% of members are
    not on Bleeding Hollow (§4.1a).
23. **Page-graph tidiness:** `phyrthepali` has a page and cards but **no art directory** —
    it will render as a placeholder. `crew_board.html` is reachable only from `board.html`,
    not from the new `index.html`. Neither is broken; both are worth a deliberate decision
    before launch.

---

## 10. Glossary

| Term | Meaning |
|---|---|
| **S.S. Wipe Fest** | The website/hangout. The ship the guild "lives on." |
| **Skill Issues** | The actual WoW guild. Bleeding Hollow (US), ~131–135 members. |
| **The board** | Ambiguous — clarify which. Either the **Discord board** (weekly PNG posted by the bot) or `board.html` (the roster page, formerly `index.html`). |
| **Cast** | The generated One Piece–style character art for guild members. |
| **Paper-doll** | Character art split into aligned transparent layers (body/legs/chest/arms/face/props) that can be animated independently. Currently benched. |
| **Slot** | One named layer in the paper-doll stack, with a fixed z-index. |
| **Anchor** | The `{x,y}` placement of a layer on the 832×1216 canvas. |
| **Transmog fingerprint** | Hash of a character's Blizzard render URL. Detects "did their look change" so unchanged characters aren't re-billed for regeneration. |
| **Render-driven generation** | Generating art *from* the real Blizzard transmog render as structural input, rather than from a text prompt describing the character. |
| **Slug** | Lowercase URL-safe identifier. Character slugs are `name-realm` (e.g. `rakdisc-proudmoore`); realm slugs replace spaces with dashes (`bleeding-hollow`). |
| **Island** | A dungeon or raid, in Voyage Map terms. |
| **Room** | One of the 11 sections of the ship on `index.html`. |
| **WANTED poster** | The One Piece bounty-poster treatment applied to ranking columns and character cards. |
| **Bounty rank** | A character's position on the WANTED board, derived from M+ score. |
| **Fails open** | Design principle: when a component breaks, degrade to a simpler working version rather than erroring. |
| **WCL** | Warcraft Logs. |
| **Raider.io** | Third-party Mythic+ score API. Public, no credentials. |
| **M+** | Mythic Plus, WoW's scored dungeon mode. |
| **Parse** | A percentile ranking of a player's damage/healing on a boss fight. |
| **The pilot** | `rakdisc-proudmoore` — Zach's own character, used as the test subject for every art pipeline change. |
| **ComfyUI** | Local node-based Stable Diffusion runner used on the RTX 4080. |
| **Nano Banana Pro** | The paid image-generation API now used for character art. |
| **ControlNet / LoRA** | Structural conditioning, and a style adapter (One Piece Wano at strength 0.40). |
| **RunPod** | Rented cloud GPU, for when local generation isn't enough. |
| **ANIM-06** | The unresolved backlog decision — flat cutout vs per-slot layers. Gates all animation work. |
| **`2.0`** | The active development branch. `main` is frozen for the live auto-post. |

---

*If you change something this document describes, update this document in the same session.
It is only useful while it is true.*

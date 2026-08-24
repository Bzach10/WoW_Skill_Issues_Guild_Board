# WoW Guild Weekly Leaderboard Bot

Automatically posts a weekly leaderboard to your guild Discord every Tuesday before reset. Pulls raid data from Warcraft Logs — guild standing vs other guilds, top DPS parses, top healing parses, realm rank leaders, most deaths, roast of the week, and (optionally) highest M+ keys via Raider.io. Runs free on GitHub Actions. No server, no hosting, no maintenance.

## The one hard dependency

Someone must upload your raid logs to Warcraft Logs each raid night, attached to your guild. Use the Warcraft Logs Uploader (live logging or upload after raid) and make sure the report is assigned to the guild, not a personal account. No logs uploaded = the bot posts a friendly "no logs this week" notice instead.

## One-time setup (~20 minutes, guild leader does this once)

### 1. Create a Warcraft Logs API client
1. Go to https://www.warcraftlogs.com/api/clients while logged in.
2. Click "Create Client." Name it anything (e.g., "Guild Board"). For the redirect URL, just enter `https://localhost` — the form requires something here, but this setup never uses it. (Redirect URLs only matter for apps where users log in through Warcraft Logs and get sent back afterward; this script authenticates directly with the Client ID and Secret, so no redirect ever happens and any valid URL works as a placeholder.) Leave "Public Client" unchecked.
3. Save the **Client ID** and **Client Secret** somewhere temporarily.

### 2. Create a Discord webhook
1. In Discord, right-click the channel where the board should post → Edit Channel → Integrations → Webhooks → New Webhook.
2. Name it (e.g., "Guild Board"), set the channel, click "Copy Webhook URL."

### 3. Create the GitHub repo
1. Make a free GitHub account if needed, then create a new **private** repository (e.g., `wow-guild-board`).
2. Upload all the files from this folder, keeping the folder structure — the workflow file must end up at `.github/workflows/weekly-board.yml`. (Easiest: on the repo page, Add file → Upload files, and drag the whole folder contents in.)

### 4. Add your secrets
In the repo: Settings → Secrets and variables → Actions → New repository secret. Add these three:

| Secret name | Value |
|---|---|
| `WCL_CLIENT_ID` | from step 1 |
| `WCL_CLIENT_SECRET` | from step 1 |
| `DISCORD_WEBHOOK_URL` | from step 2 |

### 5. Fill in `config.yml`
Edit `config.yml` in the GitHub web UI: set your guild name (exactly as shown on Warcraft Logs), realm slug (lowercase, spaces → dashes, e.g. `area-52`), and region.

### 6. Test it
Go to the Actions tab → "Weekly Guild Board" → "Run workflow" → Run. Within a minute or two the board should appear in Discord. If the run fails, click into it to read the error (most common issues: guild name/realm slug mismatch, or a secret pasted with a trailing space).

That's it. It now posts automatically every Tuesday at 9 AM ET, covering the previous 7 days of logs.

Optional: `tests/test_guild_board.py` is an offline pytest suite (no API keys needed). Run `pytest` locally after any code change to sanity-check the dedup, filtering, and formatting logic.

## Giving officers access (no coding required)

1. Repo → Settings → Collaborators → invite their GitHub accounts (free accounts are fine).
2. Their entire job each week:
   - Open `weekly_state.json` on the GitHub website, click the pencil icon.
   - Paste the winning roast into the `roast_of_the_week` section (winner, target, roast).
   - Optionally add temporary roster overrides in `roster_overrides`.
   - Click "Commit changes."
   - Optional: Actions tab → "Weekly Guild Board" → "Run workflow" to repost immediately, or just let Tuesday's automatic post include it.

Officers can also toggle categories, change `top_n`, switch difficulty, adjust the pug filter, or enable the M+ board — all from `config.yml`, no code.

## Make it yours (any member, no coding)

Everything about how the board **looks** — colors, fonts, background art, the
header/footer style, every joke on it, and the rotating weekly awards — lives
in **`theme.yml`**, safe for any member to edit right on the GitHub website.
Mistakes can't break the board: bad values fall back to the shipped design.
Preview changes instantly with `python scripts/preview_board.py --open`
(fake data, no API keys). Full walkthrough, including building your own
header/footer module: **[CUSTOMIZING.md](CUSTOMIZING.md)**.

Every post also includes a portrait phone-readable companion image and TL;DR
callout lines in the message text, so the highlights land on mobile without
pinch-zooming (toggle: `display.mobile_companion` in `config.yml`).

## Web board (one-time setup, ~5 minutes)

The weekly post promotes the **ship site** (`display.site_url` —
https://skill-issues-board.pages.dev), and that is the only site link it
carries. Separately, CI still renders a responsive HTML twin of the board
each week and publishes it, plus a per-week state snapshot, to a **public**
repo's GitHub Pages — that page is no longer linked from Discord, but it is
where the week ARCHIVE accumulates, so the private guild repo stays private.
Until this setup is done, the publish step just skips — nothing breaks.

1. Have a public repo to host the page (e.g. `wow-guild-board`). In that
   repo: Settings → Pages → Source: "Deploy from a branch" → Branch:
   `gh-pages` (created automatically by the first publish; you can set this
   after the first run).
2. Create a token that can push to it: GitHub → Settings → Developer
   settings → Fine-grained personal access tokens → Generate new token.
   Repository access: just the public repo. Permissions: **Contents:
   Read and write**. Copy the token.
3. In THIS repo: Settings → Secrets and variables → Actions → New repository
   secret → name `WEB_BOARD_TOKEN`, paste the token.
4. Check `display.web_board.repo` in `config.yml` points at that public
   repo. (The Discord button opens `display.site_url`, not this page.)

Note the page is public to anyone with the link — it shows the same
WCL/Raider.io stats that are already public, plus the roast. Once it's live,
you can set `display.mobile_companion: false` to slim the Discord post back
down to one image.

## CLI & preview

Run locally with no network calls:

```bash
python leaderboard.py --preview
```

This writes `preview.html` (and `board.png` in image-board mode) so you can see exactly how the board will look.

## Board layout

`display.layout` in `config.yml` controls how the board renders:

- **`image_board` (default, recommended)** — the whole board is drawn as a single PNG: real side-by-side Raid and Mythic+ columns, class-colored player names with class/spec icons (fetched from Wowhead's icon CDN; if the CDN is unreachable the board just renders without icons — set `display.icons: false` to turn them off), WCL-style parse colors, stat tiles, kill progress bar, and the roast card. It looks identical on desktop and mobile. The Discord embed carries only the title, announcement, and footer, plus the link buttons. If image generation ever fails, the run automatically falls back to a plain text embed instead of skipping the post.
- **`single_column`** — classic text embed, one full-width field per section, with the smaller progress image attached.
- **`two_column`** — legacy inline-field columns. Discord reflows inline fields unpredictably (especially on mobile), so this layout is kept only for backwards compatibility — avoid it.

Other useful flags:

```bash
python leaderboard.py --dry-run                              # build and print the embed, no Discord post
python leaderboard.py --difficulty heroic --lookback 7       # override difficulty/lookback
python leaderboard.py --roast "..." --roast-winner Bud      # override roast for one run
```

The GitHub Actions workflow also supports these as `workflow_dispatch` inputs.

## Where to put manual inputs (cheat sheet)

Three ways in, from most to least convenient:

| Method | Good for | How |
|---|---|---|
| **Discord channels** (recommended, set up below) | Weekly roast voting, announcements | Members post + 🔥-vote in the roast channel; officers post in the announcement channel. The Tuesday run reads both automatically. |
| **Run workflow form** | One-off overrides | Actions → Weekly Guild Board → Run workflow: roast fields, difficulty, lookback, dry run. A manually entered roast beats the Discord vote. |
| **`weekly_state.json` / `config.yml`** | Standing config, roster overrides | Edit on the GitHub website (pencil icon), commit, run the workflow. |

## Discord-powered inputs (roast voting + announcements)

Turn Discord itself into the board's input form — no extra hosting, the weekly run just reads two channels:

- **Roast channel** (e.g. `#roast-submissions`): anyone posts roasts during the week; the guild votes by reacting 🔥. The top-voted post since the week started is automatically crowned Roast of the Week (author = winner; if they @mention someone, that's the target).
- **Announcement channel** (e.g. `#board-announcements`): lock posting to officers/GM in Discord permissions; the latest message there becomes the 📢 announcement at the top of the board.

**One-time setup (~5 minutes):**

1. Go to https://discord.com/developers/applications → New Application (name it "Guild Board Reader" or similar) → Bot tab. Turn OFF "Public Bot". Click "Reset Token" and copy the token.
2. In the repo: Settings → Secrets and variables → Actions → New repository secret → name `DISCORD_BOT_TOKEN`, paste the token.
3. Invite the bot: OAuth2 → URL Generator → scope `bot` → permissions **View Channels** and **Read Message History** only → open the generated URL and add it to your server.
4. In Discord, enable Developer Mode (Settings → Advanced), then right-click each channel → **Copy Channel ID**.
5. In `config.yml`, set `discord_inputs.enabled: true` and paste the two channel IDs.

The bot never posts — the existing webhook still does that. If the token, channel IDs, or API are ever broken, the run logs a warning and falls back to whatever is in `weekly_state.json`/`config.yml`.

## The roast workflow

Members drop roasts in the roast channel all week and react 🔥 to their favorites. Tuesday's run counts the votes and crowns the winner automatically. No Discord bot set up yet? Old way still works: an officer pastes the winner into `weekly_state.json` before Tuesday, or uses the Run workflow form.

## Pugs and roster filtering

Pug-uploaded logs never affect the board — the script only queries reports attached to **your guild** on Warcraft Logs. But pugs raiding *with* you will appear in your own logs, so the `filters` section in `config.yml` controls whether they show on the board:

- `guild_members_only: false` (default) — everyone in the raid can appear, pugs included.
- `guild_members_only: true` — the script pulls your guild roster from Warcraft Logs automatically each run (synced from the in-game roster, no list to maintain) and only members appear. Add trials or friends-of-guild who aren't in yet to `always_include`.
- `always_exclude` hides specific names regardless of anything else.

If the roster lookup ever fails, the script fails open and shows everyone rather than posting an empty board. Filtering also runs *before* the Realm Rank Leaders lookups, so no API calls are wasted ranking randoms.

**Setup note for your loggers:** a member's upload only counts if they choose the guild as the destination in the WCL Uploader, which requires their WCL account to have a character claimed on the guild's roster page. Have each designated logger verify once that the guild appears in their uploader's destination dropdown.

## Multiple loggers? Covered.

If two (or more) people upload logs of the same raid night, the script automatically deduplicates: each boss pull is fingerprinted by encounter, difficulty, outcome, start time, and duration, and duplicate copies of a pull are skipped so **deaths, pull counts, and kill counts are never double-counted**. Parses are naturally immune (each player's best is kept regardless).

When the same pull exists in two logs, the winner is chosen in this order: reports from your designated primary logger first (set `preferred_uploader` in `config.yml` to their Warcraft Logs account name), then the longest/most complete report. The Actions run log shows how many duplicate pulls were skipped each week.

This also means partial logs are handled gracefully — if the backup logger started late, their fragment fills in only whatever the primary log is missing.

## How rankings work

- **Guild Standing** shows your guild's progress rank vs other guilds — realm, region, and world — for the current raid tier, straight from Warcraft Logs. The raid zone is auto-detected from this week's logs (override with `zone_id` in config if needed).
- **DPS/HPS** rank by each player's best parse percentile of the week (ilvl- and spec-normalized), so undergeared or off-meta players compete fairly. Parses only exist on kills. If one metric has no parses at the week's difficulty (e.g. mythic kills but no mythic healing parses), that metric alone falls back to heroic, then normal — and every line is labeled with the difficulty it came from ("Heroic Rotmire"), so nothing masquerades as mythic.
- **Realm Rank Leaders** looks up every raider who appeared in this week's kills and ranks them by their WCL All Stars **realm rank** for the tier (at your configured difficulty), showing region rank and best-average parse too. This is season-long standing, not just this week.
- **Deaths** count every death across all pulls of your configured difficulty, wipes included. Die in the fire, enter the leaderboard.
- **M+** shows each listed character's highest key of the current week from Raider.io.
- **Most Improved** (DPS top 5, healers top 2) compares each raider's best WCL parse from early in the season against their recent best, using every guild log in the current raid zone (up to ~6 months back, so it resets automatically each tier). Parse percentiles are gear/spec-normalized, so this rewards playing better — not just gearing up. Players need logs spanning at least 2 weeks to qualify, and only positive gains appear. Configure via `most_improved_dps` / `most_improved_healers` in `config.yml`.

**Important:** guild and player ranks on Warcraft Logs only reflect *logged* kills. If a boss kill never gets uploaded, WCL doesn't know it happened and your progress rank won't count it — one more reason consistent logging matters.

## Switching things later

- **Mythic season starts?** Change `difficulty: heroic` to `mythic` in config.
- **Add M+?** Set `mplus.enabled: true` and list your raiders in the roster.
- **Monthly instead of weekly?** In `.github/workflows/weekly-board.yml`, change the cron line to `"0 13 1 * *"` (1st of each month) and set `lookback_days: 30` in config.
- **Different post time?** Cron is in UTC. `0 13 * * 2` = Tuesday 13:00 UTC = 9 AM ET.

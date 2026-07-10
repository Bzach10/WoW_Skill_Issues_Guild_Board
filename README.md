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

Optional: `test_leaderboard.py` is an offline test suite (no API keys needed). Run `python3 test_leaderboard.py` locally after any code change to sanity-check the dedup, filtering, and formatting logic.

## Giving officers access (no coding required)

1. Repo → Settings → Collaborators → invite their GitHub accounts (free accounts are fine).
2. Their entire job each week:
   - Open `config.yml` on the GitHub website, click the pencil icon.
   - Paste the winning roast into the `roast_of_the_week` section (winner, target, roast).
   - Click "Commit changes."
   - Optional: Actions tab → "Weekly Guild Board" → "Run workflow" to repost immediately, or just let Tuesday's automatic post include it.

Officers can also toggle categories, change `top_n`, switch difficulty, adjust the pug filter, or enable the M+ board — all from the same file, no code.

## The roast workflow

The board's footer prompts people to drop healer roasts in a thread. During the week, members react to their favorites. Before Tuesday, an officer picks the winner (most reactions, or officer's choice) and pastes it into `config.yml`. The Tuesday post crowns them.

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
- **DPS/HPS** rank by each player's best parse percentile of the week (ilvl- and spec-normalized), so undergeared or off-meta players compete fairly. Parses only exist on kills.
- **Realm Rank Leaders** looks up every raider who appeared in this week's kills and ranks them by their WCL All Stars **realm rank** for the tier (at your configured difficulty), showing region rank and best-average parse too. This is season-long standing, not just this week.
- **Deaths** count every death across all pulls of your configured difficulty, wipes included. Die in the fire, enter the leaderboard.
- **M+** shows each listed character's highest key of the current week from Raider.io.

**Important:** guild and player ranks on Warcraft Logs only reflect *logged* kills. If a boss kill never gets uploaded, WCL doesn't know it happened and your progress rank won't count it — one more reason consistent logging matters.

## Switching things later

- **Mythic season starts?** Change `difficulty: heroic` to `mythic` in config.
- **Add M+?** Set `mplus.enabled: true` and list your raiders in the roster.
- **Monthly instead of weekly?** In `.github/workflows/weekly-board.yml`, change the cron line to `"0 13 1 * *"` (1st of each month) and set `lookback_days: 30` in config.
- **Different post time?** Cron is in UTC. `0 13 * * 2` = Tuesday 13:00 UTC = 9 AM ET.

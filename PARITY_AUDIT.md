# Data Parity Audit — Discord board vs Website

**Acceptance test:** the website must show everything the weekly Discord
guild board posts, plus more. This enumerates every Discord-board field and
where the site serves it. Generated data-backed twin: `site_data.parity`.

Source of the Discord fields: `guild_board/formatters.py` (`SECTION_FORMATTERS`)
and its section config in `config.yml`.

## Verdict: parity met on everything not blocked by external credentials

**7 live · 3 partial · 5 pending.** Every field has a website home. The 5
`pending` fields are blocked on the exact same credentials the Discord board
itself requires (Warcraft Logs, Blizzard, Discord bot token) — they are NOT
missing, they degrade to a documented empty shape and fill when a
credentialed refresh runs. On M+ the site **exceeds** the Discord board.

| # | Discord board field | Website location | State | Note |
|---|---|---|---|---|
| 1 | Guild Standing (realm/region/world) | `records_leaderboard.standing` | ✅ live | real |
| 2 | Overall Realm Rank | `records_leaderboard.standing` | ✅ live | real |
| 3 | M+ Weekly Keys | `competition.key_records` | ✅ **exceeds** | + per-dungeon highest |
| 4 | Season M+ Scores | `competition.rankings.overall` | ✅ **exceeds** | + by-role, by-class, movement |
| 5 | Season M+ Parses/Runs | `competition.characters[].best_runs` | ✅ **exceeds** | full per-char, timed/depleted |
| 6 | Most Improved | `competition.movement` | ✅ live | climbers + biggest gain |
| 7 | Raid Progression (bosses downed) | `island_completion.raid` | ✅ live | Raider.io, per-boss |
| 8 | Top DPS Parses | `competition.parses.leaders` | 🟡 partial | records only; full = WCL creds |
| 9 | Top Healing Parses | `competition.parses.leaders` | 🟡 partial | records only; full = WCL creds |
| 10 | Top Tank/overall Parses | `competition.parses` | 🟡 partial | WCL creds |
| 11 | Weekly Raid Boss Ranks | `island_completion.raid` | ⏳ pending | WCL realm/region ranks |
| 12 | Most Deaths | `competition` (field pending) | ⏳ pending | WCL creds |
| 13 | Roast of the Week | `guild_pulse` (fetcher built) | ⏳ pending | DISCORD_BOT_TOKEN |
| 14 | Guild Announcement / MOTD | `guild_pulse` (fetcher built) | ⏳ pending | DISCORD_BOT_TOKEN |
| 15 | Guild Achievements | `guild_achievements` | ⏳ pending | BLIZZARD creds |

## What the site adds beyond the Discord board (the "plus more")

- **Full browsable per-character detail** — every run, per-role score, realm
  & class ranks, prebuilt cross-realm links. The Discord board only shows
  top-5 summaries; the site lets you "go in and see the numbers".
- **By-role and by-class rankings** (top healer, top mage, …) — not on the
  Discord board.
- **Guild key levels cleared, per dungeon** — the Discord board shows only
  the single highest key.
- **`unranked` bucket** — the 35 members with no score yet, as a deliberate
  state rather than being silently dropped as the Discord board does.
- **Live Voyage Map / island completion, transmog diff, weekly recap** —
  entirely new surfaces.

## Cross-realm (launch blocker — resolved)

The guild is on **Bleeding Hollow**; the roster is genuinely cross-realm
(Bleeding Hollow 39, Area 52 18, Proudmoore 5, remainder mixed). Guild-level
endpoints correctly use `bleeding-hollow`; **every character is queried
against its own realm** via `config.split_name_realm`.

- **Verified:** the owner's characters resolve with real data —
  **Rakdisc-Proudmoore (rank 6, 3529)** and **Rakell-Proudmoore (rank 39,
  2995)**. 132 of 135 members resolved.
- Each character carries `realm_slug` + prebuilt `raiderio_url` /
  `warcraftlogs_url` so the front-end cannot reintroduce the guild-realm link
  bug.
- **Known separate issue (not the website):** `formatters.py`'s player links
  on the *Discord* board still use the guild realm (lines 42/75/119/353/380),
  so cross-realm members' links there are wrong. That's the web team's file
  and needs the M+ collectors to carry realm through; flagged for follow-up,
  does not affect the site.

## Fail-open

Every refresh keeps the last good data rather than blanking:
- `refresh_competition.py` keeps yesterday's cache if a bad Raider.io day
  resolves < 50% of last run's members.
- All builders degrade a missing input to a documented empty shape, never an
  exception.
- `site_data.parity` lets the front-end show "coming soon" for `pending`
  fields instead of a dead section.

## To close the 5 pending (all credential-gated)

| Pending | Unblock |
|---|---|
| Top parses, most deaths, raid boss ranks | `WCL_CLIENT_ID` / `WCL_CLIENT_SECRET` |
| Roast of the week, MOTD | `DISCORD_BOT_TOKEN` (+ `pulse_channels`) |
| Guild achievements | `BLIZZARD_CLIENT_ID` / `BLIZZARD_CLIENT_SECRET` |

All three refresh paths are built and wired; adding the secrets to the
GitHub Actions and running the refresh fills these with no code change.

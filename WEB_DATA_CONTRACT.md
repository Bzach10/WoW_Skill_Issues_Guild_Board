# Web Data Contract — for the website UI build

The backend emits JSON data layers the front-end reads for the WANTED BOARD
(competition), Voyage Map, islands, leaderboard, achievements, weekly recap
and the live Discord feed. This is the coordination surface between the
backend-data-qa branch and the website UI build session — **please raise
field-name/shape disagreements here before building against them.**

> **⭐ NEW — the `competition` layer is the headline (the WANTED BOARD).**
> It is real, live M+ data for 132 of 135 members TODAY (Raider.io public,
> no credentials), refreshed daily. See its section immediately below.
> This is the "root of the guild" data Zach wants front and center.

- Producer: `guild_board/web_data.py` (pure functions, unit-tested in
  `tests/test_web_data.py`).
- Season content source of truth: `guild_board/season.py` (verified live
  2026-07-21 — Midnight Season 1).
- Build: `python scripts/build_site_data.py [--live-dungeons]` →
  `web_data/site_data.json` plus one file per layer.
- **`schema_version` is on every envelope and every layer.** It is `1`.
  A breaking shape change bumps it; check it before parsing.

Fetch strategy: `site_data.json` is the whole bundle; each layer is also a
standalone file (`competition.json`, `recap_ribbon.json`,
`records_leaderboard.json`, `guild_achievements.json`,
`island_completion.json`, `transmog_changes.json`, `guild_pulse.json`,
`parses.json`) so a view can load just what it needs.

---

## ⭐ `competition` — the WANTED BOARD (M+ standings, live, daily)

The heart of the site. **Real data today**, no credentials: Raider.io public
API, 132/135 members resolved. Refreshed daily by
`scripts/refresh_competition.py` → `.github/workflows/daily-competition-refresh.yml`.
Every number is **browsable** — full per-character detail, not just a summary.

```json
{
  "schema_version": 1,
  "available": true,
  "season": {"slug": "season-mn-1", "name": "Midnight Season 1"},
  "based_on": "2026-07-20T12:14:49+00:00",
  "character_count": 132,

  "ranked_count": 97, "unranked_count": 35,
  "characters": [                       // FULL browsable detail, one per member
    {
      "name": "Amrevenge", "key": "amrevenge-stormrage",
      "realm": "Stormrage", "realm_slug": "stormrage",
      "raiderio_url": "https://raider.io/characters/us/stormrage/amrevenge",
      "warcraftlogs_url": "https://www.warcraftlogs.com/character/us/stormrage/amrevenge",
      "class": "Hunter", "spec": "Beast Mastery Hunter", "role": "DPS",
      "score": 3908.1,
      "scores_by_role": {"dps": 3908.1, "healer": 0, "tank": 0},
      "delta_week": 13.3, "is_new": false,
      "rank": 1, "top5": true,
      "best_runs": [
        {"dungeon": "Pit of Saron", "short": "POS", "level": 20,
         "timed": true, "upgrades": 1, "score": 492.2,
         "clear_ms": 1456281, "par_ms": 1800999}
      ],
      "ranks": {"realm_overall": 841, "realm_class": 27, "region_overall": 9122},
      "parse": {"best": 97, "boss": "Fallen-King Salhadaar", "source": "board_state"}
    }
  ],

  "rankings": {
    "overall":  [ {rank,name,key,score,class,spec,role,top5,delta_week,is_new}, … ],
    "by_role":  {"Tank": [...], "Healer": [...], "DPS": [...]},   // ranked within role
    "by_class": {"Hunter": [...], "Priest": [...], … },           // ranked within class
    "top5":     [ first 5 of overall ]                            // special treatment
  },

  "movement": {
    "climbers":     [ {name,key,delta_week}, … ],   // gained score this week, desc
    "new_to_board": [ {name,key,score}, … ],        // on the board, weren't last week
    "biggest_gain":  {name,key,delta_week}          // or null
  },

  "parses": {
    "available": "partial",     // "partial" | "none" | (future) "full"
    "source": "board_state records (WCL enrichment pending WCL creds; Raider.io has no parses)",
    "leaders": [ {name,parse,boss,role,spec}, … ]
  },

  "unranked": [ {name,key,class,spec,role}, … ],   // no season score YET
  "key_records": {                                  // guild key levels cleared
    "highest_overall": {dungeon,level,name,key},
    "by_dungeon": [ {dungeon,level,name,key,score}, … ],  // null level = none timed
    "dungeons_timed": 8, "dungeon_total": 8
  }
}
```

**⚠️ CROSS-REALM — use the prebuilt URLs.** The guild is on Bleeding Hollow
but 70% of the roster (incl. the owner's Rakdisc/Rakell on **Proudmoore**)
is cross-realm. Each character carries its own `realm_slug`, `raiderio_url`
and `warcraftlogs_url`. **Build links from these, never from the guild
realm** — doing so blanks every cross-realm member's link.

**⚠️ `unranked` is deliberate.** 35 members have no season score yet.
They're in `unranked` (and in `characters` with `rank: null`), NOT missing.
Render as "yet to set sail" / dimmed — never a blank or broken row.

### `parity` — the data parity floor (every Discord-board field)

`site_data.parity` maps each weekly-Discord-board field to where the site
serves it and its state, so you can guarantee no section renders dead:

```json
"parity": {
  "summary": {"live": 7, "partial": 3, "pending": 5, "total": 15},
  "fields": [ {"field": "mplus_weekly_keys", "served_by": "competition.key_records",
               "state": "live", "note": null}, … ]
}
```

`state` ∈ `live` (real now) · `partial` (some now, fuller with creds) ·
`pending` (structurally present, needs a credentialed refresh). All 5
`pending` are credential-blocked (WCL parses, most-deaths, roast, MOTD,
guild achievements) — the same creds the Discord board itself needs — and
each degrades to a documented empty shape you can render as "coming soon".

**Notes for the WANTED BOARD (bounty = M+ score):**
- `characters[]` is the browsable detail — render a bounty poster per member,
  drill in for `best_runs`, `scores_by_role`, `ranks`. `rank` is the
  guild-internal overall rank; `top5` flags the poster boys.
- `by_role`/`by_class` are separately ranked so you can show "top healer",
  "top mage", etc. **Roles are `Tank`/`Healer`/`DPS`** — normalized (Raider.io
  actually returns `HEALING`, handled backend-side).
- `movement` is the living-competition signal (climbers / new / biggest gain).
- `best_runs[].timed` = keystone upgraded (true) vs depleted (false).
- **`delta_week` can be `null`** for a member with no baseline yet — treat as
  "no movement data", not zero.
- **Parses are partial.** Raider.io exposes no parse percentiles, so `parse`
  is only present for the handful in `board_state` records (real WCL numbers
  from the weekly board). Full per-boss/average parses need WCL creds — the
  block says so via `parses.available`. Don't render a parse column as if
  every member has one; gate on `character.parse != null`.

**Discord:** the daily board also posts to Discord via the existing webhook
(top 5 embed + a "📱 Web Board" button to the site). Gated behind
`config competition.daily_post` (off by default). See §Discord below.

### Build against the committed sample — no backend run needed

`samples/site_data.sample.json` (+ one `*.sample.json` per layer) is a
committed bundle you can develop against directly. It is generated through
the **real producers** (`scripts/build_sample_site_data.py`), so the shapes
are identical to production — only the values are illustrative, and every
file carries `"_sample": true`.

Crucially it shows every **populated** UI state that today's live data does
not: a filled trophy hall (`available: true`, 3 trophies), dungeon islands
in all three states (`conquered` / `attempted` / `locked`), confirmed vs
inferred raid bosses, and a real transmog change. A guard test keeps it in
lockstep with the producers, so it can't silently go stale.

### Where the LIVE bundle lives

Three locations, clearly separated:

| Path | Tracked? | What it is |
|------|----------|------------|
| `samples/*.sample.json` | committed | Dev fixtures — build against these now. |
| `web_data_public/*.json` | committed by the Action | **The live served bundle.** Populated in the cloud. |
| `web_data/*.json` | gitignored | Local `build_site_data.py` scratch output. |

The **cloud path** (`web_data_public/`) is produced by the Blizzard Refresh
GitHub Action, which holds the credentials — no local secret handling. It
runs weekly (and on demand) and commits the refreshed bundle. Point the
production site at `web_data_public/`; use `samples/` until it first fills.

---

## 1. `recap_ribbon` — story-of-the-week

Auto-generated from the week-over-week diff already in `board_state.json`
(it carries a `baseline` snapshot). Ordered: records first, then by
notability.

```json
{
  "schema_version": 1,
  "week_of": "2026-07-14",
  "based_on": "2026-07-20T12:00:00+00:00",
  "beats": [
    {
      "kind": "biggest_key",
      "headline": "+20 Pit of Saron",
      "detail": "Amrevenge timed the guild's biggest key as Beast Mastery Hunter",
      "subject": "Amrevenge",
      "value": 20,
      "emphasis": "record",
      "is_new": true
    }
  ],
  "beat_count": 6
}
```

- `kind` ∈ `biggest_key`, `best_dps_parse`, `best_hps_parse`,
  `biggest_climber`, `new_on_ladder`, `standing_move`, `transmog`.
- `emphasis` ∈ `record` > `big` > `normal` — use it to weight/size the card.
- `beats` is already trimmed to `max_beats` (default 6) and sorted; render
  in order. `beat_count` is the pre-trim total.

## 2. `records_leaderboard` — sortable season dataset

```json
{
  "schema_version": 1,
  "standing": {"realm": 49, "region": 2219, "world": 6855},
  "headline_records": [
    {"id": "highest_timed_key", "label": "Biggest Timed Key",
     "holder": "Amrevenge", "value": 20, "unit": "key_level",
     "context": "Pit of Saron", "spec": "Beast Mastery Hunter", "is_new": true}
  ],
  "ladder": [
    {"rank": 1, "name": "Amrevenge", "key": "amrevenge", "score": 3908.1,
     "delta_week": 0.0, "streak_weeks": 1, "is_new": false}
  ],
  "ladder_size": 96,
  "sortable_by": ["score", "delta_week", "streak_weeks", "rank"]
}
```

- Rows arrive score-descending as a default; every row carries all
  `sortable_by` keys, so **sort client-side** — no re-fetch needed.
- `key` is the raw lowercase id (for lookups/joins); `name` is display.
- `headline_records[].unit` ∈ `key_level`, `percentile`.

## 3. `guild_achievements` — Midnight trophy hall

**Fills automatically from the cloud.** The Blizzard Refresh Action now runs
`scripts/refresh_guild_data.py` (it holds the repo secrets), which fetches
`/data/wow/guild/{realm}/{name}/achievements` and commits
`blizzard_guild_cache.json`; `build_site_data.py` reads it and this layer
flips to `available: true`. Until that Action's first credentialed run it
stays `available: false` — the shape is identical either way, so build the
trophy hall now and it populates without a code change. **No local secret
handling is required.**

```json
// pending state (today):
{"schema_version": 1, "available": false, "status": "pending_credentials",
 "source": "/data/wow/guild/{realm}/{name}/achievements",
 "total_points": 0, "trophies": []}

// populated state (once creds exist):
{"schema_version": 1, "available": true, "status": "ok",
 "total_points": 1234, "trophy_count": 42,
 "trophies": [
   {"id": 15001, "name": "Ahead of the Curve: Imperator Averzian",
    "completed_at": "2026-05-02T…Z",
    "criteria": {"is_completed": true, "child_count": 2}}
 ]}
```

**Gate on `available`.** When false, render an empty/"coming soon" hall —
`trophies` is `[]`, never fabricated.

## 4. `island_completion` — Voyage Map conquered status

Drives the clickable islands. Dungeon status is real today (Raider.io);
per-boss raid detail is partly inferred until guild achievements are wired.

```json
{
  "schema_version": 1,
  "season_slug": "season-mn-1",
  "season_name": "Midnight Season 1",
  "dungeons": {
    "conquered": 2, "total": 8,
    "islands": [
      {"id": "pit-of-saron", "name": "Pit of Saron", "kind": "dungeon",
       "challenge_mode_id": 556, "status": "conquered",
       "best_level": 20, "timed": true, "held_by": "Amrevenge"}
    ]
  },
  "raid": {
    "slug": "tier-mn-1", "display_name": "Voidspire Sanctum",
    "summary": "3/9 M", "bosses_killed": 5, "total_bosses": 9,
    "killed_by_difficulty": {"normal": 0, "heroic": 5, "mythic": 3},
    "detail_source": "raid_progression_count",
    "islands": [
      {"id": "imperator-averzian", "name": "Imperator Averzian",
       "kind": "raid_boss", "order": 1, "status": "conquered",
       "kill_confirmed": true, "inferred_from_progress": false,
       "first_kill_at": "2026-03-03T01:06:40+00:00"}
    ]
  }
}
```

- Dungeon `status` ∈ `conquered` (timed), `attempted` (run, not timed),
  `locked` (untouched).
- **`raid.detail_source`** tells you how to trust the per-boss data:
  - `guild_achievements` — authoritative. Every `kill_confirmed: true` boss
    has a real `first_kill_at`; anything not in the achievement list is
    `locked`. This is what the cloud Action produces.
  - `raid_progression_count` — fallback before the Action has run. Bosses
    within the kill count are `inferred_from_progress: true` (pull-order
    guess, `first_kill_at: null`).
- **Raid honesty flags:** `kill_confirmed` = a real, dated kill.
  `inferred_from_progress` = a pull-order guess from the aggregate count.
  **If you show an inferred boss as "conquered", give it a subtler
  treatment than a confirmed one** — and it can flip to `locked` once the
  authoritative achievement data arrives.
- The cloud Action passes `--live-dungeons`, so the served bundle has real
  dungeon data. A local build needs `--live-dungeons` too, else dungeons
  read `locked` (no cached bests).

## 5. `transmog_changes` — "what changed this week"

Before/after diff from the transmog fingerprint, baseline-snapshot pattern.

```json
{
  "schema_version": 1,
  "is_first_run": false,
  "changed": [
    {"slug": "rakdisc-proudmoore", "name": "Rakdisc", "class": "Priest",
     "spec": "Discipline", "render_url": "https://…-main-raw.png",
     "before_fingerprint": "OLD…", "after_fingerprint": "AAA…"}
  ],
  "changed_count": 1,
  "new_characters": [{"slug": "…", "name": "…"}],
  "snapshot": {"rakdisc-proudmoore": "AAA…"}
}
```

- **`is_first_run: true` → `changed` is `[]` by design** (baseline seeded;
  the ribbon must not announce that the whole cast re-transmogged).
- `snapshot` is bookkeeping the builder persists for next week — the
  front-end can ignore it.
- The manifest has no *image* diff yet (art regenerates async), so this
  reports that a look changed, not a before/after picture, until the art
  pipeline emits both versions.

## 6. `guild_pulse` — the living Discord feed (hangout heartbeat)

A rolling feed of guild-**public** Discord highlights: chat moments, memes,
banter, notable reactions. Fed by the existing read-only bot; **no new bot,
no new permissions.**

```json
{
  "schema_version": 1,
  "available": true,
  "status": "ok",
  "source": "read-only Discord bot, allowlisted guild-public channels",
  "item_count": 24,
  "by_kind": {"chat": 10, "memes": 9, "gambling": 3, "banter": 2},
  "media_note": "Discord CDN urls may expire; refresh the feed rather than hotlinking indefinitely.",
  "items": [
    {
      "author": "Tommybravoo",
      "snippet": "we timed the +21 with 4 seconds left, @Amrevenge soloed the last boss",
      "channel": "general",
      "kind": "chat",
      "timestamp": "2026-07-20T02:14:00+00:00",
      "reactions": [{"emoji": "🔥", "count": 12}, {"emoji": "😭", "count": 3}],
      "media": [],
      "has_media": false
    },
    {
      "author": "Healyeah", "snippet": "made this for the raid team",
      "channel": "memes", "kind": "memes",
      "timestamp": "2026-07-18T15:22:00+00:00",
      "reactions": [{"emoji": "🤣", "count": 21}, {"emoji": ":kekw:", "count": 14}],
      "media": [{"url": "https://cdn.discordapp.com/…/meme.png",
                 "content_type": "image/png", "width": 800, "height": 600,
                 "is_image": true, "filename": "meme.png"}],
      "has_media": true
    }
  ]
}
```

- `items` are newest-first, already privacy-filtered (see below). `kind` ∈
  whatever the config assigns per channel (`chat`, `memes`, `banter`,
  `gambling`, …) — group/tab by it.
- `author` is a **display name only** — the feed never carries a numeric
  user id or discriminator.
- `reactions`: unicode emoji as the character, custom guild emoji as
  `:name:`.
- `media`: uploaded images/clips **and** embedded gifs/videos.
  ⚠️ **Discord CDN urls can be signed/expiring — re-fetch the feed rather
  than caching a url indefinitely.** A living feed does this anyway.
- **Degraded state:** `available: false`, `status: "pending_discord_refresh"`,
  `items: []` until the credentialed Discord refresh runs. Gate on
  `available` and show an empty/"quiet in here" state — never fabricated.

### Privacy model (four layers, all enforced backend-side)

1. **Allowlist only.** Only channels in `config → discord_inputs.pulse_channels`
   are ever read. DMs and private channels are never in that list, and the
   bot physically cannot read a channel it lacks View + Read Message History
   on. There is no "read the whole server" path.
2. **Per-message opt-out.** React 🙈 (configurable) **or** put `[nofeed]`
   (configurable) in a message → it never enters the feed. No mod action.
3. **Content blocklist.** Configurable substrings drop any matching message.
4. **Bot messages skipped; display names only.**

The front-end does not need to enforce any of this — it arrives clean. But
worth a line in the UI ("react 🙈 to hide a message from the site") so
members know the opt-out exists.

## 7. `parses` — per-character WCL parse averages (credential-gated)

Current-tier Warcraft Logs **best-performance averages** per character —
the second axis of the Four Emperors ranking (Emperor Index = equal blend
of M+ score/top-score and parse-avg/100), the standings parse columns, and
the newspaper's raid sections. Refreshed by `scripts/refresh_parses.py` →
`.github/workflows/wcl-parse-refresh.yml` (WCL credentials exist only in
Actions; the script is inert locally).

```json
{
  "schema_version": 1,
  "available": true,
  "status": "ok",
  "source": "Warcraft Logs character zoneRankings",
  "season": {"slug": "season-mn-1", "name": "Midnight Season 1"},
  "tier": {"zone_id": 46, "name": "Voidspire Sanctum"},
  "sourced_at": "2026-07-24T13:30:00+00:00",
  "difficulty_scale": {"mythic": 1.0, "heroic": 0.8, "normal": 0.0, "lfr": 1.0},
  "character_count": 27,
  "characters": {
    "amrevenge-stormrage": {
      "name": "Amrevenge", "key": "amrevenge-stormrage", "class": "Hunter",
      "best_perf_avg": 92.4,          // RAW 0-100 percentile average (display)
      "scaled_perf_avg": 92.4,        // raw x difficulty factor — the Emperor axis
      "difficulty_scale": 1.0,        // the factor that was applied
      "median_perf_avg": 81.0,        // optional
      "by_role": {                    // only roles with real rankings (raw values)
        "DPS": {"best_perf_avg": 92.4, "kills": 7}
      },
      "difficulty": 5,                // WCL difficulty the data comes from (5=M, 4=H, 3=N)
      "tier": {"zone_id": 46, "name": "Voidspire Sanctum"},
      "sourced_at": "2026-07-24T13:30:00+00:00"
    }
  }
}
```

- **Rankings (Emperor Index) consume `scaled_perf_avg`; displays show
  `best_perf_avg`** (label it with `difficulty`, e.g. "92.4 · Mythic").
  The factors live in config.yml → `parses.difficulty_scale` (officer
  editable), are applied at BUILD time (retuning needs only a bundle
  rebuild, no WCL re-pull), and the envelope's `difficulty_scale` records
  what was applied. Scaled values are capped at 100. `by_role` values are
  raw; multiply by the character's `difficulty_scale` if you need them
  discounted (all of a character's blobs come from the same difficulty).
- **A factor of `0` means that difficulty is EXCLUDED**, not zeroed:
  its characters never appear in `characters` at all (render your normal
  "no logs yet" state) and the refresh sweep skips the difficulty
  entirely. Live config currently excludes `normal`. You will therefore
  never see a `difficulty: 3` entry, or a `scaled_perf_avg` of exactly 0
  from scaling, in a bundle built with that config.

- **⚠️ Keyed by the FULL `name-realm` key, exact Unicode**
  (`"violënce-bleeding-hollow"`) — the same `key` the competition layer
  uses, so joining is a dict lookup. Never join on bare names: same-named
  characters exist on different realms.
- Only characters with real rankings appear; a member with no logged kills
  at any difficulty is simply absent (render "no logs yet", not 0%).
- Per-character `difficulty` matters: parses are only comparable within one
  difficulty. Each character carries the highest difficulty they have data
  for (mythic → heroic → normal walk).
- Also merged into `competition.characters[].parse` as
  `{"best", "scaled", "by_role", "difficulty", "source": "wcl_zone_rankings"}`
  — and `competition.parses.available` becomes `"full"` when this layer is
  populated. Characters the sweep missed keep the old
  `{"best", "boss", "source": "board_state"}` fallback shape, so gate on
  `parse.source` if you need to distinguish an average from a single-boss
  record.
- **Degraded state:** `available: false`, `status: "pending_credentials"`,
  `characters: {}` until the credentialed Action has run. Gate on
  `available`.

---

## Discord publishing (verified working)

The existing webhook path (`guild_board.discord.post_to_discord`) posts the
daily board **and** a site link — confirmed by a dry-run against the real
data:

- **(a) Daily board summary**: a bounty-style embed of the top 5 with medals,
  scores, specs, and a movement footer (biggest climb / new to board).
- **(b) Site link**: a "📱 Web Board" button → `display.web_board.url`
  (already set to `https://bzach10.github.io/wow-guild-board/`), alongside a
  "Guild Logs" button.

Handles Discord 429 rate-limits and retries without buttons if a channel
webhook rejects components. Needs `DISCORD_WEBHOOK_URL` (already a repo
secret, used by the weekly board).

**What it can't do:** it's a fire-and-forget webhook — no slash commands, no
editing prior messages, no reading responses. For posting a daily board +
link that's all that's needed. It is **gated off** (`competition.daily_post:
false`) so the daily Action refreshes data without auto-posting until Zach
flips it on.

## Open coordination questions for the UI session

1. **Field names** — happy to rename anything here to match your component
   props. Cheapest to change now.
2. **`is_new` vs `emphasis`** in the ribbon — is a boolean + a 3-level enum
   the right split, or do you want a single numeric weight?
3. **Inferred raid bosses** — do you want them visually distinct from
   confirmed kills, or is "conquered is conquered" fine for v1?
4. **Ladder size** — 96 rows. Do you want it pre-paginated server-side, or
   is the full list fine to ship and virtualise client-side?

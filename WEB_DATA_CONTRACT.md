# Web Data Contract — for the website UI build

The backend emits five JSON data layers the front-end reads for the Voyage
Map, islands, leaderboard, achievements and weekly recap. This is the
coordination surface between the backend-data-qa branch and the website UI
build session — **please raise field-name/shape disagreements here before
building against them.**

- Producer: `guild_board/web_data.py` (pure functions, unit-tested in
  `tests/test_web_data.py`).
- Season content source of truth: `guild_board/season.py` (verified live
  2026-07-21 — Midnight Season 1).
- Build: `python scripts/build_site_data.py [--live-dungeons]` →
  `web_data/site_data.json` plus one file per layer.
- **`schema_version` is on every envelope and every layer.** It is `1`.
  A breaking shape change bumps it; check it before parsing.

Fetch strategy: `site_data.json` is the whole bundle; each layer is also a
standalone file (`recap_ribbon.json`, `records_leaderboard.json`,
`guild_achievements.json`, `island_completion.json`, `transmog_changes.json`)
so a view can load just what it needs.

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

---

## Open coordination questions for the UI session

1. **Field names** — happy to rename anything here to match your component
   props. Cheapest to change now.
2. **`is_new` vs `emphasis`** in the ribbon — is a boolean + a 3-level enum
   the right split, or do you want a single numeric weight?
3. **Inferred raid bosses** — do you want them visually distinct from
   confirmed kills, or is "conquered is conquered" fine for v1?
4. **Ladder size** — 96 rows. Do you want it pre-paginated server-side, or
   is the full list fine to ship and virtualise client-side?

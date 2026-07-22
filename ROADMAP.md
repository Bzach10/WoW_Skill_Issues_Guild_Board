# Guild Board Website — Build Roadmap

The agreed build order. Full idea specs live in `WEBSITE_IDEAS.md`; this
file is the *sequence* and its live status, updated as milestones land.

Zach folded four new ideas (2026-07-21) into the existing order — placed
below at their sensible points, not appended.

## Order & status

| # | Milestone | Status |
|---|---|---|
| — | **Foundation** — nav + back-to-board, scenes in live build, name legibility, blended edges, filled sides | ✅ shipped |
| — | **Fast Wins** — recap ribbon, sticky roster nav + search, tooltips, click-emote, lazy-load | ✅ shipped |
| 1 | **Settings Panel** — local-only admin, live preview, writes config | ✅ shipped |
| 2 | **Voyage Map landing page** — the map *is* the homepage; ship docked at the live current-season port, cast on deck. **Folds in VOY-07: the 12 scene dioramas ARE the ports** — docking at a port opens that scene. | ✅ shipped (VOY-07 in) |
| 3 | **Full-cast hero wall** — all 131 in one animated hall (B-02) | ✅ shipped (The Hall) |
| 4 | **Clickable voyage islands** — click an island → its dungeon/raid data + completion state (X-05). Folds in the backend's island-completion feed. | ✅ shipped (badge + live detail; feed still parked) |
| 5 | **Unlock-the-Cast meter (ENG-10)** — generated-vs-remaining progress; un-generated members as wanted-poster silhouettes. Makes the rollout itself content. Sits well beside the hero wall / roster. | ▶ in progress |
| 6 | **Weekly 2-panel manga strip (ANIM-08)** — scene stills + speech bubbles + real recap events. Reuses existing scene stills; consumes the backend recap feed (same source as the ribbon). | ⏳ |
| 7 | **Cameo-Debt Tracker (ARC-09)** — track which characters have/haven't been featured; bias future casting toward never-featured members. **Casting logic — coordinate a `featured_history` data shape with the backend/creative session.** | ⏳ |
| 8+ | **The rest** — real profile pages polish, living-diorama backdrops, transmog "what changed", achievements trophy hall, records leaderboard hub, result-driven poses, trading-card export, remaining polish (WebP/AVIF, skeleton states, grid rhythm, reduced-motion, persisted state, week archive) + remaining interactions (parallax, drag-to-arrange, boss-kill burst, emote reactions, ambient FX, spin-the-wheel) | ⏳ |

## The four folded-in ideas — where and why

- **VOY-07 (scenes as ports)** → *inside milestone 2*. The 12 monthly
  scenes become the voyage's ports; the season's dungeon/raid data still
  rides the map, but the visible ports are the dioramas. Natural merge:
  the art we already made becomes the map.
- **ENG-10 (unlock meter)** → *milestone 5*, beside the hero wall, since
  both are about the whole 131-strong cast at once.
- **ANIM-08 (manga strip)** → *milestone 6*. Display-only build; art
  reuses scene stills, text comes from the recap feed that already
  drives the ribbon.
- **ARC-09 (cameo-debt)** → *milestone 7*. It is casting logic, so it
  needs a `featured_history` feed; parked until that data is agreed with
  the backend/creative session.

## Data coordination (backend session)

Built against contracts so features light up when feeds land:
- `recap.json` — recap ribbon (live now), later the manga strip
- island-completion feed — clickable islands (milestone 4)
- `featured_history` — cameo-debt casting (milestone 7)

Until a feed lands, each feature degrades to the live Raider.io / board
data already on disk.

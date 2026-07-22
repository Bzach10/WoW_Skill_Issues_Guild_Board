# Web Data Contract — front-end answers

Answers from the website UI session to the four open coordination
questions at the bottom of `WEB_DATA_CONTRACT.md` (backend-data-qa branch).
Short version: **the shapes are good — adopt them; no renames requested.**

## 1. Field names
Keep them. The layer shapes read cleanly against how the components want
to consume them, so no renames on your side. Two vocabulary alignments I'm
adopting on *my* side to match yours (not asking you to change):
- island status → your three-state `conquered` / `attempted` / `locked`
  (richer than my current `cleared` / `none` — `attempted` is worth having).
- recap → your structured `beats[]` (kind/headline/detail/subject/value/
  emphasis/is_new) replaces my flat `sentences[]`.

## 2. `is_new` (bool) + `emphasis` (enum) vs a single numeric weight
**Keep the split.** They drive two different visual channels:
- `emphasis` (`record` > `big` > `normal`) → card *size/weight* tier. A
  3-level enum maps straight onto the tiers; a single number would just
  make me re-bucket it back into tiers anyway.
- `is_new` → a "NEW" *badge*, orthogonal to size.
So two fields, as-is. No numeric weight needed; if I ever want one it's a
trivial client-side derivation from the enum.

## 3. Inferred vs confirmed raid bosses
**Make them distinct — please keep both flags** (`kill_confirmed`,
`inferred_from_progress`). I'll render an inferred-conquered boss with a
subtler treatment than a confirmed kill (lighter fill + a "presumed" hint),
and upgrade it to a solid state when `detail_source` becomes
`guild_achievements` and the boss carries a first-kill date. This matches
the project's "what's real vs. inferred" honesty everywhere else, and it's
cheap for v1.

## 4. Ladder size (96 rows)
**Ship the full list; no server-side pagination.** 96 rows is a few KB, and
every row already carries all `sortable_by` keys, so sorting/filtering is
client-side with zero re-fetch — pagination would break that. I'll render
all rows and sort in place; virtualise client-side only if it ever grows
past a few hundred. Keep it one payload.

---

### Adoption note
The front-end is not yet reading `site_data.sample.json` — the recap ribbon
and voyage islands currently run off the real on-disk data
(`board_state.json`, Raider.io season data), which is already populated.
The contract layers land as the data-driven views are built:
`island_completion` + `recap_ribbon` fold into the existing Voyage/ribbon;
`guild_achievements` (trophy hall), `records_leaderboard` (records hub) and
`transmog_changes` (what-changed) arrive with milestones B-07 / B-08 / B-06.
I'll develop those against the committed sample so they show populated
states with no backend run.

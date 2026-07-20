# Setting up the Blizzard character-profile integration

This is scaffolding for future character-likeness features (transmog-render
art, gender/race/class/spec data) — the board itself doesn't use any of this
yet. Warcraft Logs and Raider.io don't expose transmog renders, so this
pulls them straight from Blizzard's own Character Media API. Everything here
is off until both steps below are done; nothing about the existing weekly
board changes in the meantime.

## 1. Create a Battle.net developer app (~5 minutes)

1. Go to <https://develop.battle.net/access/clients> and sign in with the
   Battle.net account you want to own this API client.
2. Click **Create Client**. Name it anything (e.g. "Guild Board Profiles").
   Redirect URL doesn't matter for this — this integration authenticates
   directly with the Client ID and Secret (client-credentials grant), the
   same pattern the Warcraft Logs setup already uses. Any placeholder URL
   (e.g. `https://localhost`) satisfies the form.
3. Once approved (usually instant, occasionally a short manual review),
   save the **Client ID** and **Client Secret**.

## 2. Add the two repo secrets

In this repo: **Settings → Secrets and variables → Actions → New repository
secret**. Add:

| Secret name | Value |
|---|---|
| `BLIZZARD_CLIENT_ID` | from step 1 |
| `BLIZZARD_CLIENT_SECRET` | from step 1 |

## 3. Flip the config toggle

In `config.yml`, set:

```yaml
blizzard:
  enabled: true
```

That's the whole setup. `blizzard.enabled: false` (the shipped default) and
missing secrets are both independent no-ops — either one being absent means
the refresh step does nothing and logs why, without failing the run.

## What runs, and when

A separate workflow, **Blizzard Profile Refresh**
(`.github/workflows/blizzard-profile-refresh.yml`), runs 15 minutes after
the weekly board every Tuesday (13:15 UTC) and can also be triggered by hand
from the **Actions** tab. It:

1. Reads the roster already cached in `roster_cache.json` (written by the
   weekly board run — no separate roster fetch needed).
2. Gets a Blizzard OAuth token via `guild_board.blizzard.get_blizzard_token`
   (client-credentials grant against `oauth.battle.net/token` — mirrors
   how `wcl.get_wcl_token` talks to Warcraft Logs).
3. For each character, fetches gender, race, class, active spec, and the
   character-media render URLs (`avatar` and `main-raw`, the full current
   -transmog portrait) from `/profile/wow/character/{realm}/{name}` and its
   `/specializations` and `/character-media` sub-resources.
4. Merges the results into `blizzard_profile_cache.json` (same shape/rules
   as `roster_cache.json`: unioned with what's already cached, so a
   character that's temporarily unreachable doesn't get dropped) and
   commits it back, same as the existing roster-cache commit step.

A character that's private, renamed, deleted, or just errors out is skipped
individually — it never aborts the rest of the batch, and never fails the
job. This is a pure data refresh (no image rendering, no GPU), so it's
fully automatable on GitHub's free runners.

## What's NOT built yet (on purpose — scaffolding only)

- Nothing reads `blizzard_profile_cache.json` for rendering yet — no board
  template, no IP-Adapter/img2img conditioning, no cast-image pipeline
  wiring. That's the next phase once this cache is populated and Zach's
  approved the approach.
- No admin UI for the cache — it's a plain JSON file, same as
  `roster_cache.json` and `board_state.json`.

## Files this adds

| File | Purpose |
|---|---|
| `guild_board/blizzard.py` | OAuth token fetch, per-character profile+media fetch, cache load/save/refresh |
| `scripts/refresh_blizzard_profiles.py` | CLI entry point the workflow runs |
| `.github/workflows/blizzard-profile-refresh.yml` | Scheduled + manual trigger |
| `blizzard_profile_cache.json` | Generated and committed on first successful run, same convention as `roster_cache.json` (not gitignored) |
| `blizzard.enabled` / `blizzard.cache_file` in `config.yml` | The on/off switch + cache path |

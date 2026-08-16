# Daily refresh runbook — how the data bundle stays fresh, whole, and honest

**Written 2026-07-24**, the day the 2026-07-23 split-brain bundle was fixed at
the source. Companion to `docs/DATA_PIPELINE.md` (credentials & contexts) and
`data/FIELD_CONTRACT.md` in wipefest-hub (layer shapes).

## The one-paragraph version

`refresh_competition.py` pulls fresh M+ data from Raider.io (public, no
credentials) into `competition_cache.json`. `build_site_data.py` rebuilds the
ENTIRE bundle — `site_data.json` plus every per-layer file — from that cache
plus the committed weekly caches, in one run. `validate_bundle.py` then
refuses any bundle whose layers disagree, and only a validated bundle is
committed (in CI) or delivered to a consumer (`deliver_bundle.py`). **No step
ever updates one layer file by hand. That is how 2026-07-23 happened.**

## What went wrong on 2026-07-23 (the incident this pipeline prevents)

A session refreshed competition data and hand-delivered `competition.json`
alone to the hub's `data/` directory. The digest layers
(`records_leaderboard.json`, `recap_ribbon.json`) kept week-old numbers —
stale ladder scores, a biggest-climber beat naming the wrong character — and
every file *claimed the same `based_on` stamp*, because the competition layer
copied its stamp from the weekly board_state instead of its own pull.
The downstream redesign's contract guard caught it a day later.

Three fixes, all on `main` now:

1. **Truthful stamps** — the competition layer's `based_on` is its own pull
   time; `week_baseline_from` names the weekly snapshot its `delta_week`
   figures are measured against. Weekly layers (recap, records) keep the
   weekly stamp. Two cadences, both visible, neither lying.
2. **`scripts/validate_bundle.py`** — the cross-layer gate. Checks that every
   standalone layer equals its copy inside `site_data.json` (catches partial
   copies), that the daily layer agrees with itself (counts / contiguous
   ranks / no score drift), that the weekly layers tell one story (recap's
   climber vs the ladder's own delta column), and that stamps are coherent.
   Exit 1 = bundle refused.
3. **`scripts/deliver_bundle.py`** — the only sanctioned local hand-off to a
consumer. Validates first, delivers the complete set or nothing, writes a
`DELIVERY.json` provenance manifest, and never touches consumer-local
files (`roster_supplement.json`).

Production does not depend on that local copy command. Every successful
bundle-producing workflow wakes `.github/workflows/publish-website.yml`,
which calls the Cloudflare Pages deploy hook and waits until the public
copy of `site_data.json` byte-matches the source bundle. Configure
`WEBSITE_DEPLOY_HOOK_URL` and `WEBSITE_HEALTH_URL` as repository secrets.
The local delivery command remains the supported Windows development path.

## The daily cycle (automated — GitHub Actions)

`.github/workflows/daily-competition-refresh.yml`, cron `0 14 * * *` UTC +
`workflow_dispatch`. Steps: refresh → rebuild bundle → **validate** →
(gated Discord post) → commit `competition_cache.json` + `web_data_public/`
in one commit. A validation failure stops the run; nothing partial is ever
committed. Requires no credentials for the refresh itself (Raider.io is
public); `DISCORD_WEBHOOK_URL` only gates the optional post step.

`.github/workflows/wcl-parse-refresh.yml`, cron `30 14 * * *` UTC +
`workflow_dispatch`, is the credentialed sibling: `refresh_parses.py` pulls
per-character current-tier parse averages from Warcraft Logs into
`parses_cache.json` (the `parses` layer + `competition.characters[].parse`),
then the same rebuild → validate → commit chain. It needs `WCL_CLIENT_ID` /
`WCL_CLIENT_SECRET` (Actions secrets only); locally the script is inert and
the layer degrades to `available: false`.

## Manual run (Windows host)

```
cd C:\dev\wipefest-board            # or the main worktree
python scripts/refresh_competition.py
python scripts/build_site_data.py --live-dungeons
python scripts/validate_bundle.py web_data
python scripts/deliver_bundle.py    # -> C:\dev\wipefest-redesign\data\source
```

Then in the consumer:

```
cd C:\dev\wipefest-redesign
python data\build_contract.py       # its own guard re-verifies
python site\_build\build.py
```

`--live-dungeons` does a full-roster Raider.io sweep (~1 min); omit it to
reuse the cached dungeon bests. `deliver_bundle.py --dry-run` validates and
reports without copying.

## What the validator refuses, and why

| section | meaning | typical cause |
|---------|---------|---------------|
| `presence` | a layer file missing/unparseable | interrupted build |
| `parity` | layer file != its site_data embed | files from two builds mixed — the 2026-07-23 defect |
| `competition` | counts/ranks/scores disagree internally | producer bug — do not ship, fix the code |
| `weekly` | recap beats contradict the ladder/records they digest | board_state edited by hand, or producer bug |
| `stamps` | weekly layers carry different based_on; baseline mismatch | files from two builds mixed |

A `stamps` WARNING (daily stamp older than weekly) means the daily refresh
is not actually running — check the Action.

## Cadence, so nobody "fixes" it wrongly

`recap_ribbon` and `records_leaderboard` are **weekly** layers (from
`board_state`, the weekly board's snapshot: streaks, week-over-week ladder,
story of the week). `competition` is **daily** (live Raider.io). Mid-week,
the weekly ladder's scores WILL trail the daily rankings — that is not a
bug, and the validator deliberately does not flag it. The bug would be the
stamps hiding it. Consumers that want one truth (the redesign) use the daily
`rankings.overall` and reconcile or drop weekly duplicates — which its
contract build already does.

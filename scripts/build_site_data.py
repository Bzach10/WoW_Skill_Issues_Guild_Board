"""Build web_data/site_data.json — the data bundle the front-end reads.

Loads the real inputs (board_state.json, cast_manifest.json, the profile
cache, an optional guild-achievements payload, and last run's transmog
snapshot), runs guild_board.web_data, and writes both the combined envelope
and one file per layer so the front-end can fetch just what a view needs.

Live M+ dungeon bests (island completion) require a full-roster Raider.io
sweep, so they are OFF by default. Pass --live-dungeons to fetch them; the
result is cached in web_data/dungeon_bests.json and reused otherwise.

Usage:
    python scripts/build_site_data.py [--live-dungeons] [--out DIR]
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guild_board import season as season_mod  # noqa: E402
from guild_board import web_data  # noqa: E402
from guild_board.blizzard import load_guild_cache  # noqa: E402
from guild_board.cast_manifest import load_manifest  # noqa: E402
from guild_board.config import load_config, load_roster_cache, split_name_realm  # noqa: E402

REPO_ROOT = str(Path(__file__).resolve().parents[1])
DEFAULT_OUT = os.path.join(REPO_ROOT, "web_data")


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def fetch_dungeon_bests(cfg, season):
    """Roster's best run per current-season dungeon, live from Raider.io.

    Uses the pooled/rate-limited session from guild_board.http via the
    raiderio helper, so it respects the same limit as the rest of the
    pipeline. Only the current season's dungeons are kept.
    """
    from guild_board.raiderio import _rio_get

    region = ((cfg or {}).get("guild") or {}).get("region", "us")
    roster, _ = load_roster_cache(cfg)
    wanted = season_mod.dungeon_names(season)
    bests = {}
    for entry in roster:
        name, realm = split_name_realm(entry)
        if not realm:
            continue
        try:
            resp = _rio_get(params={"region": region, "realm": realm,
                                    "name": name,
                                    "fields": "mythic_plus_best_runs"})
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        for run in resp.json().get("mythic_plus_best_runs") or []:
            dungeon = (run.get("dungeon") or "").strip()
            if dungeon not in wanted:
                continue
            level = run.get("mythic_level", 0)
            timed = (run.get("num_keystone_upgrades", 0) or 0) > 0
            cur = bests.get(dungeon)
            if cur is None or level > cur["level"]:
                bests[dungeon] = {"level": level, "timed": timed,
                                  "by": run.get("character", {}).get("name")
                                  or name.title()}
    return bests


def _fetch_guild_progression(cfg):
    """Live guild raid_progression from Raider.io (public, no creds)."""
    import requests
    g = (cfg or {}).get("guild") or {}
    try:
        resp = requests.get("https://raider.io/api/v1/guilds/profile",
                            params={"region": g.get("region", "us"),
                                    "realm": g.get("realm_slug"),
                                    "name": g.get("name"),
                                    "fields": "raid_progression"}, timeout=30)
        if resp.status_code == 200:
            return resp.json().get("raid_progression") or {}
    except requests.RequestException:
        pass
    return {}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-dungeons", action="store_true",
                        help="fetch per-dungeon bests from Raider.io (slow)")
    parser.add_argument("--out", default=DEFAULT_OUT, help="output directory")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cfg = load_config()
    season = season_mod.CURRENT_SEASON
    os.makedirs(args.out, exist_ok=True)

    board_state = _load_json(os.path.join(REPO_ROOT, "board_state.json"), {})
    manifest = load_manifest()
    snapshot = _load_json(os.path.join(args.out, "transmog_snapshot.json"), None)

    # Guild achievements come from the committed blizzard_guild_cache.json,
    # written by the cloud Action (scripts/refresh_guild_data.py). This is
    # what flips layer 3 from pending -> available and layer 4 from inferred
    # -> guild_achievements. Absent until the credentialed Action has run;
    # both layers degrade cleanly to their documented empty/inferred shapes.
    guild_cache, guild_updated = load_guild_cache(cfg)
    guild_ach = guild_cache.get("achievements")
    if guild_ach:
        print(f"Using committed guild achievements (updated {guild_updated}).")
    else:
        print("No committed guild achievements yet — layer 3 pending, "
              "layer 4 inferred. Run scripts/refresh_guild_data.py in the "
              "credentialed Action to populate.")

    dungeon_cache = os.path.join(args.out, "dungeon_bests.json")
    if args.live_dungeons:
        print("Fetching per-dungeon bests from Raider.io (full roster)…")
        t = time.perf_counter()
        dungeon_bests = fetch_dungeon_bests(cfg, season)
        print(f"  {len(dungeon_bests)} dungeons with runs in {time.perf_counter()-t:.0f}s")
        with open(dungeon_cache, "w", encoding="utf-8") as f:
            json.dump(dungeon_bests, f, indent=2)
    else:
        dungeon_bests = _load_json(dungeon_cache, {})

    raid_progression = _fetch_guild_progression(cfg)

    site = web_data.build_site_data(
        board_state=board_state, manifest=manifest,
        dungeon_bests=dungeon_bests, raid_progression=raid_progression,
        guild_achievements=guild_ach, transmog_snapshot=snapshot,
        guild={"name": cfg["guild"]["name"], "realm": cfg["guild"]["realm_slug"],
               "region": cfg["guild"]["region"]},
        season=season)

    # Persist the fresh transmog snapshot for next week's diff.
    with open(os.path.join(args.out, "transmog_snapshot.json"), "w", encoding="utf-8") as f:
        json.dump(site["transmog_changes"]["snapshot"], f, indent=2)

    # Combined envelope + one file per layer.
    _write(os.path.join(args.out, "site_data.json"), site)
    for layer in ("recap_ribbon", "records_leaderboard", "guild_achievements",
                  "island_completion", "transmog_changes"):
        _write(os.path.join(args.out, f"{layer}.json"), site[layer])

    print(f"\nWrote {args.out}/site_data.json (+ 5 per-layer files)")
    print(f"  recap beats     : {site['recap_ribbon']['beat_count']}")
    print(f"  ladder rows     : {site['records_leaderboard']['ladder_size']}")
    print(f"  achievements    : {'available' if site['guild_achievements']['available'] else site['guild_achievements']['status']}")
    print(f"  dungeon islands : {site['island_completion']['dungeons']['conquered']}/{site['island_completion']['dungeons']['total']} conquered")
    raid = site["island_completion"]["raid"]
    n_confirmed = sum(1 for b in raid["islands"] if b["kill_confirmed"])
    print(f"  raid islands    : {n_confirmed} confirmed / {raid['bosses_killed']} killed "
          f"(source: {raid['detail_source']})")
    print(f"  transmog changes: {site['transmog_changes']['changed_count']}"
          f"{' (first run — baseline seeded)' if site['transmog_changes']['is_first_run'] else ''}")
    return 0


def _write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    sys.exit(main())

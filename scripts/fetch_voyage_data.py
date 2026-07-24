#!/usr/bin/env python3
"""Fetch the guild's REAL per-island data for the voyage map.

    python scripts/fetch_voyage_data.py [--top 40]

Writes voyage_data.json:
  dungeons -> per dungeon, the guild's best timed key this season
  bosses   -> per raid boss, the guild's kill status and best parse

Both come from Raider.io's public API — no credentials. A dungeon or
boss nobody has done is simply absent, so the map can say "no record
yet" instead of implying a zero.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from guild_board import seasons as seasons_mod  # noqa: E402

API = "https://raider.io/api/v1"


def _cfg():
    import yaml
    with open("config.yml", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def guild_raid_progress(cfg):
    """One call: the guild's raid progression."""
    guild = cfg.get("guild") or {}
    try:
        r = requests.get(f"{API}/guilds/profile", timeout=30, params={
            "region": guild.get("region", "us"),
            "realm": guild.get("realm_slug", ""),
            "name": guild.get("name", ""),
            "fields": "raid_progression",
        })
        if r.status_code != 200:
            print(f"  guild raid_progression: HTTP {r.status_code}")
            return {}
        return r.json().get("raid_progression") or {}
    except requests.RequestException as exc:
        print(f"  guild raid_progression failed: {type(exc).__name__}")
        return {}


def best_runs(members, region, top):
    """Best timed key per dungeon across the roster.

    One request per character (season best runs), not per dungeon — 40
    calls instead of 40x8.
    """
    best = {}
    checked = 0
    for entry in members[:top]:
        if "-" not in entry:
            continue
        name, realm = entry.split("-", 1)
        try:
            r = requests.get(f"{API}/characters/profile", timeout=25, params={
                "region": region, "realm": realm, "name": name,
                "fields": "mythic_plus_best_runs",
            })
            if r.status_code != 200:
                continue
            data = r.json()
        except requests.RequestException:
            continue
        checked += 1
        for run in data.get("mythic_plus_best_runs") or []:
            dungeon = (run.get("dungeon") or "").strip()
            level = run.get("mythic_level") or 0
            if not dungeon or (run.get("num_keystone_upgrades") or 0) <= 0:
                continue
            current = best.get(dungeon)
            if current is None or level > current["level"]:
                best[dungeon] = {
                    "level": level,
                    "name": data.get("name", name),
                    "realm": realm,
                    "spec": run.get("short_name") or "",
                    "score": round(run.get("score") or 0, 1),
                    "clear_time_ms": run.get("clear_time_ms"),
                }
        time.sleep(0.05)          # be polite to a free public API
    print(f"  checked {checked} characters, found best runs in {len(best)} dungeons")
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=40,
                    help="How many roster members to query (by roster order).")
    ap.add_argument("--out", default="voyage_data.json")
    args = ap.parse_args()

    cfg = _cfg()
    season = seasons_mod.load(cfg=cfg)
    print("season:", seasons_mod.summary(season))

    roster = json.loads(Path("roster_cache.json").read_text(encoding="utf-8"))["members"]
    region = ((cfg.get("guild") or {}).get("region") or "us").lower()

    print("fetching guild raid progression")
    progression = guild_raid_progress(cfg)
    for key, value in progression.items():
        print(f"    {key}: {value.get('summary')}")

    print(f"fetching best M+ runs (top {args.top} of {len(roster)})")
    dungeons = best_runs(roster, region, args.top)

    # Only keep dungeons that are actually in this season — a leftover
    # from a previous season must not appear on the map.
    season_dungeons = {d["name"] for d in (season or {}).get("dungeons", [])}
    kept = {k: v for k, v in dungeons.items() if k in season_dungeons}
    dropped = sorted(set(dungeons) - season_dungeons)
    if dropped:
        print(f"  ignored {len(dropped)} out-of-season dungeon(s): {', '.join(dropped[:5])}")

    payload = {
        "season": (season or {}).get("id"),
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dungeons": kept,
        "raid_progression": progression,
        "bosses": {},          # filled from board_state records below
    }

    # Real parse records we already hold, matched to this season's bosses
    state = json.loads(Path("board_state.json").read_text(encoding="utf-8"))
    bosses = set((season or {}).get("raid", {}).get("bosses") or [])
    for key, label in (("best_dps_parse", "Best DPS parse"),
                       ("best_hps_parse", "Best HPS parse")):
        record = (state.get("records") or {}).get(key) or {}
        boss = (record.get("boss") or "").strip()
        # records may name a boss by its short form
        match = next((b for b in bosses if b == boss or b.startswith(boss)), None)
        if match:
            payload["bosses"].setdefault(match, {})[key] = {
                "label": label, "parse": record.get("parse"),
                "name": record.get("name"),
                "spec": " ".join(x for x in (record.get("spec"), record.get("cls")) if x),
            }

    Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")
    print(f"  dungeons with a real best key : {len(kept)} / {len(season_dungeons)}")
    print(f"  bosses with a parse record    : {len(payload['bosses'])} / {len(bosses)}")


if __name__ == "__main__":
    main()

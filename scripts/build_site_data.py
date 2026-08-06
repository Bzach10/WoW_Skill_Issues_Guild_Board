"""Build web_data/site_data.json — the data bundle the front-end reads.

Loads the real inputs (board_state.json, cast_manifest.json, the profile
cache, an optional guild-achievements payload, and last run's transmog
snapshot), runs guild_board.web_data, and writes both the combined envelope
and one file per layer so the front-end can fetch just what a view needs.

Live M+ dungeon bests (island completion) require a full-roster Raider.io
sweep, so they are OFF by default. Pass --live-dungeons to fetch them; the
result is cached in web_data/dungeon_bests.json and reused otherwise.

Also writes raid_kills.json — the per-boss, per-difficulty kill record with
dates (Raider.io guilds/boss-kill, 27 requests, ~9s). It is a sidecar, not a
site_data layer: it names WHICH bosses are down where the bundle's
killed_by_difficulty only counts them, and it degrades to available:false
without touching anything else.

Usage:
    python scripts/build_site_data.py [--live-dungeons] [--out DIR]
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guild_board import raiderio, web_data  # noqa: E402
from guild_board import season as season_mod  # noqa: E402
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


def carry_forward_raid(site, previous_island_completion):
    """LAST-GOOD semantics for the raid block (2026-07-27 incident).

    _fetch_guild_progression fails open to {} — and on 2026-07-27 Raider.io's
    guild profile endpoint 500'd (mid guild-split churn), so the rebuild wrote
    an internally-consistent raid block with EVERY kill count at zero. Zeros
    that mean "the fetch failed" must never masquerade as zeros that mean
    "no boss has died": when the fresh raid block carries no kills and the
    previously committed island_completion.json does, the previous raid block
    is carried forward verbatim, stamped `carried_forward_from` with the
    bundle timestamp it came from. The next successful live fetch replaces it
    wholesale (a genuinely new tier fetches successfully and never lands
    here). Returns True when the carry happened.

    Only call this when the live progression fetch returned nothing — the
    trigger is "no data this run", never "data we dislike".
    """
    ic = site.get("island_completion") or {}
    raid = ic.get("raid") or {}
    kbd = raid.get("killed_by_difficulty") or {}
    fresh_has_kills = bool(raid.get("bosses_killed")) or any(kbd.values())
    prev = previous_island_completion or {}
    prev_raid = prev.get("raid") or {}
    prev_kbd = prev_raid.get("killed_by_difficulty") or {}
    prev_has_kills = bool(prev_raid.get("bosses_killed")) or any(prev_kbd.values())
    if fresh_has_kills or not prev_has_kills:
        return False
    carried = dict(prev_raid)
    carried["carried_forward_from"] = prev.get("generated_at")
    ic["raid"] = carried
    return True


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


def resolve_raid_progression(fetched, cached):
    """(progression, source_label): the live fetch when it returned data,
    else the last-good cache (raid_progression_cache.json — written ONLY on
    a successful fetch, so a failing day can never poison it), else {}.

    The 2026-07-27 lesson, input-level: the committed bundle is a bad
    last-good source because one zeroed rebuild overwrites it in place —
    the 06:25 run found only its own poison to carry. The cache file has
    exactly one writer condition (fetch succeeded), so it survives any
    number of bad days between good ones.
    """
    if fetched:
        return fetched, "live"
    rp = (cached or {}).get("raid_progression")
    if rp:
        return rp, "cache"
    return {}, "none"


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

    # Guild pulse (layer 6) — the living Discord feed, written by
    # scripts/refresh_guild_pulse.py (needs DISCORD_BOT_TOKEN). Absent until
    # that refresh runs; the layer degrades to available:false.
    pulse_path = (cfg.get("discord_inputs") or {}).get(
        "pulse_cache_file", os.path.join(REPO_ROOT, "guild_pulse_cache.json"))
    pulse_items = (_load_json(pulse_path, {}) or {}).get("items")

    # Competition (the WANTED BOARD) — M+ scores/runs/ranks, refreshed daily
    # by scripts/refresh_competition.py from Raider.io's public API. Real data
    # with no credentials; degrades to empty if the cache is absent.
    competition_fetched = _load_json(
        os.path.join(REPO_ROOT, "competition_cache.json"), None)

    # Per-character WCL parses — written by scripts/refresh_parses.py in the
    # credentialed Action (Warcraft Logs creds exist only in CI). Absent
    # until that refresh runs; the layer degrades to available:false and
    # competition falls back to board_state's record holders.
    parses_fetched = _load_json(
        os.path.join(REPO_ROOT, "parses_cache.json"), None)

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

    prog_cache_path = os.path.join(REPO_ROOT, "raid_progression_cache.json")
    fetched_prog = _fetch_guild_progression(cfg)
    raid_progression, prog_source = resolve_raid_progression(
        fetched_prog, _load_json(prog_cache_path, None))
    if prog_source == "live":
        with open(prog_cache_path, "w", encoding="utf-8") as f:
            json.dump({"fetched_at": datetime.now(timezone.utc).isoformat(),
                       "source": "raider.io guilds/profile fields=raid_progression",
                       "raid_progression": raid_progression}, f, indent=2)
    elif prog_source == "cache":
        print("  WARNING: live guild progression unavailable — using last-good "
              "raid_progression_cache.json (fetched_at "
              f"{_load_json(prog_cache_path, {}).get('fetched_at')})")
    else:
        print("  WARNING: live guild progression unavailable and no last-good "
              "cache — raid layer will reflect no data this run")

    site = web_data.build_site_data(
        board_state=board_state, manifest=manifest,
        dungeon_bests=dungeon_bests, raid_progression=raid_progression,
        guild_achievements=guild_ach, transmog_snapshot=snapshot,
        pulse_items=pulse_items, competition_fetched=competition_fetched,
        parses_fetched=parses_fetched,
        # Officer-tunable difficulty discount for the parse axis; applied
        # at build time, so a config change takes effect on the next
        # rebuild with no WCL re-pull. See docs/PARSES_CONFIG_GUIDE.html.
        difficulty_scale=(cfg.get("parses") or {}).get("difficulty_scale"),
        guild={"name": cfg["guild"]["name"], "realm": cfg["guild"]["realm_slug"],
               "region": cfg["guild"]["region"]},
        season=season)

    if not raid_progression:
        # The live fetch came back empty — see carry_forward_raid: the
        # previously committed raid block (still on disk, not yet
        # overwritten) beats a zeroed one that only means "fetch failed".
        prev_ic = _load_json(os.path.join(args.out, "island_completion.json"), None)
        if carry_forward_raid(site, prev_ic):
            print("  WARNING: live guild progression unavailable — carried the "
                  "previous raid block forward (last-good, from bundle "
                  f"{(prev_ic or {}).get('generated_at')})")
        else:
            print("  WARNING: live guild progression unavailable and no "
                  "previous raid block with kills to carry — raid layer "
                  "reflects no data this run")

    # PER-BOSS RAID KILLS (raid_kills.json) — WHICH bosses are down, at which
    # difficulty, and when, from Raider.io's public guilds/boss-kill endpoint.
    # This is the named answer the aggregate raid_progression count above
    # cannot give; downstream consumers read it as the top authority over any
    # order-walk inference. It is a SIDECAR, not a site_data layer: nothing in
    # the envelope depends on it, so a bad sweep degrades exactly one file.
    # Never allowed to break the refresh — a fetch fault lands as
    # available:false (see collect_raid_boss_kills), and anything else is
    # caught here and written as the same honest empty shape.
    print("Fetching per-boss raid kills from Raider.io (public, no creds)...")
    try:
        raid_kills = raiderio.collect_raid_boss_kills(cfg, season)
    except Exception as exc:
        raid_kills = {
            "schema_version": raiderio.RAID_KILLS_SCHEMA_VERSION,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "available": False, "status": "unavailable",
            "error": f"{type(exc).__name__}: {exc}",
            "source": raiderio.RAIDERIO_BOSS_KILL_URL,
            "raid": {"slug": season["raid"]["slug"]},
            "difficulties": list(raiderio.KILL_DIFFICULTIES),
            "killed_by_difficulty": {}, "bosses": [],
        }
    _write(os.path.join(args.out, "raid_kills.json"), raid_kills)

    # Overlay named+dated raid_kills onto island_completion.raid.islands so
    # consumers reading islands[] cannot under-report vs bosses_killed
    # (guild_achievements only name Guild Run achievements — typically a
    # subset of the aggregate). Sidecar remains authoritative; this makes
    # the islands list match the headline.
    if raid_kills.get("available"):
        raid = site["island_completion"]["raid"]
        by_slug = {b.get("slug"): b for b in (raid_kills.get("bosses") or [])}
        conquered = 0
        for island in raid.get("islands") or []:
            boss = by_slug.get(island.get("id"))
            if not boss:
                continue
            kills = boss.get("kills") or {}
            # Prefer mythic date when present, else heroic, else normal.
            when = None
            for diff in ("mythic", "heroic", "normal"):
                entry = kills.get(diff) or {}
                if entry.get("defeated_at"):
                    when = entry["defeated_at"]
                    break
            if when:
                island["status"] = "conquered"
                island["kill_confirmed"] = True
                island["first_kill_at"] = when
                conquered += 1
            else:
                island["status"] = "locked"
                island["kill_confirmed"] = False
        # Aggregate bosses_killed stays the progression count (heroic+);
        # islands now name every kill raid_kills knows. Prefer heroic count
        # for the islands conquered tally alignment when heroic is complete.
        kbd = raid_kills.get("killed_by_difficulty") or {}
        heroic_n = int(kbd.get("heroic") or 0)
        if heroic_n and conquered >= heroic_n:
            raid["bosses_killed"] = max(int(raid.get("bosses_killed") or 0), heroic_n)
        raid["detail_source"] = "raid_kills"
        raid["killed_by_difficulty"] = dict(kbd)
        print(f"  raid islands    : overlaid from raid_kills "
              f"({conquered} named conquered; detail_source=raid_kills)")

    # Persist the fresh transmog snapshot for next week's diff.
    with open(os.path.join(args.out, "transmog_snapshot.json"), "w", encoding="utf-8") as f:
        json.dump(site["transmog_changes"]["snapshot"], f, indent=2)

    # Combined envelope + one file per layer.
    _write(os.path.join(args.out, "site_data.json"), site)
    layers = ("recap_ribbon", "records_leaderboard", "weekly_board",
              "guild_achievements", "island_completion", "transmog_changes",
              "guild_pulse", "competition", "parses")
    for layer in layers:
        _write(os.path.join(args.out, f"{layer}.json"), site[layer])

    print(f"\nWrote {args.out}/site_data.json (+ {len(layers)} per-layer files)")
    print(f"  recap beats     : {site['recap_ribbon']['beat_count']}")
    print(f"  ladder rows     : {site['records_leaderboard']['ladder_size']}")
    wk = site["weekly_board"]
    print(f"  weekly board    : {'available' if wk['available'] else wk['status']}"
          + (f" — week {wk['week_label']}, {wk['kills']} kills / {wk['pulls']} pulls"
             if wk["available"] else ""))
    print(f"  achievements    : {'available' if site['guild_achievements']['available'] else site['guild_achievements']['status']}")
    print(f"  dungeon islands : {site['island_completion']['dungeons']['conquered']}/{site['island_completion']['dungeons']['total']} conquered")
    raid = site["island_completion"]["raid"]
    n_confirmed = sum(1 for b in raid["islands"] if b["kill_confirmed"])
    print(f"  raid islands    : {n_confirmed} confirmed / {raid['bosses_killed']} killed "
          f"(source: {raid['detail_source']})")
    if raid_kills.get("available"):
        named = ", ".join(f"{d} {n}" for d, n in
                          (raid_kills.get("killed_by_difficulty") or {}).items() if n)
        print(f"  raid kills      : named + dated ({named or 'none yet'})")
    else:
        print(f"  raid kills      : {raid_kills.get('status')} — "
              f"{len(raid_kills.get('unresolved') or [])} boss/difficulty pair(s) "
              "unanswered; consumers fall back to count inference")
    print(f"  transmog changes: {site['transmog_changes']['changed_count']}"
          f"{' (first run — baseline seeded)' if site['transmog_changes']['is_first_run'] else ''}")
    pulse = site["guild_pulse"]
    print(f"  guild pulse     : {pulse['item_count']} items"
          f"{' (' + str(pulse['by_kind']) + ')' if pulse['available'] else ' (' + pulse['status'] + ')'}")
    comp = site["competition"]
    print(f"  competition     : {comp['character_count']} characters ranked"
          f"{'' if comp['available'] else ' (empty — run refresh_competition.py)'}")
    par = site["parses"]
    print(f"  parses          : {par['character_count']} characters with WCL averages"
          f"{'' if par['available'] else ' (' + par['status'] + ' — runs in the credentialed Action)'}")
    return 0


def _write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    sys.exit(main())

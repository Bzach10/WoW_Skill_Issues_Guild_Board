"""Refresh the per-character Warcraft Logs parse cache -- current-tier
best-performance averages (overall + per-role, EVERY enabled difficulty)
for the guild's active raiders.

This is the credentialed input for the website's parse surfaces (the Four
Emperors ranking's second axis, standings parse columns, the newspaper's
raid sections). Warcraft Logs credentials exist ONLY in GitHub Actions, so:

  * INERT without credentials: exits 0 with a note and touches nothing.
    Local runs stay offline by design; the pull runs in
    .github/workflows/wcl-parse-refresh.yml.
  * ACTIVE-GATED (config.yml -> parses.sweep): by default only characters
    seen in recent guild logs, plus anyone already cached, are queried --
    most of the roster never raids. A full-roster discovery sweep runs
    every parses.discovery_days so newly active members are found.
  * BOTH mythic and heroic are fetched for every swept character (any
    difficulty whose parses.difficulty_scale factor is > 0) -- the website
    shows them side by side, so one must never shadow the other.
  * BEST-ACROSS-METRICS: every character is asked for BOTH overall
    zoneRankings metrics (dps and hps, unbracketed) and counted on the
    higher one. The blob used to ask for `metric: default` and let WCL
    decide, which handed most healers their DAMAGE percentile (verified
    2026-07-26: Hellful's mythic overall read 84.0 damage against a real
    19.9 healing average). Taking the max needs no roster-role guess and
    pays dual-spec raiders for their better spec.
  * FAIL-OPEN like refresh_competition.py: if the fresh sweep resolves far
    fewer characters than the cache already holds (a bad WCL day), the old
    cache is kept rather than blanking every parse on the site.

Writes parses_cache.json, keyed by the FULL name-realm roster key (exact
Unicode, e.g. "violënce-bleeding-hollow") -- NEVER bare names; two
same-named characters on different realms must stay distinct.

Console output is ASCII-safe (names carry accents; CI logs and Windows
consoles must both survive them).

Usage: python scripts/refresh_parses.py [--min-fraction 0.5] [--full]
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402

from guild_board import season as season_mod  # noqa: E402
from guild_board.config import load_config, load_roster_cache  # noqa: E402
from guild_board.wcl import (  # noqa: E402
    IMPROVEMENT_MAX_DAYS,
    detect_zone,
    fetch_active_raiders,
    fetch_character_parses,
    fetch_guild_reports,
    fetch_zone_directory,
    get_wcl_token,
    resolve_raid_zone,
    resolve_zone_id,
    select_active_roster,
)
from guild_board.web_data import sweep_difficulties  # noqa: E402

REPO_ROOT = str(Path(__file__).resolve().parents[1])
CACHE_PATH = os.path.join(REPO_ROOT, "parses_cache.json")


def _say(msg):
    print(msg.encode("ascii", "backslashreplace").decode("ascii"))


def _load_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _metric_split(characters):
    """"12 hps, 54 dps" -- how many swept difficulty blocks were counted on
    each overall metric. Every character is asked for both and counted on
    the better one, so this is the run's own record of who the healing
    metric actually won for; it is diagnosis, never an input."""
    counts = {}
    for entry in characters.values():
        for sub in (entry.get("by_difficulty") or {}).values():
            metric = (sub or {}).get("metric")
            if metric:
                counts[metric] = counts.get(metric, 0) + 1
    if not counts:
        return "none recorded"
    return ", ".join(f"{n} {m}" for m, n in sorted(counts.items()))


def _discovery_due(old, discovery_days):
    """A full-roster discovery sweep is due when the cache has never had
    one, or the last one is older than discovery_days."""
    stamp = old.get("last_full_sweep")
    if not stamp:
        return True
    try:
        last = datetime.fromisoformat(stamp)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - last >= timedelta(days=discovery_days)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-fraction", type=float, default=0.5,
                        help="keep the old cache if the fresh sweep resolves "
                             "fewer than this fraction of last run's count")
    parser.add_argument("--full", action="store_true",
                        help="force a full-roster discovery sweep this run")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # Credential gate FIRST -- local runs must stay inert and offline.
    client_id = os.environ.get("WCL_CLIENT_ID", "").strip()
    client_secret = os.environ.get("WCL_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        _say("Warcraft Logs credentials not set -- skipping the parse "
             "refresh (normal locally; the pull runs in the credentialed "
             "Action). Existing parses_cache.json left untouched.")
        return 0

    cfg = load_config()
    roster, _ = load_roster_cache(cfg)
    if not roster:
        _say("roster_cache.json is empty -- run the weekly board once first.")
        return 0

    parses_cfg = cfg.get("parses") or {}
    difficulties = sweep_difficulties(parses_cfg.get("difficulty_scale"))
    if not difficulties:
        _say("All difficulties are scaled to 0 in config.yml "
             "(parses.difficulty_scale) -- nothing to sweep; keeping the "
             "existing cache.")
        return 0

    token = get_wcl_token(client_id, client_secret)
    season = season_mod.CURRENT_SEASON

    # Zones are pinned BY NAME from WCL's zone directory, so a stray
    # bonus-raid upload can never flip the sweep off the tier (the old
    # detect-from-newest-report wobble). detect_zone stays as a fallback
    # when the directory is unavailable or the name match fails.
    try:
        zone_dir = fetch_zone_directory(token)
    except (RuntimeError, requests.RequestException) as exc:
        _say(f"Zone directory lookup failed ({exc}) -- falling back to "
             "report-based detection.")
        zone_dir = []

    # One report sweep serves both zone fallback and the activity gate.
    now = datetime.now(timezone.utc)
    end_ms = int(now.timestamp() * 1000)
    start_ms = int((now - timedelta(days=IMPROVEMENT_MAX_DAYS)).timestamp() * 1000)
    reports = fetch_guild_reports(token, cfg, start_ms, end_ms, limit=50)

    override = int((cfg.get("rankings") or {}).get("zone_id", 0) or 0)
    main_raid = season["raid"]
    if override > 0:
        zone_id, tier_name = override, main_raid["display_name"]
    else:
        zone_id = resolve_zone_id(
            zone_dir, main_raid.get("api_name") or main_raid["display_name"])
        tier_name = main_raid["display_name"]
        if not zone_id:
            zone_id, zone_name = detect_zone(cfg, reports)
            tier_name = zone_name or main_raid["display_name"]
    if not zone_id:
        _say("No raid zone found (no zone-directory match, no recent guild "
             "reports, no rankings.zone_id override) -- keeping the "
             "existing cache.")
        return 0
    tier = {"zone_id": int(zone_id), "name": tier_name}
    _say(f"Current tier: {tier['name']} (WCL zone {tier['zone_id']})")

    # Bonus raids running alongside the tier (season.py extra_raids, e.g.
    # Sporefall/Rotmire). Resolution tries the raid name, then each boss
    # name -- WCL may call the world-raid zone "Rotmire" rather than
    # "Sporefall". Unresolved zones are skipped WITH A NOTE, never fatal
    # and never silent.
    extra_zones = []
    for raid in season.get("extra_raids") or []:
        zid, matched = resolve_raid_zone(zone_dir, raid)
        if zid:
            extra_zones.append({"slug": raid["slug"], "zone_id": int(zid),
                                "name": raid["display_name"]})
            _say(f"Extra zone: {raid['display_name']} (WCL zone {zid}, "
                 f"matched by name '{matched}')")
        else:
            tried = ", ".join([raid["display_name"]]
                              + [b["name"] for b in raid.get("bosses") or []])
            _say(f"Extra zone {raid['display_name']}: no WCL zone matched "
                 f"any of [{tried}] -- skipped this run.")

    zones_swept = ([{"slug": main_raid["slug"], "zone_id": tier["zone_id"],
                     "name": tier["name"]}] + extra_zones)
    _say("Zones swept this run: "
         + "; ".join(f"{z['name']} (zone {z['zone_id']})" for z in zones_swept))

    old = _load_cache()
    old_chars = old.get("characters") or {}
    old_count = len(old_chars)

    # The activity gate: whole-roster sweeps only on discovery days; daily
    # runs query recent-log participants + everyone already cached.
    sweep_mode = str(parses_cfg.get("sweep", "active")).strip().lower()
    active_days = int(parses_cfg.get("active_days", 21) or 21)
    discovery_days = int(parses_cfg.get("discovery_days", 7) or 7)
    full_sweep = (args.full or sweep_mode == "full"
                  or _discovery_due(old, discovery_days))
    # A character cached in ANY swept zone stays in the active set — a
    # Rotmire-only raider must keep refreshing through a quiet tier week.
    cached_keys = set(old_chars)
    for zone in (old.get("extra_zones") or {}).values():
        cached_keys.update((zone or {}).get("characters") or {})

    if full_sweep:
        sweep_roster = list(roster)
        _say(f"Full-roster sweep ({len(sweep_roster)} members): "
             + ("forced/configured." if (args.full or sweep_mode == "full")
                else "discovery sweep due."))
    else:
        cutoff_ms = int((now - timedelta(days=active_days)).timestamp() * 1000)
        swept_zone_ids = {zone_id} | {z["zone_id"] for z in extra_zones}
        recent = [r for r in reports
                  if (r.get("startTime") or 0) >= cutoff_ms
                  and (r.get("zone") or {}).get("id") in swept_zone_ids]
        active = fetch_active_raiders(token, cfg, recent, difficulties)
        sweep_roster = select_active_roster(
            roster, active, cached_keys,
            default_realm=cfg["guild"]["realm_slug"])
        _say(f"Active sweep: {len(sweep_roster)} of {len(roster)} roster "
             f"members ({len(active)} names in the last {active_days}d of "
             f"logs across {len(recent)} report(s), {len(cached_keys)} "
             "already cached). Full discovery runs every "
             f"{discovery_days}d.")
        if not sweep_roster:
            _say("Nobody active and nothing cached -- keeping the existing "
                 "cache untouched.")
            return 0

    _say(f"Sweeping WCL parse averages (difficulties {list(difficulties)})...")
    t = time.perf_counter()
    characters = fetch_character_parses(token, cfg, sweep_roster, zone_id,
                                        difficulties=difficulties)
    elapsed = time.perf_counter() - t
    _say(f"  {len(characters)} characters with rankings in {elapsed:.0f}s")
    _say("  counted metric (best of dps/hps per difficulty): "
         + _metric_split(characters))

    # Bonus raids: same roster, same difficulties, their own block — never
    # merged into the tier data (the Emperor Index is tier-only).
    extra_data = {}
    for zone in extra_zones:
        _say(f"Sweeping {zone['name']} (WCL zone {zone['zone_id']})...")
        t = time.perf_counter()
        zchars = fetch_character_parses(token, cfg, sweep_roster,
                                        zone["zone_id"],
                                        difficulties=difficulties)
        _say(f"  {len(zchars)} characters with {zone['name']} rankings "
             f"in {time.perf_counter() - t:.0f}s")
        extra_data[zone["slug"]] = {"zone_id": zone["zone_id"],
                                    "name": zone["name"],
                                    "characters": zchars}

    # FAIL-OPEN: a bad API day must not blank every parse on the site.
    if old_count and len(characters) < old_count * args.min_fraction:
        _say(f"  fresh sweep resolved {len(characters)} < "
             f"{args.min_fraction:.0%} of last run's {old_count} -- keeping "
             "the previous cache (fail-open).")
        return 0

    payload = {
        "last_updated": now.isoformat(),
        "last_full_sweep": (now.isoformat() if full_sweep
                            else old.get("last_full_sweep")),
        "sweep_mode": "full" if full_sweep else "active",
        "swept_count": len(sweep_roster),
        "tier": tier,
        "season_slug": season["slug"],
        # Run provenance: exactly which WCL zones this sweep covered, so a
        # missing raid downstream is always diagnosable from the data
        # itself (zones are skipped only with a logged note, never silently).
        "zones_swept": zones_swept,
        "count": len(characters),
        "characters": characters,
        "extra_zones": extra_data,
    }
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    _say(f"  wrote {CACHE_PATH}")

    def _best(c):
        return max((s.get("best_perf_avg") or 0)
                   for s in (c.get("by_difficulty") or {"": {}}).values())

    top = sorted(characters.values(), key=_best, reverse=True)[:5]
    if top:
        _say("  top 5 by best-performance average (any difficulty):")
        for i, c in enumerate(top, 1):
            diffs = ", ".join(f"{d} {s.get('best_perf_avg')}"
                              for d, s in (c.get("by_difficulty") or {}).items())
            _say(f"    {i}. {c.get('name') or c.get('key'):20} {diffs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

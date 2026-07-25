"""Refresh the per-character Warcraft Logs parse cache -- current-tier
best-performance averages (overall + per-role) for the whole roster.

This is the credentialed input for the website's parse surfaces (the Four
Emperors ranking's second axis, standings parse columns, the newspaper's
raid sections). Warcraft Logs credentials exist ONLY in GitHub Actions, so:

  * INERT without credentials: exits 0 with a note and touches nothing.
    Local runs stay offline by design; the pull runs in
    .github/workflows/wcl-parse-refresh.yml.
  * FAIL-OPEN like refresh_competition.py: if the fresh sweep resolves far
    fewer characters than the cache already holds (a bad WCL day), the old
    cache is kept rather than blanking every parse on the site.

Writes parses_cache.json, keyed by the FULL name-realm roster key (exact
Unicode, e.g. "violënce-bleeding-hollow") -- NEVER bare names; two
same-named characters on different realms must stay distinct.

Console output is ASCII-safe (names carry accents; CI logs and Windows
consoles must both survive them).

Usage: python scripts/refresh_parses.py [--min-fraction 0.5]
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guild_board import season as season_mod  # noqa: E402
from guild_board.config import load_config, load_roster_cache  # noqa: E402
from guild_board.wcl import (  # noqa: E402
    IMPROVEMENT_MAX_DAYS,
    detect_zone,
    fetch_character_parses,
    fetch_guild_reports,
    get_wcl_token,
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


def _detect_tier(token, cfg):
    """The current raid zone: config override if set, else detected from the
    guild's recent reports (same skip-the-M+-season-zones rule the weekly
    board uses). Returns (zone_id, zone_name) -- (None, None) if no reports."""
    override = int((cfg.get("rankings") or {}).get("zone_id", 0) or 0)
    if override > 0:
        return override, None
    now = datetime.now(timezone.utc)
    end_ms = int(now.timestamp() * 1000)
    start_ms = int((now - timedelta(days=IMPROVEMENT_MAX_DAYS)).timestamp() * 1000)
    reports = fetch_guild_reports(token, cfg, start_ms, end_ms, limit=50)
    return detect_zone(cfg, reports)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-fraction", type=float, default=0.5,
                        help="keep the old cache if the fresh sweep resolves "
                             "fewer than this fraction of last run's count")
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

    token = get_wcl_token(client_id, client_secret)

    zone_id, zone_name = _detect_tier(token, cfg)
    if not zone_id:
        _say("No raid zone found (no recent guild reports and no "
             "rankings.zone_id override) -- keeping the existing cache.")
        return 0
    season = season_mod.CURRENT_SEASON
    tier = {"zone_id": int(zone_id),
            "name": zone_name or season["raid"]["display_name"]}
    _say(f"Current tier: {tier['name']} (WCL zone {tier['zone_id']})")

    old = _load_cache()
    old_count = len(old.get("characters") or {})

    # One knob controls policy AND fetch: a difficulty scaled to 0 in
    # config.yml (parses.difficulty_scale) is excluded from the sweep too,
    # so the Action never spends queries on data the build would drop.
    difficulties = sweep_difficulties(
        (cfg.get("parses") or {}).get("difficulty_scale"))
    if not difficulties:
        _say("All difficulties are scaled to 0 in config.yml "
             "(parses.difficulty_scale) -- nothing to sweep; keeping the "
             "existing cache.")
        return 0
    _say(f"Sweeping WCL parse averages for {len(roster)} roster members "
         f"(difficulties {list(difficulties)})...")
    t = time.perf_counter()
    characters = fetch_character_parses(token, cfg, roster, zone_id,
                                        difficulties=difficulties)
    elapsed = time.perf_counter() - t
    _say(f"  {len(characters)} characters with rankings in {elapsed:.0f}s")

    # FAIL-OPEN: a bad API day must not blank every parse on the site.
    if old_count and len(characters) < old_count * args.min_fraction:
        _say(f"  fresh sweep resolved {len(characters)} < "
             f"{args.min_fraction:.0%} of last run's {old_count} -- keeping "
             "the previous cache (fail-open).")
        return 0

    payload = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "tier": tier,
        "season_slug": season["slug"],
        "count": len(characters),
        "characters": characters,
    }
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    _say(f"  wrote {CACHE_PATH}")

    top = sorted(characters.values(),
                 key=lambda c: c.get("best_perf_avg") or 0, reverse=True)[:5]
    if top:
        _say("  top 5 by best-performance average:")
        for i, c in enumerate(top, 1):
            _say(f"    {i}. {c.get('name') or c.get('key'):20} "
                 f"{c.get('best_perf_avg'):>5} (difficulty {c.get('difficulty')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

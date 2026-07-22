"""Refresh the competition data cache — M+ scores, best runs, ranks for the
whole roster, live from Raider.io's public API (no credentials).

This is the daily-refresh input for the WANTED BOARD. Idempotent and
FAIL-OPEN: if the live sweep returns fewer characters than we already have
cached (a bad Raider.io day), it keeps yesterday's cache rather than
blanking the board.

Writes competition_cache.json, which build_site_data.py reads to build the
competition layer.

Usage: python scripts/refresh_competition.py [--min-fraction 0.5]
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guild_board.competition import fetch_competition  # noqa: E402
from guild_board.config import load_config, load_roster_cache  # noqa: E402

REPO_ROOT = str(Path(__file__).resolve().parents[1])
CACHE_PATH = os.path.join(REPO_ROOT, "competition_cache.json")


def _load_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-fraction", type=float, default=0.5,
                        help="keep the old cache if the fresh sweep resolves "
                             "fewer than this fraction of last run's count")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cfg = load_config()
    roster, _ = load_roster_cache(cfg)
    if not roster:
        print("roster_cache.json is empty — run the weekly board once first.")
        return 0

    old = _load_cache()
    old_count = old.get("count", 0)
    # Carry yesterday's scores forward so build_competition can compute
    # day-over-day deltas. Keyed by roster slug.
    prev_day_scores = {c["key"]: c["score"] for c in old.get("characters") or []
                       if c.get("key")}

    print(f"Fetching M+ competition data for {len(roster)} roster members "
          f"from Raider.io…")
    t = time.perf_counter()
    fresh = fetch_competition(cfg, roster=roster)
    elapsed = time.perf_counter() - t
    new_count = fresh.get("count", 0)
    print(f"  resolved {new_count} characters in {elapsed:.0f}s")

    # FAIL-OPEN: a bad API day must not blank the board.
    if old_count and new_count < old_count * args.min_fraction:
        print(f"  fresh sweep resolved {new_count} < {args.min_fraction:.0%} of "
              f"last run's {old_count} — keeping yesterday's cache (fail-open).")
        return 0

    fresh["last_updated"] = datetime.now(timezone.utc).isoformat()
    fresh["prev_day_scores"] = prev_day_scores
    fresh["prev_day_at"] = old.get("last_updated")
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(fresh, f, indent=2, ensure_ascii=False)
    print(f"  wrote {CACHE_PATH}")

    top = sorted(fresh["characters"], key=lambda c: c["score"], reverse=True)[:5]
    print("  top 5:")
    for i, c in enumerate(top, 1):
        print(f"    {i}. {c['name']:14} {c['score']:>7} ({c['spec']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

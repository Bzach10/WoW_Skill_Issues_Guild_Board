"""Refresh the competition data cache — M+ scores, best runs, ranks for the
whole roster, live from Raider.io's public API (no credentials).

This is the daily-refresh input for the WANTED BOARD. Idempotent and
FAIL-OPEN: if the live sweep returns fewer characters than we already have
cached (a bad Raider.io day), it keeps yesterday's cache rather than
blanking the board.

MEMBERSHIP (2026-07-27, owner directive): the sweep roster is the LIVE
Raider.io guild roster — an actual guild roster, unlike the WCL-derived
roster_cache.json, whose member list is a by-product of log uploads (see
guild_board/guild_roster.py for the Phyrthepali incident). Two-way truth:

  * in the guild, new to us      -> swept and added this run;
  * in our cache, not in the guild -> moved to a `departed` ledger with the
    last-known record retained and a `departed_at` stamp. NEVER deleted —
    the site renders departures from this ledger. `departed_at` is the run
    that first OBSERVED the absence, an observation date, never a guessed
    leave date. A member who reappears in the live roster leaves the
    ledger automatically (transfers and crawl lag are reversible).
  * NOBODY enters the sweep who is not presently in the guild: the
    WCL-only names roster_cache retains (pugs, departed alts) stop
    leaking into the site's membership.

Fail-open here too: if the live guild pull is unreachable, empty, or
suspiciously small (below --min-fraction of the previous membership), the
run falls back to roster_cache.json exactly as before and carries the
existing departed ledger forward untouched — a bad crawl day must not
mass-depart the guild.

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
from guild_board.guild_roster import fetch_raiderio_guild_roster  # noqa: E402

REPO_ROOT = str(Path(__file__).resolve().parents[1])
CACHE_PATH = os.path.join(REPO_ROOT, "competition_cache.json")

MEMBERSHIP_SOURCE = "raider.io guild roster"


class MembershipGuard(Exception):
    """The live roster looks like a bad crawl, not a real guild state."""


def _load_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def apply_membership(old, live_members, now_iso, min_fraction=0.5):
    """Two-way roster truth against the live guild roster. Pure — testable
    offline.

    old: the previous competition cache (its characters are the previous
         site membership; its departed list is the standing ledger).
    live_members: {key: info} from fetch_raiderio_guild_roster.

    Returns (sweep_keys, membership, departed):
      sweep_keys — sorted name-realm keys to sweep: exactly the live guild.
      membership — provenance stamp for the cache/envelope.
      departed   — the updated ledger: previous members now absent from the
                   live guild (last-known record + departed_at), plus prior
                   ledger rows still absent. Rows whose key reappears in the
                   live roster are dropped (they returned).

    Raises MembershipGuard when live_members is empty or has shrunk below
    min_fraction of the previous membership — that shape is a crawl failure,
    and acting on it would depart most of the guild in one run.
    """
    if not live_members:
        raise MembershipGuard("live guild roster is empty")

    prev_chars = {c["key"]: c for c in old.get("characters") or [] if c.get("key")}
    prev_size = (old.get("membership") or {}).get("member_count") or len(prev_chars)
    if prev_size and len(live_members) < prev_size * min_fraction:
        raise MembershipGuard(
            f"live roster has {len(live_members)} members, below "
            f"{min_fraction:.0%} of the previous {prev_size} — refusing to "
            "mass-depart on what looks like a partial crawl")

    departed = []
    for key, row in ((d.get("key"), d) for d in old.get("departed") or []):
        if key and key not in live_members:
            departed.append(row)  # still gone; departed_at stays stable
    ledgered = {d["key"] for d in departed}
    for key, last_known in sorted(prev_chars.items()):
        if key not in live_members and key not in ledgered:
            departed.append({**last_known, "departed_at": now_iso})
    departed.sort(key=lambda d: d["key"])

    membership = {
        "source": MEMBERSHIP_SOURCE,
        "as_of": now_iso,
        "member_count": len(live_members),
    }
    return sorted(live_members), membership, departed


def _member_stub(key, info):
    """A live guild member the per-character sweep could not resolve (e.g.
    Raider.io has not crawled them yet). Everything here is REAL data from
    the guild-roster payload; the score fields are empty, never invented —
    downstream renders them as the deliberate unscored state."""
    return {
        "name": info.get("name") or key.split("-", 1)[0],
        "key": key,
        "realm": info.get("realm"),
        "realm_slug": info.get("realm_slug") or key.split("-", 1)[1],
        "class": info.get("class"),
        "spec": info.get("spec"),
        "role": info.get("role"),
        "score": 0,
        "scores_by_role": {"dps": 0, "healer": 0, "tank": 0},
        "best_runs": [],
        "ranks": {"realm_overall": None, "realm_class": None,
                  "region_overall": None},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-fraction", type=float, default=0.5,
                        help="keep the old cache if the fresh sweep resolves "
                             "fewer than this fraction of last run's count")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cfg = load_config()
    old = _load_cache()
    now_iso = datetime.now(timezone.utc).isoformat()

    # Membership: live guild roster first; roster_cache.json only as the
    # fail-open fallback (it retains people who left and misses people who
    # never logged — see module docstring).
    live = None
    try:
        live = fetch_raiderio_guild_roster(cfg)
    except Exception as exc:  # noqa: BLE001 — any transport failure falls open
        print(f"  live guild roster unreachable ({exc}); "
              "falling back to roster_cache.json")

    membership = departed = None
    roster = []
    if live is not None:
        try:
            roster, membership, departed = apply_membership(
                old, live, now_iso, args.min_fraction)
            print(f"Live guild roster: {len(live)} members "
                  f"({MEMBERSHIP_SOURCE}); departed ledger: {len(departed)}")
        except MembershipGuard as exc:
            print(f"  live roster REFUSED: {exc}; "
                  "falling back to roster_cache.json")

    if membership is None:
        roster, _ = load_roster_cache(cfg)
        if not roster:
            print("roster_cache.json is empty — run the weekly board once first.")
            return 0
        # Carry the standing stamp/ledger forward UNCHANGED: a day without a
        # live pull is a day without membership news, not a day of departures.
        membership = old.get("membership")
        departed = old.get("departed") or []

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

    # Live members the per-character sweep could not resolve are still
    # members: carry them as real-but-unscored stubs so membership is the
    # guild, not the subset Raider.io has crawled character pages for.
    if live is not None and membership and membership.get("source") == MEMBERSHIP_SOURCE:
        resolved = {c["key"] for c in fresh["characters"]}
        stubs = [_member_stub(k, live[k]) for k in roster if k not in resolved]
        if stubs:
            print(f"  {len(stubs)} live member(s) had no character page yet — "
                  "kept as unscored membership stubs")
            fresh["characters"].extend(stubs)
            fresh["count"] = len(fresh["characters"])

    fresh["last_updated"] = now_iso
    fresh["prev_day_scores"] = prev_day_scores
    fresh["prev_day_at"] = old.get("last_updated")
    fresh["membership"] = membership
    fresh["departed"] = departed
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

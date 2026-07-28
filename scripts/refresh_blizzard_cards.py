"""Refresh the TRADING CARD data cache: every useful Blizzard Profile API
endpoint, per roster character, slimmed to a committable shape.

This is the card game's data limb. It sits beside refresh_blizzard_profiles.py
(which serves the cast-art pipeline and keeps its own narrow cache) and shares
nothing with it but the OAuth token helper -- so this script can fail whole
and neither the board nor the cast art notices.

Needs BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET in the environment AND
blizzard.enabled: true in config.yml. Safe to run with either missing: it
says why it skipped and exits 0.

Outputs (both committed by CI, neither ever hand-edited):
    blizzard_card_cache.json          the per-character card data
    blizzard_statistic_catalog.json   every statistic name the API offers,
                                      sampled from one character -- the
                                      curation input for STAT_WANTED

Usage:
    python scripts/refresh_blizzard_cards.py [--force] [--limit N]
                                             [--only "name-realm,..."]
                                             [--workers N]

--limit / --only exist for a CHEAP first run: the endpoint set is only as
correct as the paths in the registry, and probing it against three characters
costs 50 requests instead of 2,500. The run prints the per-endpoint outcome
table either way, so a wrong path shows up as a wall of http_404 rather than
as silently missing card fields.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guild_board.blizzard_cards import (  # noqa: E402
    ENDPOINTS,
    WORKERS,
    refresh_card_cache,
)
from guild_board.config import load_config, load_roster_cache  # noqa: E402

REQUIRED_SECRETS = ("BLIZZARD_CLIENT_ID", "BLIZZARD_CLIENT_SECRET")


def _say(msg):
    print(str(msg).encode("ascii", "backslashreplace").decode("ascii"))


def _print_report(report, roster_n):
    """The measured inventory: what each endpoint actually did, this run."""
    if not report:
        return
    _say("")
    _say(f"ENDPOINT OUTCOMES ({roster_n} characters attempted)")
    _say(f"  {'endpoint':<46} outcomes")
    for label in sorted(report):
        outcomes = report[label]
        line = "  ".join(f"{k}={outcomes[k]}" for k in sorted(outcomes))
        _say(f"  {label:<46} {line}")
    total = sum(sum(o.values()) for o in report.values())
    _say(f"  total requests: {total}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="refresh even if the cache is still fresh")
    parser.add_argument("--limit", type=int, default=0,
                        help="fetch only the first N roster entries (probe run)")
    parser.add_argument("--only", default="",
                        help="comma-separated name-realm keys to fetch instead "
                             "of the roster (probe run)")
    parser.add_argument("--workers", type=int, default=WORKERS,
                        help=f"parallel character fetches (default {WORKERS})")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    cfg = load_config()

    if not (cfg.get("blizzard") or {}).get("enabled", False):
        _say("blizzard.enabled is false in config.yml -- set it to true, then "
             "re-run. See SETUP_BLIZZARD.md.")
        return 0

    missing = [n for n in REQUIRED_SECRETS if not os.environ.get(n, "").strip()]
    if missing:
        _say("Missing secret(s): {} -- they live in this repo's Actions "
             "secrets, never locally. See SETUP_BLIZZARD.md.".format(", ".join(missing)))
        return 0

    roster, _ = load_roster_cache(cfg)
    if args.only:
        roster = [e.strip().lower() for e in args.only.split(",") if e.strip()]
        _say(f"--only: {len(roster)} character(s) this run.")
    elif args.limit:
        roster = list(roster)[:args.limit]
        _say(f"--limit: first {len(roster)} roster character(s) this run.")

    if not roster:
        _say("roster_cache.json is empty or missing; nothing to refresh.")
        return 0

    _say(f"Card refresh: {len(roster)} characters x {len(ENDPOINTS)} endpoints "
         f"(+1 where a keystone season exists) = "
         f"~{len(roster) * (len(ENDPOINTS) + 1)} requests, {args.workers} workers.")

    max_age_days = 0 if (args.force or args.limit or args.only) else 7
    chars, changed, report = refresh_card_cache(
        cfg, roster, max_age_days=max_age_days, workers=args.workers)

    _print_report(report, len(roster))
    _say("")
    state = ("updated" if changed else
             "unchanged (still fresh -- use --force to override)")
    _say(f"Card cache {state} -- {len(chars)} characters on file.")
    if changed:
        seamed = {}
        for rec in chars.values():
            for s in rec.get("seams") or []:
                seamed[s] = seamed.get(s, 0) + 1
        if seamed:
            _say("Honest seams (block absent -> that endpoint did not answer):")
            for block in sorted(seamed, key=lambda b: (-seamed[b], b)):
                _say(f"  {block:<18} {seamed[block]} character(s)")
        else:
            _say("No seams: every endpoint answered for every character.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

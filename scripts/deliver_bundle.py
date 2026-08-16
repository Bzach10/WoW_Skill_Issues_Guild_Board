"""Deliver the built web-data bundle to a consumer -- complete or not at all.

Why this exists
---------------
The 2026-07-23 split-brain was not produced by the pipeline; it was produced
by a HAND-COPY of one file (competition.json) into a consumer's source
directory while the sibling digests stayed a day old. This script is the
only sanctioned way to hand the bundle to a consumer:

  1. the source bundle must pass scripts/validate_bundle.py first;
  2. the consumer receives the ENTIRE delivered set or nothing;
  3. consumer-local files (the redesign's roster_supplement.json, its
     evidence-based membership record) are never touched;
  4. a DELIVERY.json manifest records what was delivered, from where, when.

OPTIONAL files (see OPTIONAL below) ride the same atomic swap when they are
present and are never a reason to refuse a delivery -- "complete or not at
all" is a rule about the required set, not a demand that every graceful
sidecar be healthy on the same day.

Default consumer: the redesign's contract inputs at
C:/dev/wipefest-redesign/data/source. Its own build (build_contract.py)
re-verifies everything on its side, so a bad delivery cannot silently ship
even if this script is bypassed -- but don't bypass it.

Usage:
    python scripts/deliver_bundle.py [--from DIR] [--to DIR] [--dry-run]

Exit 0 on delivery, 1 on refusal. Console output is ASCII-safe.
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from validate_bundle import validate_bundle  # noqa: E402

# Exactly the files the redesign's build_contract.py loads from data/source,
# minus its consumer-local ones (roster_supplement.json -- evidence-based
# membership the pipeline knows nothing about and must never overwrite).
DELIVERED = ("competition.json", "records_leaderboard.json",
             "recap_ribbon.json", "island_completion.json",
             "guild_achievements.json", "parses.json", "site_data.json")

# Delivered when present, never a reason to refuse. raid_kills.json is the
# per-boss kill record (build_site_data.py, Raider.io guilds/boss-kill): a
# sidecar the consumer reads as top authority when it is there and does
# without when it is not. Making it REQUIRED would mean a Raider.io fault on
# the boss-kill endpoint blocks the delivery of six healthy files -- the
# opposite of what a graceful layer is for. A bundle built before this file
# existed still delivers cleanly for the same reason.
# weekly_board.json is the SAME kind of sidecar: the weekly Discord board's
# own week (kills, pulls, wipes, deaths, this week's keys and parse pools, the
# improvement pairs, the roast). It only exists once a credentialed weekly run
# has posted, so a bundle built from a data refresh alone legitimately has no
# copy -- and the consumer's paper prints an honest PENDING seam rather than a
# zero. REQUIRED would mean the whole delivery refuses on a Tuesday morning.
# articles.json is the third: the public account <-> character projection
# (character key -> {account_id, is_main}) written by scripts/refresh_articles.py.
# It only exists once the articles are open and somebody has signed, and on day
# one it is legitimately `available: false` with zero signatures. The site's
# Ship's Articles leaf prints "N of 129 hands have signed" from it and prints
# the seam when N is 0 -- so a missing file must never refuse six healthy ones.
# shares.json is the fourth: the shares ledger's public projection (opaque
# account_id -> balance + this week's earn by loop) written by
# scripts/refresh_shares.py. It is downstream of articles.json -- no
# signatures, no shares -- and is computed only when a weekly_board with a
# week window exists, so its absence is the normal state until the economy is
# opened. REQUIRED would mean the currency's first week blocks the site's.
OPTIONAL = ("raid_kills.json", "weekly_board.json", "articles.json",
            "shares.json")

DEFAULT_TO = "C:/dev/wipefest-redesign/data/source"


def _say(msg):
    print(msg.encode("ascii", "backslashreplace").decode("ascii"))


def _default_from():
    """Prefer the cloud-committed bundle when present, else local output."""
    for name in ("web_data_public", "web_data"):
        d = os.path.join(ROOT, name)
        if os.path.isdir(d) and os.path.exists(os.path.join(d, "site_data.json")):
            return d
    return os.path.join(ROOT, "web_data")


def deliver(src_dir, dest_dir, dry_run=False):
    # Gate 1: never deliver a bundle that doesn't validate.
    report = validate_bundle(src_dir)
    report.dump()
    if report.errors:
        _say(f"DELIVERY REFUSED: source bundle failed validation ({src_dir})")
        return 1

    missing = [f for f in DELIVERED if not os.path.exists(os.path.join(src_dir, f))]
    if missing:
        _say("DELIVERY REFUSED: source bundle incomplete, missing: " + ", ".join(missing))
        return 1
    if not os.path.isdir(dest_dir):
        _say(f"DELIVERY REFUSED: destination does not exist: {dest_dir}")
        return 1

    present_optional = tuple(f for f in OPTIONAL
                             if os.path.exists(os.path.join(src_dir, f)))
    files = DELIVERED + present_optional

    if dry_run:
        _say(f"dry run: would deliver {len(files)} files "
             f"{src_dir} -> {dest_dir}")
        return 0

    manifest = {
        "delivered_at": datetime.now(timezone.utc).isoformat(),
        "delivered_from": os.path.abspath(src_dir),
        "delivered_by": "wipefest-board/scripts/deliver_bundle.py",
        "files": list(files),
        "optional_absent": [f for f in OPTIONAL if f not in present_optional],
        "note": ("Complete-set delivery. roster_supplement.json is "
                 "consumer-local and never delivered or touched."),
    }

    # Stage the complete set (plus manifest) on the destination volume first,
    # so the final step is a short same-volume swap, not a long copy that can
    # die halfway through a file.
    staging = tempfile.mkdtemp(prefix=".delivery-", dir=os.path.dirname(dest_dir.rstrip("/\\")) or ".")
    try:
        for f in files:
            shutil.copy2(os.path.join(src_dir, f), os.path.join(staging, f))
        with open(os.path.join(staging, "DELIVERY.json"), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=1)
        for f in files + ("DELIVERY.json",):
            os.replace(os.path.join(staging, f), os.path.join(dest_dir, f))
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    _say(f"delivered {len(files)} files + DELIVERY.json -> {dest_dir}")
    _say("next: python data/build_contract.py in the consumer repo "
         "(its own guard re-verifies the delivery)")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="src", default=None,
                        help="bundle directory (default: web_data_public if "
                             "present, else web_data)")
    parser.add_argument("--to", dest="dest", default=DEFAULT_TO,
                        help=f"consumer source directory (default: {DEFAULT_TO})")
    parser.add_argument("--dry-run", action="store_true",
                        help="validate and report without copying")
    args = parser.parse_args(argv)
    return deliver(args.src or _default_from(), args.dest, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())

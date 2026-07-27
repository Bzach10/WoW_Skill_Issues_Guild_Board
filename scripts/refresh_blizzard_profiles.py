"""Refresh the Blizzard character-profile cache: gender, race, class, active
spec, and transmog render URLs for every character in roster_cache.json.

Needs BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET in the environment AND
blizzard.enabled: true in config.yml — see SETUP_BLIZZARD.md. Safe to run
with either missing: it logs why it skipped and exits 0 without touching
the board pipeline.

Usage: python scripts/refresh_blizzard_profiles.py [--force]
           [--extra "name-realm,name-realm,..."]

--extra appends characters to the roster list for this refresh only —
same "name-realm" slug shape roster_cache.json uses. It exists for crew
the roster pull does not carry (e.g. unverified members who need armory
appearance data for cast art). Keys only; the appearance data itself
always comes from the Blizzard API, never by hand.
"""

import argparse
import os
import sys
from pathlib import Path

# Run directly (python scripts/refresh_blizzard_profiles.py), Python only
# puts this file's own directory on sys.path, not the repo root — so
# `guild_board` isn't importable without this. Same fix scripts/preview_board.py
# already uses.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guild_board.blizzard import refresh_profile_cache  # noqa: E402
from guild_board.config import load_config, load_roster_cache  # noqa: E402

REQUIRED_SECRETS = ("BLIZZARD_CLIENT_ID", "BLIZZARD_CLIENT_SECRET")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--extra", default="",
                        help="comma-separated extra name-realm keys to refresh "
                             "alongside the roster (keys only, data from API)")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    force = args.force

    cfg = load_config()

    if not (cfg.get("blizzard") or {}).get("enabled", False):
        print("blizzard.enabled is false in config.yml — set it to true, "
              "then re-run. See SETUP_BLIZZARD.md.")
        return 0

    missing = [name for name in REQUIRED_SECRETS if not os.environ.get(name, "").strip()]
    if missing:
        print(f"Missing secret(s): {', '.join(missing)} — add them under "
              f"this repo's Settings > Secrets and variables > Actions > "
              f"Repository secrets, then re-run. See SETUP_BLIZZARD.md.")
        return 0

    roster, _ = load_roster_cache(cfg)
    extra = [e.strip().lower() for e in args.extra.split(",") if e.strip()]
    if extra:
        seen = set(roster)
        added = [e for e in extra if e not in seen]
        roster = list(roster) + added
        print(f"--extra: {len(added)} character(s) appended to this refresh.")
    if not roster:
        print("roster_cache.json is empty or missing; nothing to refresh. "
              "Run the weekly board at least once first so a roster exists.")
        return 0

    max_age_days = 0 if force else 7
    _, changed = refresh_profile_cache(cfg, roster, max_age_days=max_age_days)
    print("Blizzard profile cache updated." if changed else
          "Blizzard profile cache unchanged (still fresh — use --force to override).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

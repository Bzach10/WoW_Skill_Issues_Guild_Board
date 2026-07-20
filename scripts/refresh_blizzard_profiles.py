"""Refresh the Blizzard character-profile cache: gender, race, class, active
spec, and transmog render URLs for every character in roster_cache.json.

Needs BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET in the environment AND
blizzard.enabled: true in config.yml — see SETUP_BLIZZARD.md. Safe to run
with either missing: it logs why it skipped and exits 0 without touching
the board pipeline.

Usage: python scripts/refresh_blizzard_profiles.py [--force]
"""

import sys

from guild_board.blizzard import refresh_profile_cache
from guild_board.config import load_config, load_roster_cache


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    force = "--force" in argv

    cfg = load_config()
    roster, _ = load_roster_cache(cfg)
    if not roster:
        print("roster_cache.json is empty or missing; nothing to refresh. "
              "Run the weekly board at least once first so a roster exists.")
        return 0

    max_age_days = 0 if force else 7
    _, changed = refresh_profile_cache(cfg, roster, max_age_days=max_age_days)
    print("Blizzard profile cache updated." if changed else
          "Blizzard profile cache unchanged (disabled, no creds, or still fresh).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

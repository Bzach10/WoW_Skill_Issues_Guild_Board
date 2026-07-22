"""Refresh the Blizzard GUILD cache: guild achievements + activity.

Companion to refresh_blizzard_profiles.py, kept separate so the two data
paths are independent (a guild-endpoint hiccup never blocks the per-character
profile refresh, and vice versa). Writes blizzard_guild_cache.json.

This is what populates:
  - layer 3 (guild achievements / trophy hall), and
  - layer 4's authoritative per-boss raid kills (first-kill dates),
once build_site_data.py consumes the committed cache.

Needs BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET in the environment AND
blizzard.enabled: true in config.yml — see SETUP_BLIZZARD.md. Safe to run
with either missing: it logs why it skipped and exits 0.

Usage: python scripts/refresh_guild_data.py [--force]
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guild_board.blizzard import refresh_guild_cache  # noqa: E402
from guild_board.config import load_config  # noqa: E402

REQUIRED_SECRETS = ("BLIZZARD_CLIENT_ID", "BLIZZARD_CLIENT_SECRET")


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    force = "--force" in argv

    cfg = load_config()

    if not (cfg.get("blizzard") or {}).get("enabled", False):
        print("blizzard.enabled is false in config.yml — set it to true, "
              "then re-run. See SETUP_BLIZZARD.md.")
        return 0

    missing = [name for name in REQUIRED_SECRETS if not os.environ.get(name, "").strip()]
    if missing:
        print(f"Missing secret(s): {', '.join(missing)} — add them under this "
              f"repo's Settings > Secrets and variables > Actions > Repository "
              f"secrets, then re-run. See SETUP_BLIZZARD.md.")
        return 0

    max_age_days = 0 if force else 7
    guild_data, changed = refresh_guild_cache(cfg, max_age_days=max_age_days)
    if changed:
        ach = (guild_data.get("achievements") or {}).get("achievements") or []
        print(f"Guild cache updated: {len(ach)} achievement(s), "
              f"activity {'present' if guild_data.get('activity') else 'absent'}.")
    else:
        print("Guild cache unchanged (still fresh — use --force to override, "
              "or creds/config not set).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

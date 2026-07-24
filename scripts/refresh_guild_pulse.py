"""Refresh the Guild Pulse cache — a living feed of guild-public Discord
highlights for the website (chat, memes, banter, notable reactions).

Uses the SAME read-only bot token the weekly board already uses
(DISCORD_BOT_TOKEN). Reads ONLY the channels listed in
config.yml -> discord_inputs.pulse_channels; there is no path here that
reads DMs, private channels, or anything not explicitly allowlisted.

Writes guild_pulse_cache.json, which build_site_data.py reads to populate
the site's guild_pulse layer.

Privacy controls (all in config, all optional):
  pulse_channels        the allowlist — the only channels read
  pulse_exclude_emoji   react with this to drop a message (default 🙈)
  pulse_opt_out_marker  put this text in a message to drop it (default [nofeed])
  pulse_blocklist       list of substrings that drop any matching message
  pulse_lookback_days   how far back to look (default 14)

Usage: python scripts/refresh_guild_pulse.py
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guild_board.config import load_config  # noqa: E402
from guild_board.discord_inputs import (  # noqa: E402
    DEFAULT_EXCLUDE_EMOJI,
    DEFAULT_OPT_OUT_MARKER,
    fetch_guild_pulse,
)

CACHE_PATH = "guild_pulse_cache.json"


def main(argv=None):
    cfg = load_config()
    inputs_cfg = cfg.get("discord_inputs") or {}

    if not inputs_cfg.get("enabled", False):
        print("discord_inputs is disabled in config.yml — nothing to refresh.")
        return 0

    channels = inputs_cfg.get("pulse_channels") or []
    if not channels:
        print("No discord_inputs.pulse_channels configured — add the "
              "guild-public channels to surface (see WEB_DATA_CONTRACT.md). "
              "Nothing read.")
        return 0

    bot_token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not bot_token:
        print("DISCORD_BOT_TOKEN is not set — skipping. Set it in the Action "
              "secrets (the same token the weekly board uses).")
        return 0

    lookback = int(inputs_cfg.get("pulse_lookback_days", 14))
    since = datetime.now(timezone.utc) - timedelta(days=lookback)
    since_ms = int(since.timestamp() * 1000)

    items = fetch_guild_pulse(
        bot_token, channels, since_ms,
        per_channel_limit=int(inputs_cfg.get("pulse_per_channel_limit", 20)),
        exclude_emoji=inputs_cfg.get("pulse_exclude_emoji", DEFAULT_EXCLUDE_EMOJI),
        opt_out_marker=inputs_cfg.get("pulse_opt_out_marker", DEFAULT_OPT_OUT_MARKER),
        blocklist=inputs_cfg.get("pulse_blocklist") or [])

    path = (cfg.get("discord_inputs") or {}).get("pulse_cache_file", CACHE_PATH)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "lookback_days": lookback,
            "items": items,
        }, f, indent=2, ensure_ascii=False)

    kinds = {}
    for it in items:
        kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
    print(f"Guild pulse refreshed: {len(items)} item(s) across "
          f"{len(channels)} channel(s) -> {path}")
    print(f"  by kind: {kinds or '(none)'}")
    if not items:
        print("  (0 items — if channels are active, check the bot has View "
              "Channel + Read Message History + Message Content Intent.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

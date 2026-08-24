"""Post the daily WANTED BOARD summary to Discord — the top M+ standings
plus a button to the full site — via the existing webhook path.

Uses guild_board.discord.post_to_discord (the same webhook the weekly board
already uses), so it inherits the link buttons (incl. the ship-site link
from config display.site_url) and the 429/component-retry handling.

SAFE BY DEFAULT: this is an outward-facing post, so it does nothing unless
BOTH are true:
  - DISCORD_WEBHOOK_URL is set, and
  - config competition.daily_post is true, OR --force is passed.
That keeps the plumbing ready and testable without auto-posting until it's
deliberately switched on.

Usage: python scripts/post_competition_board.py [--force]
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guild_board.config import load_config  # noqa: E402
from guild_board.discord import post_to_discord  # noqa: E402
from guild_board.links import site_url  # noqa: E402

REPO_ROOT = str(Path(__file__).resolve().parents[1])
MEDAL = {1: "🥇", 2: "🥈", 3: "🥉"}


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def build_board_embed(competition):
    """A bounty-board style embed from the competition top 5 + a movement line."""
    top5 = competition["rankings"]["top5"]
    if not top5:
        return None
    lines = []
    for r in top5:
        medal = MEDAL.get(r["rank"], f"#{r['rank']}")
        delta = ""
        if r.get("delta_week"):
            arrow = "▲" if r["delta_week"] > 0 else "▼"
            delta = f"  {arrow}{abs(r['delta_week']):.0f}"
        lines.append(f"{medal} **{r['name']}** — {r['score']:.0f}  ·  {r['spec']}{delta}")

    mv = competition.get("movement") or {}
    footer_bits = []
    if mv.get("biggest_gain"):
        g = mv["biggest_gain"]
        footer_bits.append(f"📈 Biggest climb: {g['name']} +{g['delta_week']:.0f}")
    if mv.get("new_to_board"):
        footer_bits.append(f"🆕 {len(mv['new_to_board'])} new to the board")

    return {
        "title": "⚔️  THE WANTED BOARD  ⚔️",
        "description": "\n".join(lines),
        "color": 0xE8B923,
        "footer": {"text": "  ·  ".join(footer_bits) or "M+ season standings"},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="post even if config competition.daily_post is false")
    args = parser.parse_args(argv)

    cfg = load_config()
    if not args.force and not (cfg.get("competition") or {}).get("daily_post", False):
        print("competition.daily_post is false (and no --force) — not posting. "
              "The board data still refreshed; only the Discord post is gated.")
        return 0

    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        print("DISCORD_WEBHOOK_URL not set — nothing to post to.")
        return 0

    competition = _load(os.path.join(REPO_ROOT, "web_data_public", "competition.json"),
                        None) or _load(os.path.join(REPO_ROOT, "web_data", "competition.json"), None)
    if not competition or not competition.get("available"):
        print("No competition data available to post — run refresh_competition.py first.")
        return 0

    embed = build_board_embed(competition)
    if not embed:
        print("Competition data has no ranked characters — nothing to post.")
        return 0

    journal = site_url(cfg, "standings/")
    content = "Daily standings are up! ⚓" + (
        f"  The Captain's Journal → {journal}" if journal else "")
    post_to_discord(webhook, embed, content=content, cfg=cfg)
    print("Posted the daily WANTED BOARD to Discord.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

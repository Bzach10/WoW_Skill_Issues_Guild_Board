"""Render the Voyage Map with real data — no fake/preview data involved.

- Island roster: guild_board.voyage.build_islands() (the real season's
  dungeons + raid tier, already used elsewhere in the pipeline).
- Current island's data: a live, public Raider.io call for the roster's
  actual best timed run there this week (needs no credentials).
- Raid islands' data: pulled straight from the existing board_state.json
  records (already-collected real data, no new fetch).

Writes voyage_map_render.html to the repo root (gitignored, same
convention as board_render.html) — open it in a browser to see it.

Usage: python scripts/render_voyage_map.py
"""

import json
import sys
from pathlib import Path

# Run directly (python scripts/render_voyage_map.py), Python only puts
# this file's own directory on sys.path, not the repo root — so
# `guild_board` isn't importable without this. Same fix scripts/preview_board.py uses.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guild_board import theme as theme_mod  # noqa: E402
from guild_board import voyage  # noqa: E402
from guild_board.config import load_config  # noqa: E402
from guild_board.html_board import render_html  # noqa: E402


def _load_board_state(path="board_state.json"):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def main():
    cfg = load_config()
    theme = theme_mod.load_theme()
    board_state = _load_board_state()

    islands = voyage.build_islands()
    current_id = voyage.current_island_id(cfg)

    for island in islands:
        if island["kind"] == "dungeon":
            island["data"] = (voyage.fetch_dungeon_island_data(cfg, island["name"])
                               if island["id"] == current_id else None)
        else:
            island["data"] = voyage.fetch_raid_island_data(board_state, island["name"])

    context = {
        "guild_name": cfg["guild"]["name"],
        "season_label": "the current season",
        "islands": islands,
        "current_island_id": current_id,
        "theme": theme,
        "font_css_url": theme_mod.font_css_url(theme),
    }
    html = render_html(context, template="voyage_map.html.j2")
    out_path = "voyage_map_render.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {out_path}")
    print(f"Current island: {current_id}")
    current = next(i for i in islands if i["id"] == current_id)
    print(f"Current island data: {current.get('data')}")


if __name__ == "__main__":
    main()

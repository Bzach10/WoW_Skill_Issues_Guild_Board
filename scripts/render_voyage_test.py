#!/usr/bin/env python3
"""Render the voyage-map TEST RUN for review.

    python scripts/fetch_voyage_data.py      # live guild data (optional)
    python scripts/render_voyage_test.py

Renders every season we have content for into one page, so the Season 2
swap can be demonstrated rather than described. Private: noindex, and
the renderer refuses to write into site/.
"""

import argparse
import html
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import jinja2  # noqa: E402

from guild_board import crew as crew_mod  # noqa: E402
from guild_board import seasons as seasons_mod  # noqa: E402
from guild_board import theme as theme_mod  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("voyage_test")
TEMPLATES = Path(__file__).resolve().parent.parent / "guild_board" / "templates"
FONT_CSS = ("https://fonts.googleapis.com/css2"
            "?family=Cinzel+Decorative:wght@400;700;900"
            "&family=Inter:wght@400;600;700;900"
            "&family=JetBrains+Mono:wght@400;700&display=swap")


def _cfg(path="config.yml"):
    import yaml
    try:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except OSError:
        return {}


def _fmt_time(ms):
    if not ms:
        return None
    total = int(ms // 1000)
    return f"{total // 60}:{total % 60:02d}"


def _dungeon_detail(island, run):
    if not run:
        return (f'<span class="tag">Dungeon</span><h3>{html.escape(island["name"])}</h3>'
                f'<p class="norec">No timed key recorded here yet.</p>')
    bits = [f'<span class="tag">Dungeon</span><h3>{html.escape(island["name"])}</h3>',
            '<div class="stats">',
            f'<div class="stat"><div class="k">Guild best</div>'
            f'<div class="v">+{run["level"]}</div><div class="d">timed</div></div>',
            f'<div class="stat"><div class="k">Held by</div>'
            f'<div class="v" style="font-size:16px;">{html.escape(str(run.get("name","")))}</div>'
            f'<div class="d">{html.escape(str(run.get("realm","")).replace("-", " ").title())}</div></div>']
    if run.get("score"):
        bits.append(f'<div class="stat"><div class="k">Run score</div>'
                    f'<div class="v">{run["score"]}</div><div class="d">points</div></div>')
    clear = _fmt_time(run.get("clear_time_ms"))
    if clear:
        bits.append(f'<div class="stat"><div class="k">Clear time</div>'
                    f'<div class="v">{clear}</div><div class="d">best run</div></div>')
    bits.append("</div>")
    return "".join(bits)


def _boss_detail(island, index, killed, records):
    name = html.escape(island["name"])
    status = ("Defeated on Mythic" if index < killed.get("mythic", 0)
              else "Defeated on Heroic" if index < killed.get("heroic", 0)
              else "Defeated on Normal" if index < killed.get("normal", 0)
              else None)
    bits = [f'<span class="tag raid">Raid boss</span><h3>{name}</h3>']
    bits.append('<div class="stats">')
    bits.append(f'<div class="stat"><div class="k">Status</div>'
                f'<div class="v" style="font-size:15px;">{status or "Not yet defeated"}</div>'
                f'<div class="d">boss {index + 1} of {killed.get("total", "?")}</div></div>')
    for key, rec in (records or {}).items():
        bits.append(f'<div class="stat"><div class="k">{html.escape(rec["label"])}</div>'
                    f'<div class="v">{rec.get("parse")}</div>'
                    f'<div class="d">{html.escape(str(rec.get("name") or ""))}'
                    f'{" · " + html.escape(rec["spec"]) if rec.get("spec") else ""}</div></div>')
    bits.append("</div>")
    if not records:
        bits.append('<p class="norec" style="margin-top:12px;">'
                    'No parse record on the board for this boss yet.</p>')
    return "".join(bits)


def build_season_view(season, live):
    """One season, ready to render."""
    live = live or {}
    islands = seasons_mod.islands(season, live=live)
    raid = season.get("raid") or {}
    prog = (live.get("raid_progression") or {}).get(raid.get("slug")) or {}
    killed = {
        "normal": prog.get("normal_bosses_killed", 0),
        "heroic": prog.get("heroic_bosses_killed", 0),
        "mythic": prog.get("mythic_bosses_killed", 0),
        "total": prog.get("total_bosses") or len(raid.get("bosses") or []),
    }
    dungeons = live.get("dungeons") or {}
    bosses = live.get("bosses") or {}

    boss_index = 0
    for island in islands:
        if island["kind"] == "dungeon":
            run = dungeons.get(island["name"])
            island["detail_html"] = _dungeon_detail(island, run)
            island["state"] = "cleared" if run else "none"
        else:
            island["detail_html"] = _boss_detail(
                island, boss_index, killed, bosses.get(island["name"]))
            island["state"] = "cleared" if boss_index < max(
                killed["normal"], killed["heroic"], killed["mythic"]) else "none"
            boss_index += 1

    rows = []
    total = killed["total"] or 1
    for label, key in (("Mythic", "mythic"), ("Heroic", "heroic"), ("Normal", "normal")):
        rows.append({"label": label, "killed": killed[key], "total": killed["total"],
                     "pct": round(killed[key] / total * 100)})

    return {
        "id": season.get("id"),
        "label": season.get("label") or season.get("id"),
        "raid_name": raid.get("name"),
        "islands": islands,
        "progression": rows if any(r["killed"] for r in rows) else None,
        "note": (f"{season.get('label')} · {len(season.get('dungeons') or [])} dungeons + "
                 f"{len(raid.get('bosses') or [])} bosses in {raid.get('name')}"
                 + (f" · starts {season.get('starts', '')[:10]}" if season.get("starts") else "")),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="voyage_test.html")
    args = ap.parse_args()

    cfg = _cfg()
    theme = theme_mod.load_theme(theme_mod.THEME_FILE)
    try:
        live = json.loads(Path("voyage_data.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        live = {}
        logger.warning("No voyage_data.json — run scripts/fetch_voyage_data.py "
                       "for live guild data. Islands will show no records.")

    active = seasons_mod.active_id(cfg=cfg)
    views = []
    for season_id in seasons_mod.available():
        season = seasons_mod.load(season_id)
        if not season:
            continue
        # live data only belongs to the season it was fetched for
        views.append(build_season_view(
            season, live if live.get("season") == season_id else {}))
    if not views:
        raise SystemExit("No season content in seasons/ — nothing to render.")
    views.sort(key=lambda v: v["id"] != active)     # active first

    ctx = {
        "guild_name": (cfg.get("guild") or {}).get("name") or "Skill Issues",
        "themes": crew_mod.resolve_themes(theme),
        "default_theme": crew_mod.default_theme_key(theme),
        "font_css_url": FONT_CSS,
        "season_list": views,
        "active_season": active,
        "season_notes": {v["id"]: v["note"] for v in views},
        "fetched_note": (f"guild data fetched {live.get('fetched_at')}"
                         if live.get("fetched_at") else "no live guild data loaded"),
    }

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATES)),
                             autoescape=True)
    out = Path(args.out)
    if "site" in {p.lower() for p in out.parts}:
        raise SystemExit("Refusing to write into site/ — this is a private test run.")
    out.write_text(env.get_template("web/pages/voyage.html.j2").render(**ctx),
                   encoding="utf-8")

    for view in views:
        cleared = sum(1 for i in view["islands"] if i["state"] == "cleared")
        logger.info("%s: %d islands, %d with real progress%s",
                    view["label"], len(view["islands"]), cleared,
                    "  (ACTIVE)" if view["id"] == active else "")
    logger.info("Wrote %s", out)


if __name__ == "__main__":
    main()

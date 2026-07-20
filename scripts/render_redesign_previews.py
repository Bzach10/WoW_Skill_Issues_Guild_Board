"""Render every web layout x theme combination for side-by-side review.

    python scripts/render_redesign_previews.py            # all combos
    python scripts/render_redesign_previews.py --png      # + screenshots
    python scripts/render_redesign_previews.py --layout codex --theme gildedcodex

Output: redesign_previews/<layout>__<theme>.html (+ .png with --png) and
redesign_previews/index.html, a contact sheet linking all of them.

ABOUT THE DATA — this matters when you judge the designs:

  REAL, from the guild's own committed files:
    guild/realm/region, raid difficulty and the roast of the week
      (config.yml)
    realm / region / world rank, the season M+ score ladder, Iron
    Attendance streaks, and the guild records incl. highest timed key
      (board_state.json, last updated by the live workflow)

  FIXTURE, from scripts/preview_board.py:
    this week's raid slice — best DPS/HPS/tank parses, deaths, pulls,
    kills, the weekly M+ runs and Most Improved.

Those weekly numbers come from Warcraft Logs at build time and are not
persisted between runs, so they cannot be replayed locally without API
keys. Every layout renders them identically, so the comparison is still
apples-to-apples — just don't read the weekly parse numbers as truth.
"""

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from guild_board import html_board  # noqa: E402
from scripts import preview_board as fixture  # noqa: E402

OUT_DIR = ROOT / "redesign_previews"
THEME_DIR = ROOT / "themes"
LAYOUT_DIR = ROOT / "guild_board" / "templates" / "web"

# Specs for the real season-score names, so class colors survive the swap
# to real data (board_state.json stores scores, not specs).
KNOWN_SPECS = {
    "amrevenge": "Beast Mastery Hunter", "shadoxii": "Mistweaver Monk",
    "brewzleeh": "Brewmaster Monk", "tommybravoo": "Unholy DK",
    "rakdisc": "Discipline Priest", "floofwall": "Guardian Druid",
    "ellebasi": "Frost Mage", "tommybravox": "Havoc DH",
    "healyeah": "Augmentation Evoker", "boondocka": "Beast Mastery Hunter",
}


def discover(kind):
    """Layouts on disk (minus partials) / themes on disk."""
    if kind == "layouts":
        return sorted(p.stem.replace(".html", "") for p in LAYOUT_DIR.glob("*.html.j2")
                      if not p.name.startswith("_"))
    return sorted(p.name[len("theme."):-len(".yml")] for p in THEME_DIR.glob("theme.*.yml"))


def real_state():
    """The guild's committed state, shaped for build_context."""
    import json
    with open(ROOT / "board_state.json", "r", encoding="utf-8") as f:
        state = json.load(f)
    scores = state.get("season_scores") or {}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:5]
    season_scores = [(int(score), name.title(), KNOWN_SPECS.get(name, ""))
                     for name, score in ranked]
    baseline = state.get("baseline") or {}
    previous = {
        "standing": baseline.get("standing") or {},
        "season_scores": baseline.get("season_scores") or {},
        "streaks": baseline.get("streaks") or {},
    }
    return {
        "standing": state.get("standing") or {},
        "season_scores": season_scores,
        "streaks": state.get("streaks") or {},
        "records": state.get("records") or {},
        "previous": previous,
    }


def real_cfg():
    """The guild's real config, forced to the HTML renderer."""
    with open(ROOT / "config.yml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("display", {})["renderer"] = "html"
    return cfg


def build(cfg, state, theme_file):
    now = datetime.now(timezone.utc)
    cfg = dict(cfg)
    cfg["display"] = dict(cfg.get("display") or {})
    cfg["display"]["theme_file"] = str(theme_file)
    return html_board.build_context(
        cfg, fixture.FAKE_STATS, state["standing"], fixture.FAKE_LEADERS,
        "Voidspire Sanctum", fixture.FAKE_MPLUS, state["season_scores"],
        fixture.FAKE_SEASON_PARSES, now - timedelta(days=7), now,
        improvement=fixture.FAKE_IMPROVEMENT, mplus_weekly=fixture.FAKE_MPLUS_WEEKLY,
        previous=state["previous"], streaks=state["streaks"], records=state["records"])


# Preview pages live one directory down, so repo-relative asset paths
# need a hop up. (The real site is written to site/index.html with the
# assets copied alongside, so this only ever applies to previews.)
_ASSET_REF = re.compile(r'(url\(["\']?|src=["\'])assets/')


def render(context, layout):
    context = dict(context)
    context["web_layout_template"] = f"web/{layout}.html.j2"
    html = html_board.render_html(context, template="web.html.j2")
    return _ASSET_REF.sub(lambda m: m.group(1) + "../assets/", html)


def contact_sheet(combos):
    """A plain index so every option is one click away."""
    cards = "\n".join(
        f'    <a class="c" href="{layout}__{theme}.html">'
        f'<span class="l">{layout}</span><span class="t">{theme}</span></a>'
        for layout, theme in combos)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Guild Board — redesign options</title>
<style>
 body{{background:#0d0d12;color:#eee;font:16px/1.6 system-ui,sans-serif;margin:0;padding:40px 24px;}}
 h1{{font-size:24px;margin:0 0 6px;}} p{{color:#9a9aa8;max-width:70ch;margin:0 0 28px;}}
 .g{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;max-width:1100px;}}
 .c{{display:flex;flex-direction:column;gap:4px;padding:18px;border:1px solid #2b2b38;border-radius:10px;
    text-decoration:none;color:inherit;background:#15151d;transition:border-color .15s,background .15s;}}
 .c:hover{{border-color:#c9974a;background:#1b1b26;}}
 .l{{font-weight:700;font-size:17px;}} .t{{color:#9a9aa8;font-size:13px;}}
</style></head><body>
<h1>Guild Board — redesign options</h1>
<p>Every layout paired with every theme. Layout is the structure; theme is the paint.
Both are picked in theme.yml — <code>board.web_layout</code> and the colors/art blocks.
Resize the window (or open on your phone) to see the reflow.</p>
<div class="g">
{cards}
</div></body></html>
"""


def main():
    ap = argparse.ArgumentParser(description="Render layout x theme previews")
    ap.add_argument("--layout", help="only this layout")
    ap.add_argument("--theme", help="only this theme")
    ap.add_argument("--png", action="store_true", help="also screenshot each (needs Playwright)")
    args = ap.parse_args()

    layouts = [args.layout] if args.layout else discover("layouts")
    themes = [args.theme] if args.theme else discover("themes")
    OUT_DIR.mkdir(exist_ok=True)

    cfg, state = real_cfg(), real_state()
    combos, pages = [], []
    for theme in themes:
        theme_file = THEME_DIR / f"theme.{theme}.yml"
        if not theme_file.exists():
            print(f"  ! no such theme: {theme_file.name}")
            continue
        context = build(cfg, state, theme_file)
        for layout in layouts:
            if not (LAYOUT_DIR / f"{layout}.html.j2").exists():
                print(f"  ! no such layout: {layout}")
                continue
            out = OUT_DIR / f"{layout}__{theme}.html"
            out.write_text(render(context, layout), encoding="utf-8")
            combos.append((layout, theme))
            pages.append(out)
            print(f"  {out.relative_to(ROOT)}")

    if not combos:
        print("Nothing rendered.")
        return 1
    (OUT_DIR / "index.html").write_text(contact_sheet(combos), encoding="utf-8")
    print(f"\n{len(combos)} preview(s) + redesign_previews/index.html")

    if args.png:
        shoot(pages)
    return 0


def shoot(pages):
    """Full-page screenshots, desktop + phone widths."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed; skipping screenshots "
              "(pip install playwright && playwright install chromium)")
        return
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for path in pages:
            for label, width in (("", 1600), ("_phone", 430)):
                page = browser.new_page(viewport={"width": width, "height": 1200},
                                        device_scale_factor=1)
                page.goto(path.resolve().as_uri())
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(900)   # webfonts + icon CDN settle
                shot = path.with_name(path.stem + label + ".png")
                page.screenshot(path=str(shot), full_page=True)
                page.close()
                print(f"  shot {shot.name}")
        browser.close()


if __name__ == "__main__":
    sys.exit(main())

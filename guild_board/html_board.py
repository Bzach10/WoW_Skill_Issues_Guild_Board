"""Render the weekly board from an HTML template via headless Chromium.

The design IS the render: guild_board/templates/stone_torchlight.html.j2
carries the exact CSS of the approved design, this module feeds it the same
live data structures the Pillow renderer uses, and Playwright screenshots
the page. Animation frames are captured by pausing every CSS animation and
seeking it to phase*loop — all template animation periods divide the loop,
so any frame count loops seamlessly.

Fails open: any missing dependency or browser error returns None so the
caller falls back to the battle-tested Pillow renderer.
"""

import logging
import math
import os
import random
from pathlib import Path

from PIL import Image

from guild_board import board_image, theme_bands
from guild_board.board_image import (
    CLASS_ICONS, DIFFICULTY_NAMES, ICON_CDN, MEDAL_FILLS, SPEC_ICONS,
    _build_columns, _build_seasonal, _hero_tiles, _plural, _spec_class_keys,
)

logger = logging.getLogger(__name__)

LOOP_MS = 1200
TEMPLATE_DIR = Path(__file__).parent / "templates"
RENDER_HTML = "board_render.html"   # written to cwd so relative assets/ paths work

# band heights — MUST match the template's .hdr/.ftr/.motd/.credits CSS so
# the GIF encoder knows which rows are animated
HEADER_H = 330
FOOTER_TOTAL = 470 + 52 + 40

# tombstone geometry from the design (w, h, arched, cross, rotation)
STONES = [
    (170, 216, True, False, -2.5, ("#767268", "#56534b", "#3e3c36")),
    (180, 238, False, True, 1.6, ("#7c786d", "#5a574f", "#403e38")),
    (158, 196, True, False, -1.2, ("#6e6a60", "#514e46", "#3a3832")),
    (158, 182, False, False, 2.2, ("#6e6a60", "#514e46", "#3a3832")),
]

DEBUFFS = [
    ("inv_misc_questionmark", "bad", "Skill Issue", "40"),
    ("spell_fire_fire", "bad", "Standing in Fire (Healmates)", "6w"),
    ("inv_misc_bone_humanskull_01", "bad", "Graveyard Timeshare", None),  # deaths
    ("spell_nature_sleep", "good", "Coping", "∞"),
    ("spell_holy_layonhands", "good", "Healer Diff", "1"),
]


def _css(color):
    if isinstance(color, str):
        return color
    return f"rgb({color[0]},{color[1]},{color[2]})"


def _icon_url(row):
    spec_key, cls_key = _spec_class_keys(row.get("spec"), row.get("cls"))
    if (cls_key, spec_key) in SPEC_ICONS:
        return ICON_CDN.format(SPEC_ICONS[(cls_key, spec_key)])
    if cls_key in CLASS_ICONS:
        return ICON_CDN.format(CLASS_ICONS[cls_key])
    return None


def _flames_row(seed=13, n=9):
    """Fire licking up from the footer's bottom edge — deterministic
    positions, loop-safe durations."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        out.append({
            "left": round(3 + i * (94 / max(n - 1, 1)) + rng.random() * 3, 1),
            "w": int(46 + rng.random() * 50),
            "h": int(80 + rng.random() * 70),
            "dur": 0.6, "dur2": 0.3,
            "delay": round(-rng.random() * (LOOP_MS / 1000), 2),
        })
    return out


def _embers(seed, n):
    """Deterministic particle field; delays are negative so every phase of
    the loop is populated (matches the design's ember spray)."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        out.append({
            "left": round(rng.random() * 100, 1),
            "size": round(3 + rng.random() * 5, 1),
            "delay": round(-rng.random() * (LOOP_MS / 1000), 2),
            "drift": round((rng.random() - 0.5) * 120),
        })
    return out


def _html_rows(sections):
    """Convert the Pillow section model into template-ready dicts."""
    out = []
    for sec in sections:
        rows = []
        for i, row in enumerate(sec["rows"]):
            if "text" in row:
                rows.append({"text": row["text"]})
                continue
            rows.append({
                "rank": i + 1,
                "medal": _css(MEDAL_FILLS[i]) if i < len(MEDAL_FILLS) else None,
                "icon": _icon_url(row),
                "name": row.get("name", ""),
                "color": _css(row.get("color", (235, 236, 240))),
                "detail": row.get("detail", ""),
                "value": row.get("value", ""),
                "value_color": _css(row.get("value_color", (235, 236, 240))),
                "value_suffix": row.get("value_suffix"),
                "value_suffix_color": _css(row["value_suffix_color"]) if row.get("value_suffix_color") else None,
            })
        out.append({"title": sec["title"], "rows": rows})
    return out


def _roast(cfg):
    sections_cfg = cfg.get("sections", {})
    roast_cfg = sections_cfg.get("roast_of_the_week") or cfg.get("roast_of_the_week") or {}
    if not roast_cfg.get("enabled", True):
        return None
    if roast_cfg.get("roast"):
        quote = f"“{roast_cfg['roast']}”"
        winner = roast_cfg.get("winner", "Anonymous")
        target = roast_cfg.get("target", "")
        attr = f"— {winner}" + (f", aimed at {target}" if target else "")
    else:
        quote = "No roast submitted. Healers live to see another week."
        attr = ""
    return {"quote": quote, "attr": attr}


def build_context(cfg, stats, standing, leaders, zone_name, mplus_results,
                  mplus_season_scores, mplus_season_parses, start_dt, end_dt,
                  no_logs=False, improvement=None, mplus_weekly=None,
                  previous=None, streaks=None, records=None):
    sections_cfg = cfg.get("sections", {})
    raid_secs, mplus_secs = _build_columns(
        cfg, stats, leaders, mplus_results, mplus_season_scores, mplus_season_parses,
        no_logs, mplus_weekly=mplus_weekly, streaks=streaks, zone_name=zone_name)
    seasonal_mp, seasonal_guild = _build_seasonal(
        cfg, mplus_season_scores, mplus_season_parses, improvement,
        previous=previous, records=records)

    raid_title = (sections_cfg.get("raid_header") or {}).get("title", "Raid").upper()
    mplus_title = (sections_cfg.get("mplus_header") or {}).get("title", "Mythic Plus").upper()
    columns = [
        {"title": raid_title, "sections": _html_rows(raid_secs), "empty": "No data this week"},
        {"title": mplus_title, "sections": _html_rows(mplus_secs), "empty": "No data this week"},
        {"title": "SEASONAL MYTHIC PLUS", "sections": _html_rows(seasonal_mp), "empty": "Season data still cooking"},
        {"title": "SEASONAL GUILD", "sections": _html_rows(seasonal_guild), "empty": "Season data still cooking"},
    ]

    kills = (stats or {}).get("kills", 0)
    pulls = (stats or {}).get("pulls", 0)
    deaths_total = sum(((stats or {}).get("deaths") or {}).values())
    wipes = max(pulls - kills, 0)

    tiles = [{"label": lbl, "value": val, "delta": delta, "delta_color": _css(color)}
             for lbl, val, delta, color in _hero_tiles(stats, standing, previous)]
    if pulls > 0:
        bar_pct = max(round(kills / pulls * 100, 1), 2 if kills else 0)
        bar_label = f"{_plural(kills, 'kill')} in {_plural(pulls, 'pull')} ({kills / pulls * 100:.0f}%)"
    else:
        bar_pct, bar_label = 0, "No pulls this week"

    lookback = int(cfg.get("lookback_days", 7))
    range_label = "Raid week" if lookback == 7 else f"Last {lookback} days"
    date_range = f"{range_label}: {start_dt.strftime('%b %d')} – {end_dt.strftime('%b %d, %Y')}"
    difficulty = str(cfg.get("raid", {}).get("difficulty", "mythic"))
    if stats and stats.get("difficulty") in DIFFICULTY_NAMES:
        difficulty = DIFFICULTY_NAMES[stats["difficulty"]]
    difficulty = difficulty.upper()
    subtitle = f"{difficulty} · {zone_name}" if zone_name else f"{difficulty} WEEKLY BOARD"

    guild = cfg.get("guild", {})
    realm = (guild.get("realm_slug") or "").replace("-", " ").upper()
    region = (guild.get("region") or "").upper()

    ranked = sorted(((stats or {}).get("deaths") or {}).items(),
                    key=lambda kv: kv[1], reverse=True)[:4]
    if not ranked:
        ranked = [("Nobody", 0)]
    stones = []
    for i, (name, count) in enumerate(ranked):
        w, h, arched, cross, rot, (light, mid, dark) = STONES[i % len(STONES)]
        rate = f" · {count / pulls:.1f}/PULL" if pulls else ""
        stones.append({
            "w": w, "h": h, "arched": arched, "cross": cross, "rot": rot,
            "light": light, "mid": mid, "dark": dark,
            "radius": (f"{w // 2}px {w // 2}px 6px 6px" if arched else "14px 14px 6px 6px"),
            "name": name.upper()[:12],
            "deaths": f"{count} DEATHS{rate}",
            "epitaph": theme_bands.EPITAPHS[i % len(theme_bands.EPITAPHS)],
        })

    debuffs = []
    for icon, kind, label, stack in DEBUFFS:
        debuffs.append({"url": ICON_CDN.format(icon), "kind": kind, "title": label,
                        "stack": stack if stack is not None else str(deaths_total)})

    display_cfg = cfg.get("display") or {}
    item_src = display_cfg.get("item_art")
    if item_src and not os.path.exists(item_src):
        item_src = None
    week_index = start_dt.isocalendar()[1]
    # Brewzleeh's gambling debt compounds 9.99% weekly on a 137,000g
    # principal — deterministic, so it climbs a little more every board.
    debt = int(137_000 * (1.0999 ** week_index))

    return {
        "guild_name": guild.get("name", "Guild"),
        "realm_label": f"{realm} · {region}" if realm else region,
        "subtitle": subtitle,
        "date_range": date_range,
        "wipes": wipes,
        "deaths_total": deaths_total,
        "pulls": pulls,
        "repair": deaths_total * 57 + pulls * 23,
        "debuffs": debuffs,
        "hero_tiles": tiles if (stats is not None or standing) else [],
        "bar_pct": bar_pct,
        "bar_label": bar_label,
        "columns": columns,
        "icons_on": bool(display_cfg.get("icons", True)),
        "roast": _roast(cfg),
        "stones": stones,
        "debt": debt,
        "week_label": start_dt.strftime("%b %d"),
        "item_title": display_cfg.get("item_art_title", "GUILD ITEM OF THE MONTH"),
        "item_src": item_src,
        "motd": theme_bands.MOTD_QUIPS[week_index % len(theme_bands.MOTD_QUIPS)],
        "watermark": display_cfg.get(
            "watermark_text",
            "Powered by Guild Board · github.com/Bzach10/wow-guild-board")
            if display_cfg.get("watermark") else "",
        "header_embers": _embers(7, 26),
        "footer_embers": _embers(11, 26),
        "footer_flames": _flames_row(),
        "wisps": _embers(9, 16),
        "loop_ms": LOOP_MS,
    }


def render_html(context, template="stone_torchlight.html.j2"):
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
    return env.get_template(template).render(**context)


def generate_board_html(cfg, stats, standing, leaders, zone_name,
                        mplus_results, mplus_season_scores, mplus_season_parses,
                        start_dt, end_dt, no_logs=False, output_path="board.png",
                        animate=False, frames=10, duration_ms=120, **kwargs):
    """Render the board via headless Chromium; PNG, or a looping GIF when
    animate=True. Returns the output path, or None on ANY failure so the
    caller can fall back to the Pillow renderer."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.info("Playwright not installed; using the Pillow renderer.")
        return None
    try:
        context = build_context(
            cfg, stats, standing, leaders, zone_name, mplus_results,
            mplus_season_scores, mplus_season_parses, start_dt, end_dt,
            no_logs=no_logs, **kwargs)
        html = render_html(context)
        html_path = Path(RENDER_HTML)
        html_path.write_text(html, encoding="utf-8")

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": board_image.WIDTH, "height": 1400})
            page.goto(html_path.resolve().as_uri())
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1200)   # webfonts + CDN icons settle

            if not animate:
                page.screenshot(path=output_path, full_page=True)
                browser.close()
                logger.info("Generated HTML board at %s", output_path)
                return output_path

            # Freeze the clock and step through the loop frame by frame.
            page.evaluate("document.getAnimations().forEach(a => a.pause())")
            imgs = []
            for i in range(frames):
                t = i / frames * LOOP_MS
                page.evaluate(f"document.getAnimations().forEach(a => a.currentTime = {t})")
                page.evaluate(f"window.__setPhase && window.__setPhase({i / frames})")
                shot = page.screenshot(full_page=True)
                import io
                imgs.append(Image.open(io.BytesIO(shot)).convert("RGB"))
            browser.close()

        return _encode_gif(imgs, output_path, frames, duration_ms)
    except Exception as exc:
        logger.warning("HTML board render failed (%s); using the Pillow renderer.", exc)
        return None


def _encode_gif(frames_l, output_path, frames, duration_ms):
    """Shared-palette GIF with the static middle copied verbatim from
    frame 0 — same anti-shimmer scheme as the Pillow pipeline."""
    base = frames_l[0]
    header_h = HEADER_H
    footer_h = FOOTER_TOTAL
    for scale in (1.0, 0.8, 0.65, 0.5):
        imgs = frames_l if scale == 1.0 else [
            im.resize((int(im.width * scale), int(im.height * scale)),
                      Image.LANCZOS) for im in frames_l]
        pal = imgs[0].quantize(colors=255, method=Image.MEDIANCUT)
        q = [im.quantize(palette=pal, dither=Image.FLOYDSTEINBERG) for im in imgs]
        mid_top = int(header_h * scale) + 8
        mid_bot = int((base.height - footer_h) * scale) - 8
        if mid_bot > mid_top:
            still = q[0].crop((0, mid_top, imgs[0].width, mid_bot))
            for frame in q[1:]:
                frame.paste(still, (0, mid_top))
        q[0].save(output_path, save_all=True, append_images=q[1:],
                  duration=duration_ms, loop=0, optimize=True, disposal=1)
        size = os.path.getsize(output_path)
        if size <= board_image.GIF_MAX_BYTES:
            logger.info("Generated HTML animated board at %s (%s frames, %.1fMB, scale %.0f%%)",
                        output_path, frames, size / 1e6, scale * 100)
            return output_path
    logger.info("HTML animated board too large even downscaled; falling back.")
    return None

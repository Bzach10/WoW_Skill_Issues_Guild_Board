"""Render the weekly board from HTML templates via headless Chromium.

The design IS the render — and the design is modular: board.html.j2 is
the skeleton (info strip, hero, columns, roast, MOTD), while the header
and footer are swappable modules under templates/headers/ and
templates/footers/, chosen in theme.yml. Colors, backgrounds, fonts and
every gag line come from theme.yml too (guild_board/theme.py owns the
defaults). Playwright screenshots the page; animation frames are
captured by pausing every CSS animation and seeking it to phase*loop.

A portrait phone-readable companion (mobile.html.j2) can be captured in
the same browser session and posted alongside the landscape board.

Fails open: any missing dependency or browser error returns None so the
caller falls back to the battle-tested Pillow renderer.
"""

import io
import logging
import os
import random
import re
from pathlib import Path

from PIL import Image

from guild_board import awards as awards_mod
from guild_board import board_image
from guild_board import integrity
from guild_board import theme as theme_mod
from guild_board.board_image import (
    CLASS_ICONS, DIFFICULTY_NAMES, ICON_CDN, MEDAL_FILLS, SPEC_ICONS,
    _CLASS_KEY_DISPLAY, _build_columns, _build_seasonal, _hero_tiles,
    _plural, _rgb, _spec_class_keys,
)
from guild_board.config import get_class_color

logger = logging.getLogger(__name__)

# The TL;DR lines shown in the Discord post text, derived from the EXACT
# rows the rendered board shows — set by build_context so the text and the
# image can never disagree. main.py reads this after a successful render.
LAST_TLDR = None

LOOP_MS = 1200
TEMPLATE_DIR = Path(__file__).parent / "templates"
RENDER_HTML = "board_render.html"          # written to cwd so relative assets/ paths work
RENDER_MOBILE_HTML = "board_mobile_render.html"

# retained as defaults; the live values come from the theme's module map
WIDTH = 3000
HEADER_H = 300
FOOTER_TOTAL = 430 + 52 + 40

# tombstone geometry (w, h, arched, cross, rotation) — stones are pure art
# now; names/deaths live on high-contrast plates beneath them
STONES = [
    (170, 178, True, False, -2.5, ("#7c7869", "#5c594c", "#403e37")),
    (180, 196, False, True, 1.6, ("#827e6e", "#605d50", "#434139")),
    (158, 162, True, False, -1.2, ("#746f61", "#575447", "#3c3a33")),
    (158, 150, False, False, 2.2, ("#746f61", "#575447", "#3c3a33")),
]


def _css(color):
    if isinstance(color, str):
        return color
    return f"rgb({color[0]},{color[1]},{color[2]})"


_INK_RE = re.compile(r"rgb\((\d+),(\d+),(\d+)\)")


def _ink(css):
    """Darken a screen color into ink for LIGHT parchment posters.
    Class colors are designed for dark backgrounds; on paper they must be
    printed like ink — same hue, deep enough to read. Whitish colors
    (Priest) become dark sepia rather than washed gray."""
    m = _INK_RE.match(css or "")
    if not m:
        return css
    r, g, b = (int(v) for v in m.groups())
    if min(r, g, b) > 195:
        return "rgb(52,44,34)"
    return f"rgb({int(r * 0.52)},{int(g * 0.52)},{int(b * 0.52)})"


def _icon_url(row):
    spec_key, cls_key = _spec_class_keys(row.get("spec"), row.get("cls"))
    if (cls_key, spec_key) in SPEC_ICONS:
        return ICON_CDN.format(SPEC_ICONS[(cls_key, spec_key)])
    if cls_key in CLASS_ICONS:
        return ICON_CDN.format(CLASS_ICONS[cls_key])
    return None


# colors that mean "class unknown": board_image's TEXT default and
# get_class_color's #CCCCCC fallback — both eligible for lookup backfill
UNKNOWN_COLORS = (None, (235, 236, 240), (204, 204, 204))


def _cls_color(cls_key):
    return _rgb(get_class_color(_CLASS_KEY_DISPLAY.get(cls_key, cls_key.title())))


def _class_lookup(stats, leaders, mplus_results, season_scores, season_parses,
                  improvement, mplus_weekly, records):
    """name -> class key, learned from EVERY source on the board. A player
    whose class is only known in one section (e.g. best_dps carries cls,
    All Stars only carries 'Holy') gets colored consistently everywhere."""
    lookup = {}

    def learn(name, cls=None, spec=None):
        key = (name or "").strip().lower()
        if not key or key in lookup:
            return
        _, cls_key = _spec_class_keys(spec, cls)
        if cls_key:
            lookup[key] = cls_key

    for pool in ((stats or {}).get("best_dps") or {}, (stats or {}).get("best_hps") or {},
                 (stats or {}).get("best_tanks") or {}):
        for name, info in pool.items():
            learn(name, info.get("cls"), info.get("spec"))
    for pool in ((mplus_weekly or {}).get("dps") or {}, (mplus_weekly or {}).get("hps") or {},
                 (mplus_weekly or {}).get("tanks") or {}):
        for name, info in pool.items():
            learn(name, info.get("cls"), info.get("spec"))
    for entry in leaders or []:
        learn(entry.get("name"), entry.get("cls"), entry.get("spec"))
    for item in mplus_results or []:
        if len(item) >= 5:
            learn(item[2], None, item[3])
    for score, name, spec in season_scores or []:
        learn(name, None, spec)
    for item in season_parses or []:
        if len(item) >= 4:
            learn(item[2], None, item[3])
    for lst in ((improvement or {}).get("dps") or [], (improvement or {}).get("hps") or []):
        for e in lst:
            learn(e.get("name"), e.get("cls"), e.get("spec"))
    for rec in (records or {}).values():
        if isinstance(rec, dict):
            learn(rec.get("name"), rec.get("cls"), rec.get("spec"))
    return lookup


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


def _html_rows(sections, lookup=None):
    """Convert the Pillow section model into template-ready dicts.
    Rows that came through class-blind (white name, no icon) get both
    filled in from the cross-section class lookup."""
    lookup = lookup or {}
    out = []
    for sec in sections:
        rows = []
        for i, row in enumerate(sec["rows"]):
            if "text" in row:
                rows.append({"text": row["text"]})
                continue
            key = (row.get("name") or "").strip().lower()
            color = row.get("color")
            if color in UNKNOWN_COLORS and key in lookup:
                color = _cls_color(lookup[key])
            if color in UNKNOWN_COLORS:
                color = (235, 236, 240)
            icon = _icon_url(row)
            if icon is None and key in lookup:
                icon = ICON_CDN.format(CLASS_ICONS[lookup[key]])
            color_css = _css(color)
            value_css = _css(row.get("value_color", (235, 236, 240)))
            suffix_css = _css(row["value_suffix_color"]) if row.get("value_suffix_color") else None
            rows.append({
                "rank": i + 1,
                "medal": _css(MEDAL_FILLS[i]) if i < len(MEDAL_FILLS) else None,
                "icon": icon,
                "name": row.get("name", ""),
                "color": color_css,
                "ink": _ink(color_css),
                "detail": row.get("detail", ""),
                "detail_bits": [b for b in (row.get("detail_bits")
                                            or ([row["detail"]] if row.get("detail") else [])) if b],
                "value": row.get("value", ""),
                "value_color": value_css,
                "value_ink": _ink(value_css),
                "value_suffix": row.get("value_suffix"),
                "value_suffix_color": suffix_css,
                "value_suffix_ink": _ink(suffix_css) if suffix_css else None,
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


def _headline(stats, standing, previous, records):
    """The week's single biggest story, as one big line at the top of the
    hero band — record broken > rank climbed > bosses killed > copium."""
    formats = {
        "highest_timed_key": lambda r: (
            f"NEW GUILD RECORD — {r['name'].upper()} TIMED A +{r['level']} {r['dungeon'].upper()}"),
        "best_dps_parse": lambda r: (
            f"NEW GUILD RECORD — {r['name'].upper()} PARSED {r['parse']:.0f}% ON {r['boss'].upper()}"),
        "best_hps_parse": lambda r: (
            f"NEW HEALING RECORD — {r['name'].upper()} PARSED {r['parse']:.0f}% ON {r['boss'].upper()}"),
    }
    for key, fmt in formats.items():
        rec = (records or {}).get(key)
        if rec and rec.get("new") and rec.get("name"):
            try:
                return fmt(rec)
            except (KeyError, TypeError, ValueError):
                continue
    prev_realm = ((previous or {}).get("standing") or {}).get("realm")
    realm = (standing or {}).get("realm")
    if realm and prev_realm and not (standing or {}).get("stale"):
        try:
            up = int(prev_realm) - int(realm)
            if up > 0:
                return f"REALM RANK #{int(realm):,} — UP {up} THIS WEEK"
        except (TypeError, ValueError):
            pass
    kills = (stats or {}).get("kills") or 0
    pulls = (stats or {}).get("pulls") or 0
    if kills:
        return f"{kills} BOSS{'ES' if kills != 1 else ''} DOWN IN {pulls} PULLS — GO AGANE"
    if pulls:
        return f"{pulls} PULLS OF PROGRESS — THE KILL IS COMING"
    return None


def _tldr_from_columns(columns, standing):
    """Phone-readable callouts sourced from the very rows the board shows.
    One computation, three surfaces (image, web, post text) — they can
    never drift apart again."""
    def first_row(title_prefix, role=None):
        for col in columns:
            for sec in col.get("sections", []):
                if not sec["title"].startswith(title_prefix):
                    continue
                for row in sec["rows"]:
                    if "text" in row:
                        continue
                    if role and (row.get("detail_bits") or [""])[0] != role:
                        continue
                    return row
        return None

    lines = []
    for title, icon, label, role in (
            ("TOP DPS PARSES", "\U0001F5E1️", "Top DPS", None),
            ("TOP HEALING PARSES", "\U0001F49A", "Top heals", None),
            ("TOP PARSES", "\U0001F6E1️", "Top tank", "Tank")):
        row = first_row(title, role)
        if row:
            lines.append(f"{icon} {label}: **{row['name']}** {row['value']}")
    if standing and standing.get("realm"):
        suffix = " (last wk)" if standing.get("stale") else ""
        lines.append(f"\U0001F3F0 Realm rank **#{standing['realm']:,}**{suffix}")
    return lines


def _debt_card(theme, week_index):
    """The compounding-debt tooltip, fully theme-driven. Returns None when
    the guild retires the gag (footer.debt.enabled: false)."""
    cfg = (theme.get("footer") or {}).get("debt") or {}
    if not cfg.get("enabled", True):
        return None
    try:
        rate = float(cfg.get("weekly_rate_pct", 9.99)) / 100.0
        principal = float(cfg.get("principal", 137_000))
    except (TypeError, ValueError):
        rate, principal = 0.0999, 137_000.0
    amount = int(principal * ((1.0 + rate) ** week_index))
    lines = []
    for raw in cfg.get("lines") or []:
        left, _, right = str(raw).partition("|")
        lines.append({
            "left": left,
            "right": right or None,
            "green": left.startswith(("Equip:", "Use:")),
        })
    return {
        "title": cfg.get("title", "Gambling Debt"),
        "amount": amount,
        "climbing_note": cfg.get("climbing_note", "and climbing"),
        "interest_note": cfg.get("interest_note", ""),
        "lines": lines,
        "flavor": cfg.get("flavor", ""),
        "requires": cfg.get("requires", ""),
    }


def _build_stones(stats, pulls, lookup):
    """Graveyard tombstones for the week's top-4 deaths, class-tinted."""
    ranked = sorted(((stats or {}).get("deaths") or {}).items(),
                    key=lambda kv: kv[1], reverse=True)[:4]
    if not ranked:
        ranked = [("Nobody", 0)]
    stones = []
    for i, (name, count) in enumerate(ranked):
        w, h, arched, cross, rot, (light, mid, dark) = STONES[i % len(STONES)]
        rate = f" · {count / pulls:.1f}/PULL" if pulls else ""
        cls_key = lookup.get(name.strip().lower())
        carved = name.upper()[:16]
        # engraved name sized to the stone's width; darkened class color
        # keeps the carved look while still reading as the player's class
        carve_size = max(15, min(24, int((w - 38) / (0.62 * max(len(carved), 1)))))
        if cls_key:
            r, g_, b = _cls_color(cls_key)
            carve_color = f"rgb({int(r * 0.55)},{int(g_ * 0.55)},{int(b * 0.55)})"
        else:
            carve_color = "#3a362d"
        stones.append({
            "w": w, "h": h, "arched": arched, "cross": cross, "rot": rot,
            "light": light, "mid": mid, "dark": dark,
            "radius": (f"{w // 2}px {w // 2}px 6px 6px" if arched else "14px 14px 6px 6px"),
            "name": carved,
            "carve_size": carve_size,
            "carve_color": carve_color,
            "color": _css(_cls_color(cls_key)) if cls_key else "#f4f0e4",
            "deaths": f"{count} DEATHS{rate}",
        })
    return stones


def _build_debuffs(theme, deaths_total):
    """Theme-driven fake raid debuffs; a stack of "deaths" shows the real total."""
    debuffs = []
    for d in (theme.get("header") or {}).get("debuffs") or []:
        stack = str(d.get("stack", ""))
        if stack == "deaths":
            stack = str(deaths_total)
        debuffs.append({"url": ICON_CDN.format(d.get("icon", "inv_misc_questionmark")),
                        "kind": d.get("kind", "bad"),
                        "title": d.get("label", ""), "stack": stack})
    return debuffs


def build_context(cfg, stats, standing, leaders, zone_name, mplus_results,
                  mplus_season_scores, mplus_season_parses, start_dt, end_dt,
                  no_logs=False, improvement=None, mplus_weekly=None,
                  previous=None, streaks=None, records=None):
    sections_cfg = cfg.get("sections", {})
    display_cfg = cfg.get("display") or {}
    theme = theme_mod.load_theme(display_cfg.get("theme_file", theme_mod.THEME_FILE))
    modules = theme_mod.resolve_templates(theme)
    width = int((theme.get("board") or {}).get("width") or WIDTH)
    week_index = start_dt.isocalendar()[1]

    raid_secs, mplus_secs = _build_columns(
        cfg, stats, leaders, mplus_results, mplus_season_scores, mplus_season_parses,
        no_logs, mplus_weekly=mplus_weekly, streaks=streaks, zone_name=zone_name)
    seasonal_mp, seasonal_guild = _build_seasonal(
        cfg, mplus_season_scores, mplus_season_parses, improvement,
        previous=previous, records=records, leaders=leaders)

    # Rotating mid-pack spotlights ride in the Seasonal Guild column
    awards_cfg = theme.get("awards") or {}
    if awards_cfg.get("enabled", True):
        seasonal_guild = list(seasonal_guild) + awards_mod.weekly_awards(
            week_index, stats=stats, streaks=streaks,
            season_scores=mplus_season_scores, previous=previous,
            per_week=int(awards_cfg.get("per_week", 2)),
            top_n=int(awards_cfg.get("top_n", 3)))

    lookup = _class_lookup(stats, leaders, mplus_results, mplus_season_scores,
                           mplus_season_parses, improvement, mplus_weekly, records)
    raid_title = (sections_cfg.get("raid_header") or {}).get("title", "Raid").upper()
    mplus_title = (sections_cfg.get("mplus_header") or {}).get("title", "Mythic Plus").upper()
    columns = [
        {"title": raid_title, "sections": _html_rows(raid_secs, lookup), "empty": "No data this week"},
        {"title": mplus_title, "sections": _html_rows(mplus_secs, lookup), "empty": "No data this week"},
        {"title": "SEASONAL MYTHIC PLUS", "sections": _html_rows(seasonal_mp, lookup), "empty": "Season data still cooking"},
        {"title": "SEASONAL GUILD", "sections": _html_rows(seasonal_guild, lookup), "empty": "Season data still cooking"},
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

    stones = _build_stones(stats, pulls, lookup)
    debuffs = _build_debuffs(theme, deaths_total)

    item_src = (theme.get("backgrounds") or {}).get("item") or display_cfg.get("item_art")
    if item_src and not os.path.exists(item_src):
        item_src = None

    debt_card = _debt_card(theme, week_index)
    quips = theme.get("motd_quips") or ["Git Gud."]

    global LAST_TLDR
    LAST_TLDR = _tldr_from_columns(columns, standing)

    # Self-heal before anything renders: clamp impossible values, recompute
    # inconsistent math, flag suspect data — loudly, but never block a post.
    ctx_probe = {"columns": columns, "hero_tiles": tiles, "pulls": pulls, "wipes": wipes}
    integrity.run_all(context=ctx_probe, records=records, standing=standing)
    wipes = ctx_probe["wipes"]

    wipes_sub = str((theme.get("header") or {}).get("wipes_sub", ""))
    try:
        wipes_sub = wipes_sub.format(deaths=deaths_total, pulls=pulls, wipes=wipes)
    except (KeyError, IndexError, ValueError):
        pass

    return {
        "guild_name": guild.get("name", "Guild"),
        "realm_label": f"{realm} · {region}" if realm else region,
        "profile_base": ("https://www.warcraftlogs.com/character/"
                         f"{(guild.get('region') or 'us').lower()}/"
                         f"{(guild.get('realm_slug') or '').lower()}/"),
        "tldr": LAST_TLDR,
        "subtitle": subtitle,
        "date_range": date_range,
        "wipes": wipes,
        "deaths_total": deaths_total,
        "pulls": pulls,
        "repair": deaths_total * 57 + pulls * 23,
        "debuffs": debuffs,
        "hero_tiles": tiles if (stats is not None or standing) else [],
        "headline": _headline(stats, standing, previous, records),
        "bar_pct": bar_pct,
        "bar_label": bar_label,
        "columns": columns,
        "icons_on": bool(display_cfg.get("icons", True)),
        "roast": _roast(cfg),
        "stones": stones,
        "debt": debt_card["amount"] if debt_card else 0,
        "debt_card": debt_card,
        "week_label": start_dt.strftime("%b %d"),
        "item_title": (theme.get("footer") or {}).get("item_title",
                                                      display_cfg.get("item_art_title", "GUILD ITEM OF THE MONTH")),
        "item_src": item_src,
        "motd": quips[week_index % len(quips)],
        "watermark": display_cfg.get(
            "watermark_text",
            "Powered by Guild Board · github.com/Bzach10/wow-guild-board")
            if display_cfg.get("watermark") else "",
        "width": width,
        "theme": theme,
        "font_css_url": theme_mod.font_css_url(theme),
        "bg_rgb": "{},{},{}".format(*theme_mod.hex_to_rgb((theme.get("colors") or {}).get("background"))),
        "hdr_wipes_sub": wipes_sub,
        "header_template": modules["header_template"],
        "footer_template": modules["footer_template"],
        "header_h": modules["header_h"],
        "footer_total": modules["footer_total"],
        "header_embers": _embers(7, 26),
        "footer_embers": _embers(11, 26),
        "footer_flames": _flames_row(),
        "wisps": _embers(9, 16),
        "loop_ms": LOOP_MS,
    }


def render_html(context, template="board.html.j2"):
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(theme_mod.template_loader_paths()),
                      autoescape=True)
    return env.get_template(template).render(**context)


def generate_web_board(cfg, stats, standing, leaders, zone_name,
                       mplus_results, mplus_season_scores, mplus_season_parses,
                       start_dt, end_dt, no_logs=False,
                       output_path="site/index.html", **kwargs):
    """The responsive web twin of the board image (templates/web.html.j2),
    written to site/ for CI to publish to GitHub Pages. Pure HTML render —
    no browser needed. Best-effort: returns the path or None, and never
    raises into the posting flow."""
    try:
        context = build_context(
            cfg, stats, standing, leaders, zone_name, mplus_results,
            mplus_season_scores, mplus_season_parses, start_dt, end_dt,
            no_logs=no_logs, **kwargs)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_html(context, template="web.html.j2"),
                       encoding="utf-8")
        logger.info("Generated web board at %s", out)
        return str(out)
    except Exception as exc:
        logger.warning("Web board render failed (%s); the post proceeds without it.", exc)
        return None


def _capture_mobile(browser, context, mobile_path):
    """Portrait companion PNG in the same browser session. Best-effort:
    a mobile failure never sinks the main board."""
    try:
        html = render_html(context, template="mobile.html.j2")
        html_path = Path(RENDER_MOBILE_HTML)
        html_path.write_text(html, encoding="utf-8")
        page = browser.new_page(viewport={"width": 1080, "height": 1400})
        page.goto(html_path.resolve().as_uri())
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(800)
        page.screenshot(path=mobile_path, full_page=True)
        page.close()
        logger.info("Generated mobile companion at %s", mobile_path)
        return mobile_path
    except Exception as exc:
        logger.warning("Mobile companion render failed (%s); posting desktop board only.", exc)
        return None


def generate_board_html(cfg, stats, standing, leaders, zone_name,
                        mplus_results, mplus_season_scores, mplus_season_parses,
                        start_dt, end_dt, no_logs=False, output_path="board.png",
                        animate=False, frames=10, duration_ms=120,
                        mobile_path=None, **kwargs):
    """Render the board via headless Chromium; PNG, or a looping GIF when
    animate=True. When mobile_path is set, a portrait companion PNG is
    captured too. Returns the main output path, or None on ANY failure so
    the caller can fall back to the Pillow renderer."""
    if mobile_path:
        Path(mobile_path).unlink(missing_ok=True)   # never post a stale one
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
        width = context["width"]

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": width, "height": 1400})
            page.goto(html_path.resolve().as_uri())
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1200)   # webfonts + CDN icons settle
            # drop whole facts (not mid-word ellipses) once fonts are final
            page.evaluate("window.__fitDetails && window.__fitDetails()")

            if not animate:
                page.screenshot(path=output_path, full_page=True)
                if mobile_path:
                    _capture_mobile(browser, context, mobile_path)
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
                imgs.append(Image.open(io.BytesIO(shot)).convert("RGB"))
            if mobile_path:
                _capture_mobile(browser, context, mobile_path)
            browser.close()

        return _encode_gif(imgs, output_path, frames, duration_ms,
                           key_colors=_collect_key_colors(context),
                           header_h=context["header_h"],
                           footer_total=context["footer_total"])
    except Exception as exc:
        logger.warning("HTML board render failed (%s); using the Pillow renderer.", exc)
        return None


def _collect_key_colors(context):
    """Every text color actually on the board (class colors, parse tiers,
    medals) plus the fixed UI accents. These get RESERVED palette slots so
    GIF quantization can never shift them — without this, the fire art's
    thousand browns crowd the palette and orange parses turn pink."""
    import re
    seen = []

    def add(css):
        m = re.match(r"rgb\((\d+),(\d+),(\d+)\)", css or "")
        if m:
            c = tuple(int(v) for v in m.groups())
            if c not in seen:
                seen.append(c)

    for col in context.get("columns", []):
        for sec in col.get("sections", []):
            for row in sec.get("rows", []):
                if "text" in row:
                    continue
                add(row.get("color"))
                add(row.get("value_color"))
                add(row.get("value_suffix_color"))
                add(row.get("medal"))
    for c in [(230, 180, 70), (235, 236, 240), (150, 154, 164), (95, 99, 110),
              (229, 72, 77), (76, 220, 86), (163, 53, 238), (255, 128, 0),
              (30, 255, 0), (255, 209, 0), (229, 204, 128), (56, 144, 255)]:
        if c not in seen:
            seen.append(c)
    return seen[:80]


def _encode_gif(frames_l, output_path, frames, duration_ms, key_colors=None,
                header_h=HEADER_H, footer_total=FOOTER_TOTAL):
    """Shared-palette GIF with the static middle copied verbatim from
    frame 0 — same anti-shimmer scheme as the Pillow pipeline. key_colors
    get reserved palette slots so text colors survive quantization exactly.
    Band heights come from the theme's header/footer modules."""
    base = frames_l[0]
    key_colors = key_colors or []
    for scale in (1.0, 0.8, 0.65, 0.5):
        imgs = frames_l if scale == 1.0 else [
            im.resize((int(im.width * scale), int(im.height * scale)),
                      Image.LANCZOS) for im in frames_l]
        adaptive = imgs[0].quantize(colors=256 - len(key_colors), method=Image.MEDIANCUT)
        palette = adaptive.getpalette()[:3 * (256 - len(key_colors))]
        for c in key_colors:
            palette.extend(c)
        pal = Image.new("P", (1, 1))
        pal.putpalette(palette)
        q = [im.quantize(palette=pal, dither=Image.FLOYDSTEINBERG) for im in imgs]
        mid_top = int(header_h * scale) + 8
        mid_bot = int((base.height - footer_total) * scale) - 8
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

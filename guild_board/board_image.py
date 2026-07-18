"""Render the full weekly guild board as a single PNG.

Discord embeds can't do aligned columns, so the board is drawn with Pillow
instead: real two-column layout (Raid left, Mythic+ right), class-colored
player names, WCL-style parse colors, and a height computed from the content
so nothing ever gets clipped.
"""

import logging

from PIL import Image, ImageDraw, ImageFont

from guild_board.config import get_class_color

logger = logging.getLogger(__name__)

# --- palette -----------------------------------------------------------------
BG = (17, 18, 23)
PANEL = (26, 28, 35)
PANEL_BORDER = (45, 48, 58)
ACCENT = (230, 180, 70)
TEXT = (235, 236, 240)
MUTED = (150, 154, 164)
FAINT = (95, 99, 110)
RED = (229, 72, 77)

# Gold, silver, bronze, then orange/blue mirroring the old 🥇🥈🥉🔶🔷 medals
MEDAL_FILLS = [
    (241, 196, 83),
    (176, 182, 192),
    (205, 127, 68),
    (255, 172, 51),
    (85, 172, 238),
]

DIFFICULTY_NAMES = {1: "LFR", 3: "Normal", 4: "Heroic", 5: "Mythic"}

# --- layout constants ---------------------------------------------------------
WIDTH = 1200
MARGIN = 36
GUTTER = 24
COL_PAD = 22
COL_W = (WIDTH - 2 * MARGIN - GUTTER) // 2
ROW_H = 36
SEC_TITLE_H = 32
SEC_GAP = 16
COL_HEADER_H = 46

_FONT_CANDIDATES = {
    False: [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ],
    True: [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ],
}


def _load_font(size, bold=False):
    for path in _FONT_CANDIDATES[bold]:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _fonts():
    return {
        "title": _load_font(38, bold=True),
        "subtitle": _load_font(19),
        "date": _load_font(17),
        "col_header": _load_font(21, bold=True),
        "sec_title": _load_font(15, bold=True),
        "name": _load_font(17, bold=True),
        "detail": _load_font(15),
        "tile_label": _load_font(13),
        "tile_value": _load_font(28, bold=True),
        "badge": _load_font(13, bold=True),
        "quote": _load_font(20),
    }


def _rgb(hex_color):
    hex_color = (hex_color or "#CCCCCC").lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _fmt_amount(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return f"{n:.0f}"


def _parse_color(p):
    """WCL-style parse tier colors."""
    if p >= 99:
        return (229, 204, 128)   # gold
    if p >= 95:
        return (255, 128, 0)     # legendary orange
    if p >= 75:
        return (163, 53, 238)    # epic purple
    if p >= 50:
        return (56, 144, 255)    # rare blue
    if p >= 25:
        return (76, 220, 86)     # uncommon green
    return (157, 157, 157)       # common gray


def _cap(name):
    return name[:1].upper() + name[1:] if name else name


def _short_boss(boss):
    """'Chimaerus, the Undreamt God' -> 'Chimaerus'."""
    return (boss or "").split(",")[0].strip()


def _fit(draw, text, font, max_w):
    """Ellipsize text to fit max_w pixels."""
    if max_w <= 0:
        return ""
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    text = text.rstrip(" .·#,")
    return (text + "…") if text else ""


def _wrap(draw, text, font, max_w):
    words = (text or "").split()
    lines, cur = [], ""
    for word in words:
        candidate = f"{cur} {word}".strip()
        if not cur or draw.textlength(candidate, font=font) <= max_w:
            cur = candidate
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def _enabled(sections, name, default=True):
    return (sections.get(name) or {}).get("enabled", default)


def _plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


# --- board model ----------------------------------------------------------------
# A section is {"title": str, "rows": [row]}; a row is either
# {"name", "color", "detail", "value", "value_color"} or {"text": str}.

def _parse_rows(best, unit, top_n, diff_name=""):
    ranked = sorted(best.items(), key=lambda kv: kv[1]["parse"], reverse=True)[:top_n]
    rows = []
    for name, info in ranked:
        parse = info.get("parse") or 0
        boss = _short_boss(info.get("boss", ""))
        if boss and diff_name:
            boss = f"{diff_name} {boss}"
        detail_bits = [
            info.get("spec") or "",
            boss,
            f"{_fmt_amount(info.get('amount') or 0)} {unit}",
        ]
        rows.append({
            "name": _cap(name),
            "color": _rgb(get_class_color(info.get("cls") or info.get("spec"))),
            "detail": " · ".join(b for b in detail_bits if b),
            "value": f"{parse:.0f}%",
            "value_color": _parse_color(parse),
        })
    return rows


def _leader_rows(leaders, top_n):
    rows = []
    for entry in leaders[:top_n]:
        # Boss last so it truncates first — the rank matters more than the boss.
        detail_bits = [entry.get("spec") or ""]
        if entry.get("region_rank"):
            detail_bits.append(f"Region #{entry['region_rank']:,}")
        if isinstance(entry.get("best_avg"), (int, float)):
            detail_bits.append(f"{entry['best_avg']:.1f} avg")
        if entry.get("boss"):
            detail_bits.append(_short_boss(entry["boss"]))
        rows.append({
            "name": _cap(entry["name"]),
            "color": _rgb(get_class_color(entry.get("spec"))),
            "detail": " · ".join(b for b in detail_bits if b),
            "value": f"Realm #{entry['realm_rank']:,}",
            "value_color": ACCENT if entry["realm_rank"] <= 3 else TEXT,
        })
    return rows


def _death_rows(deaths, top_n, class_lookup):
    ranked = sorted(deaths.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    rows = []
    for name, count in ranked:
        cls = class_lookup.get(name.lower())
        rows.append({
            "name": _cap(name),
            "color": _rgb(get_class_color(cls)) if cls else TEXT,
            "detail": "",
            "value": _plural(count, "death"),
            "value_color": RED,
        })
    return rows


def _mplus_week_rows(results, top_n):
    rows = []
    for item in results[:top_n]:
        if len(item) == 4:
            level, dungeon, name, timed = item
            spec = ""
        else:
            level, dungeon, name, spec, timed = item
        detail_bits = [spec, dungeon, "timed" if timed else "over time"]
        rows.append({
            "name": _cap(name),
            "color": _rgb(get_class_color(spec)),
            "detail": " · ".join(b for b in detail_bits if b),
            "value": f"+{level}",
            "value_color": ACCENT,
        })
    return rows


def _season_score_rows(scores, top_n):
    rows = []
    for score, name, spec in scores[:top_n]:
        rows.append({
            "name": _cap(name),
            "color": _rgb(get_class_color(spec)),
            "detail": spec or "",
            "value": f"{score:.0f}",
            "value_color": ACCENT,
        })
    return rows


def _season_run_rows(parses, top_n):
    rows = []
    for item in parses[:top_n]:
        if len(item) == 5:
            value, dungeon, name, spec, is_wcl = item
        else:
            value, dungeon, name, spec = item
            is_wcl = False
        rows.append({
            "name": _cap(name),
            "color": _rgb(get_class_color(spec)),
            "detail": " · ".join(b for b in [spec, dungeon] if b),
            "value": f"{value:.0f}%" if is_wcl else f"{value:.0f}",
            "value_color": _parse_color(value) if is_wcl else TEXT,
        })
    return rows


def _improve_rows(entries):
    """Rows for the Most Improved panels: early → late parse, with throughput."""
    rows = []
    for e in entries:
        detail_bits = [
            e.get("spec") or "",
            f"{e['early_parse']:.0f}% → {e['late_parse']:.0f}%",
            f"{_fmt_amount(e.get('early_amount') or 0)} → {_fmt_amount(e.get('late_amount') or 0)}",
        ]
        rows.append({
            "name": _cap(e["name"]),
            "color": _rgb(get_class_color(e.get("cls") or e.get("spec"))),
            "detail": " · ".join(b for b in detail_bits if b),
            "value": f"+{e['delta']:.0f}%",
            "value_color": (76, 220, 86),
        })
    return rows


def _build_columns(cfg, stats, leaders, mplus_results, season_scores, season_parses, no_logs):
    sections_cfg = cfg.get("sections", {})
    top_n = int(cfg.get("top_n", 5))

    class_lookup = {}
    if stats:
        for pool in (stats.get("best_dps") or {}, stats.get("best_hps") or {}):
            for name, info in pool.items():
                if info.get("cls"):
                    class_lookup[name.lower()] = info["cls"]

    raid = []
    if no_logs and _enabled(sections_cfg, "no_logs_notice"):
        message = (sections_cfg.get("no_logs_notice") or {}).get(
            "message", "No raid logs found for the last {lookback_days} days.")
        raid.append({
            "title": "NO LOGS THIS WEEK",
            "rows": [{"text": message.format(lookback_days=cfg.get("lookback_days", 7))}],
        })
    if stats:
        # Label bosses with the difficulty the data actually came from
        # (the fallback may have downgraded mythic -> heroic -> normal).
        diff_name = DIFFICULTY_NAMES.get(stats.get("difficulty"), "")
        if _enabled(sections_cfg, "top_dps") and stats.get("best_dps"):
            raid.append({"title": "TOP DPS PARSES", "rows": _parse_rows(stats["best_dps"], "DPS", top_n, diff_name)})
        if _enabled(sections_cfg, "top_healing") and stats.get("best_hps"):
            raid.append({"title": "TOP HEALING PARSES", "rows": _parse_rows(stats["best_hps"], "HPS", top_n, diff_name)})
    if leaders and _enabled(sections_cfg, "realm_rank_leaders"):
        raid.append({"title": "WEEKLY BOSS RANKS", "rows": _leader_rows(leaders, top_n)})
    if stats and _enabled(sections_cfg, "most_deaths") and stats.get("deaths"):
        raid.append({"title": "GRAVEYARD CAMPERS", "rows": _death_rows(stats["deaths"], top_n, class_lookup)})

    mplus = []
    if mplus_results and _enabled(sections_cfg, "mplus"):
        mplus.append({"title": "THIS WEEK'S KEYS", "rows": _mplus_week_rows(mplus_results, top_n)})
    if season_scores and _enabled(sections_cfg, "mplus_season_scores"):
        mplus.append({"title": "SEASON M+ SCORES", "rows": _season_score_rows(season_scores, top_n)})
    if season_parses and _enabled(sections_cfg, "mplus_season_parses", _enabled(sections_cfg, "mplus_season_runs")):
        mplus.append({"title": "BEST SEASON RUNS", "rows": _season_run_rows(season_parses, top_n)})

    return raid, mplus


# --- rendering --------------------------------------------------------------------

def _section_height(section):
    return SEC_TITLE_H + len(section["rows"]) * ROW_H


def _column_height(sections):
    if not sections:
        return COL_HEADER_H + ROW_H + 2 * COL_PAD
    body = sum(_section_height(s) for s in sections) + SEC_GAP * (len(sections) - 1)
    return COL_HEADER_H + body + 2 * COL_PAD


def _draw_rank_badge(draw, x, cy, index, font):
    r = 11
    if index < len(MEDAL_FILLS):
        draw.ellipse([x, cy - r, x + 2 * r, cy + r], fill=MEDAL_FILLS[index])
        num_color = (20, 20, 24)
    else:
        draw.ellipse([x, cy - r, x + 2 * r, cy + r], outline=FAINT, width=1)
        num_color = MUTED
    num = str(index + 1)
    w = draw.textlength(num, font=font)
    draw.text((x + r - w / 2, cy - 8), num, font=font, fill=num_color)


def _draw_row(draw, x, y, w, index, row, fonts):
    cy = y + ROW_H // 2

    if "text" in row:
        text = _fit(draw, row["text"], fonts["detail"], w)
        draw.text((x, cy - 9), text, font=fonts["detail"], fill=MUTED)
        return

    _draw_rank_badge(draw, x, cy, index, fonts["badge"])

    value = row.get("value", "")
    vw = draw.textlength(value, font=fonts["name"])
    draw.text((x + w - vw, cy - 10), value, font=fonts["name"], fill=row.get("value_color", TEXT))

    nx = x + 32
    name = _fit(draw, row.get("name", ""), fonts["name"], w - 32 - vw - 16)
    draw.text((nx, cy - 10), name, font=fonts["name"], fill=row.get("color", TEXT))

    detail = row.get("detail")
    if detail:
        dx = nx + draw.textlength(name, font=fonts["name"]) + 10
        max_dw = x + w - vw - 16 - dx
        if max_dw > 40:
            detail = _fit(draw, detail, fonts["detail"], max_dw)
            draw.text((dx, cy - 9), detail, font=fonts["detail"], fill=MUTED)


def _draw_column(draw, x0, y0, height, title, sections, fonts, empty_text="No data this week"):
    draw.rounded_rectangle([x0, y0, x0 + COL_W, y0 + height], radius=12,
                           fill=PANEL, outline=PANEL_BORDER, width=1)
    x = x0 + COL_PAD
    w = COL_W - 2 * COL_PAD
    y = y0 + COL_PAD

    draw.rectangle([x, y + 2, x + 4, y + 24], fill=ACCENT)
    draw.text((x + 14, y), title, font=fonts["col_header"], fill=TEXT)
    y += COL_HEADER_H

    if not sections:
        draw.text((x, y + 8), empty_text, font=fonts["detail"], fill=FAINT)
        return

    for si, section in enumerate(sections):
        if si:
            y += SEC_GAP
        draw.text((x, y), section["title"], font=fonts["sec_title"], fill=ACCENT)
        title_w = draw.textlength(section["title"], font=fonts["sec_title"])
        draw.line([x + title_w + 12, y + 9, x + w, y + 9], fill=PANEL_BORDER, width=1)
        y += SEC_TITLE_H
        for i, row in enumerate(section["rows"]):
            _draw_row(draw, x, y, w, i, row, fonts)
            y += ROW_H


def _hero_tiles(stats, standing):
    tiles = []
    if stats:
        tiles.append(("KILLS", str(stats.get("kills", 0))))
        tiles.append(("PULLS", str(stats.get("pulls", 0))))
        tiles.append(("DEATHS", str(sum((stats.get("deaths") or {}).values()))))
    if standing:
        if standing.get("realm"):
            tiles.append(("REALM RANK", f"#{standing['realm']:,}"))
        if standing.get("region"):
            tiles.append(("REGION RANK", f"#{standing['region']:,}"))
        if standing.get("world"):
            tiles.append(("WORLD RANK", f"#{standing['world']:,}"))
    return tiles[:6]


def _draw_hero(draw, y0, height, stats, standing, fonts):
    x0, x1 = MARGIN, WIDTH - MARGIN
    draw.rounded_rectangle([x0, y0, x1, y0 + height], radius=12,
                           fill=PANEL, outline=PANEL_BORDER, width=1)
    pad = 22
    tiles = _hero_tiles(stats, standing)
    if tiles:
        tile_w = (x1 - x0 - 2 * pad) // len(tiles)
        for i, (label, value) in enumerate(tiles):
            tx = x0 + pad + i * tile_w
            draw.text((tx, y0 + 16), label, font=fonts["tile_label"], fill=MUTED)
            draw.text((tx, y0 + 34), value, font=fonts["tile_value"], fill=TEXT)

    # kill progress bar
    kills = stats.get("kills", 0) if stats else 0
    pulls = stats.get("pulls", 0) if stats else 0
    bar_x, bar_y = x0 + pad, y0 + 82
    bar_w, bar_h = (x1 - x0) - 2 * pad, 18
    draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h],
                           radius=9, fill=(38, 40, 48))
    if pulls > 0:
        fill_w = max(int(bar_w * kills / pulls), bar_h if kills else 0)
        if kills:
            draw.rounded_rectangle([bar_x, bar_y, bar_x + fill_w, bar_y + bar_h],
                                   radius=9, fill=ACCENT)
        label = f"{_plural(kills, 'kill')} in {_plural(pulls, 'pull')} ({kills / pulls * 100:.0f}%)"
    else:
        label = "No pulls this week"
    tw = draw.textlength(label, font=fonts["tile_label"])
    draw.text((bar_x + (bar_w - tw) / 2, bar_y + 2), label,
              font=fonts["tile_label"], fill=TEXT)


def _roast_lines(cfg, draw, fonts, max_w):
    sections_cfg = cfg.get("sections", {})
    roast_cfg = sections_cfg.get("roast_of_the_week") or cfg.get("roast_of_the_week") or {}
    if not roast_cfg.get("enabled", True):
        return None, None
    if roast_cfg.get("roast"):
        quote = f"“{roast_cfg['roast']}”"
        winner = roast_cfg.get("winner", "Anonymous")
        target = roast_cfg.get("target", "")
        attribution = f"— {winner}" + (f", aimed at {target}" if target else "")
    else:
        quote = "No roast submitted. Healers live to see another week."
        attribution = ""
    return _wrap(draw, quote, fonts["quote"], max_w), attribution


def generate_board_image(cfg, stats, standing, leaders, zone_name,
                         mplus_results, mplus_season_scores, mplus_season_parses,
                         start_dt, end_dt, no_logs=False, output_path="board.png",
                         improvement=None):
    """Render the full weekly board and save it as a PNG."""
    fonts = _fonts()
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    raid_sections, mplus_sections = _build_columns(
        cfg, stats, leaders, mplus_results, mplus_season_scores, mplus_season_parses, no_logs)

    sections_cfg = cfg.get("sections", {})
    raid_title = (sections_cfg.get("raid_header") or {}).get("title", "Raid").upper()
    mplus_title = (sections_cfg.get("mplus_header") or {}).get("title", "Mythic Plus").upper()

    # Most Improved: two panels at the bottom (DPS left, healers right)
    imp = improvement or {}
    imp_dps = [{"title": "SEASON PARSE GAIN", "rows": _improve_rows(imp["dps"])}] if imp.get("dps") else []
    imp_heal = [{"title": "SEASON PARSE GAIN", "rows": _improve_rows(imp["hps"])}] if imp.get("hps") else []
    show_improvement = bool(imp_dps or imp_heal)

    header_h = 96
    show_hero = stats is not None or bool(standing)
    hero_h = 120 if show_hero else 0
    col_h = max(_column_height(raid_sections), _column_height(mplus_sections))
    imp_h = max(_column_height(imp_dps), _column_height(imp_heal)) if show_improvement else 0

    quote_max_w = WIDTH - 2 * MARGIN - 2 * COL_PAD
    roast_lines, roast_attr = _roast_lines(cfg, measure, fonts, quote_max_w)
    roast_h = (20 + 24 + len(roast_lines) * 28 + 26) if roast_lines else 0

    height = MARGIN + header_h
    if show_hero:
        height += hero_h + GUTTER
    height += col_h
    if show_improvement:
        height += GUTTER + imp_h
    if roast_lines:
        height += GUTTER + roast_h
    height += MARGIN

    img = Image.new("RGB", (WIDTH, height), BG)
    draw = ImageDraw.Draw(img)

    # header
    y = MARGIN
    guild_name = cfg["guild"]["name"]
    draw.text((MARGIN, y), guild_name, font=fonts["title"], fill=ACCENT)

    lookback = int(cfg.get("lookback_days", 7))
    range_label = "Raid week" if lookback == 7 else f"Last {lookback} days"
    date_range = f"{range_label}: {start_dt.strftime('%b %d')} – {end_dt.strftime('%b %d, %Y')}"
    dw = draw.textlength(date_range, font=fonts["date"])
    draw.text((WIDTH - MARGIN - dw, y + 18), date_range, font=fonts["date"], fill=MUTED)

    difficulty = str(cfg.get("raid", {}).get("difficulty", "mythic"))
    if stats and stats.get("difficulty") in DIFFICULTY_NAMES:
        difficulty = DIFFICULTY_NAMES[stats["difficulty"]]
    difficulty = difficulty.upper()
    subtitle = f"{difficulty} · {zone_name}" if zone_name else f"{difficulty} WEEKLY BOARD"
    draw.text((MARGIN, y + 52), subtitle, font=fonts["subtitle"], fill=MUTED)
    draw.line([MARGIN, y + 86, WIDTH - MARGIN, y + 86], fill=PANEL_BORDER, width=1)
    y += header_h

    if show_hero:
        _draw_hero(draw, y, hero_h, stats, standing, fonts)
        y += hero_h + GUTTER

    _draw_column(draw, MARGIN, y, col_h, raid_title, raid_sections, fonts)
    _draw_column(draw, MARGIN + COL_W + GUTTER, y, col_h, mplus_title, mplus_sections, fonts)
    y += col_h

    if show_improvement:
        y += GUTTER
        _draw_column(draw, MARGIN, y, imp_h, "MOST IMPROVED DPS", imp_dps, fonts,
                     empty_text="Not enough season data yet")
        _draw_column(draw, MARGIN + COL_W + GUTTER, y, imp_h, "MOST IMPROVED HEALERS", imp_heal, fonts,
                     empty_text="Not enough season data yet")
        y += imp_h

    if roast_lines:
        y += GUTTER
        x0, x1 = MARGIN, WIDTH - MARGIN
        draw.rounded_rectangle([x0, y, x1, y + roast_h], radius=12,
                               fill=PANEL, outline=PANEL_BORDER, width=1)
        ty = y + 20
        draw.text((x0 + COL_PAD, ty), "ROAST OF THE WEEK", font=fonts["sec_title"], fill=ACCENT)
        ty += 24
        for line in roast_lines:
            draw.text((x0 + COL_PAD, ty), line, font=fonts["quote"], fill=TEXT)
            ty += 28
        if roast_attr:
            aw = draw.textlength(roast_attr, font=fonts["detail"])
            draw.text((x1 - COL_PAD - aw, ty - 2), roast_attr, font=fonts["detail"], fill=MUTED)

    img.save(output_path, "PNG")
    logger.info("Generated board image at %s (%sx%s)", output_path, WIDTH, height)
    return output_path

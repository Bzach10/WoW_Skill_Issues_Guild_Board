"""Render the full weekly guild board as a single PNG.

Discord embeds can't do aligned columns, so the board is drawn with Pillow
instead: real two-column layout (Raid left, Mythic+ right), class-colored
player names, WCL-style parse colors, and a height computed from the content
so nothing ever gets clipped.
"""

import logging
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from guild_board.config import get_class_color

logger = logging.getLogger(__name__)

# --- class/spec icons --------------------------------------------------------
ICON_CDN = "https://wow.zamimg.com/images/wow/icons/large/{}.jpg"
ICON_SIZE = 22
ICON_CACHE_DIR = ".icon_cache"
_ICON_CACHE = {}

CLASS_ICONS = {
    "warrior": "classicon_warrior",
    "paladin": "classicon_paladin",
    "hunter": "classicon_hunter",
    "rogue": "classicon_rogue",
    "priest": "classicon_priest",
    "deathknight": "classicon_deathknight",
    "shaman": "classicon_shaman",
    "mage": "classicon_mage",
    "warlock": "classicon_warlock",
    "monk": "classicon_monk",
    "druid": "classicon_druid",
    "demonhunter": "classicon_demonhunter",
    "evoker": "classicon_evoker",
}

CLASS_KEY_ALIASES = {"dk": "deathknight", "dh": "demonhunter"}

# Specs whose name uniquely identifies the class — lets rows that only
# know the spec (e.g. WCL All Stars) still resolve an icon and color.
# Ambiguous specs (frost, holy, protection, restoration) are excluded.
SPEC_TO_CLASS = {
    "arms": "warrior", "fury": "warrior",
    "retribution": "paladin",
    "beastmastery": "hunter", "marksmanship": "hunter", "survival": "hunter",
    "assassination": "rogue", "outlaw": "rogue", "subtlety": "rogue",
    "discipline": "priest", "shadow": "priest",
    "blood": "deathknight", "unholy": "deathknight",
    "elemental": "shaman", "enhancement": "shaman",
    "arcane": "mage", "fire": "mage",
    "affliction": "warlock", "demonology": "warlock", "destruction": "warlock",
    "brewmaster": "monk", "mistweaver": "monk", "windwalker": "monk",
    "balance": "druid", "feral": "druid", "guardian": "druid",
    "havoc": "demonhunter", "vengeance": "demonhunter",
    "devastation": "evoker", "preservation": "evoker", "augmentation": "evoker",
}

SPEC_ICONS = {
    ("warrior", "arms"): "ability_warrior_savageblow",
    ("warrior", "fury"): "ability_warrior_innerrage",
    ("warrior", "protection"): "ability_warrior_defensivestance",
    ("paladin", "holy"): "spell_holy_holybolt",
    ("paladin", "protection"): "ability_paladin_shieldofthetemplar",
    ("paladin", "retribution"): "spell_holy_auraoflight",
    ("hunter", "beastmastery"): "ability_hunter_bestialdiscipline",
    ("hunter", "marksmanship"): "ability_hunter_focusedaim",
    ("hunter", "survival"): "ability_hunter_camouflage",
    ("rogue", "assassination"): "ability_rogue_deadlybrew",
    ("rogue", "outlaw"): "ability_rogue_waylay",
    ("rogue", "subtlety"): "ability_stealth",
    ("priest", "discipline"): "spell_holy_powerwordshield",
    ("priest", "holy"): "spell_holy_guardianspirit",
    ("priest", "shadow"): "spell_shadow_shadowwordpain",
    ("deathknight", "blood"): "spell_deathknight_bloodpresence",
    ("deathknight", "frost"): "spell_deathknight_frostpresence",
    ("deathknight", "unholy"): "spell_deathknight_unholypresence",
    ("shaman", "elemental"): "spell_nature_lightning",
    ("shaman", "enhancement"): "spell_shaman_improvedstormstrike",
    ("shaman", "restoration"): "spell_nature_magicimmunity",
    ("mage", "arcane"): "spell_holy_magicalsentry",
    ("mage", "fire"): "spell_fire_firebolt02",
    ("mage", "frost"): "spell_frost_frostbolt02",
    ("warlock", "affliction"): "spell_shadow_deathcoil",
    ("warlock", "demonology"): "spell_shadow_metamorphosis",
    ("warlock", "destruction"): "spell_shadow_rainoffire",
    ("monk", "brewmaster"): "spell_monk_brewmaster_spec",
    ("monk", "mistweaver"): "spell_monk_mistweaver_spec",
    ("monk", "windwalker"): "spell_monk_windwalker_spec",
    ("druid", "balance"): "spell_nature_starfall",
    ("druid", "feral"): "ability_druid_catform",
    ("druid", "guardian"): "ability_racial_bearform",
    ("druid", "restoration"): "spell_nature_healingtouch",
    ("demonhunter", "havoc"): "ability_demonhunter_specdps",
    ("demonhunter", "vengeance"): "ability_demonhunter_spectank",
    ("evoker", "devastation"): "classicon_evoker_devastation",
    ("evoker", "preservation"): "classicon_evoker_preservation",
    ("evoker", "augmentation"): "classicon_evoker_augmentation",
}

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

DIFFICULTY_NAMES = {1: "LFR", 3: "Normal", 4: "Heroic", 5: "Mythic", 10: "M+"}

# --- layout constants ---------------------------------------------------------
WIDTH = 1500
MARGIN = 36
GUTTER = 24
COL_PAD = 22
COL_W = (WIDTH - 2 * MARGIN - GUTTER) // 2
ROW_H = 36
HEADER_ART_H = 340   # theme art banner across the top (guild sign area)
ART_INFO_H = 48      # slim info strip under the header banner
FOOTER_ART_H = 380   # theme art banner across the bottom
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


def _load_theme_art(cfg):
    """Optional artwork that frames the board (display.theme_art path).
    Fails open: missing or unreadable art just renders the plain board."""
    path = (cfg.get("display") or {}).get("theme_art") or ""
    if not path:
        return None
    try:
        return Image.open(path).convert("RGB")
    except Exception as exc:
        logger.info("Theme art %s not usable (%s); rendering without it.", path, exc)
        return None


def _paste_banner(img, art, y, h, anchor):
    """Full-width slice of the art: top-anchored for the header (the guild
    sign), bottom-anchored for the footer (the scene), with a dark tint
    for cohesion and an edge fade into the page background."""
    ratio = WIDTH / art.width
    scaled = art.resize((WIDTH, max(int(art.height * ratio), h)), Image.LANCZOS)
    if anchor == "top":
        band = scaled.crop((0, 0, WIDTH, h))
    else:
        band = scaled.crop((0, scaled.height - h, WIDTH, scaled.height))
    img.paste(band, (0, y))

    img.paste(Image.new("RGB", (WIDTH, h), BG), (0, y), Image.new("L", (WIDTH, h), 70))

    fade_h = min(90, h)
    ramp = Image.new("L", (1, fade_h))
    for i in range(fade_h):
        alpha = int(255 * (i / max(fade_h - 1, 1)))
        ramp.putpixel((0, i), alpha if anchor == "top" else 255 - alpha)
    ramp = ramp.resize((WIDTH, fade_h))
    solid = Image.new("RGB", (WIDTH, fade_h), BG)
    if anchor == "top":
        img.paste(solid, (0, y + h - fade_h), ramp)
    else:
        img.paste(solid, (0, y), ramp)


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
        # Hard-break single words wider than the panel (URLs, keyboard mash)
        while draw.textlength(word, font=font) > max_w and len(word) > 1:
            head = word
            while head and draw.textlength(head, font=font) > max_w:
                head = head[:-1]
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(head)
            word = word[len(head):]
        candidate = f"{cur} {word}".strip()
        if not cur or draw.textlength(candidate, font=font) <= max_w:
            cur = candidate
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def _fit_bits(draw, bits, font, max_w):
    """Fit ' · '-joined facts into max_w by dropping trailing facts whole,
    so rows show complete information instead of mid-number ellipses."""
    bits = [b for b in bits if b]
    while bits:
        text = " · ".join(bits)
        if draw.textlength(text, font=font) <= max_w:
            return text
        if len(bits) == 1:
            return _fit(draw, text, font, max_w)
        bits = bits[:-1]
    return ""


def _norm_key(text):
    return "".join(ch for ch in (text or "").lower() if ch.isalpha())


def _spec_class_keys(spec, cls):
    """Split spec strings like "Brewmaster Monk" or "Unholy DK" into
    normalized (spec_key, class_key) for icon lookup."""
    tokens = [t for t in (spec or "").replace("-", " ").split() if t]
    cls_key = CLASS_KEY_ALIASES.get(_norm_key(cls), _norm_key(cls)) if cls else ""
    spec_tokens = tokens
    if not cls_key and tokens:
        for take in (2, 1):
            if len(tokens) >= take:
                cand = _norm_key("".join(tokens[-take:]))
                cand = CLASS_KEY_ALIASES.get(cand, cand)
                if cand in CLASS_ICONS:
                    cls_key = cand
                    spec_tokens = tokens[:-take]
                    break
    spec_key = _norm_key("".join(spec_tokens))
    if not cls_key and spec_key in SPEC_TO_CLASS:
        cls_key = SPEC_TO_CLASS[spec_key]
    return spec_key, cls_key


_CLASS_KEY_DISPLAY = {"deathknight": "Death Knight", "demonhunter": "Demon Hunter"}


def _class_color_for(spec, cls):
    """Class color via the same spec/class inference the icons use, so
    spec-only rows (e.g. WCL All Stars 'Unholy') still get colored names."""
    _, cls_key = _spec_class_keys(spec, cls)
    if cls_key:
        display = _CLASS_KEY_DISPLAY.get(cls_key, cls_key.title())
        return _rgb(get_class_color(display))
    return _rgb(get_class_color(cls or spec))


def _fetch_icon(name):
    """Download (and disk-cache) an icon; return (image, mask) or None."""
    if name in _ICON_CACHE:
        return _ICON_CACHE[name]
    icon = None
    try:
        cache_dir = Path(ICON_CACHE_DIR)
        cache_dir.mkdir(exist_ok=True)
        path = cache_dir / f"{name}.jpg"
        if not path.exists():
            resp = requests.get(ICON_CDN.format(name), timeout=10)
            if resp.status_code == 200 and resp.content:
                path.write_bytes(resp.content)
        if path.exists():
            img = Image.open(path).convert("RGB").resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
            mask = Image.new("L", (ICON_SIZE, ICON_SIZE), 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                [0, 0, ICON_SIZE - 1, ICON_SIZE - 1], radius=5, fill=255)
            icon = (img, mask)
    except Exception as exc:
        logger.debug("Icon %s unavailable: %s", name, exc)
    _ICON_CACHE[name] = icon
    return icon


def _row_icon(row):
    """Spec icon first, class icon as fallback, None if neither resolves."""
    spec_key, cls_key = _spec_class_keys(row.get("spec"), row.get("cls"))
    candidates = []
    if (cls_key, spec_key) in SPEC_ICONS:
        candidates.append(SPEC_ICONS[(cls_key, spec_key)])
    if cls_key in CLASS_ICONS:
        candidates.append(CLASS_ICONS[cls_key])
    for name in candidates:
        icon = _fetch_icon(name)
        if icon:
            return icon
    return None


def _enabled(sections, name, default=True):
    return (sections.get(name) or {}).get("enabled", default)


def _plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


# --- board model ----------------------------------------------------------------
# A section is {"title": str, "rows": [row]}; a row is either
# {"name", "color", "detail", "value", "value_color"} or {"text": str}.

def _streak_bit(streaks, name):
    """"3w streak" tag for players active multiple weeks running."""
    count = (streaks or {}).get((name or "").strip().lower(), 0)
    return f"{count}w streak" if count >= 2 else ""


def _parse_rows(best, unit, top_n, diff_name="", streaks=None):
    ranked = sorted(best.items(), key=lambda kv: kv[1]["parse"], reverse=True)[:top_n]
    rows = []
    for name, info in ranked:
        parse = info.get("parse") or 0
        boss = _short_boss(info.get("boss", ""))
        # Per-row difficulty wins: a fallback row stays labeled "Heroic ..."
        # even in an otherwise-mythic week. M+ rows show the key level.
        row_diff = DIFFICULTY_NAMES.get(info.get("difficulty"), diff_name)
        if boss and info.get("key_level"):
            boss = f"+{info['key_level']} {boss}"
        elif boss and row_diff:
            boss = f"{row_diff} {boss}"
        detail_bits = [
            info.get("spec") or "",
            boss,
            _streak_bit(streaks, name),
        ]
        rows.append({
            "name": _cap(name),
            "color": _rgb(get_class_color(info.get("cls") or info.get("spec"))),
            "spec": info.get("spec") or "",
            "cls": info.get("cls") or "",
            "detail": " · ".join(b for b in detail_bits if b),
            "detail_bits": detail_bits,
            "value": f"{parse:.0f}%",
            "value_color": _parse_color(parse),
            # The raw throughput sits beside the parse in the value column,
            # where nothing ever gets trimmed away.
            "value_suffix": _fmt_amount(info.get("amount") or 0),
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
            "color": _class_color_for(entry.get("spec"), entry.get("cls")),
            "spec": entry.get("spec") or "",
            "cls": entry.get("cls") or "",
            "detail": " · ".join(b for b in detail_bits if b),
            "detail_bits": detail_bits,
            "value": f"Realm #{entry['realm_rank']:,}",
            "value_color": ACCENT if entry["realm_rank"] <= 3 else TEXT,
        })
    return rows


def _death_rows(deaths, top_n, class_lookup, pulls=0):
    ranked = sorted(deaths.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    rows = []
    for name, count in ranked:
        cls = class_lookup.get(name.lower())
        # Rate first (fair: dying a lot across many pulls is commitment),
        # raw total in grey beside it.
        row = {
            "name": _cap(name),
            "color": _rgb(get_class_color(cls)) if cls else TEXT,
            "cls": cls or "",
            "detail": "",
            "value": f"{count / pulls:.1f}/pull" if pulls else _plural(count, "death"),
            "value_color": RED,
        }
        if pulls:
            row["value_suffix"] = f"{count} total"
        rows.append(row)
    return rows


def _mplus_week_rows(results, top_n, streaks=None):
    # Only timed keys make the board (belt-and-braces: the collector
    # already filters, but manual roster data may not).
    timed_only = [item for item in results if item[-1]]
    rows = []
    for item in timed_only[:top_n]:
        if len(item) == 4:
            level, dungeon, name, _ = item
            spec = ""
        else:
            level, dungeon, name, spec, _ = item
        detail_bits = [spec, dungeon, _streak_bit(streaks, name)]
        rows.append({
            "name": _cap(name),
            "color": _rgb(get_class_color(spec)),
            "spec": spec or "",
            "detail": " · ".join(b for b in detail_bits if b),
            "detail_bits": detail_bits,
            "value": f"+{level}",
            "value_color": ACCENT,
        })
    return rows


def _season_score_rows(scores, top_n, prev_scores=None):
    prev_scores = prev_scores or {}
    rows = []
    for score, name, spec in scores[:top_n]:
        row = {
            "name": _cap(name),
            "color": _rgb(get_class_color(spec)),
            "spec": spec or "",
            "detail": spec or "",
            "value": f"{score:.0f}",
            "value_color": ACCENT,
        }
        prev = prev_scores.get(name.strip().lower())
        if prev_scores:
            if prev is None:
                row["value_suffix"] = "NEW"
                row["value_suffix_color"] = ACCENT
            elif score - prev >= 1:
                row["value_suffix"] = f"\u25b2{score - prev:.0f}"
                row["value_suffix_color"] = (76, 220, 86)
        rows.append(row)
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
            "spec": spec or "",
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
            DIFFICULTY_NAMES.get(e.get("difficulty"), ""),
            f"{e['early_parse']:.0f}% → {e['late_parse']:.0f}%",
            f"{_fmt_amount(e.get('early_amount') or 0)} → {_fmt_amount(e.get('late_amount') or 0)}",
        ]
        rows.append({
            "name": _cap(e["name"]),
            "color": _rgb(get_class_color(e.get("cls") or e.get("spec"))),
            "spec": e.get("spec") or "",
            "cls": e.get("cls") or "",
            "detail": " · ".join(b for b in detail_bits if b),
            "detail_bits": detail_bits,
            "value": f"+{e['delta']:.0f}%",
            "value_color": (76, 220, 86),
        })
    return rows


def _sec(title, rows, empty_text="No data pulled this week"):
    """A section that keeps its title visible even when empty."""
    return {"title": title, "rows": rows if rows else [{"text": empty_text}]}


def _record_rows(records):
    """The season record book: holder, what they hold, and NEW when broken."""
    rows = []
    key_rec = (records or {}).get("highest_timed_key")
    if key_rec:
        row = {
            "name": _cap(key_rec.get("name", "")),
            "color": _rgb(get_class_color(key_rec.get("spec"))),
            "spec": key_rec.get("spec") or "",
            "detail": " \u00b7 ".join(b for b in ["Highest timed key", key_rec.get("dungeon", "")] if b),
            "value": f"+{key_rec.get('level', 0)}",
            "value_color": ACCENT,
        }
        if key_rec.get("new"):
            row["value_suffix"] = "NEW"
            row["value_suffix_color"] = ACCENT
        rows.append(row)
    for state_key, label in (("best_dps_parse", "Best DPS parse"), ("best_hps_parse", "Best HPS parse")):
        rec = (records or {}).get(state_key)
        if not rec:
            continue
        diff = DIFFICULTY_NAMES.get(rec.get("difficulty"), "")
        boss = _short_boss(rec.get("boss", ""))
        if boss and diff:
            boss = f"{diff} {boss}"
        parse = rec.get("parse") or 0
        row = {
            "name": _cap(rec.get("name", "")),
            "color": _rgb(get_class_color(rec.get("cls") or rec.get("spec"))),
            "spec": rec.get("spec") or "",
            "cls": rec.get("cls") or "",
            "detail": " \u00b7 ".join(b for b in [label, boss] if b),
            "value": f"{parse:.0f}%",
            "value_color": _parse_color(parse),
        }
        if rec.get("new"):
            row["value_suffix"] = "NEW"
            row["value_suffix_color"] = ACCENT
        rows.append(row)
    return rows


def _closest_race(season_scores):
    """The tightest gap on the season ladder — rivalry fuel."""
    if not season_scores or len(season_scores) < 2:
        return None
    best = None
    ladder = season_scores[:6]
    for (s1, n1, _), (s2, n2, _) in zip(ladder, ladder[1:]):
        gap = s1 - s2
        if best is None or gap < best[0]:
            best = (gap, n1, n2)
    gap, leader, chaser = best
    if gap <= 50:
        return f"{_cap(chaser)} trails {_cap(leader)} by just {gap:.0f} \u2014 one good key flips it"
    return f"{_cap(chaser)} trails {_cap(leader)} by {gap:.0f}"


def _titled(base, pool):
    """Append the difficulty the rows actually came from, when uniform —
    "TOP HEALING PARSES · HEROIC" makes fallback sections honest."""
    diffs = {info.get("difficulty") for info in (pool or {}).values()}
    if len(diffs) == 1:
        name = DIFFICULTY_NAMES.get(next(iter(diffs)), "")
        if name and name != "M+":
            return f"{base} \u00b7 {name.upper()}"
    return base


def _build_columns(cfg, stats, leaders, mplus_results, season_scores, season_parses, no_logs, mplus_weekly=None, streaks=None, zone_name=None):
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
        if _enabled(sections_cfg, "top_dps"):
            rows = _parse_rows(stats.get("best_dps") or {}, "DPS", top_n, diff_name, streaks)
            raid.append(_sec(_titled("TOP DPS PARSES", stats.get("best_dps")), rows))
        if _enabled(sections_cfg, "top_healing"):
            rows = _parse_rows(stats.get("best_hps") or {}, "HPS", top_n, diff_name, streaks)
            raid.append(_sec(_titled("TOP HEALING PARSES", stats.get("best_hps")), rows))
    if (stats or leaders) and _enabled(sections_cfg, "realm_rank_leaders"):
        raid.append(_sec("WEEKLY BOSS RANKS", _leader_rows(leaders or [], top_n)))
    if stats and _enabled(sections_cfg, "most_deaths"):
        campers_title = "GRAVEYARD CAMPERS"
        camper_diff = DIFFICULTY_NAMES.get(stats.get("difficulty"), "")
        camper_zone = (zone_name or "").strip()
        context = " ".join(b for b in [camper_diff.upper(), camper_zone.upper()] if b)
        if context:
            campers_title += f" \u00b7 {context[:34]}"
        raid.append(_sec(campers_title,
                         _death_rows(stats.get("deaths") or {}, top_n, class_lookup,
                                     pulls=stats.get("pulls") or 0)))

    mplus = []
    if mplus_results is not None and _enabled(sections_cfg, "mplus"):
        mplus.append(_sec("TOP TIMED KEYS THIS WEEK", _mplus_week_rows(mplus_results, top_n, streaks),
                          "No timed keys this week"))
    if mplus_weekly is not None and _enabled(sections_cfg, "mplus_weekly_parses"):
        empty = "No M+ logs uploaded this week"
        mplus.append(_sec("TOP M+ DPS THIS WEEK",
                          _parse_rows(mplus_weekly.get("dps") or {}, "DPS", top_n), empty))
        mplus.append(_sec("TOP M+ HPS THIS WEEK",
                          _parse_rows(mplus_weekly.get("hps") or {}, "HPS", top_n), empty))

    return raid, mplus


def _build_seasonal(cfg, season_scores, season_parses, improvement, previous=None, records=None):
    """The bottom Seasonal band: two internal columns of season-long data."""
    sections_cfg = cfg.get("sections", {})
    top_n = int(cfg.get("top_n", 5))
    imp = improvement or {}
    prev_scores = (previous or {}).get("season_scores") or {}

    improve_empty = "No qualifying gains yet — needs 2+ weeks of logs"

    scores_sec = runs_sec = race_sec = records_sec = dps_sec = hps_sec = None
    if season_scores is not None and _enabled(sections_cfg, "mplus_season_scores"):
        scores_sec = _sec("SEASON M+ SCORES", _season_score_rows(season_scores or [], top_n, prev_scores))
        race = _closest_race(season_scores or [])
        if race and _enabled(sections_cfg, "closest_race"):
            race_sec = _sec("CLOSEST RACE", [{"text": race}])
    if season_parses is not None and _enabled(sections_cfg, "mplus_season_parses", _enabled(sections_cfg, "mplus_season_runs")):
        runs_sec = _sec("BEST SEASON RUNS", _season_run_rows(season_parses or [], top_n))
    if "dps" in imp:
        dps_sec = _sec("MOST IMPROVED DPS", _improve_rows(imp.get("dps") or []), improve_empty)
    if "hps" in imp:
        hps_sec = _sec("MOST IMPROVED HEALERS", _improve_rows(imp.get("hps") or []), improve_empty)
    if records and _enabled(sections_cfg, "guild_records"):
        record_rows = _record_rows(records)
        if record_rows:
            records_sec = _sec("GUILD RECORDS \u00b7 SEASON", record_rows)

    # Paired rows: each tuple renders at the same y, so partners align
    pairs = [(scores_sec, runs_sec), (dps_sec, hps_sec), (race_sec, records_sec)]
    return [pair for pair in pairs if pair[0] or pair[1]]


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


def _draw_row(img, draw, x, y, w, index, row, fonts, icons=True):
    cy = y + ROW_H // 2

    if "text" in row:
        text = _fit(draw, row["text"], fonts["detail"], w)
        draw.text((x, cy - 9), text, font=fonts["detail"], fill=MUTED)
        return

    _draw_rank_badge(draw, x, cy, index, fonts["badge"])

    value = row.get("value", "")
    vw = draw.textlength(value, font=fonts["name"])
    total_vw = vw
    suffix = row.get("value_suffix") or ""
    if suffix:
        suffix = f" · {suffix}"
        total_vw += draw.textlength(suffix, font=fonts["detail"])
    vx = x + w - total_vw
    draw.text((vx, cy - 10), value, font=fonts["name"], fill=row.get("value_color", TEXT))
    if suffix:
        draw.text((vx + vw, cy - 9), suffix, font=fonts["detail"],
                  fill=row.get("value_suffix_color", MUTED))
    vw = total_vw

    nx = x + 32
    if icons:
        # Reserve the icon slot even when unresolved so names stay aligned
        icon = _row_icon(row)
        if icon:
            img.paste(icon[0], (int(nx), int(cy - ICON_SIZE // 2)), icon[1])
        nx += ICON_SIZE + 8

    name = _fit(draw, row.get("name", ""), fonts["name"], x + w - vw - 16 - nx)
    draw.text((nx, cy - 10), name, font=fonts["name"], fill=row.get("color", TEXT))

    detail = row.get("detail")
    if detail:
        dx = nx + draw.textlength(name, font=fonts["name"]) + 10
        max_dw = x + w - vw - 16 - dx
        if max_dw > 40:
            bits = row.get("detail_bits")
            if bits:
                detail = _fit_bits(draw, bits, fonts["detail"], max_dw)
            else:
                detail = _fit(draw, detail, fonts["detail"], max_dw)
            draw.text((dx, cy - 9), detail, font=fonts["detail"], fill=MUTED)


def _draw_column(img, draw, x0, y0, height, title, sections, fonts,
                 empty_text="No data this week", icons=True):
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

    _draw_sections(img, draw, x, y, w, sections, fonts, icons)


def _draw_sections(img, draw, x, y, w, sections, fonts, icons=True):
    for si, section in enumerate(sections):
        if si:
            y += SEC_GAP
        draw.text((x, y), section["title"], font=fonts["sec_title"], fill=ACCENT)
        title_w = draw.textlength(section["title"], font=fonts["sec_title"])
        draw.line([x + title_w + 12, y + 9, x + w, y + 9], fill=PANEL_BORDER, width=1)
        y += SEC_TITLE_H
        for i, row in enumerate(section["rows"]):
            _draw_row(img, draw, x, y, w, i, row, fonts, icons=icons)
            y += ROW_H


def _seasonal_height(pairs):
    body = sum(max(_section_height(s) if s else 0 for s in pair) for pair in pairs)
    body += SEC_GAP * max(len(pairs) - 1, 0)
    return COL_HEADER_H + body + 2 * COL_PAD


def _draw_seasonal(img, draw, y0, height, pairs, fonts, icons=True):
    """Full-width Seasonal panel: paired sections rendered side by side."""
    x0, x1 = MARGIN, WIDTH - MARGIN
    draw.rounded_rectangle([x0, y0, x1, y0 + height], radius=12,
                           fill=PANEL, outline=PANEL_BORDER, width=1)
    x = x0 + COL_PAD
    y = y0 + COL_PAD
    draw.rectangle([x, y + 2, x + 4, y + 24], fill=ACCENT)
    draw.text((x + 14, y), "SEASONAL", font=fonts["col_header"], fill=TEXT)
    y += COL_HEADER_H

    inner_w = (x1 - x0 - 2 * COL_PAD - GUTTER) // 2
    for i, (left_sec, right_sec) in enumerate(pairs):
        if i:
            y += SEC_GAP
        if left_sec:
            _draw_sections(img, draw, x, y, inner_w, [left_sec], fonts, icons)
        if right_sec:
            _draw_sections(img, draw, x + inner_w + GUTTER, y, inner_w, [right_sec], fonts, icons)
        y += max(_section_height(s) if s else 0 for s in (left_sec, right_sec))


def _rank_delta(prev, cur):
    """Rank movement: climbing (a smaller number) is the good direction."""
    if not prev or not cur or prev == cur:
        return "", MUTED
    diff = prev - cur
    if diff > 0:
        return f"\u25b2{diff:,}", (76, 220, 86)
    return f"\u25bc{-diff:,}", RED


def _hero_tiles(stats, standing, previous=None):
    prev_standing = (previous or {}).get("standing") or {}
    stale = bool((standing or {}).get("stale"))
    tiles = []
    if stats:
        tiles.append(("KILLS", str(stats.get("kills", 0)), "", MUTED))
        tiles.append(("PULLS", str(stats.get("pulls", 0)), "", MUTED))
        tiles.append(("DEATHS", str(sum((stats.get("deaths") or {}).values())), "", MUTED))
    if standing:
        for key, label in (("realm", "REALM RANK"), ("region", "REGION RANK"), ("world", "WORLD RANK")):
            if standing.get(key):
                if stale:
                    label += " \u00b7 LAST WK"
                    delta, color = "", MUTED
                else:
                    delta, color = _rank_delta(prev_standing.get(key), standing[key])
                tiles.append((label, f"#{standing[key]:,}", delta, color))
    return tiles[:6]


def _draw_hero(draw, y0, height, stats, standing, fonts, previous=None):
    x0, x1 = MARGIN, WIDTH - MARGIN
    draw.rounded_rectangle([x0, y0, x1, y0 + height], radius=12,
                           fill=PANEL, outline=PANEL_BORDER, width=1)
    pad = 22
    tiles = _hero_tiles(stats, standing, previous)
    if tiles:
        tile_w = (x1 - x0 - 2 * pad) // len(tiles)
        for i, (label, value, delta, delta_color) in enumerate(tiles):
            tx = x0 + pad + i * tile_w
            draw.text((tx, y0 + 16), label, font=fonts["tile_label"], fill=MUTED)
            draw.text((tx, y0 + 34), value, font=fonts["tile_value"], fill=TEXT)
            if delta:
                value_w = draw.textlength(value, font=fonts["tile_value"])
                draw.text((tx + value_w + 8, y0 + 44), delta,
                          font=fonts["tile_label"], fill=delta_color)

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
                         improvement=None, mplus_weekly=None, previous=None,
                         streaks=None, records=None):
    """Render the full weekly board and save it as a PNG."""
    fonts = _fonts()
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    raid_sections, mplus_sections = _build_columns(
        cfg, stats, leaders, mplus_results, mplus_season_scores, mplus_season_parses,
        no_logs, mplus_weekly=mplus_weekly, streaks=streaks, zone_name=zone_name)
    seasonal_pairs = _build_seasonal(
        cfg, mplus_season_scores, mplus_season_parses, improvement, previous=previous,
        records=records)
    show_seasonal = bool(seasonal_pairs)

    sections_cfg = cfg.get("sections", {})
    raid_title = (sections_cfg.get("raid_header") or {}).get("title", "Raid").upper()
    mplus_title = (sections_cfg.get("mplus_header") or {}).get("title", "Mythic Plus").upper()

    theme = _load_theme_art(cfg)
    header_h = (HEADER_ART_H + ART_INFO_H) if theme else 96
    show_hero = stats is not None or bool(standing)
    hero_h = 120 if show_hero else 0
    col_h = max(_column_height(raid_sections), _column_height(mplus_sections))
    seasonal_h = _seasonal_height(seasonal_pairs) if show_seasonal else 0

    quote_max_w = WIDTH - 2 * MARGIN - 2 * COL_PAD
    roast_lines, roast_attr = _roast_lines(cfg, measure, fonts, quote_max_w)
    roast_h = (20 + 24 + len(roast_lines) * 28 + 26) if roast_lines else 0

    height = (0 if theme else MARGIN) + header_h
    if show_hero:
        height += hero_h + GUTTER
    height += col_h
    if show_seasonal:
        height += GUTTER + seasonal_h
    if roast_lines:
        height += GUTTER + roast_h
    if theme:
        height += GUTTER + FOOTER_ART_H   # footer art runs flush to the edge
    else:
        height += MARGIN

    img = Image.new("RGB", (WIDTH, height), BG)
    draw = ImageDraw.Draw(img)

    # header
    lookback = int(cfg.get("lookback_days", 7))
    range_label = "Raid week" if lookback == 7 else f"Last {lookback} days"
    date_range = f"{range_label}: {start_dt.strftime('%b %d')} – {end_dt.strftime('%b %d, %Y')}"
    difficulty = str(cfg.get("raid", {}).get("difficulty", "mythic"))
    if stats and stats.get("difficulty") in DIFFICULTY_NAMES:
        difficulty = DIFFICULTY_NAMES[stats["difficulty"]]
    difficulty = difficulty.upper()
    subtitle = f"{difficulty} · {zone_name}" if zone_name else f"{difficulty} WEEKLY BOARD"

    if theme:
        _paste_banner(img, theme, 0, HEADER_ART_H, "top")
        strip_y = HEADER_ART_H + 2
        draw.text((MARGIN, strip_y + 6), subtitle, font=fonts["subtitle"], fill=MUTED)
        dw = draw.textlength(date_range, font=fonts["date"])
        draw.text((WIDTH - MARGIN - dw, strip_y + 8), date_range, font=fonts["date"], fill=MUTED)
        draw.line([MARGIN, strip_y + ART_INFO_H - 8, WIDTH - MARGIN, strip_y + ART_INFO_H - 8],
                  fill=PANEL_BORDER, width=1)
        y = HEADER_ART_H + ART_INFO_H
    else:
        y = MARGIN
        draw.text((MARGIN, y), cfg["guild"]["name"], font=fonts["title"], fill=ACCENT)
        dw = draw.textlength(date_range, font=fonts["date"])
        draw.text((WIDTH - MARGIN - dw, y + 18), date_range, font=fonts["date"], fill=MUTED)
        draw.text((MARGIN, y + 52), subtitle, font=fonts["subtitle"], fill=MUTED)
        draw.line([MARGIN, y + 86, WIDTH - MARGIN, y + 86], fill=PANEL_BORDER, width=1)
        y += header_h

    if show_hero:
        _draw_hero(draw, y, hero_h, stats, standing, fonts, previous=previous)
        y += hero_h + GUTTER

    icons = bool((cfg.get("display") or {}).get("icons", True))
    _draw_column(img, draw, MARGIN, y, col_h, raid_title, raid_sections, fonts, icons=icons)
    _draw_column(img, draw, MARGIN + COL_W + GUTTER, y, col_h, mplus_title, mplus_sections, fonts, icons=icons)
    y += col_h

    if show_seasonal:
        y += GUTTER
        _draw_seasonal(img, draw, y, seasonal_h, seasonal_pairs, fonts, icons=icons)
        y += seasonal_h

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

    if theme:
        _paste_banner(img, theme, height - FOOTER_ART_H, FOOTER_ART_H, "bottom")

    display_cfg = cfg.get("display") or {}
    if display_cfg.get("watermark"):
        text = display_cfg.get(
            "watermark_text",
            "Powered by Guild Board · github.com/Bzach10/wow-guild-board")
        wfont = _load_font(12)
        tw = draw.textlength(text, font=wfont)
        wx, wy = WIDTH - MARGIN - tw, height - 24
        draw.text((wx + 1, wy + 1), text, font=wfont, fill=(0, 0, 0))
        draw.text((wx, wy), text, font=wfont, fill=FAINT)

    img.save(output_path, "PNG")
    logger.info("Generated board image at %s (%sx%s)", output_path, WIDTH, height)
    return output_path

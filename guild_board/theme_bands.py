"""Skill Issues custom header/footer bands — drop-in for wow-guild-board.

Replicates the approved HTML designs (2a "War Room" header, 2b "Roast &
Recruit / Graveyard Memorial" footer) in Pillow so the weekly GitHub Action
renders them with LIVE data: wipes, deaths, pulls, and repair-bill estimate
come from this week's stats instead of frozen numbers.

Install: copy this file to guild_board/theme_bands.py and the three PNGs to
assets/ (see README.md in this handoff for the 6-line board_image.py patch).
"""

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

HEADER_BAND_H = 380          # art band; the info strip below is drawn by board_image
FOOTER_BAND_H = 624          # 572 art + 52 MOTD strip

ASSET_DIR = Path("assets")

# palette (matches board_image.py)
BG = (17, 18, 23)
PANEL = (18, 19, 25)
PANEL_BORDER = (58, 52, 39)
ACCENT = (230, 180, 70)
TEXT = (235, 236, 240)
MUTED = (150, 154, 164)
FAINT = (95, 99, 110)
RED = (229, 72, 77)
GREEN = (76, 220, 86)
EPIC = (163, 53, 238)
LEGENDARY = (255, 128, 0)
UNCOMMON = (30, 255, 0)
GOLD_TEXT = (255, 209, 0)

_FONT_CANDIDATES = {
    False: [
        "assets/fonts/Cinzel-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ],
    True: [
        "assets/fonts/Cinzel-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ],
}
_font_cache = {}


def _font(size, bold=False, display=False):
    """display=True prefers the Cinzel file if present (drop one into
    assets/fonts/ for the carved-stone look); everything falls back to the
    same system fonts board_image uses."""
    key = (size, bold, display)
    if key in _font_cache:
        return _font_cache[key]
    candidates = list(_FONT_CANDIDATES[bold])
    if not display:
        candidates = [c for c in candidates if "Cinzel" not in c]
    for path in candidates:
        try:
            _font_cache[key] = ImageFont.truetype(path, size)
            return _font_cache[key]
        except Exception:
            continue
    _font_cache[key] = ImageFont.load_default()
    return _font_cache[key]


def _load(path):
    try:
        return Image.open(path).convert("RGB")
    except Exception as exc:
        logger.info("Band asset %s not usable (%s)", path, exc)
        return None


def _center(draw, cx, y, text, font, fill):
    w = draw.textlength(text, font=font)
    draw.text((cx - w / 2, y), text, font=font, fill=fill)


def _carved(draw, cx, y, text, font):
    """Chiseled-into-stone lettering: light below, shadow above, dark face."""
    w = draw.textlength(text, font=font)
    x = cx - w / 2
    draw.text((x, y + 3), text, font=font, fill=(208, 192, 160))
    draw.text((x, y - 2), text, font=font, fill=(30, 24, 18))
    draw.text((x, y), text, font=font, fill=(67, 53, 42))


def _fmt_g(n):
    return f"{n:,}"


def _glow(img, cx, cy, rx, ry, color, alpha, steps=12):
    """Soft radial glow via stacked translucent ellipses."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for i in range(steps, 0, -1):
        f = i / steps
        a = int(alpha * (1 - f) ** 2)
        d.ellipse([cx - rx * f, cy - ry * f, cx + rx * f, cy + ry * f],
                  fill=color + (a,))
    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"), (0, 0))


def _flame(img, cx, base_y):
    """Small stylized campfire/torch flame: three stacked tongues."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for w, h, color, a in ((56, 92, (224, 122, 40), 200), (36, 66, (246, 176, 78), 220), (18, 40, (255, 233, 168), 235)):
        d.ellipse([cx - w // 2, base_y - h, cx + w // 2, base_y], fill=color + (a,))
    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"), (0, 0))


def _fetch_icon(name, size):
    """Wowhead CDN icon with disk cache; fails open to None (slot stays empty)."""
    try:
        import requests
        cache = Path(".icon_cache"); cache.mkdir(exist_ok=True)
        p = cache / f"{name}.jpg"
        if not p.exists():
            r = requests.get(f"https://wow.zamimg.com/images/wow/icons/large/{name}.jpg", timeout=10)
            if r.status_code == 200 and r.content:
                p.write_bytes(r.content)
        if p.exists():
            return Image.open(p).convert("RGB").resize((size, size), Image.LANCZOS)
    except Exception as exc:
        logger.debug("icon %s unavailable: %s", name, exc)
    return None


# ---------------------------------------------------------------- header ----

def draw_header_band(img, stats=None):
    W = img.width
    draw = ImageDraw.Draw(img)
    wall = _load(ASSET_DIR / "wall_header.png")
    if wall:
        img.paste(wall.resize((W, HEADER_BAND_H), Image.LANCZOS), (0, 0))
    else:
        draw.rectangle([0, 0, W, HEADER_BAND_H], fill=(38, 30, 23))
    _glow(img, W // 2, HEADER_BAND_H + 60, int(W * 0.32), 220, (224, 122, 40), 70)

    kills = (stats or {}).get("kills", 0)
    pulls = (stats or {}).get("pulls", 0)
    deaths = sum(((stats or {}).get("deaths") or {}).values())
    wipes = max(pulls - kills, 0)
    repair = deaths * 57 + pulls * 23   # honest-ish estimate; tune freely

    # --- carved stone plaque -------------------------------------------------
    draw.rounded_rectangle([44, 36, 644, 344], radius=12, fill=(61, 49, 35), outline=(32, 25, 18), width=2)
    plaque = _load(ASSET_DIR / "plaque.png")
    if plaque:
        img.paste(plaque.resize((572, 280), Image.LANCZOS), (58, 50))
    cx = 344
    _carved(draw, cx, 76, "SKILL", _font(92, bold=True, display=True))
    _carved(draw, cx, 172, "ISSUES", _font(92, bold=True, display=True))
    _carved(draw, cx, 284, "B L E E D I N G   H O L L O W   ·   U S", _font(16, bold=True))
    for rx, ry in ((72, 62), (616, 62), (74, 318), (614, 318)):
        draw.ellipse([rx - 8, ry - 8, rx + 8, ry + 8], fill=(70, 58, 42), outline=(28, 22, 16))
        draw.ellipse([rx - 5, ry - 6, rx + 1, ry], fill=(141, 122, 94))

    # --- live widgets --------------------------------------------------------
    widgets = [
        (700, 380, "WIPES THIS WEEK", str(wipes), RED if wipes else GREEN,
         f"deaths: {deaths} · personal best: still zero"),
        (1106, 400, "SEASON REPAIR BILL (EST.)", _fmt_g(repair), TEXT,
         "donations welcome · thoughts & prayers accepted"),
        (1532, 330, "\u201cGO AGANE\u201d COUNTER", str(pulls), TEXT,
         "morale: unaffected · copium: stable"),
    ]
    for x, w, label, value, vcolor, sub in widgets:
        draw.rounded_rectangle([x, 44, x + w, 214], radius=12, fill=PANEL, outline=PANEL_BORDER, width=1)
        draw.text((x + 24, 64), label, font=_font(19, bold=True), fill=ACCENT)
        draw.text((x + 24, 96), value, font=_font(54, bold=True), fill=vcolor)
        draw.text((x + 24, 176), sub, font=_font(15), fill=MUTED)
    # gold + silver coins beside the repair value
    vw = draw.textlength(_fmt_g(repair), font=_font(54, bold=True))
    gx = int(1106 + 24 + vw + 14)
    draw.ellipse([gx, 128, gx + 20, 148], fill=(230, 180, 70), outline=(138, 100, 32))
    draw.ellipse([gx + 3, 131, gx + 11, 139], fill=(255, 233, 168))
    draw.text((gx + 30, 116), "43", font=_font(30, bold=True), fill=(176, 182, 192))
    sx = gx + 30 + int(draw.textlength("43", font=_font(30, bold=True))) + 8
    draw.ellipse([sx, 132, sx + 14, 146], fill=(176, 182, 192), outline=(106, 112, 124))

    # --- debuff bar ----------------------------------------------------------
    draw.text((700, 272), "ACTIVE RAID DEBUFFS", font=_font(14, bold=True), fill=(184, 188, 198))
    debuffs = [
        ("inv_misc_questionmark", RED, "40"),          # Skill Issue
        ("spell_fire_fire", RED, "6w"),                # Standing in Fire (Healmates)
        ("inv_misc_bone_humanskull_01", RED, str(deaths)),  # Graveyard Timeshare
        ("spell_nature_sleep", GREEN, "\u221e"),        # Coping
        ("spell_holy_layonhands", GREEN, "1"),          # Healer Diff
    ]
    ix = 950
    for name, border, stack in debuffs:
        icon = _fetch_icon(name, 52)
        if icon:
            img.paste(icon, (ix, 300))
        else:
            draw.rectangle([ix, 300, ix + 52, 352], fill=(30, 32, 40))
        draw.rectangle([ix - 2, 298, ix + 54, 354], outline=border, width=2)
        sw = draw.textlength(stack, font=_font(17, bold=True))
        draw.text((ix + 51 - sw, 333), stack, font=_font(17, bold=True), fill=(0, 0, 0))
        draw.text((ix + 50 - sw, 332), stack, font=_font(17, bold=True), fill=(255, 255, 255))
        ix += 66
    draw.text((950, 250), "Skill Issue · Standing in Fire (Healmates) · Graveyard Timeshare · Coping · Healer Diff",
              font=_font(14), fill=FAINT)

    # --- torch + hanging GIT GUD shingle ------------------------------------
    tx = W - 470
    _glow(img, tx, 210, 90, 110, (224, 122, 40), 110)
    draw.rounded_rectangle([tx - 7, 190, tx + 7, 266], radius=7, fill=(58, 44, 30), outline=(32, 25, 18))
    _flame(img, tx, 196)

    sx0 = W - 96 - 250
    for cxn in (sx0 + 50, sx0 + 200):
        draw.line([cxn, 0, cxn, 74], fill=(42, 33, 22), width=4)
    draw.rounded_rectangle([sx0, 74, sx0 + 250, 196], radius=8, fill=(90, 64, 40), outline=(43, 33, 23), width=3)
    for py in range(96, 196, 24):
        draw.line([sx0 + 4, py, sx0 + 246, py], fill=(69, 48, 29), width=2)
    _center(draw, sx0 + 125, 92, "GIT GUD", _font(42, bold=True, display=True), (38, 28, 18))
    _center(draw, sx0 + 125, 150, "MGMT IS NOT RESPONSIBLE", _font(12, bold=True), (46, 36, 24))


# ---------------------------------------------------------------- footer ----

RULES = [
    ("Codex of Conduct", EPIC, 34, True),
    ("Binds when you join", TEXT, 20, False),
    ("Guild Charter                                     Unique", TEXT, 20, False),
    ("+10 Blaming the Healer", TEXT, 20, False),
    ("+5 Ignoring Swirlies", TEXT, 20, False),
    ("Equip: Rule 1 — It is always Healmates' fault.", UNCOMMON, 20, False),
    ("Equip: Rule 2 — The swirly is a suggestion.", UNCOMMON, 20, False),
    ("Equip: Rule 3 — \u201cOne more pull\u201d legally means five.", UNCOMMON, 20, False),
    ("Equip: Rule 4 — GBank tab 3 is not your personal bank.", UNCOMMON, 20, False),
    ("\u201cIf you die in the fire, you lose DKP we don't track.\u201d", GOLD_TEXT, 20, False),
    ("Requires: Skill (missing)", (255, 32, 32), 20, False),
]

RECRUIT = [
    ("Now Recruiting: Anyone With Hands", LEGENDARY, 30, True),
    ("Binds on invite", TEXT, 20, False),
    ("Warm Body                                        Any Spec", TEXT, 20, False),
    ("+100% Attendance Aura (aspirational)", TEXT, 20, False),
    ("Equip: Knows what a swirly is. (preferred, not required)", UNCOMMON, 20, False),
    ("Equip: Has released spirit at least once unassisted.", UNCOMMON, 20, False),
    ("Use: Presses defensives before dying. (2 Min Cooldown)", UNCOMMON, 20, False),
    ("\u201cHealmates needs backup. Or a replacement.", GOLD_TEXT, 20, False),
    ("  Mostly a replacement.\u201d", GOLD_TEXT, 20, False),
    ("Apply in #recruitment · literally no requirements", TEXT, 20, False),
]

EPITAPHS = [
    "\u201cFound the one-shot. Repeatedly.\u201d",
    "\u201cDied to the same swirly. Times ten.\u201d",
    "\u201cDid the mechanics. Mechanics did him back.\u201d",
    "\u201cThe healer. Yes, the healer.\u201d",
]

MOTD_QUIPS = [
    "MORE DOTS. MORE DOTS. \u2026 OK STOP DOTS.",
    "That's a 50 DKP MINUS.",
    "Healmates has now stood in the fire for 6 consecutive weeks — a new guild record.",
    "Key depleted? That is a you problem.",
    "At least Leeroy had a plan.",
    "Raid times: Tue/Thu, 8 PM to whenever Rakdisc stops blaming people.",
    "Repair bills are self-inflicted and therefore not reimbursable.",
]


def _tooltip(draw, x, y, w, lines, outline):
    h = 40
    for _, _, size, _ in lines:
        h += int(size * 1.6)
    draw.rounded_rectangle([x, y, x + w, y + h], radius=8, fill=(7, 7, 24), outline=outline, width=2)
    ty = y + 22
    for text, color, size, display in lines:
        draw.text((x + 28, ty), text, font=_font(size, bold=(size > 24), display=display), fill=color)
        ty += int(size * 1.6)
    return h


def draw_footer_band(img, y, stats=None, week_index=0):
    W = img.width
    draw = ImageDraw.Draw(img)
    art_h = FOOTER_BAND_H - 52
    wall = _load(ASSET_DIR / "wall_footer.png")
    if wall:
        img.paste(wall.resize((W, art_h), Image.LANCZOS), (0, y))
    else:
        draw.rectangle([0, y, W, y + art_h], fill=(34, 27, 21))

    _tooltip(draw, 60, y + 46, 600, RULES, (67, 67, 92))
    _tooltip(draw, W - 60 - 600, y + 60, 600, RECRUIT, (92, 74, 46))

    # --- graveyard memorial --------------------------------------------------
    mx0, mx1 = 60 + 600 + 44, W - 60 - 600 - 44
    mw = mx1 - mx0
    _center(draw, (mx0 + mx1) // 2, y + 30, "GRAVEYARD CAMPERS MEMORIAL", _font(16, bold=True), ACCENT)
    fy = y + 62
    fh = art_h - 130
    draw.rounded_rectangle([mx0, fy, mx1, fy + fh], radius=10, fill=(14, 16, 20), outline=(150, 122, 62), width=3)
    _glow(img, (mx0 + mx1) // 2, fy + fh, int(mw * 0.42), 150, (58, 220, 90), 60)

    ranked = sorted(((stats or {}).get("deaths") or {}).items(), key=lambda kv: kv[1], reverse=True)[:4]
    if not ranked:
        ranked = [("Nobody", 0)]
    pulls = (stats or {}).get("pulls", 0)
    stone_w, gap = 190, 34
    total = len(ranked) * (stone_w + gap) + 210
    sx = (mx0 + mx1) // 2 - total // 2
    ground = fy + fh - 26
    grays = [(118, 114, 104), (124, 120, 109), (110, 106, 96), (110, 106, 96)]
    for i, (name, count) in enumerate(ranked):
        h = 236 - i * 18
        top = ground - h
        g = grays[i % len(grays)]
        dark = tuple(int(v * 0.55) for v in g)
        draw.ellipse([sx, top, sx + stone_w, top + 110], fill=g, outline=dark)
        draw.rectangle([sx, top + 55, sx + stone_w, ground], fill=g)
        draw.rectangle([sx, top + 55, sx + stone_w, ground], outline=dark)
        scx = sx + stone_w // 2
        _center(draw, scx, top + 26, "R.I.P.", _font(22, bold=True, display=True), (46, 44, 39))
        _center(draw, scx, top + 56, name.upper()[:12], _font(20, bold=True), (46, 44, 39))
        rate = f" · {count / pulls:.1f}/PULL" if pulls else ""
        _center(draw, scx, top + 86, f"{count} DEATHS{rate}", _font(14, bold=True), (70, 63, 46))
        _center(draw, scx, top + 112, EPITAPHS[i % len(EPITAPHS)][:34], _font(12), (74, 70, 61))
        sx += stone_w + gap
    # reserved campfire plot
    _glow(img, sx + 90, ground - 10, 90, 70, (224, 122, 40), 120)
    draw.polygon([(sx + 30, ground - 4), (sx + 92, ground - 18), (sx + 96, ground - 6), (sx + 34, ground + 6)], fill=(66, 47, 29))
    draw.polygon([(sx + 150, ground - 4), (sx + 88, ground - 18), (sx + 84, ground - 6), (sx + 146, ground + 6)], fill=(58, 42, 26))
    _flame(img, sx + 90, ground - 14)
    draw.rounded_rectangle([sx + 14, ground + 10, sx + 166, ground + 40], radius=6, fill=(58, 44, 26), outline=(33, 24, 9), width=2)
    _center(draw, sx + 90, ground + 16, "RESERVED: HEALMATES", _font(13, bold=True), (217, 196, 154))
    _center(draw, (mx0 + mx1) // 2, fy + fh + 12, "Plots assigned by deaths-per-pull. The campfire is load-bearing.",
            _font(15), MUTED)

    # --- MOTD strip ----------------------------------------------------------
    sy = y + art_h
    draw.rectangle([0, sy, W, sy + 52], fill=(13, 14, 19))
    draw.rectangle([0, sy, 120, sy + 52], fill=(26, 28, 35))
    draw.text((26, sy + 16), "MOTD", font=_font(16, bold=True), fill=ACCENT)
    quip = MOTD_QUIPS[week_index % len(MOTD_QUIPS)]
    draw.text((150, sy + 14), quip, font=_font(19), fill=ACCENT)
    draw.line([0, sy, W, sy], fill=(45, 48, 58), width=1)

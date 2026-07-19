"""Skill Issues custom header/footer bands — drop-in for wow-guild-board.

Faithful Pillow port of the approved HTML design (2a "War Room" header,
2b "Graveyard Memorial" footer, claude.ai artifact baf8f774): same colors,
sizes, rotations, gradients and glows as the published CSS, rendered with
LIVE data — wipes, deaths, pulls and repair-bill estimate come from this
week's stats instead of frozen numbers.

Layout deltas from the artifact (owner-approved): the recruiting poster is
replaced by the Guild Item of the Month card, and the MOTD ticker is a
static quip rotating weekly (a scrolling ticker cannot loop in a 1.2s GIF).
"""

import logging
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

logger = logging.getLogger(__name__)

HEADER_BAND_H = 380          # art band; the info strip below is drawn by board_image
FOOTER_ART_H_DESIGN = 520    # visible slice of the footer wall art
MOTD_H = 52
CREDITS_H = 40
FOOTER_BAND_H = FOOTER_ART_H_DESIGN + MOTD_H + CREDITS_H   # 612

ASSET_DIR = Path("assets")

# palette (matches the design CSS)
BG = (17, 18, 23)            # #111217
PANEL = (15, 16, 22)         # rgba(15,16,22,.9) widget fill
PANEL_BORDER = (58, 52, 39)  # #3a3427
ACCENT = (230, 180, 70)      # #e6b446
TEXT = (235, 236, 240)       # #ebecf0
MUTED = (150, 154, 164)      # #969aa4
FAINT = (95, 99, 110)        # #5f636e
RED = (229, 72, 77)          # #e5484d
GREEN = (76, 220, 86)        # #4cdc56
EPIC = (163, 53, 238)        # #a335ee
LEGENDARY = (255, 128, 0)    # #ff8000
UNCOMMON = (30, 255, 0)      # #1eff00
GOLD_TEXT = (255, 209, 0)    # #ffd100

_FONT_CANDIDATES = {
    (False, False): [
        "assets/fonts/Cinzel-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ],
    (True, False): [
        "assets/fonts/Cinzel-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ],
    (False, True): [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
        "C:/Windows/Fonts/segoeuii.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ],
    (True, True): [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
        "C:/Windows/Fonts/segoeuiz.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ],
}
_font_cache = {}


def _font(size, bold=False, display=False, italic=False):
    """display=True prefers the Cinzel file if present (the carved-stone
    look); everything falls back to the same system fonts board_image uses."""
    size = int(size)
    key = (size, bold, display, italic)
    if key in _font_cache:
        return _font_cache[key]
    candidates = list(_FONT_CANDIDATES[(bold, italic)])
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


def _spaced(draw, x, y, text, font, fill, spacing):
    """Letter-spaced text (CSS letter-spacing has no Pillow equivalent)."""
    cx = x
    for ch in text:
        draw.text((cx, y), ch, font=font, fill=fill)
        cx += draw.textlength(ch, font=font) + spacing
    return cx - spacing - x


def _spaced_w(draw, text, font, spacing):
    return sum(draw.textlength(c, font=font) for c in text) + spacing * (len(text) - 1)


def _spaced_center(draw, cx, y, text, font, fill, spacing):
    w = _spaced_w(draw, text, font, spacing)
    _spaced(draw, cx - w / 2, y, text, font, fill, spacing)


def _vgrad(w, h, stops):
    """Vertical linear gradient; stops = [(t, (r,g,b)), ...] with t in 0..1."""
    img = Image.new("RGB", (1, max(h, 1)))
    for yy in range(h):
        t = yy / max(h - 1, 1)
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t0 <= t <= t1:
                f = (t - t0) / max(t1 - t0, 1e-6)
                img.putpixel((0, yy), tuple(int(a + (b - a) * f) for a, b in zip(c0, c1)))
                break
        else:
            img.putpixel((0, yy), stops[-1][1])
    return img.resize((max(w, 1), max(h, 1)))


def _fmt_g(n):
    return f"{n:,}"


def _flicker(phase, k, lo=0.86, hi=1.14):
    """Deterministic flame/glow wobble for animation frames (phase 0..1)."""
    return lo + (hi - lo) * (0.5 + 0.5 * math.sin(2 * math.pi * (phase + k)))


def _glow(img, cx, cy, rx, ry, color, alpha, steps=12, clip=None):
    """Soft radial glow via stacked translucent ellipses. `clip` confines the
    glow to a box — animated glows must stay inside their band so the GIF
    pipeline can redraw bands alone without touching the static columns."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for i in range(steps, 0, -1):
        f = i / steps
        a = int(alpha * (1 - f) ** 2)
        d.ellipse([cx - rx * f, cy - ry * f, cx + rx * f, cy + ry * f],
                  fill=color + (a,))
    box = tuple(int(v) for v in clip) if clip else (0, 0, img.width, img.height)
    region = Image.alpha_composite(img.crop(box).convert("RGBA"),
                                   overlay.crop(box)).convert("RGB")
    img.paste(region, box[:2])


def _embers(img, x0, y0, x1, y1, phase, seed=7, n=22, color=(255, 200, 120)):
    """Looping rising embers. Every particle's position/alpha is a pure
    function of (phase + offset) mod 1, so ANY frame count loops seamlessly
    and frame k is deterministic. Drawing is clipped to the given box."""
    rng = random.Random(seed)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    h = (y1 - y0) + 40
    for _ in range(n):
        px = x0 + rng.random() * (x1 - x0)
        off = rng.random()
        drift = (rng.random() - 0.5) * 90
        size = 2 + rng.random() * 4
        t = (phase + off) % 1.0
        y = y1 - t * h
        x = px + drift * t
        a = int(235 * min(t / 0.12, 1.0) * (1.0 - t) ** 1.5)
        if a <= 0:
            continue
        d.ellipse([x - size, y - size, x + size, y + size],
                  fill=(224, 122, 40, a // 2))
        cs = size * 0.45
        d.ellipse([x - cs, y - cs, x + cs, y + cs], fill=color + (a,))
    box = (int(x0), int(y0), int(x1), int(y1))
    region = Image.alpha_composite(img.crop(box).convert("RGBA"),
                                   overlay.crop(box)).convert("RGB")
    img.paste(region, box[:2])


def _flames(img, cx, base_y, tongues, phase, blur=4):
    """Blurred stacked flame tongues, the design's flamePulse look.
    tongues = [(w, h, color, alpha)] largest first; flicker + sway per
    tongue via phase. Rendered on a local tile so the blur stays cheap."""
    max_w = max(t[0] for t in tongues) + 40
    max_h = max(t[1] for t in tongues) + 50
    tile = Image.new("RGBA", (max_w, max_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    tcx, tby = max_w // 2, max_h - 10
    for i, (w, h, color, a) in enumerate(tongues):
        hh = int(h * _flicker(phase, 0.37 * i))
        sway = int(4 * math.sin(2 * math.pi * (phase + 0.21 * i)))
        d.ellipse([tcx + sway - w // 2, tby - hh, tcx + sway + w // 2, tby],
                  fill=color + (a,))
    tile = tile.filter(ImageFilter.GaussianBlur(blur))
    img.paste(tile, (int(cx - tcx), int(base_y - tby)), tile)


TORCH_TONGUES = [(64, 130, (224, 122, 40), 200),
                 (42, 100, (246, 176, 78), 220),
                 (22, 62, (255, 233, 168), 235)]
CAMPFIRE_TONGUES = [(56, 84, (224, 122, 40), 200),
                    (36, 64, (246, 176, 78), 220),
                    (18, 40, (255, 233, 168), 235)]


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


def _rounded_glow(img, box, color, spread=14, alpha=90):
    """Soft colored halo around a rounded box (the CSS box-shadow glow)."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for i in range(spread, 0, -2):
        a = int(alpha * (1 - i / spread) ** 1.5)
        d.rounded_rectangle([box[0] - i, box[1] - i, box[2] + i, box[3] + i],
                            radius=8 + i, outline=color + (a,), width=2)
    clip = (max(box[0] - spread, 0), max(box[1] - spread, 0),
            min(box[2] + spread, img.width), min(box[3] + spread, img.height))
    region = Image.alpha_composite(img.crop(clip).convert("RGBA"),
                                   overlay.crop(clip)).convert("RGB")
    img.paste(region, clip[:2])


def _alpha_panel(img, box, fill, alpha, radius, outline=None, ring=None):
    """Translucent rounded panel (the rgba(...) cards) with optional 1px
    inner ring, composited over the wall art."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rounded_rectangle(box, radius=radius, fill=fill + (alpha,))
    box_i = (int(box[0]), int(box[1]), int(box[2]), int(box[3]))
    region = Image.alpha_composite(img.crop(box_i).convert("RGBA"),
                                   overlay.crop(box_i)).convert("RGB")
    img.paste(region, box_i[:2])
    draw = ImageDraw.Draw(img)
    if outline:
        draw.rounded_rectangle(box, radius=radius, outline=outline, width=1)
    if ring:
        draw.rounded_rectangle([box[0] + 1, box[1] + 1, box[2] - 1, box[3] - 1],
                               radius=max(radius - 1, 1), outline=ring, width=1)


# ---------------------------------------------------------------- header ----

def _draw_plaque(img):
    """Carved wooden plaque, rotated -0.8deg like the design."""
    m = 24                              # tile margin so rotation never clips
    tile = Image.new("RGBA", (600 + 2 * m, 308 + 2 * m), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    # wooden frame: linear-gradient(160deg, #6b5943, #3d3123)
    frame = _vgrad(600, 308, [(0.0, (107, 89, 67)), (1.0, (61, 49, 35))])
    mask = Image.new("L", (600, 308), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, 599, 307], radius=12, fill=255)
    tile.paste(frame, (m, m), mask)
    # parchment inset
    parchment = _load(ASSET_DIR / "plaque.png")
    if parchment:
        p = parchment.resize((572, 280), Image.LANCZOS)
        pmask = Image.new("L", (572, 280), 0)
        ImageDraw.Draw(pmask).rounded_rectangle([0, 0, 571, 279], radius=6, fill=255)
        tile.paste(p, (m + 14, m + 14), pmask)
    # chiseled lettering: light below, shadow above, dark face (#43352a)
    def carved(cx, y, textv, fnt, spacing):
        w = _spaced_w(td, textv, fnt, spacing)
        x = cx - w / 2
        _spaced(td, x, y + 2, textv, fnt, (255, 244, 214, 100), spacing)
        _spaced(td, x, y - 2, textv, fnt, (0, 0, 0, 140), spacing)
        _spaced(td, x, y, textv, fnt, (67, 53, 42, 255), spacing)
    cx = m + 300
    big = _font(88, bold=True, display=True)
    carved(cx, m + 52, "SKILL", big, 9)
    carved(cx, m + 148, "ISSUES", big, 5)
    sub = _font(15, bold=True)
    _spaced_center(td, cx, m + 262, "BLEEDING HOLLOW · US", sub, (90, 74, 56, 255), 6)
    # corner nails
    for nx, ny in ((m + 28, m + 26), (m + 572, m + 26), (m + 30, m + 280), (m + 570, m + 280)):
        td.ellipse([nx - 8, ny - 8, nx + 8, ny + 8], fill=(61, 49, 35, 255))
        td.ellipse([nx - 6, ny - 6, nx + 2, ny + 1], fill=(141, 122, 94, 255))
    tile = tile.rotate(0.8, resample=Image.BICUBIC, center=(tile.width // 2, tile.height // 2))
    img.paste(tile, (44 - m, 36 - m), tile)


def draw_header_band(img, stats=None, phase=0.0):
    W = img.width
    draw = ImageDraw.Draw(img)
    wall = _load(ASSET_DIR / "wall_header.png")
    if wall:
        img.paste(wall.resize((W, HEADER_BAND_H), Image.LANCZOS), (0, 0))
    else:
        draw.rectangle([0, 0, W, HEADER_BAND_H], fill=(38, 30, 23))
    # fire-glow rising from below (glowPulse)
    _glow(img, W // 2, HEADER_BAND_H + 60, int(W * 0.50), 220, (224, 122, 40),
          int(58 * _flicker(phase, 0.5, 0.6, 1.2)), clip=(0, 0, W, HEADER_BAND_H))
    _embers(img, 0, 0, W, HEADER_BAND_H, phase, seed=7, n=26)

    kills = (stats or {}).get("kills", 0)
    pulls = (stats or {}).get("pulls", 0)
    deaths = sum(((stats or {}).get("deaths") or {}).values())
    wipes = max(pulls - kills, 0)
    repair = deaths * 57 + pulls * 23   # honest-ish estimate; tune freely

    _draw_plaque(img)

    # --- live widgets (design: rgba(15,16,22,.9), #3a3427, 12px radius) -----
    widgets = [
        (700, 380, "WIPES THIS WEEK", str(wipes), RED if wipes else GREEN,
         f"deaths: {deaths} · personal best: still zero"),
        (1106, 400, "SEASON REPAIR BILL (EST.)", _fmt_g(repair), TEXT,
         "donations welcome · thoughts & prayers accepted"),
        (1532, 330, "“GO AGANE” COUNTER", str(pulls), TEXT,
         "morale: unaffected · copium: stable"),
    ]
    label_f = _font(14, bold=True)
    value_f = _font(52, bold=True)
    sub_f = _font(14)
    for x, w, label, value, vcolor, sub in widgets:
        _alpha_panel(img, (x, 44, x + w, 210), PANEL, 230, 12, outline=PANEL_BORDER)
        _spaced(draw, x + 24, 66, label, label_f, ACCENT, 2)
        draw.text((x + 24, 92), value, font=value_f, fill=vcolor)
        draw.text((x + 24, 172), sub, font=sub_f, fill=MUTED)
    # gold + silver coins beside the repair value
    vw = draw.textlength(_fmt_g(repair), font=value_f)
    gx = int(1106 + 24 + vw + 12)
    draw.ellipse([gx, 124, gx + 18, 142], fill=ACCENT, outline=(138, 100, 32))
    draw.ellipse([gx + 3, 127, gx + 10, 134], fill=(255, 233, 168))
    draw.text((gx + 28, 112), "43", font=_font(30, bold=True), fill=(176, 182, 192))
    sx = gx + 28 + int(draw.textlength("43", font=_font(30, bold=True))) + 8
    draw.ellipse([sx, 128, sx + 13, 141], fill=(176, 182, 192), outline=(106, 112, 124))

    # --- debuff bar: label inline with glowing icons (design row) -----------
    debuffs = [
        ("inv_misc_questionmark", RED, "40"),               # Skill Issue
        ("spell_fire_fire", RED, "6w"),                     # Standing in Fire (Healmates)
        ("inv_misc_bone_humanskull_01", RED, str(deaths)),  # Graveyard Timeshare
        ("spell_nature_sleep", GREEN, "∞"),            # Coping
        ("spell_holy_layonhands", GREEN, "1"),              # Healer Diff
    ]
    lbl = "ACTIVE RAID DEBUFFS"
    lbl_f = _font(13, bold=True)
    _spaced(draw, 700, 288, lbl, lbl_f, (184, 188, 198), 2)
    ix = 700 + int(_spaced_w(draw, lbl, lbl_f, 2)) + 22
    stack_f = _font(16, bold=True)
    for name, border, stack in debuffs:
        box = (ix, 266, ix + 52, 318)
        _rounded_glow(img, box, border, spread=12, alpha=100)
        icon = _fetch_icon(name, 52)
        if icon:
            img.paste(icon, (ix, 266))
        else:
            draw.rectangle(box, fill=(30, 32, 40))
        draw.rounded_rectangle([ix - 2, 264, ix + 54, 320], radius=8, outline=border, width=2)
        sw = draw.textlength(stack, font=stack_f)
        draw.text((ix + 51 - sw, 299), stack, font=stack_f, fill=(0, 0, 0))
        draw.text((ix + 50 - sw, 298), stack, font=stack_f, fill=(255, 255, 255))
        ix += 64

    # --- torch (right:420, blurred flamePulse stack) ------------------------
    tx = W - 455
    _glow(img, tx, 200, 100, 120, (224, 122, 40),
          int(110 * _flicker(phase, 0.15, 0.75, 1.2)), clip=(0, 0, W, HEADER_BAND_H))
    draw.rounded_rectangle([tx - 7, 216, tx + 7, 292], radius=7,
                           fill=(58, 44, 30), outline=(43, 33, 23))
    _flames(img, tx, 226, TORCH_TONGUES, phase, blur=4)

    # --- hanging GIT GUD shingle (signSwing) --------------------------------
    sx0 = W - 96 - 250
    for cxn in (sx0 + 48, sx0 + 202):
        draw.line([cxn, 0, cxn, 74], fill=(42, 33, 22), width=4)
    plank = Image.new("RGBA", (290, 156), (0, 0, 0, 0))
    pd = ImageDraw.Draw(plank)
    # repeating wood stripes: #5a4028 / #4c3520 / #63482d / #45301d
    wood = Image.new("RGB", (250, 116))
    stripes = [(22, (90, 64, 40)), (2, (76, 53, 32)), (22, (99, 72, 45)), (2, (69, 48, 29))]
    yy = 0
    while yy < 116:
        for hgt, col in stripes:
            if yy >= 116:
                break
            ImageDraw.Draw(wood).rectangle([0, yy, 250, min(yy + hgt, 116)], fill=col)
            yy += hgt
    wmask = Image.new("L", (250, 116), 0)
    ImageDraw.Draw(wmask).rounded_rectangle([0, 0, 249, 115], radius=8, fill=255)
    plank.paste(wood, (20, 20), wmask)
    pd.rounded_rectangle([20, 20, 270, 136], radius=8, outline=(43, 33, 23), width=3)
    git_f = _font(44, bold=True, display=True)
    gw = _spaced_w(pd, "GIT GUD", git_f, 4)
    _spaced(pd, 145 - gw / 2, 32, "GIT GUD", git_f, (255, 220, 160, 70), 4)
    _spaced(pd, 145 - gw / 2, 30, "GIT GUD", git_f, (37, 26, 16, 255), 4)
    _spaced_center(pd, 145, 96, "MGMT IS NOT RESPONSIBLE", _font(12, bold=True), (46, 33, 20, 255), 3)
    angle = 1.0 * math.sin(2 * math.pi * phase)
    plank = plank.rotate(angle, resample=Image.BICUBIC, center=(145, 20))
    img.paste(plank, (sx0 - 20, 54), plank)


# ---------------------------------------------------------------- footer ----

RULES_TITLE = "Codex of Conduct"
RULES = [
    ("Binds when you join", TEXT, None),
    ("Guild Charter", TEXT, "Unique"),
    ("+10 Blaming the Healer", TEXT, None),
    ("+5 Ignoring Swirlies", TEXT, None),
    ("Equip: Rule 1 — It is always Healmates' fault.", UNCOMMON, None),
    ("Equip: Rule 2 — The swirly is a suggestion.", UNCOMMON, None),
    ("Equip: Rule 3 — “One more pull” legally means five.", UNCOMMON, None),
    ("Equip: Rule 4 — GBank tab 3 is not your personal bank.", UNCOMMON, None),
    ("“If you die in the fire, you lose DKP we don't track.”", GOLD_TEXT, None),
    ("Requires: Skill (missing)", (255, 32, 32), None),
]

EPITAPHS = [
    "“Found the one-shot. Repeatedly.”",
    "“Died to the same swirly. Times ten.”",
    "“Did the mechanics. Mechanics did him back.”",
    "“The healer. Yes, the healer.”",
]

MOTD_QUIPS = [
    "MORE DOTS. MORE DOTS. … OK STOP DOTS.",
    "That's a 50 DKP MINUS.",
    "Healmates has now stood in the fire for 6 consecutive weeks — a new guild record.",
    "Key depleted? That is a you problem.",
    "At least Leeroy had a plan.",
    "Raid times: Tue/Thu, 8 PM to whenever Rakdisc stops blaming people.",
    "Repair bills are self-inflicted and therefore not reimbursable.",
]

# per-stone geometry from the design: (width, height, arched?, cross?,
# rotation deg, light, mid, dark) — only the second stone bears a cross
STONE_SPECS = [
    (170, 216, True, False, -2.5, (118, 114, 104), (86, 83, 75), (62, 60, 54)),
    (180, 238, False, True, 1.6, (124, 120, 109), (90, 87, 79), (64, 62, 56)),
    (158, 196, True, False, -1.2, (110, 106, 96), (81, 78, 70), (58, 56, 50)),
    (158, 182, False, False, 2.2, (110, 106, 96), (81, 78, 70), (58, 56, 50)),
]


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:3]


def _draw_stone(img, x_center, ground_y, spec, name, count, pulls, epitaph):
    w, h, arched, cross, rot, light, mid, dark = spec
    m = 20
    tile = Image.new("RGBA", (w + 2 * m, h + 2 * m), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    # silhouette
    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    if arched:
        md.ellipse([0, 0, w, min(w, h)], fill=255)
        md.rectangle([0, w // 2, w, h], fill=255)
    else:
        md.rounded_rectangle([0, 0, w - 1, h - 1], radius=14, fill=255)
    grad = _vgrad(w, h, [(0.0, light), (0.55, mid), (1.0, dark)])
    tile.paste(grad, (m, m), mask)
    # top highlight
    hl = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(hl).ellipse([6, 4, w - 6, 40], fill=(255, 255, 255, 26))
    tile.paste(Image.alpha_composite(tile.crop((m, m, m + w, m + h)), hl), (m, m), mask)

    ty = m + (34 if arched else 26)
    scx = m + w // 2
    if cross:
        td.rectangle([scx - 3, ty, scx + 3, ty + 48], fill=(52, 50, 44))
        td.rectangle([scx - 12, ty + 11, scx + 12, ty + 17], fill=(52, 50, 44))
        ty += 56
    else:
        _center(td, scx, ty, "R.I.P.", _font(21, bold=True, display=True), (46, 44, 39))
        ty += 30
    _center(td, scx, ty, name.upper()[:12], _font(19, bold=True), (46, 44, 39))
    ty += 27
    rate = f" · {count / pulls:.1f}/PULL" if pulls else ""
    _center(td, scx, ty, f"{count} DEATHS{rate}", _font(13, bold=True), (70, 63, 46))
    ty += 24
    ep_f = _font(12, italic=True)
    for line in _wrap(td, epitaph, ep_f, w - 26):
        _center(td, scx, ty, line, ep_f, (74, 70, 61))
        ty += 16

    tile = tile.rotate(-rot, resample=Image.BICUBIC, center=(tile.width // 2, tile.height))
    img.paste(tile, (int(x_center - tile.width // 2), int(ground_y - h - m)), tile)


def _tooltip_card(img, draw, x, y0, w, h, border, ring):
    _alpha_panel(img, (x, y0, x + w, y0 + h), (7, 7, 24), 240, 8,
                 outline=border, ring=ring)


def _draw_codex(img, draw, x, y0, w):
    line_h = 31
    h = 52 + 50 + len(RULES) * line_h
    _tooltip_card(img, draw, x, y0, w, h, (67, 67, 92), (52, 52, 76))
    draw.text((x + 30, y0 + 24), RULES_TITLE, font=_font(32, bold=True, display=True), fill=EPIC)
    ty = y0 + 24 + 50
    body_f = _font(20)
    for text, color, right in RULES:
        draw.text((x + 30, ty), text, font=body_f, fill=color)
        if right:
            rw = draw.textlength(right, font=body_f)
            draw.text((x + w - 30 - rw, ty), right, font=body_f, fill=color)
        ty += line_h
    return h


def _item_card(img, draw, x, y0, w, item, title):
    """Guild Item of the Month card — lives where the recruiting poster
    used to hang. Swap assets/item_art.png monthly for a rotating gag."""
    pad, title_h = 30, 62
    if item is not None:
        scale = min((w - 2 * pad) / item.width, 360 / item.height, 1.0)
        iw, ih = max(int(item.width * scale), 1), max(int(item.height * scale), 1)
    else:
        iw, ih = 0, 110
    card_h = title_h + ih + pad + 6
    _tooltip_card(img, draw, x, y0, w, card_h, (92, 74, 46), (76, 60, 34))
    draw.text((x + pad, y0 + 22), title, font=_font(32, bold=True, display=True), fill=LEGENDARY)
    if item is not None:
        scaled = item.resize((iw, ih), Image.LANCZOS)
        ix = x + (w - iw) // 2
        img.paste(scaled, (ix, y0 + title_h))
        draw.rounded_rectangle([ix - 2, y0 + title_h - 2, ix + iw + 2, y0 + title_h + ih + 2],
                               radius=6, outline=(150, 122, 62), width=2)
    else:
        _center(draw, x + w // 2, y0 + title_h + 38, "New item arriving soon™",
                _font(20), MUTED)
    return card_h


def draw_footer_band(img, y, stats=None, week_index=0, phase=0.0,
                     item_art=None, item_art_title="GUILD ITEM OF THE MONTH",
                     week_label=None):
    W = img.width
    draw = ImageDraw.Draw(img)
    art_h = FOOTER_ART_H_DESIGN
    wall = _load(ASSET_DIR / "wall_footer.png")
    if wall:
        # the design shows the top 520px slice of the 572px wall art
        full = wall.resize((W, 572), Image.LANCZOS)
        img.paste(full.crop((0, 0, W, art_h)), (0, y))
    else:
        draw.rectangle([0, y, W, y + art_h], fill=(34, 27, 21))
    _glow(img, W // 2, y + art_h + 60, int(W * 0.45), 200, (58, 220, 90),
          int(34 * _flicker(phase, 0.4, 0.6, 1.2)), clip=(0, y, W, y + art_h))
    _embers(img, 0, y, W, y + art_h, phase, seed=11, n=22)

    # --- left: codex tooltip, right: item of the month ----------------------
    codex_h = 52 + 50 + len(RULES) * 31
    _draw_codex(img, draw, 60, y + (art_h - codex_h) // 2, 600)
    if item_art is None:
        item_art = _load(ASSET_DIR / "item_art.png")
    pad, title_h = 30, 62
    if item_art is not None:
        scale = min((600 - 2 * pad) / item_art.width, 360 / item_art.height, 1.0)
        card_h = title_h + max(int(item_art.height * scale), 1) + pad + 6
    else:
        card_h = title_h + 110 + pad + 6
    _item_card(img, draw, W - 60 - 600, y + (art_h - card_h) // 2, 600,
               item_art, item_art_title)

    # --- graveyard campers memorial (1080x390, centered) --------------------
    mw, mh = 1080, 390
    mx0 = W // 2 - mw // 2
    mx1 = mx0 + mw
    fy = y + (art_h - mh) // 2 + 14
    title = "GRAVEYARD CAMPERS MEMORIAL"
    if week_label:
        title += f" · WEEK OF {week_label.upper()}"
    _spaced_center(draw, W // 2, fy - 32, title, _font(15, bold=True), ACCENT, 4)

    # box: outer ring + gold border + night-sky gradient
    draw.rounded_rectangle([mx0 - 1, fy - 1, mx1 + 1, fy + mh + 1], radius=11,
                           outline=(45, 48, 58), width=1)
    grad = _vgrad(mw, mh, [(0.0, (13, 15, 20)), (0.55, (19, 23, 32)), (1.0, (16, 19, 12))])
    gmask = Image.new("L", (mw, mh), 0)
    ImageDraw.Draw(gmask).rounded_rectangle([0, 0, mw - 1, mh - 1], radius=10, fill=255)
    img.paste(grad, (mx0, fy), gmask)
    draw.rounded_rectangle([mx0, fy, mx1, fy + mh], radius=10, outline=(150, 122, 62), width=3)

    inner = (mx0 + 3, fy + 3, mx1 - 3, fy + mh - 3)
    _glow(img, (mx0 + mx1) // 2, fy + mh + 40, int(mw * 0.55), 190, (58, 220, 90),
          int(64 * _flicker(phase, 0.66, 0.8, 1.2)), clip=inner)
    # souls of the fallen drift up between the tombstones
    _embers(img, mx0 + 20, fy + 16, mx1 - 20, fy + mh - 12, phase,
            seed=9, n=16, color=(182, 255, 176))
    # ground fog
    fog = Image.new("RGBA", (mw - 6, 74), (0, 0, 0, 0))
    for row in range(74):
        t = row / 73
        col = (23, 26, 16) if t < 0.55 else (14, 16, 9)
        a = int(255 * min(t / 0.4, 1.0))
        ImageDraw.Draw(fog).rectangle([0, row, mw - 6, row], fill=col + (a,))
    img.paste(Image.alpha_composite(
        img.crop((inner[0], fy + mh - 3 - 74, inner[2], fy + mh - 3)).convert("RGBA"),
        fog).convert("RGB"), (inner[0], fy + mh - 3 - 74))

    ranked = sorted(((stats or {}).get("deaths") or {}).items(), key=lambda kv: kv[1], reverse=True)[:4]
    if not ranked:
        ranked = [("Nobody", 0)]
    pulls = (stats or {}).get("pulls", 0)
    ground = fy + mh - 26
    gap = 38
    widths = [STONE_SPECS[i % len(STONE_SPECS)][0] for i in range(len(ranked))]
    total = sum(widths) + 190 + gap * len(ranked)
    sx = (mx0 + mx1) // 2 - total // 2
    for i, (name, count) in enumerate(ranked):
        spec = STONE_SPECS[i % len(STONE_SPECS)]
        _draw_stone(img, sx + spec[0] // 2, ground, spec, name, count, pulls,
                    EPITAPHS[i % len(EPITAPHS)])
        sx += spec[0] + gap

    # campfire plot
    ccx = sx + 95
    _glow(img, ccx, ground - 20, 95, 80, (224, 122, 40),
          int(120 * _flicker(phase, 0.05, 0.75, 1.2)), clip=inner)
    for ang, off in ((-14, -32), (14, 32)):
        log = Image.new("RGBA", (76, 26), (0, 0, 0, 0))
        ImageDraw.Draw(log).rounded_rectangle([6, 7, 70, 19], radius=6, fill=(74, 53, 32))
        log = log.rotate(ang, resample=Image.BICUBIC)
        img.paste(log, (int(ccx + off - 38), int(ground - 16)), log)
    _flames(img, ccx, ground - 8, CAMPFIRE_TONGUES, phase, blur=3)
    draw.rounded_rectangle([ccx - 78, ground + 4, ccx + 78, ground + 32], radius=6,
                           fill=(58, 44, 26), outline=(33, 24, 9), width=2)
    _spaced_center(draw, ccx, ground + 10, "RESERVED: HEALMATES", _font(13, bold=True), (217, 196, 154), 1)
    _center(draw, ccx, ground + 38, "6 consecutive weeks in the fire", _font(12, italic=True), (125, 130, 144))

    _center(draw, (mx0 + mx1) // 2, fy + mh + 12,
            "Plots assigned by deaths-per-pull. The campfire is load-bearing.",
            _font(16, italic=True), MUTED)

    # --- MOTD strip ---------------------------------------------------------
    sy = y + art_h
    draw.rectangle([0, sy, W, sy + MOTD_H], fill=(13, 14, 19))
    draw.line([0, sy, W, sy], fill=(45, 48, 58), width=1)
    chip_f = _font(15, bold=True)
    chip_w = 24 + int(_spaced_w(draw, "MOTD", chip_f, 3)) + 24
    draw.rectangle([0, sy, chip_w, sy + MOTD_H], fill=(26, 28, 35))
    draw.line([chip_w, sy, chip_w, sy + MOTD_H], fill=(45, 48, 58), width=1)
    _spaced(draw, 24, sy + 17, "MOTD", chip_f, ACCENT, 3)
    quip = MOTD_QUIPS[week_index % len(MOTD_QUIPS)]
    draw.text((chip_w + 26, sy + 14), quip, font=_font(19), fill=ACCENT)

    # --- credits bar --------------------------------------------------------
    cy = sy + MOTD_H
    draw.rectangle([0, cy, W, cy + CREDITS_H], fill=(11, 12, 16))
    draw.text((36, cy + 11), "“Git Gud.” — ancient guild proverb",
              font=_font(14), fill=FAINT)

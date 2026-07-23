#!/usr/bin/env python3
"""Assemble the 10x3 labeled model-quality comparison grid:
Blizzard Render | Nano Banana Pro Edit | Nano Banana Edit (cheap)
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = REPO_ROOT / "cast" / "_rnd_img2img" / "model_bakeoff_v2" / "inputs"
OUT_DIR = REPO_ROOT / "cast" / "_rnd_img2img" / "model_bakeoff_v2" / "outputs"
DEST = Path(
    r"C:\Users\zachf\OneDrive\Documents\WoW Server Stuff\Diven WoW Guild Board"
    r"\WoW_Skill_Issues_Guild_Board\previews\model_comparison_grid.png"
)

ROWS = [
    ("rakdisc-proudmoore", "Rakdisc — Nightborne Priest (cloth) [pilot]"),
    ("floofwall-queldorei", "Floofwall — Pandaren Monk (leather) [pilot]"),
    ("healyeah-queldorei", "Healyeah — Dracthyr Evoker (mail) [pilot]"),
    ("balcmeg-queldorei", "Balcmeg — Mag'har Orc Warrior (plate)"),
    ("jilk-eldrethalas", "Jilk — Draenei Shaman (mail)"),
    ("mushabi-anubarak", "Mushabi — Orc Rogue (leather)"),
    ("beroben-emerald-dream", "Beroben — Gnome Mage (cloth)"),
    ("kathrobbin-zuljin", "Kathrobbin — Blood Elf Paladin (plate)"),
    ("yur-whisperwind", "Yur — Night Elf Demon Hunter (leather)"),
    ("flemel-area-52", "Flemel — Troll Warlock (cloth)"),
]

CELL_W = 420
CELL_H = 560
GAP = 10
MARGIN = 24
ROW_LABEL_H = 40
HEADER_H = 64
TITLE_H = 56

COL_HEADERS = [
    "Blizzard Render (source)",
    "Nano Banana PRO Edit  (~$0.14)",
    "Nano Banana Edit  (~$0.038)",
]

BG = (24, 24, 28)
FG = (240, 240, 240)
SUBFG = (190, 190, 195)
ROWBAND = (40, 40, 46)


def load_font(size, bold=False):
    candidates = [
        "arialbd.ttf" if bold else "arial.ttf",
        "segoeuib.ttf" if bold else "segoeui.ttf",
    ]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def fit(im, w, h):
    im = im.convert("RGB")
    src_ratio = im.width / im.height
    dst_ratio = w / h
    if src_ratio > dst_ratio:
        new_h = h
        new_w = int(h * src_ratio)
    else:
        new_w = w
        new_h = int(w / src_ratio)
    im = im.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - w) // 2
    top = (new_h - h) // 2
    return im.crop((left, top, left + w, top + h))


def main():
    n = len(ROWS)
    total_w = MARGIN * 2 + CELL_W * 3 + GAP * 2
    total_h = (
        MARGIN * 2
        + TITLE_H
        + HEADER_H
        + n * (ROW_LABEL_H + CELL_H + GAP)
    )
    canvas = Image.new("RGB", (total_w, total_h), BG)
    draw = ImageDraw.Draw(canvas)

    title_font = load_font(30, bold=True)
    header_font = load_font(20, bold=True)
    row_font = load_font(20, bold=True)

    draw.text(
        (MARGIN, MARGIN),
        "Model Quality Comparison — Nano Banana Pro vs. Standard (bold-ink anime restyle)",
        font=title_font,
        fill=FG,
    )

    y = MARGIN + TITLE_H
    col_x = [MARGIN + i * (CELL_W + GAP) for i in range(3)]
    for i, header in enumerate(COL_HEADERS):
        bbox = draw.textbbox((0, 0), header, font=header_font)
        tw = bbox[2] - bbox[0]
        draw.text(
            (col_x[i] + (CELL_W - tw) / 2, y + (HEADER_H - 24) / 2),
            header,
            font=header_font,
            fill=SUBFG,
        )
    y += HEADER_H

    for entry, label in ROWS:
        draw.rectangle([MARGIN, y, MARGIN + CELL_W * 3 + GAP * 2, y + ROW_LABEL_H - 6], fill=ROWBAND)
        draw.text((MARGIN + 10, y + 6), label, font=row_font, fill=FG)
        y += ROW_LABEL_H

        render_im = Image.open(INPUT_DIR / f"{entry}.png")
        pro_im = Image.open(OUT_DIR / f"{entry}_pro.png")
        cheap_im = Image.open(OUT_DIR / f"{entry}_cheap.png")

        for i, im in enumerate((render_im, pro_im, cheap_im)):
            cell = fit(im, CELL_W, CELL_H)
            canvas.paste(cell, (col_x[i], y))
            draw.rectangle(
                [col_x[i], y, col_x[i] + CELL_W, y + CELL_H],
                outline=(70, 70, 76),
                width=1,
            )
        y += CELL_H + GAP

    DEST.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(DEST)
    print(f"Saved: {DEST}  ({canvas.size[0]}x{canvas.size[1]})")


if __name__ == "__main__":
    main()

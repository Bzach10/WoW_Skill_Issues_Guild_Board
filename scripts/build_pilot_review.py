"""Build a single side-by-side review image from cast_manifest.json entries
— for handing a batch of freshly generated characters to Zach for QA
(style consistency + individual quality) before scaling up.

Usage: python scripts/build_pilot_review.py [slug ...]
       (defaults to the 3 pilots if no slugs given)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from guild_board.cast_manifest import load_manifest  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SLUGS = ["rakdisc-proudmoore", "floofwall-queldorei", "healyeah-queldorei"]

BG_COLOR = (235, 235, 232)
PANEL_W, PANEL_H = 832, 1216
GUTTER = 50
TOP_MARGIN = 90
LABEL_BLOCK_H = 130
TITLE_TEXT = "Cast Pilot Review — One Piece Style"

FONT_DIR = Path(r"C:\Windows\Fonts")


def _font(name, size):
    try:
        return ImageFont.truetype(str(FONT_DIR / name), size)
    except OSError:
        return ImageFont.load_default()


def _center_text(draw, cx, y, text, font, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    draw.text((cx - w / 2, y), text, font=font, fill=fill)


def build_review(slugs, out_path):
    manifest = load_manifest()
    n = len(slugs)
    width = GUTTER + n * (PANEL_W + GUTTER)
    height = TOP_MARGIN + PANEL_H + LABEL_BLOCK_H

    canvas = Image.new("RGB", (width, height), BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    title_font = _font("arialbd.ttf", 42)
    name_font = _font("arialbd.ttf", 34)
    detail_font = _font("arial.ttf", 26)

    _center_text(draw, width / 2, 24, TITLE_TEXT, title_font, (40, 40, 40))

    for i, slug in enumerate(slugs):
        char = manifest["characters"].get(slug)
        if char is None:
            raise KeyError(f"{slug} not found in cast_manifest.json")

        board_rel = char["styles"]["one_piece"]["board"]
        board_path = REPO_ROOT / board_rel
        panel = Image.open(board_path).convert("RGBA")

        x = GUTTER + i * (PANEL_W + GUTTER)
        y = TOP_MARGIN
        canvas.paste(panel, (x, y), panel)

        cx = x + PANEL_W / 2
        label_y = TOP_MARGIN + PANEL_H + 14
        _center_text(draw, cx, label_y, char["name"], name_font, (30, 30, 30))

        detail = f"{char['race']} {char['class']} — {char['spec']}"
        _center_text(draw, cx, label_y + 46, detail, detail_font, (80, 80, 80))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    return str(out_path)


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    slugs = argv if argv else DEFAULT_SLUGS
    out_path = REPO_ROOT / "previews" / "pilot_review_lineup.png"
    saved = build_review(slugs, out_path)
    print(f"saved {saved}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

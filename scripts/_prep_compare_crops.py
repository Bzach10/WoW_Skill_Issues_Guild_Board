#!/usr/bin/env python3
"""Crop cached Blizzard renders to a 3:4 portrait box centered on the
character, for the nano-banana model-quality comparison. Writes to
cast/_rnd_img2img/model_bakeoff_v2/inputs/<entry>.png
"""
from pathlib import Path
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "cast" / "_renders_cache"
OUT_DIR = REPO_ROOT / "cast" / "_rnd_img2img" / "model_bakeoff_v2" / "inputs"

ENTRIES = [
    "rakdisc-proudmoore",
    "floofwall-queldorei",
    "healyeah-queldorei",
    "balcmeg-queldorei",
    "jilk-eldrethalas",
    "mushabi-anubarak",
    "beroben-emerald-dream",
    "kathrobbin-zuljin",
    "yur-whisperwind",
    "flemel-area-52",
]


def bbox_of_content(im, bg_thresh=245):
    gray = im.convert("L")
    px = gray.load()
    w, h = gray.size
    left, top, right, bottom = w, h, 0, 0
    # sample every 2px for speed
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            if px[x, y] < bg_thresh:
                if x < left:
                    left = x
                if x > right:
                    right = x
                if y < top:
                    top = y
                if y > bottom:
                    bottom = y
    return left, top, right, bottom


def crop_3x4(im):
    w, h = im.size
    left, top, right, bottom = bbox_of_content(im)
    cx = (left + right) / 2
    cy = (top + bottom) / 2
    content_h = bottom - top
    # pad content height by 12% top/bottom for breathing room, then
    # clamp to source bounds and re-derive the other side to hold 3:4
    target_h = min(content_h * 1.24, h)
    target_w = target_h * 3 / 4
    if target_w > w:
        target_w = w
        target_h = target_w * 4 / 3

    x0 = cx - target_w / 2
    x1 = cx + target_w / 2
    y0 = cy - target_h / 2
    y1 = cy + target_h / 2

    if x0 < 0:
        x1 -= x0
        x0 = 0
    if x1 > w:
        x0 -= (x1 - w)
        x1 = w
    if y0 < 0:
        y1 -= y0
        y0 = 0
    if y1 > h:
        y0 -= (y1 - h)
        y1 = h

    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    return im.crop((int(x0), int(y0), int(x1), int(y1)))


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for entry in ENTRIES:
        src = SRC_DIR / f"{entry}.png"
        raw = Image.open(src)
        if raw.mode in ("RGBA", "LA") or "transparency" in raw.info:
            raw = raw.convert("RGBA")
            white_bg = Image.new("RGB", raw.size, (255, 255, 255))
            white_bg.paste(raw, mask=raw.split()[-1])
            im = white_bg
        else:
            im = raw.convert("RGB")
        cropped = crop_3x4(im)
        out_path = OUT_DIR / f"{entry}.png"
        cropped.save(out_path)
        print(f"{entry}: {im.size} -> {cropped.size} ({cropped.size[0]/cropped.size[1]:.3f})")


if __name__ == "__main__":
    main()

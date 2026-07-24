#!/usr/bin/env python3
"""Verify the paper-doll idle rig is actually moving, and capture it.

Produces:
  previews/idle_loop.gif          the crew breathing, one full loop
  previews/doll_assembled.png     one assembled character, close up
  previews/doll_layer_stack.png   that character's layers, exploded

Usage:
  python scripts/capture_idle.py --page crew_board_doll.html
"""

import argparse
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "previews"

# 3.4s idle loop; 17 frames at 200ms covers it with room to spare.
FRAMES = 17
FRAME_MS = 200


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", default="crew_board_doll.html")
    args = ap.parse_args()
    page_path = ROOT / args.page
    if not page_path.exists():
        sys.exit(f"{page_path} not found — render it first.")
    OUT.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720},
                                device_scale_factor=1)
        page.goto(page_path.as_uri(), wait_until="domcontentloaded")
        page.wait_for_timeout(1200)

        # Bring the stage into view so the idle rig is unpaused.
        page.evaluate("document.querySelector('.stage').scrollIntoView({block:'center'})")
        page.wait_for_timeout(700)

        # --- prove the bones actually move -------------------------------
        motion = page.evaluate("""async () => {
            const m = [...document.querySelectorAll('.member')]
                .find(x => x.querySelector('.doll[data-mode="layered"]'))
                || document.querySelector('.member');
            const pick = sel => m.querySelector(sel);
            const targets = {
                doll: pick('.doll'),
                arms: pick('.bone[data-bone="arms"]'),
                head: pick('.bone[data-bone="head"]'),
                cloak: pick('.bone[data-bone="cloak"]'),
                weapon: pick('.bone[data-bone="weapon_main"]'),
            };
            const seen = {};
            for (const k in targets) seen[k] = new Set();
            for (let i = 0; i < 12; i++) {
                for (const k in targets) {
                    if (targets[k]) seen[k].add(getComputedStyle(targets[k]).transform);
                }
                await new Promise(s => setTimeout(s, 150));
            }
            const out = {idle: m.dataset.idle || 'playing'};
            for (const k in seen) out[k] = seen[k].size;
            return out;
        }""")
        print("distinct transform frames per bone:", motion)
        moving = [k for k, v in motion.items()
                  if k != "idle" and isinstance(v, int) and v > 1]
        if not moving:
            print("WARNING: nothing animated — the rig is not running.")
        else:
            print("animating:", ", ".join(sorted(moving)))

        # --- capture the loop --------------------------------------------
        stage = page.query_selector(".stage")
        frames = []
        for i in range(FRAMES):
            shot = OUT / f"_idle_{i:02d}.png"
            stage.screenshot(path=str(shot))
            frames.append(Image.open(shot).convert("RGB"))
            page.wait_for_timeout(FRAME_MS)

        # Halve it — a 1280px-wide GIF is needlessly heavy for a preview.
        frames = [f.resize((f.width // 2, f.height // 2), Image.LANCZOS)
                  for f in frames]
        frames[0].save(OUT / "idle_loop.gif", save_all=True,
                       append_images=frames[1:], duration=FRAME_MS,
                       loop=0, optimize=True)
        print("wrote", OUT / "idle_loop.gif")
        for i in range(FRAMES):
            (OUT / f"_idle_{i:02d}.png").unlink(missing_ok=True)

        # --- one assembled character, close up ---------------------------
        member = page.query_selector(".member .doll[data-mode='layered']") \
            or page.query_selector(".member .doll")
        member.screenshot(path=str(OUT / "doll_assembled.png"))
        print("wrote", OUT / "doll_assembled.png")

        # --- the same character, layers exploded --------------------------
        srcs = page.evaluate("""() => {
            const d = document.querySelector(".doll[data-mode='layered']")
                   || document.querySelector('.doll');
            return [...d.querySelectorAll('.bone')].map(b => ({
                slot: b.dataset.slot, src: b.getAttribute('src')}));
        }""")
        _explode(srcs, OUT / "doll_layer_stack.png")
        print("wrote", OUT / "doll_layer_stack.png")

        browser.close()


def _explode(srcs, out_path):
    """Lay each layer out side by side, then the assembled result."""
    tiles = []
    for entry in srcs:
        path = ROOT / entry["src"]
        if not path.exists():
            continue
        img = Image.open(path).convert("RGBA")
        img.thumbnail((190, 280))
        tiles.append((entry["slot"], img))
    if not tiles:
        return

    composite = None
    for entry in srcs:
        path = ROOT / entry["src"]
        if not path.exists():
            continue
        layer = Image.open(path).convert("RGBA")
        composite = layer if composite is None else Image.alpha_composite(composite, layer)
    if composite is not None:
        composite.thumbnail((190, 280))
        tiles.append(("ASSEMBLED", composite))

    pad, label_h = 14, 18
    w = (190 + pad) * len(tiles) + pad
    h = 280 + label_h * 2 + pad * 2
    sheet = Image.new("RGBA", (w, h), (24, 15, 40, 255))
    from PIL import ImageDraw
    draw = ImageDraw.Draw(sheet)
    x = pad
    for slot, img in tiles:
        sheet.alpha_composite(img, (x + (190 - img.width) // 2, pad + label_h))
        draw.text((x + 4, pad - 2), slot, fill=(216, 162, 74, 255))
        x += 190 + pad
    sheet.convert("RGB").save(out_path)


if __name__ == "__main__":
    main()

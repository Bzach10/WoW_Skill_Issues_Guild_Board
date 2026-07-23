"""Side-by-side: a character's REAL Blizzard transmog vs our paper-doll.

This is a decision artifact, not a progress shot. The question it exists
to answer is whether the archetype-based paper-doll can plausibly read as
a specific person's character — so it puts the two images at the same
height, on the same neutral field, with no flattering crops.

    python scripts/overnight/compare_transmog.py <real.png> <doll.png> <out.png>
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

PANEL_H = 900
PAD = 40
LABEL_H = 54
CAPTION_H = 230
BG = (26, 22, 34)
FG = (232, 228, 240)
DIM = (150, 142, 168)
ACCENT = (232, 176, 96)


def _font(size, bold=False):
    for name in (("arialbd.ttf", "segoeuib.ttf") if bold
                 else ("arial.ttf", "segoeui.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _trim(path, tol=8):
    """Crop to the subject, whatever the backdrop is (alpha or flat colour)."""
    im = Image.open(path).convert("RGBA")
    a = np.asarray(im)
    alpha = a[..., 3]
    if (alpha < 250).mean() > 0.02:          # has real transparency
        mask = alpha > 24
    else:                                     # flat backdrop: key the corner
        rgb = a[..., :3].astype(int)
        corner = np.median(np.concatenate([
            rgb[:8, :8].reshape(-1, 3), rgb[:8, -8:].reshape(-1, 3)]), axis=0)
        mask = np.abs(rgb - corner).sum(axis=2) > tol * 3
    ys, xs = np.nonzero(mask)
    if not len(ys):
        return im
    return im.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))


def _fit(im, h):
    w = max(1, int(im.width * h / im.height))
    return im.resize((w, h), Image.LANCZOS)


def build(panels, out_path, title, notes):
    """panels: [(path, label, colour), ...] — rendered left to right."""
    imgs = [(_fit(_trim(p), PANEL_H), label, colour)
            for p, label, colour in panels]

    panel_w = max(im.width for im, _, _ in imgs) + PAD
    n = len(imgs)
    total_w = panel_w * n + PAD * (n + 1)
    total_h = LABEL_H + PANEL_H + PAD * 2 + CAPTION_H + 30

    canvas = Image.new("RGB", (total_w, total_h), BG)
    d = ImageDraw.Draw(canvas)
    f_title, f_label = _font(30, True), _font(21, True)
    f_note, f_head = _font(19), _font(20, True)

    d.text((PAD, 16), title, font=f_title, fill=FG)

    top = LABEL_H + 22
    for i, (im, label, colour) in enumerate(imgs):
        x0 = PAD + i * (panel_w + PAD)
        d.rectangle([x0, top - 4, x0 + panel_w, top + PANEL_H + 8],
                    outline=(58, 52, 72))
        d.text((x0 + 10, top - 32), label, font=f_label, fill=colour)
        canvas.paste(im, (x0 + (panel_w - im.width) // 2, top), im)

    cy = top + PANEL_H + 30
    d.text((PAD, cy), "What does not match", font=f_head, fill=ACCENT)
    cy += 30
    for note in notes:
        d.text((PAD + 8, cy), f"•  {note}", font=f_note, fill=DIM)
        cy += 26

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    return out_path


MORNING_NOTES = [
    "FIXED  headgear slot (z=65, from the frontend's contract update) — her mitre now renders ABOVE the face",
    "FIXED  props authored on a SQUARE canvas, so the mitre is no longer stretched by the 832x1216 body frame",
    "FIXED  weapon slots populated — holy fire and orb, placed at MEASURED hand positions, not canvas fractions",
    "FIXED  crimson enters the palette (was pure white/gold), driven from her real transmog's extracted colours",
    "",
    "STILL OFF — honest list, all visible above:",
    "  - robe is cream-dominant; hers is CRIMSON-dominant with a cream front panel",
    "  - silhouette is a floor-length gown with a train; hers is a knee-length tabard over legs",
    "  - still barefoot; hers has pale spiral-cuffed boots",
    "  - mitre reads tall/narrow like a tiara rather than her rounded mitre, and sits slightly high",
    "  - no distinct shoulder pauldrons; hers are structured red-and-gold",
    "  - face is still the shared base face, not derived from her character",
    "",
    "ROOT CAUSE of the silhouette gap: ControlNet conditions on the base body's edges, so the garment",
    "cannot depart from that outline. Measured tradeoff — strength 0.85 holds registration (head IoU 0.965)",
    "but forbids new shapes; strength 0.45 permits them but drifts the head 19px and breaks layer alignment.",
    "Fixing this needs a robe-shaped conditioning source per archetype, not a prompt change.",
]

NOTES = [
    "PALETTE  real is crimson + cream + gold; the archetype is plain white + gold. Red absent entirely.",
    "HEAD     real wears a tall gold bishop's mitre. Archetype is bare-headed — 'head' is never generated.",
    "HANDS    real holds holy fire + a glowing orb. Archetype has none — 'weapon_main'/'weapon_off' never generated.",
    "FEET     real wears pale spiral-cuffed boots. Archetype is barefoot.",
    "SHAPE    real is a knee-length layered tabard over legs. Archetype is a floor-length gown with a train.",
    "FACE     archetype face comes from the shared base body; nothing about it is derived from her character.",
    "",
    "PANEL 3 is the hero-prop experiment: her actual mitre, generated as a standalone prop and placed on the",
    "head slot. It proves props generate and composite cleanly — and exposes two blockers: the contract puts",
    "face (z=61) ABOVE head (z=60), so an opaque face layer occludes headgear; and props rendered on the tall",
    "832x1216 canvas come out stretched. Both are fixable, neither is a prompt problem.",
]


def main(argv):
    out = "cast/_review/rakdisc_fidelity_options.png"
    panels = [
        ("cast/rakdisc/_real_transmog_reference.png",
         "1. REAL — Blizzard transmog", FG),
        ("cast/rakdisc-proudmoore/one_piece/composite.png",
         "2. ARCHETYPE ONLY — what we ship today", ACCENT),
        ("cast/_hero_test/composite.png",
         "3. + HERO PROP — her actual mitre", (150, 210, 150)),
    ]
    path = build(panels, out,
                 "Rakdisc — how close can the paper-doll get?", NOTES)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

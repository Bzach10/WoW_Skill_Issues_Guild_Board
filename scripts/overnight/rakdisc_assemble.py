"""Assemble the gear-accurate Rakdisc against the UPDATED layer contract.

Uses the frontend's new slots:
    headgear (z=65)  above face, so a mitre is no longer occluded
    weapon_main/off  props placed at their contract grip pivots

The headgear render came back as a full bust rather than an isolated
object (the prompt's "no character" negative did not hold), so it is
cropped to the mitre before placement. Cropping a good render beats
re-rolling a prompt that already produced the right design.
"""

import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compose import DEFAULT_PIVOT, render as compose_render  # noqa: E402
from engine import log  # noqa: E402
from hero import place_prop  # noqa: E402
from layers import extract_layers, write_layers  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "cast" / "rakdisc-proudmoore" / "one_piece"
PROPS = REPO / "cast" / "_props" / "rakdisc"
BASE = REPO / "cast" / "_approved" / "rakdisc-proudmoore" / "_source_body.png"
GEAR = REPO / "cast" / "_props" / "rakdisc_gear_raw.png"

CANVAS_W, CANVAS_H = 832, 1216

# The mitre occupies roughly the top two-thirds of its 1024 render, above
# the shoulders the model added unbidden.
MITRE_CROP = (295, 0, 700, 745)


def measure(body_png):
    """Read anatomy off the body art rather than assuming canvas fractions.

    Every race sits differently in the frame — a pandaren's hands are not
    where a nightborne's are — so props are placed against measured
    landmarks, which generalises without per-character tuning.
    """
    import numpy as np
    alpha = np.asarray(Image.open(body_png).convert("RGBA"))[..., 3] > 24
    ys, xs = np.nonzero(alpha)
    top = int(ys.min())

    # Head centre: median x across the first band below the crown.
    head_band = alpha[top:top + 120]
    hys, hxs = np.nonzero(head_band)
    head_cx = int(np.median(hxs)) if len(hxs) else alpha.shape[1] // 2

    # Brow: far enough down the skull to clear the hair, high enough to
    # leave the face visible. ~62% of the way through the head band.
    brow_y = top + int(120 * 0.62)

    # Hands: the widest extremes in the band where arms hang free.
    band = alpha[int(alpha.shape[0] * 0.48):int(alpha.shape[0] * 0.57)]
    bys, bxs = np.nonzero(band)
    if len(bxs):
        hand_y = int(alpha.shape[0] * 0.52)
        hand_l = (int(bxs.min()) + 6, hand_y)
        hand_r = (int(bxs.max()) - 6, hand_y)
    else:
        hand_l, hand_r = (int(alpha.shape[1] * 0.35), 630), \
                         (int(alpha.shape[1] * 0.65), 630)

    return {"head_top": top, "head_cx": head_cx, "brow_y": brow_y,
            "hand_l": hand_l, "hand_r": hand_r}


def crop_mitre(src, dest):
    im = Image.open(src).convert("RGB").crop(MITRE_CROP)
    im.save(dest)
    return dest


def main():
    log("=" * 62)
    log("RAKDISC ASSEMBLE — updated contract (headgear z=65, prop slots)")

    # 1. Body + garment layers from the robe render.
    layers = extract_layers(BASE, GEAR)
    written = write_layers(layers, OUT)
    log(f"  garment layers: {', '.join(sorted(written))}")

    # 2. Headgear on the crown, stopping at the brow.
    #
    # The contract's default headgear pivot is a generic fraction of the
    # canvas; anchoring the ART there put a 250px mitre straight over her
    # face. Now that headgear sits ABOVE face (z=65), covering the face is
    # a real failure mode rather than a harmless overlap — so placement is
    # measured off the body art: crown at y=100, brow at ~175.
    anatomy = measure(OUT / "body.png")
    mitre = crop_mitre(PROPS / "headgear_raw.png", PROPS / "_headgear_crop.png")
    place_prop(mitre, OUT / "headgear.png",
               anchor=(anatomy["head_cx"], anatomy["brow_y"]), height_px=160)
    log(f"  headgear -> headgear.png (crown->brow, "
        f"cx={anatomy['head_cx']} brow={anatomy['brow_y']})")

    # 3. Weapons in her HANDS, not at the generic canvas pivots. The
    #    contract pivot is where a weapon ROTATES, which is not the same
    #    point as where this character's hand happens to be.
    hands = ((("weapon_main", 170), anatomy["hand_r"]),
             (("weapon_off", 140), anatomy["hand_l"]))
    for (slot, height), (hx, hy) in hands:
        src = PROPS / f"{slot}_raw.png"
        if not src.exists():
            log(f"  {slot}: missing render, skipping", "WARN")
            continue
        place_prop(src, OUT / f"{slot}.png",
                   anchor=(hx, hy + height // 2), height_px=height)
        log(f"  {slot} -> {slot}.png at hand ({hx}, {hy})")

    # 4. Composite + idle preview.
    still, gif, slots = compose_render(OUT, OUT)
    log(f"  layers composited: {', '.join(slots)}")
    log(f"  still -> {still}")
    log(f"  gif   -> {gif}")
    log("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())

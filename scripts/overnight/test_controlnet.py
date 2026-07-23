"""Does ControlNet render the gear AND hold the pose?

The two failure modes are opposite, so we measure both rather than
trusting either alone:

  * gear missing  -> silhouette barely differs from the base (the img2img
                     failure: high IoU, no robe)
  * pose drifted  -> silhouette differs wildly (alignment lost)

The sweet spot is a MIDDLE IoU: robe present, body underneath unmoved.
So IoU alone cannot score this — we also measure how much NEW area the
render added below the neck, which is where a robe should appear.
"""
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import (ComfyClient, collect_outputs, controlnet_graph, log,  # noqa: E402
                    stage_input)
from test_align import drift, silhouette  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
BASE = REPO / "cast" / "_sweeps" / "body_lora40.png"
OUT = REPO / "cast" / "_sweeps"

ROBE_POS = (
    "one piece anime style, cel shaded, clean bold lineart, "
    "full body single character, standing straight front view, "
    "slender elven woman, lavender purple skin, glowing golden eyes, "
    "white hair in a tight neat bun, "
    "wearing a long flowing white and gold priest robe, "
    "wide draping sleeves, layered cloth skirt down to the floor, "
    "gold trim, holy vestments, ornate embroidery, "
    "full body head to feet, flat plain light grey background, "
    "even flat lighting, no shadow"
)
ROBE_NEG = (
    "cropped, cut off, out of frame, close-up, nude, bare legs, "
    "leotard, swimsuit, skin tight, "
    "multiple characters, weapon, staff, background scenery, text, "
    "watermark, blurry, extra limbs, dynamic pose, tilted, perspective"
)


def added_area(base_mask, new_mask):
    """Fraction of the canvas that is gear-not-body, below the head."""
    h = base_mask.shape[0]
    below_neck = slice(int(h * 0.22), h)
    added = np.logical_and(new_mask[below_neck], ~base_mask[below_neck]).sum()
    return added / base_mask[below_neck].size


def main():
    client = ComfyClient()
    staged = stage_input(BASE, "overnight_base_body.png")
    base_mask = silhouette(BASE)
    log("=== CONTROLNET TEST: does the robe render AND stay aligned? ===")

    for strength, endp in ((0.85, 0.80), (0.70, 0.60), (0.55, 0.45)):
        tag = f"s{int(strength*100)}e{int(endp*100)}"
        graph = controlnet_graph(staged, ROBE_POS, ROBE_NEG, seed=4242,
                                 prefix=f"overnight/cn_{tag}",
                                 strength=strength, end_percent=endp)
        t0 = time.time()
        try:
            outputs = client.run(graph, label=f"cn_{tag}")
        except Exception as exc:
            log(f"  {tag} FAILED: {exc}", "ERROR")
            continue
        paths = collect_outputs(outputs)
        if not paths:
            log(f"  {tag}: no image", "ERROR")
            continue
        dest = OUT / f"cn_{tag}.png"
        dest.write_bytes(paths[0].read_bytes())

        new_mask = silhouette(dest)
        iou, (dx, dy) = drift(base_mask, new_mask)
        log(f"  strength={strength} end={endp} {time.time()-t0:.0f}s  "
            f"IoU={iou:.3f}  added={added_area(base_mask, new_mask)*100:.1f}%  "
            f"drift=({dx:+.1f},{dy:+.1f})px -> {dest.name}")

    log("want: added% clearly >0 (robe exists) with small drift (pose held)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

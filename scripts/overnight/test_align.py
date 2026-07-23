"""Does img2img keep the gear aligned to the base body?

Everything downstream rests on this. If a robe painted at partial denoise
sits on the same shoulders as the base body, we can diff the two and
recover a gear layer that is aligned BY CONSTRUCTION. If the pose drifts,
the whole extract-by-difference approach is dead and we need ControlNet.

Sweeps denoise, and reports the measured silhouette drift for each so the
choice is a number rather than an eyeball.
"""
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import (ComfyClient, collect_outputs, img2img_graph, log,  # noqa: E402
                    stage_input)

REPO = Path(__file__).resolve().parents[2]
BASE = REPO / "cast" / "_sweeps" / "body_lora40.png"
OUT = REPO / "cast" / "_sweeps"

ROBE_POS = (
    "one piece anime style, cel shaded, clean bold lineart, "
    "full body single character, standing straight front view, "
    "slender elven woman, lavender purple skin, glowing golden eyes, "
    "white hair in a tight neat bun, "
    "wearing an elegant flowing white and gold priest robe, "
    "long draping sleeves, layered cloth skirt to the ankles, "
    "gold trim, holy vestments, "
    "full body head to feet, flat plain light grey background, "
    "even flat lighting, no shadow"
)
ROBE_NEG = (
    "cropped, cut off, out of frame, close-up, nude, bare legs, leotard, "
    "multiple characters, weapon, staff, background scenery, text, "
    "watermark, blurry, extra limbs, dynamic pose, tilted, perspective"
)


def silhouette(path, bg_tol=28):
    """Boolean mask of 'not the flat grey backdrop'."""
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(np.int16)
    # Backdrop is the modal corner colour.
    corners = np.concatenate([a[:8, :8].reshape(-1, 3), a[:8, -8:].reshape(-1, 3),
                              a[-8:, :8].reshape(-1, 3), a[-8:, -8:].reshape(-1, 3)])
    bg = np.median(corners, axis=0)
    dist = np.abs(a - bg).sum(axis=2)
    return dist > bg_tol


def drift(mask_a, mask_b):
    """Intersection-over-union of two silhouettes, plus centroid shift."""
    inter = np.logical_and(mask_a, mask_b).sum()
    union = np.logical_or(mask_a, mask_b).sum()
    iou = inter / union if union else 0.0

    def centroid(m):
        ys, xs = np.nonzero(m)
        return (xs.mean(), ys.mean()) if len(xs) else (0, 0)

    ax, ay = centroid(mask_a)
    bx, by = centroid(mask_b)
    return iou, (bx - ax, by - ay)


def main():
    if not BASE.exists():
        log(f"base body missing: {BASE}", "ERROR")
        return 1

    client = ComfyClient()
    staged = stage_input(BASE, "overnight_base_body.png")
    base_mask = silhouette(BASE)
    log(f"=== ALIGNMENT TEST (base silhouette = {base_mask.sum()} px) ===")

    for denoise in (0.40, 0.55, 0.70):
        tag = f"d{int(denoise*100)}"
        graph = img2img_graph(staged, ROBE_POS, ROBE_NEG, seed=4242,
                              prefix=f"overnight/align_{tag}", denoise=denoise)
        t0 = time.time()
        try:
            outputs = client.run(graph, label=f"align_{tag}")
        except Exception as exc:
            log(f"  {tag} FAILED: {exc}", "ERROR")
            continue
        paths = collect_outputs(outputs)
        if not paths:
            log(f"  {tag}: no image", "ERROR")
            continue
        dest = OUT / f"align_{tag}.png"
        dest.write_bytes(paths[0].read_bytes())

        iou, (dx, dy) = drift(base_mask, silhouette(dest))
        log(f"  denoise={denoise} {time.time()-t0:.0f}s  IoU={iou:.3f}  "
            f"centroid drift=({dx:+.1f},{dy:+.1f})px  -> {dest.name}")
    log("higher IoU = gear stayed on the same body. <0.75 means drift is "
        "eating the alignment and ControlNet is required.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

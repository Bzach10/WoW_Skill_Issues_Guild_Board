#!/usr/bin/env python3
"""Deterministic cutout matting for a plain-solid-background source image.

Why not rembg alone: rembg's saliency segmentation treats the character's
MAIN BODY as "the subject" and often zeroes out anything spatially
detached from it at high confidence — a weapon held out at arm's length,
a floating magic orb, a staff tip — even though those pixels are clearly
not background. That is a systematic failure mode for action-pose art,
not something alpha-matting or model-switching fixes.

Since the source is a KNOWN flat solid color, we don't need ML saliency
at all: any pixel far enough from the background color in color-space is
foreground, full stop, regardless of whether it touches the main torso
blob. Flood-filling the background color inward from the four canvas
edges (rather than a single global color threshold) additionally
protects against a background-colored patch appearing *inside* the
character (e.g. a pale robe) being misread as background, since it is
never reached by the border flood-fill unless it is actually contiguous
with the true backdrop.
"""
import numpy as np
from PIL import Image
from collections import deque


def _flood_fill_background(rgb, bg_color, tol, small_hole_frac=0.005):
    """Boolean mask, True where a pixel is background.

    Two passes: border-connected background-colored pixels (the actual
    backdrop), PLUS any small ENCLOSED background-colored pocket — a gap
    in the character's silhouette (e.g. backdrop visible between an arm
    and a cape) that a pure border flood-fill can't reach because it
    isn't connected to the edge. Small pockets are almost always such
    gaps; a LARGE enclosed same-colored region is left alone, since that
    is more likely to be genuine background-colored gear (e.g. green fel
    effects) than a hole.

    The "flat" backdrop is rarely pixel-uniform (subtle vignette/noise),
    which can strand isolated speckles a strict per-pixel comparison
    can't reach — a light blur before the distance check smooths that
    away without touching the final RGB/alpha we output.
    """
    from scipy.ndimage import uniform_filter, label
    smoothed = uniform_filter(rgb.astype(np.float32), size=(3, 3, 1))
    h, w, _ = rgb.shape
    diff = np.abs(smoothed - np.array(bg_color, dtype=np.float32))
    dist = diff.sum(axis=2)  # cheap L1 color distance
    is_bg_color = dist <= tol

    visited = np.zeros((h, w), dtype=bool)
    q = deque()

    def seed(y, x):
        if is_bg_color[y, x] and not visited[y, x]:
            visited[y, x] = True
            q.append((y, x))

    for x in range(w):
        seed(0, x)
        seed(h - 1, x)
    for y in range(h):
        seed(y, 0)
        seed(y, w - 1)

    while q:
        y, x = q.popleft()
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and is_bg_color[ny, nx] and not visited[ny, nx]:
                visited[ny, nx] = True
                q.append((ny, nx))

    # Second pass: small enclosed background-colored pockets.
    remaining_bg = is_bg_color & ~visited
    labels, n = label(remaining_bg)
    max_hole_px = small_hole_frac * h * w
    for i in range(1, n + 1):
        component = labels == i
        if component.sum() <= max_hole_px:
            visited |= component

    return visited


def _soft_edge_alpha(rgb, bg_mask, bg_color, feather=3):
    """255 for foreground, 0 for background, with a short feather ramp at
    the boundary based on color distance so edges anti-alias instead of
    hard-cutting."""
    h, w, _ = rgb.shape
    diff = np.abs(rgb.astype(np.int16) - np.array(bg_color, dtype=np.int16))
    dist = diff.sum(axis=2).astype(np.float32)

    alpha = np.where(bg_mask, 0, 255).astype(np.float32)

    # Only feather pixels adjacent to the fill (dilate bg_mask by 1 and
    # look at the ring) to avoid softening real internal edges.
    from scipy.ndimage import binary_dilation
    ring = binary_dilation(bg_mask, iterations=feather) & ~bg_mask
    ramp = np.clip(dist / max(1, feather * 40), 0, 1) * 255
    alpha[ring] = np.minimum(alpha[ring], ramp[ring])
    return alpha.astype(np.uint8)


def clean_cutout(src_path, dst_path, bg_color=(128, 128, 128), tol=45, feather=3,
                  small_hole_frac=0.02):
    """Matte a plain-solid-bg character image into a transparent PNG that
    preserves every foreground pixel regardless of connectivity to the
    main body. Returns (retained_area, total_nonbg_area) pixel counts for
    validation.
    """
    im = Image.open(src_path).convert("RGB")
    rgb = np.array(im)

    bg_mask = _flood_fill_background(rgb, bg_color, tol, small_hole_frac=small_hole_frac)

    # Ground truth for validation: every pixel that is simply not
    # background-colored, regardless of position/connectivity. A correct
    # flood-fill result should retain ~all of this.
    diff_all = np.abs(rgb.astype(np.int16) - np.array(bg_color, dtype=np.int16))
    nonbg_color_mask = diff_all.sum(axis=2) > tol
    total_nonbg_area = int(nonbg_color_mask.sum())

    alpha = _soft_edge_alpha(rgb, bg_mask, bg_color, feather=feather)
    retained_area = int((alpha > 128).sum())

    out = np.dstack([rgb, alpha])
    Image.fromarray(out, mode="RGBA").save(dst_path)
    return retained_area, total_nonbg_area


if __name__ == "__main__":
    import sys
    src, dst = sys.argv[1], sys.argv[2]
    bg = tuple(int(x) for x in sys.argv[3].split(",")) if len(sys.argv) > 3 else (128, 128, 128)
    retained, total = clean_cutout(src, dst, bg_color=bg)
    ratio = retained / total if total else 1.0
    print(f"retained {retained}/{total} px ({ratio:.1%})")

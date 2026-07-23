"""Turn a base body + a geared render into aligned, transparent layers.

The trick that makes this a paper doll rather than a slideshow: the gear
render is produced by ControlNet from the base body's own edge map, so
both images describe the SAME body at the SAME pixels. Anything that
differs between them is, by construction, gear — and it is already in
register with the body. No manual alignment, no per-item rigging.

Extraction:
    body   = base render, background keyed out
    gear   = (geared render) minus (base body), split into the contract's
             slots by region: sleeves to `arms`, torso to `chest`,
             everything below the hip to `legs`
    face   = the head region of the base, kept as its own layer so it can
             be swapped for expressions without redrawing the body

Every layer is written full-canvas (832x1216) with anchor {0,0}, which is
the simplest thing the contract accepts and means the runtime never has
to reason about offsets — only about pivots.
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

REPO = Path(__file__).resolve().parents[2]
CANVAS_W, CANVAS_H = 832, 1216

# Region bands as fractions of canvas height, used to split one garment
# into the contract's slots. Tuned to the base body's proportions.
BAND_HEAD_BOTTOM = 0.215   # chin
BAND_HIP = 0.500           # waist/hip line: chest above, legs below
# Sleeves live outside this horizontal core; the torso lives inside it.
CORE_X_LO, CORE_X_HI = 0.42, 0.58


def _bg_color(arr):
    """Modal corner colour — the flat backdrop the renders are drawn on."""
    corners = np.concatenate([
        arr[:8, :8].reshape(-1, 3), arr[:8, -8:].reshape(-1, 3),
        arr[-8:, :8].reshape(-1, 3), arr[-8:, -8:].reshape(-1, 3)])
    return np.median(corners, axis=0)


def foreground_mask(path, tol=28):
    """True where the render is subject rather than backdrop."""
    arr = np.asarray(Image.open(path).convert("RGB")).astype(np.int16)
    dist = np.abs(arr - _bg_color(arr)).sum(axis=2)
    return dist > tol


def _to_rgba(src_path, mask, feather=1.2):
    """Apply a mask as alpha, with a slight feather so composited edges do
    not alias into hard jaggies against the board background.

    Accepts either a boolean mask or float coverage in [0,1], so the
    seam-free band splits can pass their gradients straight through.
    """
    im = Image.open(src_path).convert("RGB")
    alpha = Image.fromarray(
        (np.clip(mask.astype(np.float32), 0, 1) * 255).astype(np.uint8), mode="L")
    if feather:
        alpha = alpha.filter(ImageFilter.GaussianBlur(feather))
    out = im.convert("RGBA")
    out.putalpha(alpha)
    return out


def _canvas(im):
    """Every layer ships at the contract canvas, no exceptions."""
    if im.size != (CANVAS_W, CANVAS_H):
        im = im.resize((CANVAS_W, CANVAS_H), Image.LANCZOS)
    return im


def _band(shape, y_lo=0.0, y_hi=1.0, x_lo=0.0, x_hi=1.0, invert_x=False):
    h, w = shape
    m = np.zeros(shape, dtype=bool)
    ys, xs = slice(int(h * y_lo), int(h * y_hi)), slice(int(w * x_lo), int(w * x_hi))
    if invert_x:
        m[ys, :] = True
        m[ys, xs] = False
    else:
        m[ys, xs] = True
    return m


# How far a layer reaches past its nominal band, and over how many pixels
# it fades out there. See _split_gear() for why this is not symmetric.
OVERLAP_PX = 26
RAMP_PX = 34


def _profile(n, lo, hi, ramp_lo=0, ramp_hi=0):
    """1-D coverage profile: 1 inside [lo,hi], fading out over the ramps."""
    idx = np.arange(n, dtype=np.float32)
    prof = np.ones(n, dtype=np.float32)
    prof *= (np.clip((idx - lo) / ramp_lo, 0, 1) if ramp_lo > 0
             else (idx >= lo).astype(np.float32))
    prof *= (np.clip((hi - idx) / ramp_hi, 0, 1) if ramp_hi > 0
             else (idx <= hi).astype(np.float32))
    return prof


def _soft_band(shape, y_lo=0.0, y_hi=1.0, x_lo=0.0, x_hi=1.0,
               ramp_top=0, ramp_bottom=0, ramp_inner=0, invert_x=False):
    """A band with feathered edges, as float coverage in [0,1]."""
    h, w = shape
    yp = _profile(h, h * y_lo, h * y_hi, ramp_top, ramp_bottom)
    if invert_x:
        # Two side columns: fade towards the body's centre line.
        left = _profile(w, -1, w * x_lo, 0, ramp_inner)
        right = _profile(w, w * x_hi, w + 1, ramp_inner, 0)
        xp = np.clip(left + right, 0, 1)
    else:
        xp = _profile(w, w * x_lo, w * x_hi, ramp_inner, ramp_inner)
    return np.outer(yp, xp)


def _split_gear(gear, shape):
    """Split one garment into arms/chest/legs without visible seams.

    The naive version cut the garment with hard rectangles, and every cut
    line showed on the composite as a faint rectangular seam — because a
    hard alpha edge sits over a body layer whose colour is close but not
    identical.

    The fix relies on z-order. Each layer is drawn OVER the one below it,
    so we let the upper layer reach past its boundary and fade out there,
    while the lower layer stays fully opaque underneath the fade. The
    gradient then blends two copies of the same pixels rather than
    exposing an edge, and nothing shows through, because there is never
    background under a fade — only the opaque layer beneath.

        legs  (z=30)  hard top edge, raised to sit under the chest fade
        chest (z=40)  fades out downward over legs, inward-hard at sides
        arms  (z=50)  fades inward over chest
    """
    gear_f = gear.astype(np.float32)

    legs = gear_f * _soft_band(
        shape, y_lo=BAND_HIP - (OVERLAP_PX / shape[0]))

    chest = gear_f * _soft_band(
        shape, y_lo=BAND_HEAD_BOTTOM,
        y_hi=BAND_HIP + (OVERLAP_PX / shape[0]),
        x_lo=CORE_X_LO, x_hi=CORE_X_HI,
        ramp_top=RAMP_PX // 2, ramp_bottom=RAMP_PX, ramp_inner=0)

    arms = gear_f * _soft_band(
        shape, y_lo=BAND_HEAD_BOTTOM,
        y_hi=BAND_HIP + (OVERLAP_PX / shape[0]),
        x_lo=CORE_X_LO + (OVERLAP_PX / shape[1]),
        x_hi=CORE_X_HI - (OVERLAP_PX / shape[1]),
        ramp_top=RAMP_PX // 2, ramp_bottom=RAMP_PX,
        ramp_inner=RAMP_PX, invert_x=True)

    return {"arms": arms, "chest": chest, "legs": legs}


def extract_layers(base_path, gear_path, diff_tol=42):
    """Return {slot: RGBA image} for one character in one gear set."""
    base_rgb = np.asarray(Image.open(base_path).convert("RGB")).astype(np.int16)
    gear_rgb = np.asarray(Image.open(gear_path).convert("RGB")).astype(np.int16)
    if base_rgb.shape != gear_rgb.shape:
        raise ValueError(f"size mismatch: {base_rgb.shape} vs {gear_rgb.shape}")

    base_fg = foreground_mask(base_path)
    gear_fg = foreground_mask(gear_path)
    shape = base_fg.shape

    # Gear = where the two renders disagree, anywhere the geared render
    # has subject. Below the chin only: the head is the base's to own, and
    # small facial resampling noise must not leak into a garment layer.
    changed = np.abs(base_rgb - gear_rgb).sum(axis=2) > diff_tol
    gear = changed & gear_fg & _band(shape, y_lo=BAND_HEAD_BOTTOM)

    layers = {}

    # --- body: the base, minus nothing. Gear layers sit on top of it. ---
    layers["body"] = _to_rgba(base_path, base_fg)

    # --- face: head region of the base, its own layer for expressions ---
    layers["face"] = _to_rgba(base_path, base_fg & _band(shape, y_hi=BAND_HEAD_BOTTOM))

    # --- garment -> arms / chest / legs, with overlapping soft edges ----
    for slot, mask in _split_gear(gear, shape).items():
        if mask.sum() > 500:          # ignore specks; an empty slot is fine
            layers[slot] = _to_rgba(gear_path, mask)

    return {k: _canvas(v) for k, v in layers.items()}


def write_layers(layers, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    for slot, im in layers.items():
        p = out_dir / f"{slot}.png"
        im.save(p)
        written[slot] = p
    return written


def cutout(src_path, out_path, tol=28):
    """Background-key a standalone render (weapons, props) to RGBA.

    Deliberately not rembg: our renders sit on a flat keyed backdrop, so
    a colour key is exact, instant, and CPU-free, where a salient-object
    model would guess — and would happily eat a thin staff shaft.
    """
    mask = foreground_mask(src_path, tol=tol)
    im = _canvas(_to_rgba(src_path, mask))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path)
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("usage: layers.py <base.png> <gear.png> <out_dir>")
        raise SystemExit(1)
    written = write_layers(extract_layers(sys.argv[1], sys.argv[2]), sys.argv[3])
    for slot, path in written.items():
        print(f"  {slot:12} -> {path}")

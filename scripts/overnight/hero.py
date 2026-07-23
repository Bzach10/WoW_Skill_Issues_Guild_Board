"""Character-specific "hero" props: the pieces that carry identity.

The archetype library can dress a torso, but it cannot make someone look
like THEMSELVES. What reads as "that's my toon" is almost always a small
number of signature items — a bishop's mitre, a specific weapon, a
distinctive cloak — and those live in exactly the contract slots the
garment extractor never fills (head, weapon_main, weapon_off, cloak).

Hero props sidestep the hardest problem in the pipeline. A garment has to
be generated ON the body and stay in register with it; a prop is
generated ALONE on a flat backdrop and then PLACED at its contract
anchor. There is no alignment to lose, because there was never a body in
the render to drift from.

    place_prop(prop_png, out_png, anchor=(x, y), height_px=..., ...)
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from layers import CANVAS_H, CANVAS_W, foreground_mask, _to_rgba  # noqa: E402


def cut_prop(prop_path, tol=30):
    """Background-key a standalone prop render and crop it to its content."""
    mask = foreground_mask(prop_path, tol=tol)
    rgba = _to_rgba(prop_path, mask, feather=1.0)
    ys, xs = np.nonzero(mask)
    if not len(ys):
        raise ValueError(f"{prop_path}: nothing but background")
    return rgba.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))


def head_top_of(body_png, search_frac=0.45):
    """Where the character's head actually starts, in canvas px.

    Measured from the art rather than assumed, so a prop sits correctly on
    a 7-foot orc and a hunched pandaren without per-race tuning.
    """
    mask = np.asarray(Image.open(body_png).convert("RGBA"))[..., 3] > 24
    band = mask[:int(mask.shape[0] * search_frac)]
    ys, xs = np.nonzero(band)
    if not len(ys):
        return int(CANVAS_H * 0.10), CANVAS_W // 2
    top = int(ys.min())
    # Centre on the head's own width at its widest, not the whole figure —
    # a trailing cloak or tail would drag a full-figure centroid sideways.
    head_rows = band[top:top + max(8, int(CANVAS_H * 0.06))]
    hys, hxs = np.nonzero(head_rows)
    cx = int(np.median(hxs)) if len(hxs) else CANVAS_W // 2
    return top, cx


def place_prop(prop_path, out_path, anchor, height_px, overlap=0.0, flip=False):
    """Scale a cut-out prop and place it on a full contract canvas.

    anchor    (x, y) in canvas px — where the prop's BOTTOM-CENTRE lands
    height_px how tall the prop should render
    overlap   fraction of the prop's height pushed BELOW the anchor, so a
              helmet sits down over the brow instead of hovering on it
    """
    prop = cut_prop(prop_path)
    w = max(1, int(prop.width * height_px / prop.height))
    prop = prop.resize((w, int(height_px)), Image.LANCZOS)

    canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    ax, ay = anchor
    x = int(ax - prop.width / 2)
    y = int(ay - prop.height + prop.height * overlap)
    canvas.alpha_composite(prop, (max(0, x), max(0, y)))

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    return out_path


def place_headpiece(prop_path, body_png, out_path, height_frac=0.19,
                    sink=0.34):
    """Place a helmet/hat on the head, measured off the body art."""
    top, cx = head_top_of(body_png)
    height_px = CANVAS_H * height_frac
    # Anchor at the head top, then sink the prop down over the skull.
    return place_prop(prop_path, out_path, anchor=(cx, top + height_px * sink),
                      height_px=height_px, overlap=0.0)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("usage: hero.py <prop.png> <body.png> <out.png> [height_frac] [sink]")
        raise SystemExit(1)
    hf = float(sys.argv[4]) if len(sys.argv) > 4 else 0.19
    sk = float(sys.argv[5]) if len(sys.argv) > 5 else 0.34
    print(place_headpiece(sys.argv[1], sys.argv[2], sys.argv[3], hf, sk))

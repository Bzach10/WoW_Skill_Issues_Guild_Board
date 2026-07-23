"""Composite a layer set into a still, and into an animated idle preview.

Reads the SAME numbers the shipped web runtime uses — z-order, bone
mapping, and fractional pivots are imported from guild_board.paperdoll in
the frontend worktree when it is reachable, so this preview cannot drift
from what the site will actually render. If it is not reachable we fall
back to a local copy of the contract and say so loudly, because a preview
that silently disagrees with production is worse than no preview.

Outputs:
    <out>/composite.png   the still, layers stacked in contract z-order
    <out>/idle.gif        the idle rig: what the board will actually do
"""

import importlib.util
import math
import sys
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[2]
FRONTEND_PAPERDOLL = Path(r"C:\wt\fc\guild_board\paperdoll.py")
CANVAS_W, CANVAS_H = 832, 1216

# Fallback copy of the contract, used only if the runtime module is not
# reachable. Kept identical to paperdoll.py's constants.
_FALLBACK_Z = {"cloak": 10, "body": 20, "legs": 30, "chest": 40, "arms": 50,
               "head": 60, "face": 61, "weapon_off": 70, "weapon_main": 71,
               "composite": 20}
_FALLBACK_BONE = {"cloak": "cloak", "body": "torso", "legs": "legs",
                  "chest": "torso", "arms": "arms", "head": "head",
                  "face": "head", "weapon_off": "weapon_off",
                  "weapon_main": "weapon_main", "composite": "torso"}
_FALLBACK_PIVOT = {"cloak": (0.50, 0.22), "body": (0.50, 0.95),
                   "legs": (0.50, 0.55), "chest": (0.50, 0.45),
                   "arms": (0.50, 0.30), "head": (0.50, 0.30),
                   "face": (0.50, 0.30), "weapon_off": (0.32, 0.42),
                   "weapon_main": (0.68, 0.42), "composite": (0.50, 0.95)}


def load_contract():
    """Prefer the runtime's own constants; fall back with a warning."""
    if FRONTEND_PAPERDOLL.exists():
        try:
            spec = importlib.util.spec_from_file_location(
                "_fc_paperdoll", FRONTEND_PAPERDOLL)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.SLOT_Z, mod.SLOT_BONE, mod.DEFAULT_PIVOT, "runtime"
        except Exception as exc:
            print(f"WARN: could not import runtime contract ({exc}); "
                  f"using local fallback", file=sys.stderr)
    else:
        print("WARN: frontend paperdoll.py not found; using local fallback",
              file=sys.stderr)
    return _FALLBACK_Z, _FALLBACK_BONE, _FALLBACK_PIVOT, "fallback"


SLOT_Z, SLOT_BONE, DEFAULT_PIVOT, CONTRACT_SOURCE = load_contract()

# The idle rig, mirroring the runtime's documented motion:
# (amplitude in degrees, period in seconds, phase offset)
BONE_MOTION = {
    "torso": (0.7, 5.2, 0.0),
    "legs": (-0.5, 5.2, 0.0),
    "arms": (1.6, 4.8, 0.6),
    "head": (-0.9, 5.2, 0.3),
    "cloak": (2.6, 4.6, 1.1),
    "weapon_main": (2.4, 4.1, 0.2),
    "weapon_off": (2.2, 4.4, 0.9),
}
BREATH_PERIOD, BREATH_PX = 3.4, 5.0


def load_layers(layer_dir):
    """All contract slots present on disk, in z-order.

    "composite" is excluded deliberately. It is a real contract slot (the
    v1 flat cut-out), but it is ALSO the filename this module writes its
    own output to — so including it composites the previous render back
    into the new one, compounding a little more ghosting every run.
    A still is an output, never an input.
    """
    layer_dir = Path(layer_dir)
    found = []
    for slot in sorted(SLOT_Z, key=lambda s: SLOT_Z[s]):
        if slot == "composite":
            continue
        p = layer_dir / f"{slot}.png"
        if p.exists():
            found.append((slot, Image.open(p).convert("RGBA")))
    return found


def _rotate_about(im, degrees, pivot_xy):
    """Rotate a full-canvas layer about a pivot without moving the canvas."""
    if not degrees:
        return im
    px, py = pivot_xy
    # Translate pivot to origin, rotate, translate back — expressed as a
    # single affine so we resample exactly once.
    rad = math.radians(-degrees)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    a, b = cos_a, sin_a
    c = px - cos_a * px - sin_a * py
    d, e = -sin_a, cos_a
    f = py + sin_a * px - cos_a * py
    return im.transform(im.size, Image.AFFINE, (a, b, c, d, e, f),
                        resample=Image.BICUBIC)


def compose(layers, t=None, bg=(24, 20, 32, 255)):
    """Stack layers; if `t` is given, apply the idle rig at that time."""
    canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), bg)
    breath = 0.0
    if t is not None:
        breath = math.sin(2 * math.pi * t / BREATH_PERIOD) * BREATH_PX

    for slot, im in layers:
        frame = im
        if t is not None:
            bone = SLOT_BONE.get(slot, "torso")
            amp, period, phase = BONE_MOTION.get(bone, (0.0, 1.0, 0.0))
            angle = amp * math.sin(2 * math.pi * (t / period) + phase)
            fx, fy = DEFAULT_PIVOT.get(slot, (0.5, 0.95))
            frame = _rotate_about(frame, angle, (fx * CANVAS_W, fy * CANVAS_H))
            if breath:
                frame = frame.transform(
                    frame.size, Image.AFFINE, (1, 0, 0, 0, 1, -breath),
                    resample=Image.BICUBIC)
        canvas = Image.alpha_composite(canvas, frame)
    return canvas


def render(layer_dir, out_dir, frames=24, seconds=5.2, scale=0.5):
    layer_dir, out_dir = Path(layer_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    layers = load_layers(layer_dir)
    if not layers:
        raise SystemExit(f"no contract layers found in {layer_dir}")

    still_path = out_dir / "composite.png"
    compose(layers).convert("RGB").save(still_path, quality=95)

    size = (int(CANVAS_W * scale), int(CANVAS_H * scale))
    gif_frames = [compose(layers, t=seconds * i / frames)
                  .convert("RGB").resize(size, Image.LANCZOS)
                  for i in range(frames)]
    gif_path = out_dir / "idle.gif"
    gif_frames[0].save(gif_path, save_all=True, append_images=gif_frames[1:],
                       duration=int(seconds * 1000 / frames), loop=0,
                       optimize=True)

    return still_path, gif_path, [s for s, _ in layers]


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: compose.py <layer_dir> <out_dir>")
        raise SystemExit(1)
    still, gif, slots = render(sys.argv[1], sys.argv[2])
    print(f"contract source: {CONTRACT_SOURCE}")
    print(f"layers: {', '.join(slots)}")
    print(f"still : {still}")
    print(f"gif   : {gif}")

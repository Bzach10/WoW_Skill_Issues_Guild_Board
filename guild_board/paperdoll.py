"""The paper-doll compositor: assemble a character from layered art.

A character is not one picture. It is a stack of original-art layers —
base body, face, and a gear layer per equipment slot — composited at
fixed anchor points on a fixed canvas, in a fixed z-order. Each layer is
also a BONE: it carries a pivot, so the web runtime can rotate it for
idle animation without any of the art changing.

THE CONTRACT (owned and published by the art pipeline session; this
module implements the consuming half):

    canvas   fixed pixel size every layer is authored against
    slots    cloak < body < legs < chest < arms < head < weapons
             (the scene background sits below all of them, but it
             belongs to the board, not the character)
    anchor   where a layer's top-left sits on the canvas, in canvas px
    pivot    the point a layer rotates about, in canvas px — the joint

Manifest shapes we accept, newest first:

  v2 (paper-doll): styles.<style>.layers = [
        {"slot": "chest", "src": "cast/<id>/<style>/chest.png",
         "anchor": {"x": 0, "y": 0}, "pivot": {"x": 416, "y": 300},
         "z": 40}, ... ]

  v1 (flat cut-out): styles.<style>.board = "…/board.png"
        Rendered as a single "composite" layer on the body bone, so
        today's flat art animates on the same rig and lights up as a
        real doll the moment layers appear.

Everything degrades: a layer whose file is missing is dropped, a
character with no usable layers falls back to the flat cut-out, and a
character with neither falls back to the silhouette. There is no input
that produces a broken character.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# The canvas every layer is authored against. A manifest may override it
# per style; this is the fallback and matches the pilot renders.
DEFAULT_CANVAS = {"w": 832, "h": 1216}

# z-order, low to high. The scene background is deliberately absent: it
# is the board's layer, composited under the whole cast.
SLOT_Z = {
    "cloak": 10,
    "body": 20,
    "legs": 30,
    "chest": 40,
    "arms": 50,
    "head": 60,
    "face": 61,
    "weapon_off": 70,
    "weapon_main": 71,
    # the v1 flat cut-out, which stands in for the whole stack
    "composite": 20,
}

SLOT_ORDER = ["cloak", "body", "legs", "chest", "arms", "head", "face",
              "weapon_off", "weapon_main", "composite"]

# Which bone drives each slot. Bones are what the runtime animates; the
# art never changes, only the transform applied to it.
SLOT_BONE = {
    "cloak": "cloak",
    "body": "torso",
    "legs": "legs",
    "chest": "torso",
    "arms": "arms",
    "head": "head",
    "face": "head",
    "weapon_off": "weapon_off",
    "weapon_main": "weapon_main",
    "composite": "torso",
}

# Default pivots as a FRACTION of the canvas, so they hold at any canvas
# size. These are joints: the shoulder line for arms, the neck for head
# and cloak, the grip for weapons.
DEFAULT_PIVOT = {
    "cloak": (0.50, 0.22),
    "body": (0.50, 0.95),
    "legs": (0.50, 0.55),
    "chest": (0.50, 0.45),
    "arms": (0.50, 0.30),
    "head": (0.50, 0.30),
    "face": (0.50, 0.30),
    "weapon_off": (0.32, 0.42),
    "weapon_main": (0.68, 0.42),
    "composite": (0.50, 0.95),
}


def canvas_for(style_assets):
    """The canvas this style's layers are authored against."""
    canvas = (style_assets or {}).get("canvas")
    if isinstance(canvas, dict):
        try:
            w, h = int(canvas.get("w") or 0), int(canvas.get("h") or 0)
            if w > 0 and h > 0:
                return {"w": w, "h": h}
        except (TypeError, ValueError):
            pass
    return dict(DEFAULT_CANVAS)


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _exists(src):
    if not src or not isinstance(src, str):
        return None
    if not Path(src).exists():
        return None
    return src.replace(os.sep, "/")


def _layer_from_entry(entry, canvas, index):
    """One manifest layer -> one renderable bone layer, or None."""
    if not isinstance(entry, dict):
        return None
    slot = str(entry.get("slot") or "").strip().lower()
    src = _exists(entry.get("src"))
    if not src:
        if entry.get("src"):
            logger.info("Paper-doll layer %r points at a missing file (%s); "
                        "dropping that layer.", slot or "?", entry.get("src"))
        return None
    if slot not in SLOT_Z:
        # An unknown slot still renders — we simply cannot place it in the
        # documented order, so it sits just above the body and keeps its
        # authored position.
        logger.info("Unknown paper-doll slot %r; rendering it above the body.", slot)

    anchor = entry.get("anchor") if isinstance(entry.get("anchor"), dict) else {}
    pivot = entry.get("pivot") if isinstance(entry.get("pivot"), dict) else {}
    fx, fy = DEFAULT_PIVOT.get(slot, (0.5, 0.9))

    ax, ay = _num(anchor.get("x"), 0.0), _num(anchor.get("y"), 0.0)
    px = _num(pivot.get("x"), fx * canvas["w"])
    py = _num(pivot.get("y"), fy * canvas["h"])

    try:
        z = int(entry.get("z"))
    except (TypeError, ValueError):
        z = SLOT_Z.get(slot, 25 + index)

    return {
        "slot": slot or f"layer{index}",
        "src": src,
        "bone": SLOT_BONE.get(slot, "torso"),
        "z": z,
        # Percentages so the doll scales with its container instead of
        # being pinned to authored pixels.
        "left_pct": round(ax / canvas["w"] * 100, 4),
        "top_pct": round(ay / canvas["h"] * 100, 4),
        "origin_pct": (round(px / canvas["w"] * 100, 4),
                       round(py / canvas["h"] * 100, 4)),
    }


def assemble(style_assets, fallback_board=None):
    """Assemble one character's layer stack.

    Returns {"layers": [...], "canvas": {...}, "mode": "layered"|"flat"|"none"}
    ordered bottom-to-top and ready to render directly.
    """
    style_assets = style_assets if isinstance(style_assets, dict) else {}
    canvas = canvas_for(style_assets)

    raw = style_assets.get("layers")
    layers = []
    if isinstance(raw, list):
        for i, entry in enumerate(raw):
            layer = _layer_from_entry(entry, canvas, i)
            if layer:
                layers.append(layer)

    if layers:
        layers.sort(key=lambda item: (item["z"],
                                      SLOT_ORDER.index(item["slot"])
                                      if item["slot"] in SLOT_ORDER else 99))
        return {"layers": layers, "canvas": canvas, "mode": "layered"}

    # v1 fallback: the flat cut-out, mounted on the torso bone so it
    # breathes on the same rig as a real doll.
    flat = _exists(style_assets.get("board")) or _exists(fallback_board)
    if flat:
        fx, fy = DEFAULT_PIVOT["composite"]
        return {
            "layers": [{
                "slot": "composite", "src": flat, "bone": "torso",
                "z": SLOT_Z["composite"], "left_pct": 0.0, "top_pct": 0.0,
                "origin_pct": (round(fx * 100, 4), round(fy * 100, 4)),
            }],
            "canvas": canvas,
            "mode": "flat",
        }

    return {"layers": [], "canvas": canvas, "mode": "none"}


def contract_summary():
    """What this runtime consumes — mirrored in LAYER_CONTRACT.md so the
    pipeline session can diff it against what it publishes."""
    return {
        "canvas": dict(DEFAULT_CANVAS),
        "slot_z_order": [s for s in SLOT_ORDER if s != "composite"],
        "bones": sorted(set(SLOT_BONE.values())),
        "layer_fields": ["slot", "src", "anchor{x,y}", "pivot{x,y}", "z"],
    }

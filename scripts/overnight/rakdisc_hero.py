"""Build a gear-accurate Rakdisc — the approved template, before any scale.

Ground truth is her REAL Blizzard transmog render on disk, not a generic
archetype. Per-slot equipment data would be better, but the backend's
equipment code has no credentials yet, and the render is the actual
appearance those item IDs would only approximate anyway.

Targets, read off the reference:
    crimson + cream + gold vestments   (not the generic white robe)
    gold bishop's mitre                -> headgear slot (z=65, NEW)
    holy fire                          -> weapon_main
    glowing orb                        -> weapon_off
    pale spiral-cuffed boots           -> inside legs

Props are rendered on a SQUARE canvas, per the frontend's new PROP_SLOTS
rule — a mitre generated in the 832x1216 body frame comes out stretched,
which is exactly what the first hero test produced.

Every asset checkpoints, and any single failure is logged and skipped
rather than taking down the run.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import (ComfyClient, collect_outputs, controlnet_graph, log,  # noqa: E402
                    load_state, mark_done, mark_failed, save_state,
                    stage_input, txt2img_graph)

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "cast" / "rakdisc-proudmoore" / "one_piece"
PROPS = REPO / "cast" / "_props" / "rakdisc"
BASE = REPO / "cast" / "_approved" / "rakdisc-proudmoore" / "_source_body.png"

STYLE = ("one piece anime style, cel shaded, clean bold lineart, "
         "flat plain light grey background, even flat lighting, no shadow")

# Her identity, restated in every prompt so ControlNet cannot drift it.
WHO = ("a tall slender nightborne elf woman, lavender purple skin, "
       "long pointed ears, glowing golden eyes, white hair in a tight bun")

# --- the garment, in HER colours -----------------------------------------
GEAR_POS = (
    f"{WHO}, wearing ornate crimson red and cream white priest vestments, "
    "heavy gold trim and gold filigree, structured crimson and gold "
    "shoulder pauldrons, a long layered tabard with a white front panel "
    "over deep red robes, wide draping sleeves, gold belt, "
    "pale white boots, holy bishop regalia, "
    f"full body head to feet, standing straight front view, {STYLE}"
)
GEAR_NEG = (
    "plain white robe, all white, monochrome, floor length gown, long train, "
    "barefoot, bare legs, nude, leotard, swimsuit, casual clothes, "
    "cropped, cut off, multiple characters, text, watermark, blurry, "
    "dynamic pose, tilted, perspective, helmet, hood, weapon"
)

# --- props: square canvas, one object, nothing else ----------------------
PROP_NEG = ("person, face, head, body, character, hands, multiple objects, "
            "duplicate, text, watermark, blurry, dark background, scenery")

PROPS_SPEC = {
    "headgear": (
        "a single tall pointed golden bishop mitre helm, ornate gold metal "
        "with a cream white front panel, a glowing amber gem at the brow, "
        "gold side flanges, symmetrical, facing forward, "
        f"one object centered on a plain flat light grey background, {STYLE}",
        991,
    ),
    "weapon_main": (
        "a single burst of glowing holy fire, bright orange and gold flame, "
        "a floating flame wisp, radiant, no hand, no arm, "
        f"one object centered on a plain flat light grey background, {STYLE}",
        1207,
    ),
    "weapon_off": (
        "a single glowing golden holy orb, a radiant sphere of light with "
        "a bright core and soft golden glow, ornate gold ring around it, "
        f"one object centered on a plain flat light grey background, {STYLE}",
        1331,
    ),
}

PROP_SIZE = 1024  # square, per the contract's PROP_SLOTS rule


def build_gear(client, state):
    key = "rak:gear"
    raw = PROPS.parent / "rakdisc_gear_raw.png"
    if key in state["done"] and raw.exists():
        log("  gear: already checkpointed")
        return raw
    staged = stage_input(BASE, "rak_hero_base.png")
    graph = controlnet_graph(staged, GEAR_POS, GEAR_NEG, seed=4242,
                             prefix="overnight/rak_gear",
                             strength=0.85, end_percent=0.80,
                             lora_strength=0.40)
    outputs = client.run(graph, label=key)
    paths = collect_outputs(outputs)
    if not paths:
        raise RuntimeError("gear render produced no image")
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(paths[0].read_bytes())
    mark_done(state, key, raw)
    log(f"  gear -> {raw.name}")
    return raw


def build_props(client, state):
    PROPS.mkdir(parents=True, exist_ok=True)
    built = {}
    for slot, (prompt, seed) in PROPS_SPEC.items():
        key = f"rak:prop:{slot}"
        dest = PROPS / f"{slot}_raw.png"
        if key in state["done"] and dest.exists():
            log(f"  prop {slot}: already checkpointed")
            built[slot] = dest
            continue
        graph = txt2img_graph(prompt, PROP_NEG, seed=seed,
                              prefix=f"overnight/rak_prop_{slot}",
                              w=PROP_SIZE, h=PROP_SIZE, lora_strength=0.40)
        try:
            outputs = client.run(graph, label=key)
            paths = collect_outputs(outputs)
            if not paths:
                raise RuntimeError("no image")
            dest.write_bytes(paths[0].read_bytes())
            mark_done(state, key, dest)
            built[slot] = dest
            log(f"  prop {slot} -> {dest.name}")
        except Exception as exc:
            mark_failed(state, key, exc)
            log(f"  prop {slot} FAILED (continuing): {exc}", "ERROR")
    return built


def main(argv):
    state = load_state()
    save_state(state)
    client = ComfyClient()
    log("=" * 62)
    log("RAKDISC HERO PASS — gear-accurate template build")
    if not client.healthy():
        log("ComfyUI not healthy", "ERROR")
        return 1

    t0 = time.time()
    try:
        gear = build_gear(client, state)
    except Exception as exc:
        mark_failed(state, "rak:gear", exc)
        log(f"  gear FAILED: {exc}", "ERROR")
        gear = None

    props = build_props(client, state)
    log(f"HERO PASS RENDERS DONE in {time.time() - t0:.0f}s "
        f"(gear={'ok' if gear else 'FAILED'}, props={sorted(props)})")
    log("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Find a LoRA strength / prompt that yields a USABLE base body.

The first smoke render failed in three specific ways, and each maps to a
knob rather than to bad luck:

  * absurd elongation      -> Wano LoRA at 0.75 is driving proportion
  * arms fused to the torso -> "A-pose" as words does not control pose
  * hair curtaining the body -> a base body must not carry a hair mass
                                that gear layers then have to sit under

So: sweep LoRA strength down, and constrain hair explicitly. Pose is the
one thing prompt words will not fix reliably; that is ControlNet's job
and is handled separately.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import ComfyClient, collect_outputs, log, txt2img_graph  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "cast" / "_sweeps"

BASE_POS = (
    "one piece anime style, cel shaded, clean bold lineart, "
    "full body character reference sheet, single character, "
    "standing straight, feet together, arms straight down and away from "
    "the sides, palms open facing forward, front view, facing viewer, "
    "symmetrical, natural human proportions, "
    "slender elven woman, lavender purple skin, glowing golden eyes, "
    "white hair in a tight neat bun, "
    "plain simple dark sleeveless leotard, barefoot, "
    "full body head to feet, flat plain light grey background, "
    "even flat lighting, no shadow"
)
NEG = (
    "cropped, cut off, out of frame, close-up, portrait, "
    "long hair, flowing hair, hair covering body, huge hair, "
    "horns, antlers, tail, wings, "
    "elongated body, distorted anatomy, tiny head, stretched limbs, "
    "multiple characters, weapon, armor, robe, cloak, cape, hood, "
    "background scenery, text, watermark, blurry, extra limbs, "
    "dynamic pose, action pose, tilted, perspective"
)

VARIANTS = [
    ("lora00", 0.00),
    ("lora25", 0.25),
    ("lora40", 0.40),
    ("lora55", 0.55),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    client = ComfyClient()
    log("=== SWEEP: base body, LoRA strength ===")
    for name, strength in VARIANTS:
        graph = txt2img_graph(BASE_POS, NEG, seed=4242,
                              prefix=f"overnight/sweep_{name}",
                              lora_strength=strength)
        t0 = time.time()
        try:
            outputs = client.run(graph, label=f"sweep_{name}")
        except Exception as exc:
            log(f"  {name} FAILED: {exc}", "ERROR")
            continue
        paths = collect_outputs(outputs)
        if not paths:
            log(f"  {name}: no image", "ERROR")
            continue
        dest = OUT / f"body_{name}.png"
        dest.write_bytes(paths[0].read_bytes())
        log(f"  {name} (lora={strength}) {time.time()-t0:.0f}s -> {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Smoke test: one Nightborne-female base body, end to end, timed.

Proves the whole path (submit -> tiled decode -> file on disk) before we
commit the night to it, and tells us how long one layer actually costs so
the overnight schedule is based on a measurement rather than a guess.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import ComfyClient, collect_outputs, log, log_resources, txt2img_graph  # noqa: E402

POS = (
    "one piece anime style, cel shaded, clean bold lineart, "
    "full body single character, standing straight in a neutral A-pose, "
    "arms held slightly away from the body, palms open, facing the viewer, "
    "symmetrical, tall slender elven woman, lavender purple skin, "
    "long flowing white hair, glowing golden eyes, elegant sharp features, "
    "plain simple form-fitting dark bodysuit, barefoot, "
    "entire body visible from head to feet, standing on nothing, "
    "flat plain light grey background, even lighting, no shadows"
)
NEG = (
    "cropped, cut off, out of frame, close-up, portrait, bust, "
    "multiple characters, twins, weapon, staff, sword, armor, robe, cloak, "
    "cape, hood, jewelry, background scenery, landscape, furniture, text, "
    "watermark, signature, logo, blurry, low quality, extra limbs, "
    "extra fingers, dynamic pose, action pose, running, sitting, "
    "perspective, foreshortening, tilted"
)


def main():
    log("=== SMOKE TEST: Nightborne female base body ===")
    log_resources("pre")
    client = ComfyClient()

    if not client.healthy():
        log("comfy unhealthy at smoke-test start", "ERROR")
        return 1

    graph = txt2img_graph(POS, NEG, seed=77010, prefix="overnight/smoke_body")
    t0 = time.time()
    outputs = client.run(graph, label="smoke_body")
    elapsed = time.time() - t0

    paths = collect_outputs(outputs)
    if not paths:
        log("no image produced", "ERROR")
        return 1

    dest = Path(__file__).resolve().parents[2] / "cast" / "_overnight_smoke.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(paths[0].read_bytes())

    log(f"SMOKE OK in {elapsed:.0f}s -> {dest}")
    log_resources("post")
    log(f"MEASURED: one 832x1216 layer costs ~{elapsed:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

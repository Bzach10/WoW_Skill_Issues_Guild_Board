"""Generate a One Piece style illustration for every opted-in roster member,
using their real Blizzard profile (gender/race/class/active spec) for the
prompt and their transmog render as an IP-Adapter likeness reference.

WAITS ON REAL DATA. If blizzard_profile_cache.json is empty (the scheduled
Blizzard Action hasn't populated it yet, or blizzard.enabled is still
false), this prints why and exits 0 — it never invents roster members or
generates from guesses. See SETUP_BLIZZARD.md for the Blizzard setup and
CUSTOMIZING.md-adjacent docs for the art pipeline.

Needs a running ComfyUI server (127.0.0.1:8188) with:
  - Illustrious-XL-v1.1.safetensors (checkpoint)
  - one_piece_wano_style.safetensors (LoRA)
  - CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors (clip_vision)
  - ip-adapter-plus_sdxl_vit-h.safetensors (ipadapter)

Usage: python scripts/generate_cast.py [--limit N]
"""

import json
import os
import random
import shutil
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

# Run directly (python scripts/generate_cast.py), Python only puts this
# file's own directory on sys.path, not the repo root — so `guild_board`
# isn't importable without this. Same fix scripts/preview_board.py uses.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guild_board.blizzard import load_profile_cache  # noqa: E402
from guild_board.cast_art import (  # noqa: E402
    build_ipadapter_graph,
    build_prompt,
    opted_in_characters,
)
from guild_board.config import load_config  # noqa: E402

COMFY = "http://127.0.0.1:8188"
COMFY_INPUT_DIR = r"C:\Users\zachf\AppData\Local\Comfy-Desktop\ComfyUI-Shared\input"
COMFY_OUTPUT_DIR = r"C:\Users\zachf\AppData\Local\Comfy-Desktop\ComfyUI-Shared\output"
CAST_DIR = "cast/crew"

CKPT = "Illustrious-XL-v1.1.safetensors"
LORA = "one_piece_wano_style.safetensors"
CLIP_VISION = "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"
IPADAPTER_FILE = "ip-adapter-plus_sdxl_vit-h.safetensors"


def _download_reference_image(url, dest_filename):
    import requests
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    dest = os.path.join(COMFY_INPUT_DIR, dest_filename)
    with open(dest, "wb") as f:
        f.write(resp.content)
    return dest_filename


def _post_prompt(graph, client_id):
    body = json.dumps({"prompt": graph, "client_id": client_id}).encode()
    req = urllib.request.Request(f"{COMFY}/prompt", data=body,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _wait_for_output(prompt_id, timeout_s=300):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        with urllib.request.urlopen(f"{COMFY}/history/{prompt_id}", timeout=30) as r:
            hist = json.loads(r.read())
        if prompt_id in hist and hist[prompt_id].get("outputs"):
            return hist[prompt_id]["outputs"]
        if prompt_id in hist and hist[prompt_id].get("status", {}).get("status_str") == "error":
            raise RuntimeError(hist[prompt_id]["status"])
        time.sleep(3)
    raise TimeoutError(f"prompt {prompt_id} did not finish in {timeout_s}s")


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    limit = None
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])

    cfg = load_config()
    characters, last_updated = load_profile_cache(cfg)
    if not characters:
        print("blizzard_profile_cache.json has no characters yet — the "
              "Blizzard Action hasn't populated it, or blizzard.enabled is "
              "false. Nothing to generate; not inventing roster members.")
        return 0

    targets = opted_in_characters(cfg, characters)
    if limit:
        targets = dict(list(targets.items())[:limit])
    if not targets:
        print("Cache has characters, but all are opted out (cast.opt_out "
              "in config.yml). Nothing to generate.")
        return 0

    os.makedirs(CAST_DIR, exist_ok=True)
    client_id = str(uuid.uuid4())
    generated = []
    for key, profile in targets.items():
        built = build_prompt(profile)
        if not built:
            print(f"  skip {key}: profile missing race/class")
            continue
        positive, negative = built

        ref_url = profile.get("transmog_render_url")
        if not ref_url:
            print(f"  skip {key}: no transmog render URL in cache")
            continue

        try:
            ref_filename = _download_reference_image(ref_url, f"transmog_{key}.png")
        except Exception as exc:
            print(f"  skip {key}: couldn't fetch transmog render ({exc})")
            continue

        seed = random.randint(1, 2**31 - 1)
        graph = build_ipadapter_graph(
            CKPT, LORA, CLIP_VISION, IPADAPTER_FILE, ref_filename,
            positive, negative, seed, filename_prefix=f"cast_crew/{key}",
        )
        print(f"=== submitting {key} ===")
        try:
            resp = _post_prompt(graph, client_id)
            outputs = _wait_for_output(resp["prompt_id"])
        except (urllib.error.HTTPError, RuntimeError, TimeoutError) as exc:
            print(f"  FAILED {key}: {exc}")
            continue

        for img in outputs.get("9", {}).get("images", []):
            src = os.path.join(COMFY_OUTPUT_DIR, img.get("subfolder", ""), img["filename"])
            if not os.path.exists(src):
                continue
            dst = os.path.join(CAST_DIR, f"{key}.png")
            shutil.copy2(src, dst)
            print(f"  saved -> {dst}")
            generated.append(dst)

    print(f"=== DONE: {len(generated)} generated ===")
    for path in generated:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

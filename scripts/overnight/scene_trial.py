"""Generate Healyeah in the APPROVED raidhall/scene style (w025 recipe).

Reuses the exact proven wiring — guild_board.cast_art.build_ipadapter_graph
with ip_weight 0.25, clip-skip-2, tiled VAE, and the detail pass — so the
output sits in the same visual family as Rakdisc's scene1_raidhall_w025,
which is the look Zach approved.

Fixing the earlier miss: the previous Healyeah came out as a FERAL
QUADRUPED dragon with no scene. He is a Dracthyr — a bipedal armoured
dragonkin — and an Augmentation Evoker, which is the BRONZE dragonflight:
sand, time, and fate magic. Both go in hard, positive and negative.

Several seeds per run; they are cheap and the pick is a judgement call.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from guild_board.cast_art import build_ipadapter_graph  # noqa: E402

from engine import (ComfyClient, collect_outputs, log, load_state,  # noqa: E402
                    mark_done, mark_failed, save_state, stage_input)

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "cast" / "healyeah"

CKPT = "Illustrious-XL-v1.1.safetensors"
LORA = "one_piece_wano_style.safetensors"
CLIP_VISION = "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"
IPADAPTER = "ip-adapter-plus_sdxl_vit-h.safetensors"

REF = REPO / "cast" / "healyeah" / "_real_transmog_reference.png"

# Read off his real transmog: tan/bronze scales, gold+white pauldrons with
# red gems, crimson gauntlets and armoured skirt, gold sun-boss belt, a
# glowing gold crystal in hand.
POSITIVE = (
    # SPECIES FIRST, and in words the model actually knows. "Dracthyr" is
    # not a concept it has — asking for one yields a human with wings, which
    # is exactly how the previous attempt failed. "Anthropomorphic dragon
    # man with a snout" is understood, and is what a Dracthyr looks like.
    "an anthropomorphic dragon man, a tall bipedal dragon-headed humanoid "
    "standing upright on two clawed legs, a draconic head with a long "
    "reptilian snout and sharp teeth, glowing reptilian eyes, no human face, "
    "tan and bronze scaled skin covering his whole body, "
    "large bronze membranous dragon wings spread wide behind him, "
    "curved dark horns swept back from his skull, "
    "ornate gold and white armored pauldrons set with red gems, "
    "crimson red armored gauntlets and a layered armored skirt, "
    "a gold belt with a glowing sun emblem, clawed feet, "
    "holding aloft a radiant glowing golden crystal, "
    "bronze dragonflight augmentation evoker, swirling golden sand and "
    "shimmering threads of time magic spiraling around him, "
    "standing inside a sunlit bronze dragon spire, ornate dragon stonework "
    "arches, warm golden shafts of light, Dragonflight Thaldraszus "
    "architecture, glowing bronze runes on the floor, "
    "anime illustration, soft cel shading, warm cinematic lighting, "
    "detailed painted background, full body, single character, "
    "heroic standing pose, facing the viewer"
)

NEGATIVE = (
    # The exact failure being corrected — twice over.
    "human face, human head, human skin, human man, humanoid face, "
    "bare human face, black hair, hair, anime boy, handsome man, "
    "feral dragon, quadruped dragon, dragon on all fours, four-legged "
    "dragon, wyvern, drake, full dragon body, animal dragon, "
    "demon, demonic, fel green, imp, devil, horned demon, "
    "elf, orc, furry, fur, magenta armor, pink armor, purple robe, "
    # Framing / quality.
    "plain background, empty background, no background, gradient background, "
    "cropped, cut off, out of frame, close-up, portrait crop, bust shot, "
    "multiple characters, two dragons, text, watermark, signature, logo, "
    "blurry, low detail, extra limbs, extra wings, deformed hands, "
    "photorealistic, 3d render"
)

SEEDS = [70201, 70202, 70203]


def main(argv):
    state = load_state()
    save_state(state)
    client = ComfyClient()
    OUT.mkdir(parents=True, exist_ok=True)

    log("=" * 62)
    log("SCENE TRIAL — Healyeah, approved w025 recipe, Dragonflight scene")
    if not client.healthy():
        log("ComfyUI not healthy", "ERROR")
        return 1
    if not REF.exists():
        log(f"missing transmog reference: {REF}", "ERROR")
        return 1

    ref_name = stage_input(REF, "healyeah_transmog_ref.png")
    log(f"  reference staged: {ref_name}")

    made = []
    for i, seed in enumerate(SEEDS, 1):
        key = f"scene:healyeah:{seed}"
        dest = OUT / f"healyeah_dragonflight_scene_w030_s{seed}.png"
        if key in state["done"] and dest.exists():
            log(f"  seed {seed}: already checkpointed")
            made.append(dest)
            continue
        graph = build_ipadapter_graph(
            CKPT, LORA, CLIP_VISION, IPADAPTER, ref_name,
            POSITIVE, NEGATIVE, seed,
            filename_prefix=f"overnight/healyeah_scene_{seed}",
            ip_weight=0.30, lora_strength=0.85, detail_pass=True,
        )
        t0 = time.time()
        try:
            outputs = client.run(graph, label=key, stall_limit_s=1200)
            paths = collect_outputs(outputs, node="9")
            if not paths:
                raise RuntimeError("no image returned")
            dest.write_bytes(paths[0].read_bytes())
            mark_done(state, key, dest)
            made.append(dest)
            log(f"  [{i}/{len(SEEDS)}] seed {seed} {time.time()-t0:.0f}s -> {dest.name}")
        except Exception as exc:
            mark_failed(state, key, exc)
            log(f"  [{i}/{len(SEEDS)}] seed {seed} FAILED (continuing): {exc}",
                "ERROR")

    log(f"SCENE TRIAL DONE — {len(made)}/{len(SEEDS)} produced")
    log("=" * 62)
    return 0 if made else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

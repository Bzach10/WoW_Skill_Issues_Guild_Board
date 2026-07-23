#!/usr/bin/env python3
"""Run the 10-character Nano Banana Pro vs standard model-quality
comparison. Calls scripts/runpod_edit.py for each (character, model)
pair with the same style prompt and the same 3:4-cropped input image.
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = REPO_ROOT / "cast" / "_rnd_img2img" / "model_bakeoff_v2" / "inputs"
OUT_DIR = REPO_ROOT / "cast" / "_rnd_img2img" / "model_bakeoff_v2" / "outputs"

CHARACTERS = [
    ("rakdisc-proudmoore", "Rakdisc", "Nightborne", "Priest"),
    ("floofwall-queldorei", "Floofwall", "Pandaren", "Monk"),
    ("healyeah-queldorei", "Healyeah", "Dracthyr", "Evoker"),
    ("balcmeg-queldorei", "Balcmeg", "Mag'har Orc", "Warrior"),
    ("jilk-eldrethalas", "Jilk", "Draenei", "Shaman"),
    ("mushabi-anubarak", "Mushabi", "Orc", "Rogue"),
    ("beroben-emerald-dream", "Beroben", "Gnome", "Mage"),
    ("kathrobbin-zuljin", "Kathrobbin", "Blood Elf", "Paladin"),
    ("yur-whisperwind", "Yur", "Night Elf", "Demon Hunter"),
    ("flemel-area-52", "Flemel", "Troll", "Warlock"),
]

PROMPT_TEMPLATE = (
    "Restyle this World of Warcraft character transmog render into clean "
    "bold-ink anime art in the style of One Piece: bold black linework, "
    "flat cel shading, vibrant saturated colors, dynamic heroic action "
    "pose. This character is a {race} {klass}. Preserve the character's "
    "exact armor, weapons, colors, and gear details from the reference "
    "image precisely, do not invent new equipment. Keep the character's "
    "race accurate (skin tone, ears, tusks, horns, fur, or other racial "
    "features exactly as shown). Add a fitting class-fantasy background "
    "scene matching their class and spec. Full character visible head to "
    "toe, portrait framing, 3:4 aspect ratio."
)

MODELS = ["nano-banana-pro-edit", "nano-banana-edit"]


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for entry, name, race, klass in CHARACTERS:
        if only and only != entry:
            continue
        input_path = INPUT_DIR / f"{entry}.png"
        prompt = PROMPT_TEMPLATE.format(race=race, klass=klass)
        for model in MODELS:
            tag = "pro" if model == "nano-banana-pro-edit" else "cheap"
            out_path = OUT_DIR / f"{entry}_{tag}.png"
            if out_path.exists():
                print(f"[skip] {out_path} already exists")
                continue
            cmd = [
                sys.executable, str(REPO_ROOT / "scripts" / "runpod_edit.py"),
                model, str(out_path),
                "--prompt", prompt,
                "--image", str(input_path),
            ]
            if model == "nano-banana-pro-edit":
                cmd += ["--extra", "resolution=2K"]
            print(f"[run] {name} ({model})")
            result = subprocess.run(cmd, cwd=REPO_ROOT)
            if result.returncode != 0:
                print(f"[FAILED] {name} {model}", file=sys.stderr)


if __name__ == "__main__":
    main()

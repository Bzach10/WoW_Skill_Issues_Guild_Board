"""Style presets for the render-driven cast pipeline: every knob that
defines a visual style (checkpoint, LoRA(s), sampler, denoise, ControlNet
config, prompt) lives in one named YAML file under styles/. The pipeline
itself (guild_board/render_pipeline.py) is style-agnostic — it takes a
style dict and never hardcodes a look. A new art style later is a new
preset file + a regenerate, not a code change.

Same fail-open convention as guild_board/theme.py: a missing, partial, or
broken preset file falls back to DEFAULT_STYLE for whatever it's missing,
rather than crashing a run.
"""

import copy
import os

import yaml

STYLES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "styles")

DEFAULT_STYLE = {
    "name": "one_piece",
    "model": {
        "checkpoint": "Illustrious-XL-v1.1.safetensors",
        "clip_skip": 2,
    },
    "loras": [
        {"name": "one_piece_wano_style.safetensors", "strength": 1.0},
    ],
    "sampler": {
        "name": "dpmpp_2m",
        "scheduler": "karras",
        "cfg": 6.5,
        "steps": 30,
    },
    "img2img": {
        "denoise": 0.65,
    },
    "controlnet": {
        "enabled": False,
        "model": "controlnet-union-sdxl-1.0.safetensors",
        # xinsir's union model needs SetUnionControlNetType to pick which
        # bundled conditioning type it's receiving; ComfyUI's stock node
        # exposes it as this exact combo-box string (not an index).
        "union_type": "canny/lineart/anime_lineart/mlsd",
        "preprocessor": "canny",
        # Canny node thresholds are normalized 0-1, NOT 0-255.
        "canny_low_threshold": 0.2,
        "canny_high_threshold": 0.4,
        "strength": 0.5,
        "start_percent": 0.0,
        "end_percent": 0.6,
    },
    "canvas": {
        "width": 832,
        "height": 1216,
    },
    "prompt": {
        "positive_suffix": (
            "one_piece_wano_style, One Piece anime art style, bold thick "
            "black ink outlines, cel shading with subtle soft-edged "
            "shadow shapes for a light touch of volume and form, a faint "
            "hint of rim light, mostly flat-colored fills, expressive "
            "anime-style face with big eyes, single character "
            "illustration, full body, original character, no text, no "
            "watermark, no signature, no logo, isolated on a plain solid "
            "flat light-gray background, no scenery, no environment"
        ),
        "negative": (
            "Luffy, Monkey D. Luffy, straw hat, strawhat pirates, Roronoa "
            "Zoro, Zoro, Nami, Sanji, Usopp, Tony Tony Chopper, Chopper, "
            "Nico Robin, Franky, Brook, Trafalgar Law, Ace, Shanks, named "
            "anime characters, existing anime characters, copyrighted "
            "characters, photorealistic, photo, 3d render, video game "
            "render, realistic skin texture, semi-realistic shading, "
            "painterly, soft airbrushed shading, smooth gradient shading, "
            "western comic style, dark muddy colors, canvas texture, "
            "fabric texture, blurry, low detail, text, watermark, "
            "signature, logo, extra limbs, extra fingers, deformed hands, "
            "cropped, out of frame, reference sheet, turnaround, multiple "
            "poses, grid, chibi, abstract, illegible, calligraphy, "
            "symbol, logo shape, dark background, night sky, busy "
            "background, background scenery, ornate background"
        ),
    },
    "background": {
        # Generation targets a plain/neutral background on purpose — the
        # Healyeah incident showed rembg can genuinely fail (not just a
        # soft edge, a real segmentation miss) on a dark subject against a
        # dark/busy background. Enforcing a neutral background at
        # generation time is the fix, not fancier matting after the fact.
        "mode": "neutral",
    },
    "cutout": {
        "model": "u2net",
        # Off by default: tested both ways during pipeline validation.
        # Alpha matting didn't fix the Healyeah segmentation failure
        # (that needed a neutral background at generation time, which
        # the prompt above already enforces) and it introduced a new
        # color-bleed artifact on an otherwise-clean white-background
        # render (Rakdisc). Plain u2net was clean in both cases.
        "alpha_matting": False,
    },
}


def _deep_merge(base, override):
    """Recursive dict merge; override wins, lists replace wholesale."""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_style(name, styles_dir=None):
    """Load styles/<name>.yaml merged over DEFAULT_STYLE. Fails open: a
    missing or broken file just means the default style — a style-preset
    typo should never crash a generation run.
    """
    styles_dir = styles_dir or STYLES_DIR
    path = os.path.join(styles_dir, f"{name}.yaml")
    try:
        with open(path, encoding="utf-8") as f:
            override = yaml.safe_load(f) or {}
    except (FileNotFoundError, yaml.YAMLError):
        override = {}
    style = _deep_merge(DEFAULT_STYLE, override)
    style["name"] = name
    return style


def list_styles(styles_dir=None):
    """Every style preset file available (by filename, without extension)."""
    styles_dir = styles_dir or STYLES_DIR
    if not os.path.isdir(styles_dir):
        return []
    return sorted(
        os.path.splitext(f)[0] for f in os.listdir(styles_dir)
        if f.endswith((".yaml", ".yml"))
    )

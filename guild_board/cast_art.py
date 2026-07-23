"""Build One Piece style illustration prompts + IP-Adapter graphs for
real roster members, driven entirely by guild_board.blizzard's profile
cache (gender/race/class/active spec/transmog render URL).

This module never invents a character: every function here either takes
a real profile dict (from blizzard_profile_cache.json) or returns
None/empty when there's nothing real to work with. scripts/generate_cast.py
is the thing that actually loops the roster and drives ComfyUI.
"""

CLASS_FLAVOR = {
    "Warrior": "wielding a massive two-handed weapon, battle-worn plate armor",
    "Paladin": "radiant holy plate armor, wielding a glowing hammer, a faint halo of light",
    "Hunter": "leather ranger gear, a bow in hand, a loyal beast companion at her side",
    "Rogue": "dark leather assassin gear, twin daggers, a hood pulled low",
    "Priest": "flowing priest robes, a faint glow of light or shadow around the hands",
    "Death Knight": "dark unholy plate armor, wreathed in frost runes, wielding a runeblade",
    "Shaman": "tribal elemental-themed gear, crackling with lightning, wielding a totem",
    "Mage": "an arcane spellcaster's robes, a glowing staff, sparks of arcane energy",
    "Warlock": "dark occult robes, wreathed in green fel fire, a small demon companion nearby",
    "Monk": "martial artist's robes, fists wreathed in glowing chi energy, a dynamic stance",
    "Druid": "wild nature-themed leather gear, faint animal features, wreathed in nature energy",
    "Demon Hunter": "blindfolded glowing green eyes, fel-green tattoos, twin glaives, small bat wings",
    "Evoker": "draconic-inspired robes, faint dragon-scale patterns, glowing elemental energy",
}

STYLE_SUFFIX = (
    ", one_piece_wano_style, One Piece anime art style, bold thick black ink "
    "outlines, flat cel shading, exaggerated cartoonish anime proportions, "
    "expressive comic linework, dynamic goofy action pose, big expressive "
    "anime eyes, single character illustration, one pose only, full body, "
    "isolated on a plain solid flat background, no scenery, no environment, "
    "no magic circle, original character, no text, no watermark, no "
    "signature, no logo"
)

BASE_NEGATIVE = (
    "Luffy, Monkey D. Luffy, straw hat, strawhat pirates, Roronoa Zoro, Zoro, "
    "Nami, Sanji, Usopp, Tony Tony Chopper, Chopper, Nico Robin, Franky, "
    "Brook, Trafalgar Law, Ace, Shanks, named anime characters, existing "
    "anime characters, copyrighted characters, cosplay, fan art of an "
    "existing character, photorealistic, photo, 3d render, realistic skin "
    "texture, western comic style, dark muddy colors, blurry, low detail, "
    "text, watermark, signature, logo, extra limbs, extra fingers, "
    "deformed hands, cropped, out of frame, bust shot, close-up, portrait "
    "crop, background scenery, magic circle, stars, clouds, ornate "
    "background, reference sheet, character sheet, model sheet, turnaround, "
    "multiple views, multiple poses, grid, tiled, comparison chart, "
    "multiple characters, split screen, panels, chibi"
)

GENDER_WORD = {"Male": "male", "Female": "female"}
OPPOSITE_GENDER_NEGATIVE = {"Male": "female, woman, girl", "Female": "male, boy, man, masculine"}


def build_prompt(profile):
    """profile: one entry from blizzard_profile_cache.json's "characters"
    dict (has name/realm/gender/race/class/active_spec/transmog_render_url).

    Returns (positive_prompt, negative_prompt) or None if the profile is
    missing the fields needed to describe a real character.
    """
    race = (profile.get("race") or "").strip()
    cls = (profile.get("class") or "").strip()
    if not race or not cls:
        return None

    gender = GENDER_WORD.get(profile.get("gender"), "")
    spec = (profile.get("active_spec") or "").strip()
    flavor = CLASS_FLAVOR.get(cls, "adventurer's gear, a weapon at the ready")
    spec_bit = f"{spec} specialization, " if spec else ""

    positive = (
        f"{gender} {race} {cls}, {spec_bit}{flavor}, huge goofy confident "
        f"grin, dynamic action pose" + STYLE_SUFFIX
    ).strip()

    negative = BASE_NEGATIVE
    opposite = OPPOSITE_GENDER_NEGATIVE.get(profile.get("gender"))
    if opposite:
        negative = f"{opposite}, {negative}"

    return positive, negative


DETAIL_UPSCALE_MODEL = "4x-UltraSharp.pth"


def build_ipadapter_graph(ckpt, lora, clip_vision, ipadapter_file, ref_image_filename,
                          positive, negative, seed, filename_prefix,
                          width=832, height=1216, ip_weight=0.6,
                          weight_type="linear", lora_strength=0.85,
                          steps=32, detail_pass=True, hires_scale=1.5,
                          hires_denoise=0.45, hires_steps=20,
                          upscale_model=DETAIL_UPSCALE_MODEL):
    """Checkpoint -> LoRA -> clip-skip-2 -> IPAdapter(reference image) ->
    KSampler -> SaveImage. Mirrors the wiring proven by
    scripts/generate_cast.py's smoke test.

    All VAE decode/encode steps use the tiled nodes (VAEDecodeTiled /
    VAEEncodeTiled, 512px tiles), not the plain ones. Found the hard way:
    KSampler finished a 30-step pass in 17s while the plain VAEDecode right
    after it hung indefinitely under tight VRAM (Comfy Desktop's dynamic
    VRAM staging never recovered). Tiled decode/encode uses a fraction of
    the VRAM per chunk and sidesteps that hang regardless of what else is
    using the GPU.

    detail_pass=True (the default) adds a second stage for sharper, more
    refined output: decode -> ESRGAN upscale (4x-UltraSharp) -> downscale
    to hires_scale x the base resolution -> re-encode -> a second, lower-
    denoise KSampler refinement pass using the SAME IPAdapter-conditioned
    model, before the final decode. This needs no new checkpoint/LoRA —
    just the one small (67MB) upscale model already in models/upscale_models.
    Set detail_pass=False to fall back to the original single-pass graph.
    """
    graph = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "2": {"class_type": "LoraLoader",
              "inputs": {"model": ["1", 0], "clip": ["1", 1], "lora_name": lora,
                         "strength_model": lora_strength, "strength_clip": lora_strength}},
        "10": {"class_type": "CLIPSetLastLayer", "inputs": {"clip": ["2", 1], "stop_at_clip_layer": -2}},
        "11": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": clip_vision}},
        "12": {"class_type": "IPAdapterModelLoader", "inputs": {"ipadapter_file": ipadapter_file}},
        "13": {"class_type": "LoadImage", "inputs": {"image": ref_image_filename}},
        "14": {"class_type": "IPAdapterAdvanced",
               "inputs": {"model": ["2", 0], "ipadapter": ["12", 0], "image": ["13", 0],
                          "weight": ip_weight, "weight_type": weight_type,
                          "combine_embeds": "concat", "start_at": 0.0, "end_at": 1.0,
                          "embeds_scaling": "V only", "clip_vision": ["11", 0]}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"batch_size": 1, "height": height, "width": width}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["10", 0], "text": positive}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["10", 0], "text": negative}},
        "3": {"class_type": "KSampler",
              "inputs": {"cfg": 6.5, "denoise": 1.0, "latent_image": ["5", 0],
                         "model": ["14", 0], "negative": ["7", 0], "positive": ["6", 0],
                         "sampler_name": "dpmpp_2m", "scheduler": "karras",
                         "seed": seed, "steps": steps}},
    }

    if not detail_pass:
        graph["8"] = {"class_type": "VAEDecodeTiled",
              "inputs": {"samples": ["3", 0], "vae": ["1", 2], "tile_size": 512,
                         "overlap": 64, "temporal_size": 64, "temporal_overlap": 8}}
        graph["9"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": filename_prefix, "images": ["8", 0]}}
        return graph

    graph.update({
        "20": {"class_type": "VAEDecodeTiled",
              "inputs": {"samples": ["3", 0], "vae": ["1", 2], "tile_size": 512,
                         "overlap": 64, "temporal_size": 64, "temporal_overlap": 8}},
        "21": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": upscale_model}},
        "22": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["21", 0], "image": ["20", 0]}},
        "23": {"class_type": "ImageScale",
               "inputs": {"image": ["22", 0], "upscale_method": "lanczos", "crop": "disabled",
                          "width": int(width * hires_scale), "height": int(height * hires_scale)}},
        "24": {"class_type": "VAEEncodeTiled",
               "inputs": {"pixels": ["23", 0], "vae": ["1", 2], "tile_size": 512,
                          "overlap": 64, "temporal_size": 64, "temporal_overlap": 8}},
        "16": {"class_type": "KSampler",
               "inputs": {"cfg": 6.5, "denoise": hires_denoise, "latent_image": ["24", 0],
                          "model": ["14", 0], "negative": ["7", 0], "positive": ["6", 0],
                          "sampler_name": "dpmpp_2m", "scheduler": "karras",
                          "seed": seed, "steps": hires_steps}},
        "8": {"class_type": "VAEDecodeTiled",
              "inputs": {"samples": ["16", 0], "vae": ["1", 2], "tile_size": 512,
                         "overlap": 64, "temporal_size": 64, "temporal_overlap": 8}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": filename_prefix, "images": ["8", 0]}},
    })
    return graph


def opted_in_characters(cfg, characters):
    """characters: the dict loaded from blizzard_profile_cache.json's
    "characters" key. Filters out config.yml's cast.opt_out entries
    (lowercase "name-realm", same convention as filters.always_exclude).
    """
    cast_cfg = (cfg or {}).get("cast", {})
    opt_out = {n.lower() for n in cast_cfg.get("opt_out", [])}
    return {key: profile for key, profile in (characters or {}).items()
            if key.lower() not in opt_out}

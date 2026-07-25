"""The render-driven cast pipeline: one function, identical for every
character — the real Blizzard transmog render is the only variable. All
visual-style knobs (checkpoint, LoRA(s), sampler, denoise, ControlNet,
prompt) come from a guild_board.styles preset, never hardcoded here, so a
new art style later is a new preset file, not a code change.

    crop_to_content()  ->  restyle_via_img2img()  ->  cutout_to_board()
           (PIL, CPU)         (ComfyUI, GPU)            (rembg, CPU)

R&D finding this is built on: running img2img directly on the raw
transmog render fails badly, because Blizzard's renders place the
character in only a small fraction of the canvas (confirmed: one
render's actual content was ~21% of the image width). At low denoise
that framing survives almost exactly (a tiny, illegible character); at
high denoise the model has too little real structure to anchor to and
hallucinates the character away into an abstract shape. crop_to_content()
fixes that — it is not optional set-dressing.

ControlNet (Canny, from the same cropped render) is layered on top
specifically to stop a second problem: identity loss at the denoise
levels needed for full style transfer (a race's hair/ears/skin tone
could disappear by denoise 0.7 with no ControlNet). Locking the edge
structure lets denoise run high enough for real style transfer while the
silhouette stays anchored to the real render.
"""

import json
import os
import random
import time
import urllib.error
import urllib.request

from PIL import Image, ImageOps

from guild_board.styles import load_style

COMFY = "http://127.0.0.1:8188"
COMFY_INPUT_DIR = r"C:\Users\zachf\AppData\Local\Comfy-Desktop\ComfyUI-Shared\input"
COMFY_OUTPUT_DIR = r"C:\Users\zachf\AppData\Local\Comfy-Desktop\ComfyUI-Shared\output"
CAST_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cast")


def stage_render_from_url(url, dest_filename, comfy_input_dir=None):
    """Download a transmog render (or any image URL) into ComfyUI's input
    dir under dest_filename, ready for restyle_via_img2img(). Returns
    dest_filename for convenience (that's what restyle_via_img2img wants).
    """
    comfy_input_dir = comfy_input_dir or COMFY_INPUT_DIR
    os.makedirs(comfy_input_dir, exist_ok=True)
    dest_path = os.path.join(comfy_input_dir, dest_filename)
    with urllib.request.urlopen(url, timeout=30) as r:
        data = r.read()
    with open(dest_path, "wb") as f:
        f.write(data)
    return dest_filename


def crop_to_content(src_path, dst_path, size, margin_frac=0.06):
    """Crop a transmog render to its alpha-channel content bbox (plus a
    small margin) then fit it onto a plain white canvas of `size`. See
    the module docstring — this is a correctness fix, not optional.
    """
    img = Image.open(src_path).convert("RGBA")
    bbox = img.getchannel("A").getbbox()
    if bbox:
        x0, y0, x1, y1 = bbox
        w, h = x1 - x0, y1 - y0
        mx, my = int(w * margin_frac), int(h * margin_frac)
        x0, y0 = max(0, x0 - mx), max(0, y0 - my)
        x1, y1 = min(img.width, x1 + mx), min(img.height, y1 + my)
        img = img.crop((x0, y0, x1, y1))
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    flat = Image.alpha_composite(bg, img).convert("RGB")
    fitted = ImageOps.contain(flat, size)
    canvas = Image.new("RGB", size, (255, 255, 255))
    x, y = (size[0] - fitted.width) // 2, (size[1] - fitted.height) // 2
    canvas.paste(fitted, (x, y))
    canvas.save(dst_path)
    return dst_path


def build_img2img_graph(style, src_image_filename, seed):
    """Pure function: style dict + a filename already staged in
    ComfyUI's input dir -> the ComfyUI API graph dict. No network calls —
    easy to unit test the wiring without a running server.
    """
    graph = {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": style["model"]["checkpoint"]}},
    }

    # Chain every LoRA in the preset onto the checkpoint's model/clip.
    model_link, clip_link = ["1", 0], ["1", 1]
    for i, lora in enumerate(style.get("loras", [])):
        node_id = f"lora{i}"
        graph[node_id] = {
            "class_type": "LoraLoader",
            "inputs": {"model": model_link, "clip": clip_link,
                       "lora_name": lora["name"],
                       "strength_model": lora["strength"],
                       "strength_clip": lora["strength"]},
        }
        model_link, clip_link = [node_id, 0], [node_id, 1]

    graph["10"] = {"class_type": "CLIPSetLastLayer",
                   "inputs": {"clip": clip_link, "stop_at_clip_layer": -style["model"]["clip_skip"]}}
    graph["13"] = {"class_type": "LoadImage", "inputs": {"image": src_image_filename}}
    graph["14"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["13", 0], "vae": ["1", 2]}}
    graph["6"] = {"class_type": "CLIPTextEncode",
                  "inputs": {"clip": ["10", 0], "text": style["prompt"]["positive_suffix"]}}
    graph["7"] = {"class_type": "CLIPTextEncode",
                  "inputs": {"clip": ["10", 0], "text": style["prompt"]["negative"]}}

    positive_link, negative_link = ["6", 0], ["7", 0]

    cn = style.get("controlnet", {})
    if cn.get("enabled"):
        graph["20"] = {"class_type": "Canny",
                       "inputs": {"image": ["13", 0],
                                  "low_threshold": cn["canny_low_threshold"],
                                  "high_threshold": cn["canny_high_threshold"]}}
        graph["21"] = {"class_type": "ControlNetLoader",
                       "inputs": {"control_net_name": cn["model"]}}
        graph["22"] = {"class_type": "SetUnionControlNetType",
                       "inputs": {"control_net": ["21", 0], "type": cn["union_type"]}}
        graph["23"] = {"class_type": "ControlNetApplyAdvanced",
                       "inputs": {"positive": positive_link, "negative": negative_link,
                                  "control_net": ["22", 0], "image": ["20", 0],
                                  "strength": cn["strength"],
                                  "start_percent": cn["start_percent"],
                                  "end_percent": cn["end_percent"], "vae": ["1", 2]}}
        positive_link, negative_link = ["23", 0], ["23", 1]

    graph["3"] = {"class_type": "KSampler",
                  "inputs": {"cfg": style["sampler"]["cfg"], "denoise": style["img2img"]["denoise"],
                             "latent_image": ["14", 0], "model": model_link,
                             "negative": negative_link, "positive": positive_link,
                             "sampler_name": style["sampler"]["name"],
                             "scheduler": style["sampler"]["scheduler"],
                             "seed": seed, "steps": style["sampler"]["steps"]}}
    graph["8"] = {"class_type": "VAEDecodeTiled",
                  "inputs": {"samples": ["3", 0], "vae": ["1", 2], "tile_size": 512,
                             "overlap": 64, "temporal_size": 64, "temporal_overlap": 8}}
    graph["9"] = {"class_type": "SaveImage",
                  "inputs": {"filename_prefix": "cast_render_pipeline/restyle", "images": ["8", 0]}}
    return graph


def _submit_and_wait(graph, client_id, timeout_s=300):
    body = json.dumps({"prompt": graph, "client_id": client_id}).encode()
    req = urllib.request.Request(f"{COMFY}/prompt", data=body,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        pid = json.loads(r.read())["prompt_id"]

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        with urllib.request.urlopen(f"{COMFY}/history/{pid}", timeout=30) as r:
            hist = json.loads(r.read())
        if pid in hist and hist[pid].get("outputs"):
            return hist[pid]["outputs"]
        if pid in hist and hist[pid].get("status", {}).get("status_str") == "error":
            raise RuntimeError(f"ComfyUI job {pid} errored: {hist[pid]['status']}")
        time.sleep(3)
    raise TimeoutError(f"ComfyUI job {pid} did not finish in {timeout_s}s")


def restyle_via_img2img(character_slug, ref_render_filename, style_name="one_piece",
                        seed=None, client_id="render-pipeline"):
    """crop -> stage into ComfyUI's input dir -> img2img restyle (+
    ControlNet if the style enables it). Returns the absolute path to the
    restyled (still opaque) image in ComfyUI's own output directory.

    ref_render_filename must already be staged in COMFY_INPUT_DIR.
    """
    style = load_style(style_name)
    seed = seed if seed is not None else random.randint(1, 2**31 - 1)

    ref_src = os.path.join(COMFY_INPUT_DIR, ref_render_filename)
    canvas = (style["canvas"]["width"], style["canvas"]["height"])
    cropped_filename = f"{character_slug}_{style_name}_src.png"
    cropped_path = os.path.join(COMFY_INPUT_DIR, cropped_filename)
    crop_to_content(ref_src, cropped_path, canvas)

    graph = build_img2img_graph(style, cropped_filename, seed)
    outputs = _submit_and_wait(graph, client_id)

    for img in outputs.get("9", {}).get("images", []):
        path = os.path.join(COMFY_OUTPUT_DIR, img.get("subfolder", ""), img["filename"])
        if os.path.exists(path):
            return path, cropped_path
    raise RuntimeError(f"img2img job for {character_slug} produced no output image")


_rembg_sessions = {}


def cutout_to_board(src_path, character_slug, style_name="one_piece", cast_root=None):
    """rembg cut-out -> cast/<slug>/<style>/board.png (RGBA, real alpha).
    CPU only. Alpha matting is on by default per the style preset, but
    per the Healyeah incident: matting alone cannot recover a genuine
    segmentation failure (dark subject against a dark/busy background
    misread as background, not just a soft edge) — the style preset's
    plain-background prompt suffix is the real fix for that, this is a
    secondary edge-quality pass.
    """
    from rembg import new_session, remove

    style = load_style(style_name)
    model_name = style["cutout"]["model"]
    if model_name not in _rembg_sessions:
        _rembg_sessions[model_name] = new_session(model_name, providers=["CPUExecutionProvider"])
    session = _rembg_sessions[model_name]

    with open(src_path, "rb") as f:
        data = f.read()
    kwargs = {}
    if style["cutout"].get("alpha_matting"):
        kwargs.update(alpha_matting=True, alpha_matting_foreground_threshold=240,
                      alpha_matting_background_threshold=10, alpha_matting_erode_size=10)
    out_bytes = remove(data, session=session, **kwargs)

    cast_root = cast_root or CAST_ROOT
    out_dir = os.path.join(cast_root, character_slug, style_name)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "board.png")
    with open(out_path, "wb") as f:
        f.write(out_bytes)
    return out_path


def render_cast_member(character_slug, ref_render_filename, style_name="one_piece",
                       seed=None, cast_root=None):
    """The full loop: crop -> img2img (+ ControlNet) -> cut-out ->
    cast/<slug>/<style>/board.png. Also saves the cropped source render
    to cast/<slug>/_render.png (the manifest's "source_render" field).

    Returns (board_path, source_render_path).
    """
    cast_root = cast_root or CAST_ROOT
    restyled_path, cropped_src_path = restyle_via_img2img(
        character_slug, ref_render_filename, style_name, seed)
    board_path = cutout_to_board(restyled_path, character_slug, style_name, cast_root)

    char_dir = os.path.join(cast_root, character_slug)
    os.makedirs(char_dir, exist_ok=True)
    source_render_path = os.path.join(char_dir, "_render.png")
    Image.open(cropped_src_path).save(source_render_path)

    return board_path, source_render_path

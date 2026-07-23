"""Offline tests for guild_board.render_pipeline: crop_to_content (pure
PIL) and build_img2img_graph (pure dict-building, no ComfyUI needed)."""

from PIL import Image

from guild_board.render_pipeline import (
    _face_crop_box,
    _parse_face_bbox_output,
    build_face_refine_graph,
    build_img2img_graph,
    crop_to_content,
    stage_render_from_url,
)
from guild_board.styles import load_style


def _make_test_render(tmp_path, canvas=(400, 300), content_box=(150, 100, 250, 200)):
    """A synthetic 'Blizzard render': mostly-transparent canvas with a
    small opaque colored square standing in for the character, exactly
    like the real problem this pipeline works around.
    """
    img = Image.new("RGBA", canvas, (0, 0, 0, 0))
    x0, y0, x1, y1 = content_box
    for x in range(x0, x1):
        for y in range(y0, y1):
            img.putpixel((x, y), (200, 50, 50, 255))
    path = str(tmp_path / "fake_render.png")
    img.save(path)
    return path


def test_crop_to_content_fills_the_frame(tmp_path):
    src = _make_test_render(tmp_path)
    dst = str(tmp_path / "cropped.png")
    crop_to_content(src, dst, size=(832, 1216))

    out = Image.open(dst).convert("RGB")
    assert out.size == (832, 1216)

    # The colored content should now occupy a much larger fraction of the
    # canvas than the tiny 100x100 patch did in the 400x300 original —
    # that fraction growing is the entire point of this function.
    colored_pixels = sum(
        1 for x in range(0, out.width, 4) for y in range(0, out.height, 4)
        if out.getpixel((x, y))[0] > 150 and out.getpixel((x, y))[1] < 100
    )
    total_sampled = (out.width // 4) * (out.height // 4)
    assert colored_pixels / total_sampled > 0.15  # was ~8% of the original canvas


def test_crop_to_content_handles_fully_transparent_image(tmp_path):
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    src = str(tmp_path / "blank.png")
    img.save(src)
    dst = str(tmp_path / "blank_out.png")
    crop_to_content(src, dst, size=(832, 1216))  # must not raise on getbbox() -> None
    assert Image.open(dst).size == (832, 1216)


def test_build_img2img_graph_basic_wiring():
    style = load_style("one_piece")
    style["controlnet"]["enabled"] = False
    graph = build_img2img_graph(style, "some_render.png", seed=123)

    assert graph["1"]["inputs"]["ckpt_name"] == style["model"]["checkpoint"]
    assert graph["13"]["inputs"]["image"] == "some_render.png"
    assert graph["14"]["inputs"]["pixels"] == ["13", 0]
    assert graph["6"]["inputs"]["text"] == style["prompt"]["positive_suffix"]
    assert graph["7"]["inputs"]["text"] == style["prompt"]["negative"]
    assert graph["3"]["inputs"]["denoise"] == style["img2img"]["denoise"]
    assert graph["3"]["inputs"]["seed"] == 123
    # no ControlNet nodes when disabled
    assert "20" not in graph and "21" not in graph and "23" not in graph
    # KSampler conditioning goes straight to the plain CLIPTextEncode nodes
    assert graph["3"]["inputs"]["positive"] == ["6", 0]
    assert graph["3"]["inputs"]["negative"] == ["7", 0]


def test_build_img2img_graph_single_lora_chains_from_checkpoint():
    style = load_style("one_piece")
    style["controlnet"]["enabled"] = False
    graph = build_img2img_graph(style, "render.png", seed=1)

    assert graph["lora0"]["inputs"]["model"] == ["1", 0]
    assert graph["lora0"]["inputs"]["clip"] == ["1", 1]
    assert graph["lora0"]["inputs"]["lora_name"] == style["loras"][0]["name"]
    # sampler's model comes from the last LoRA in the chain, not the raw checkpoint
    assert graph["3"]["inputs"]["model"] == ["lora0", 0]
    assert graph["10"]["inputs"]["clip"] == ["lora0", 1]


def test_build_img2img_graph_chains_multiple_loras():
    style = load_style("one_piece")
    style["controlnet"]["enabled"] = False
    style["loras"] = [
        {"name": "first.safetensors", "strength": 1.0},
        {"name": "second.safetensors", "strength": 0.7},
    ]
    graph = build_img2img_graph(style, "render.png", seed=1)

    assert graph["lora0"]["inputs"]["model"] == ["1", 0]
    assert graph["lora1"]["inputs"]["model"] == ["lora0", 0]
    assert graph["lora1"]["inputs"]["clip"] == ["lora0", 1]
    assert graph["3"]["inputs"]["model"] == ["lora1", 0]


def test_build_img2img_graph_controlnet_wiring_when_enabled():
    style = load_style("one_piece")
    style["controlnet"]["enabled"] = True
    graph = build_img2img_graph(style, "render.png", seed=42)

    assert graph["20"]["class_type"] == "Canny"
    assert graph["20"]["inputs"]["image"] == ["13", 0]
    assert graph["20"]["inputs"]["low_threshold"] == style["controlnet"]["canny_low_threshold"]

    assert graph["21"]["class_type"] == "ControlNetLoader"
    assert graph["21"]["inputs"]["control_net_name"] == style["controlnet"]["model"]

    assert graph["22"]["class_type"] == "SetUnionControlNetType"
    assert graph["22"]["inputs"]["type"] == style["controlnet"]["union_type"]
    assert graph["22"]["inputs"]["control_net"] == ["21", 0]

    assert graph["23"]["class_type"] == "ControlNetApplyAdvanced"
    assert graph["23"]["inputs"]["control_net"] == ["22", 0]
    assert graph["23"]["inputs"]["image"] == ["20", 0]
    assert graph["23"]["inputs"]["positive"] == ["6", 0]
    assert graph["23"]["inputs"]["negative"] == ["7", 0]

    # KSampler now conditions on the ControlNet-wrapped outputs, not the raw ones
    assert graph["3"]["inputs"]["positive"] == ["23", 0]
    assert graph["3"]["inputs"]["negative"] == ["23", 1]


def test_build_img2img_graph_uses_tiled_vae_decode():
    style = load_style("one_piece")
    graph = build_img2img_graph(style, "render.png", seed=1)
    assert graph["8"]["class_type"] == "VAEDecodeTiled"


def test_stage_render_from_url_writes_into_comfy_input_dir(tmp_path, monkeypatch):
    fake_bytes = b"not-really-a-png-but-bytes-are-bytes"

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return fake_bytes

    monkeypatch.setattr(
        "guild_board.render_pipeline.urllib.request.urlopen",
        lambda url, timeout=30: _FakeResponse(),
    )

    dest_dir = str(tmp_path / "comfy_input")
    result = stage_render_from_url("https://example.com/fake-render.png",
                                    "some-slug_transmog.png", comfy_input_dir=dest_dir)

    assert result == "some-slug_transmog.png"
    staged_path = tmp_path / "comfy_input" / "some-slug_transmog.png"
    assert staged_path.read_bytes() == fake_bytes


def test_parse_face_bbox_output_extracts_first_face():
    outputs = {
        "4": {"text": ['[\n    [\n        {"x": 474.7, "y": 83.6, "width": 44.1, '
                       '"height": 52.8, "label": "face", "score": 0.34}\n    ]\n]']},
    }
    bbox = _parse_face_bbox_output(outputs)
    assert bbox == {"x": 474.7, "y": 83.6, "width": 44.1, "height": 52.8,
                     "label": "face", "score": 0.34}


def test_parse_face_bbox_output_none_when_no_face_detected():
    # MediaPipeFaceLandmarker's missing_frame_fallback="empty" produces an
    # empty per-frame list, not a missing key — must not crash on this.
    assert _parse_face_bbox_output({"4": {"text": ["[[]]"]}}) is None


def test_parse_face_bbox_output_none_when_node_missing():
    assert _parse_face_bbox_output({}) is None


def test_parse_face_bbox_output_none_on_garbage_text():
    assert _parse_face_bbox_output({"4": {"text": ["not json"]}}) is None


def test_face_crop_box_centers_on_bbox_with_margin():
    bbox = {"x": 100, "y": 100, "width": 40, "height": 50}
    x0, y0, x1, y1 = _face_crop_box(bbox, img_size=(832, 1216), margin_mult=1.9)
    cx, cy = 120, 125
    # crop should be centered on the bbox center...
    assert abs((x0 + x1) / 2 - cx) < 2
    assert abs((y0 + y1) / 2 - cy) < 2
    # ...and meaningfully larger than the raw bbox (context margin applied)
    assert (x1 - x0) > 40 and (y1 - y0) > 50


def test_face_crop_box_clamps_to_image_bounds():
    # A face near the top-left corner shouldn't produce negative coords.
    bbox = {"x": 5, "y": 5, "width": 30, "height": 30}
    x0, y0, x1, y1 = _face_crop_box(bbox, img_size=(832, 1216))
    assert x0 >= 0 and y0 >= 0
    assert x1 <= 832 and y1 <= 1216


def test_build_face_refine_graph_no_controlnet_nodes():
    style = load_style("one_piece")
    graph = build_face_refine_graph(style, "face_crop.png", seed=7)
    assert "20" not in graph and "21" not in graph and "23" not in graph
    assert graph["3"]["inputs"]["positive"] == ["6", 0]
    assert graph["3"]["inputs"]["denoise"] == 0.55


def test_build_face_refine_graph_appends_extra_positive_and_face_negative():
    style = load_style("one_piece")
    graph = build_face_refine_graph(style, "face_crop.png", seed=7,
                                    extra_positive="draconic dragon-person face")
    assert graph["6"]["inputs"]["text"].endswith("draconic dragon-person face")
    assert "generic featureless face" in graph["7"]["inputs"]["text"]

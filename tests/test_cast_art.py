"""Offline tests for guild_board.cast_art: prompt building from real
Blizzard profile data, and the opt-out filter. No network calls."""

from guild_board import cast_art


def test_build_prompt_uses_real_profile_fields():
    profile = {
        "name": "Rakdisc", "realm": "proudmoore", "gender": "Female",
        "race": "Nightborne", "class": "Priest", "active_spec": "Discipline",
        "transmog_render_url": "https://example.com/main-raw.jpg",
    }
    result = cast_art.build_prompt(profile)
    assert result is not None
    positive, negative = result
    assert "female" in positive
    assert "Nightborne" in positive
    assert "Priest" in positive
    assert "Discipline" in positive
    assert "one_piece_wano_style" in positive
    assert "Luffy" in negative
    assert "male, boy, man" in negative  # opposite-gender reinforcement


def test_build_prompt_missing_race_or_class_returns_none():
    assert cast_art.build_prompt({"gender": "Male"}) is None
    assert cast_art.build_prompt({"race": "Human"}) is None


def test_build_prompt_never_invents_a_class_flavor():
    # An unrecognized class name still produces a sane, non-crashing prompt.
    profile = {"gender": "Male", "race": "Human", "class": "Totally Not A Class"}
    positive, _ = cast_art.build_prompt(profile)
    assert "Totally Not A Class" in positive


def test_opted_in_characters_respects_opt_out():
    characters = {
        "rakdisc-proudmoore": {"name": "Rakdisc"},
        "ghost-proudmoore": {"name": "Ghost"},
    }
    cfg = {"cast": {"opt_out": ["Ghost-Proudmoore"]}}
    result = cast_art.opted_in_characters(cfg, characters)
    assert list(result.keys()) == ["rakdisc-proudmoore"]


def test_opted_in_characters_default_is_everyone():
    characters = {"a-realm": {}, "b-realm": {}}
    assert cast_art.opted_in_characters({}, characters) == characters


def test_build_ipadapter_graph_wires_reference_image_through():
    graph = cast_art.build_ipadapter_graph(
        "ckpt.safetensors", "lora.safetensors", "clipvision.safetensors",
        "ipadapter.safetensors", "ref.png", "positive text", "negative text",
        seed=123, filename_prefix="cast_crew/test",
    )
    assert graph["13"]["inputs"]["image"] == "ref.png"
    assert graph["14"]["inputs"]["model"] == ["2", 0]
    assert graph["3"]["inputs"]["model"] == ["14", 0]  # first pass uses the IPAdapter-conditioned model
    assert graph["6"]["inputs"]["text"] == "positive text"
    assert graph["7"]["inputs"]["text"] == "negative text"


def test_build_ipadapter_graph_detail_pass_is_default_and_wired():
    graph = cast_art.build_ipadapter_graph(
        "ckpt.safetensors", "lora.safetensors", "clipvision.safetensors",
        "ipadapter.safetensors", "ref.png", "positive text", "negative text",
        seed=123, filename_prefix="cast_crew/test",
    )
    # first-pass image feeds the ESRGAN upscale, not straight to SaveImage
    assert graph["20"]["inputs"]["samples"] == ["3", 0]
    assert graph["22"]["inputs"]["image"] == ["20", 0]
    assert graph["21"]["inputs"]["model_name"] == cast_art.DETAIL_UPSCALE_MODEL
    # downscaled to hires_scale x the base resolution before re-encoding
    assert graph["23"]["inputs"]["width"] == int(832 * 1.5)
    assert graph["23"]["inputs"]["height"] == int(1216 * 1.5)
    # second pass reuses the SAME IPAdapter-conditioned model, at low denoise
    assert graph["16"]["inputs"]["model"] == ["14", 0]
    assert graph["16"]["inputs"]["denoise"] == 0.45
    assert graph["16"]["inputs"]["latent_image"] == ["24", 0]
    # final output comes from the refined second pass
    assert graph["8"]["inputs"]["samples"] == ["16", 0]
    assert graph["9"]["inputs"]["images"] == ["8", 0]


def test_build_ipadapter_graph_detail_pass_false_is_single_stage():
    graph = cast_art.build_ipadapter_graph(
        "ckpt.safetensors", "lora.safetensors", "clipvision.safetensors",
        "ipadapter.safetensors", "ref.png", "positive text", "negative text",
        seed=123, filename_prefix="cast_crew/test", detail_pass=False,
    )
    assert "16" not in graph  # no second-pass sampler
    assert "21" not in graph  # no upscale model loader
    assert graph["8"]["inputs"]["samples"] == ["3", 0]  # decodes straight from the first pass

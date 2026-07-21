"""Offline tests for guild_board.styles: fail-open preset loading."""

from guild_board import styles


def test_load_style_missing_file_returns_default(tmp_path):
    style = styles.load_style("nonexistent", styles_dir=str(tmp_path))
    assert style["model"]["checkpoint"] == styles.DEFAULT_STYLE["model"]["checkpoint"]
    assert style["controlnet"]["enabled"] is False


def test_load_style_merges_yaml_override(tmp_path):
    (tmp_path / "custom.yaml").write_text(
        "img2img:\n  denoise: 0.42\ncontrolnet:\n  enabled: true\n",
        encoding="utf-8")
    style = styles.load_style("custom", styles_dir=str(tmp_path))
    assert style["img2img"]["denoise"] == 0.42
    assert style["controlnet"]["enabled"] is True
    # untouched keys still fall back to defaults
    assert style["sampler"]["cfg"] == styles.DEFAULT_STYLE["sampler"]["cfg"]


def test_load_style_broken_yaml_falls_back_to_default(tmp_path):
    (tmp_path / "broken.yaml").write_text("img2img: [unterminated", encoding="utf-8")
    style = styles.load_style("broken", styles_dir=str(tmp_path))
    assert style["img2img"]["denoise"] == styles.DEFAULT_STYLE["img2img"]["denoise"]


def test_load_style_sets_name_field(tmp_path):
    style = styles.load_style("my_style", styles_dir=str(tmp_path))
    assert style["name"] == "my_style"


def test_list_styles(tmp_path):
    (tmp_path / "one_piece.yaml").write_text("name: one_piece\n", encoding="utf-8")
    (tmp_path / "chibi.yml").write_text("name: chibi\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")
    assert styles.list_styles(styles_dir=str(tmp_path)) == ["chibi", "one_piece"]


def test_list_styles_missing_dir_returns_empty():
    assert styles.list_styles(styles_dir=r"C:\definitely\not\a\real\path") == []


def test_one_piece_preset_loads_and_enables_controlnet():
    style = styles.load_style("one_piece")
    assert style["controlnet"]["enabled"] is True
    assert style["controlnet"]["model"] == "controlnet-union-sdxl-1.0.safetensors"
    assert 0.0 <= style["controlnet"]["canny_low_threshold"] <= 1.0
    assert 0.0 <= style["controlnet"]["canny_high_threshold"] <= 1.0

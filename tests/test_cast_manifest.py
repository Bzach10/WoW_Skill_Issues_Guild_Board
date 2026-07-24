"""Offline tests for guild_board.cast_manifest: the character storage
contract (add/remove, versioned style results, rollback, refresh diff)."""

import json

import pytest

from guild_board import cast_manifest as cm


def _profile(**overrides):
    base = {
        "name": "Rakdisc", "realm": "proudmoore", "gender": "Female",
        "race": "Nightborne", "class": "Priest", "active_spec": "Discipline",
        "transmog_render_url": "https://example.com/rakdisc/v1.png",
    }
    base.update(overrides)
    return base


def test_load_manifest_missing_file_returns_empty(tmp_path):
    manifest = cm.load_manifest(str(tmp_path / "nope.json"))
    assert manifest == {"active_style": None, "styles_available": [], "characters": {}}


def test_load_manifest_broken_json_falls_back_to_empty(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    manifest = cm.load_manifest(str(path))
    assert manifest["characters"] == {}


def test_save_and_load_roundtrip(tmp_path):
    path = str(tmp_path / "cast_manifest.json")
    manifest = cm.load_manifest(path)
    cm.add_character(manifest, "rakdisc-proudmoore", _profile())
    cm.save_manifest(manifest, path)

    reloaded = cm.load_manifest(path)
    assert reloaded["characters"]["rakdisc-proudmoore"]["name"] == "Rakdisc"


def test_add_character_populates_expected_fields():
    manifest = cm.load_manifest("does-not-exist.json")
    cm.add_character(manifest, "rakdisc-proudmoore", _profile())
    char = manifest["characters"]["rakdisc-proudmoore"]
    assert char["race"] == "Nightborne"
    assert char["class"] == "Priest"
    assert char["spec"] == "Discipline"
    assert char["gender"] == "Female"
    assert char["realm"] == "proudmoore"
    assert char["styles"] == {}
    assert char["history"] == []


def test_add_character_is_noop_if_already_present():
    manifest = cm.load_manifest("nope.json")
    cm.add_character(manifest, "rakdisc-proudmoore", _profile())
    cm.add_character(manifest, "rakdisc-proudmoore", _profile(name="Someone Else"))
    assert manifest["characters"]["rakdisc-proudmoore"]["name"] == "Rakdisc"


def test_remove_character():
    manifest = cm.load_manifest("nope.json")
    cm.add_character(manifest, "rakdisc-proudmoore", _profile())
    cm.remove_character(manifest, "rakdisc-proudmoore")
    assert "rakdisc-proudmoore" not in manifest["characters"]


def test_remove_character_missing_slug_is_safe_noop():
    manifest = cm.load_manifest("nope.json")
    cm.remove_character(manifest, "nobody-here")  # should not raise


def test_record_style_result_first_time_is_version_1():
    manifest = cm.load_manifest("nope.json")
    cm.add_character(manifest, "rakdisc-proudmoore", _profile())
    cm.record_style_result(manifest, "rakdisc-proudmoore", "one_piece",
                           "cast/rakdisc-proudmoore/one_piece/board.png")
    entry = manifest["characters"]["rakdisc-proudmoore"]["styles"]["one_piece"]
    assert entry["version"] == 1
    assert entry["board"] == "cast/rakdisc-proudmoore/one_piece/board.png"
    assert "one_piece" in manifest["styles_available"]


def test_record_style_result_sets_active_style_when_unset():
    manifest = cm.load_manifest("nope.json")
    cm.add_character(manifest, "rakdisc-proudmoore", _profile())
    assert manifest["active_style"] is None
    cm.record_style_result(manifest, "rakdisc-proudmoore", "one_piece", "board.png")
    assert manifest["active_style"] == "one_piece"


def test_record_style_result_bumps_version_and_pushes_history():
    manifest = cm.load_manifest("nope.json")
    cm.add_character(manifest, "rakdisc-proudmoore", _profile())
    cm.record_style_result(manifest, "rakdisc-proudmoore", "one_piece", "v1.png")
    cm.record_style_result(manifest, "rakdisc-proudmoore", "one_piece", "v2.png")

    char = manifest["characters"]["rakdisc-proudmoore"]
    assert char["styles"]["one_piece"]["version"] == 2
    assert char["styles"]["one_piece"]["board"] == "v2.png"
    assert len(char["history"]) == 1
    assert char["history"][0]["version"] == 1
    assert char["history"][0]["board"] == "v1.png"
    assert "replaced_at" in char["history"][0]


def test_record_style_result_unknown_character_raises():
    manifest = cm.load_manifest("nope.json")
    with pytest.raises(KeyError):
        cm.record_style_result(manifest, "nobody", "one_piece", "board.png")


def test_set_primary_form_swaps_board_and_versions():
    manifest = cm.load_manifest("nope.json")
    cm.add_character(manifest, "rakdisc-proudmoore", _profile())
    cm.record_style_result(manifest, "rakdisc-proudmoore", "one_piece", "light.png",
                           forms={"light": "light.png", "shadow": "shadow.png"})
    cm.set_primary_form(manifest, "rakdisc-proudmoore", "one_piece", "shadow")

    entry = manifest["characters"]["rakdisc-proudmoore"]["styles"]["one_piece"]
    assert entry["board"] == "shadow.png"
    assert entry["version"] == 2  # versioned like any other write


def test_set_primary_form_unknown_form_raises():
    manifest = cm.load_manifest("nope.json")
    cm.add_character(manifest, "rakdisc-proudmoore", _profile())
    cm.record_style_result(manifest, "rakdisc-proudmoore", "one_piece", "light.png",
                           forms={"light": "light.png"})
    with pytest.raises(KeyError):
        cm.set_primary_form(manifest, "rakdisc-proudmoore", "one_piece", "shadow")


def test_rollback_style_restores_prior_version():
    manifest = cm.load_manifest("nope.json")
    cm.add_character(manifest, "rakdisc-proudmoore", _profile())
    cm.record_style_result(manifest, "rakdisc-proudmoore", "one_piece", "v1.png")
    cm.record_style_result(manifest, "rakdisc-proudmoore", "one_piece", "v2.png")
    cm.rollback_style(manifest, "rakdisc-proudmoore", "one_piece", to_version=1)

    char = manifest["characters"]["rakdisc-proudmoore"]
    # rollback writes a NEW version (3) whose content matches v1 — nothing lost
    assert char["styles"]["one_piece"]["board"] == "v1.png"
    assert char["styles"]["one_piece"]["version"] == 3
    # v2 is now itself in history, so rolling forward again is possible
    boards_in_history = [h["board"] for h in char["history"]]
    assert "v1.png" in boards_in_history
    assert "v2.png" in boards_in_history


def test_rollback_style_unknown_version_raises():
    manifest = cm.load_manifest("nope.json")
    cm.add_character(manifest, "rakdisc-proudmoore", _profile())
    cm.record_style_result(manifest, "rakdisc-proudmoore", "one_piece", "v1.png")
    with pytest.raises(KeyError):
        cm.rollback_style(manifest, "rakdisc-proudmoore", "one_piece", to_version=99)


def test_set_active_style_refuses_unregistered_style():
    manifest = cm.load_manifest("nope.json")
    cm.set_active_style(manifest, "chibi")
    assert manifest["active_style"] is None  # unchanged, fails open


def test_set_active_style_switches_when_registered():
    manifest = cm.load_manifest("nope.json")
    cm.add_character(manifest, "rakdisc-proudmoore", _profile())
    cm.record_style_result(manifest, "rakdisc-proudmoore", "one_piece", "v1.png")
    cm.register_style(manifest, "chibi")
    cm.set_active_style(manifest, "chibi")
    assert manifest["active_style"] == "chibi"


def test_character_slugs_needing_refresh_detects_new_and_changed():
    manifest = cm.load_manifest("nope.json")
    cm.add_character(manifest, "rakdisc-proudmoore", _profile(), transmog_fingerprint="fp-old")

    blizzard_characters = {
        "rakdisc-proudmoore": _profile(transmog_render_url="https://example.com/rakdisc/v2.png"),
        "floofwall-queldorei": _profile(name="Floofwall"),
    }
    changed = cm.character_slugs_needing_refresh(
        manifest, blizzard_characters, fingerprint_fn=lambda p: p["transmog_render_url"])

    assert set(changed) == {"rakdisc-proudmoore", "floofwall-queldorei"}


def test_character_slugs_needing_refresh_no_change_when_fingerprint_matches():
    manifest = cm.load_manifest("nope.json")
    cm.add_character(manifest, "rakdisc-proudmoore", _profile(),
                     transmog_fingerprint="same-url")

    blizzard_characters = {"rakdisc-proudmoore": _profile()}
    changed = cm.character_slugs_needing_refresh(
        manifest, blizzard_characters, fingerprint_fn=lambda p: "same-url")

    assert changed == []


def test_record_style_result_preserves_keys_it_does_not_own():
    # Regression: the art pipeline writes a v2 payload (layers + canvas)
    # into the style entry. A later regen through record_style_result used
    # to rebuild the entry from scratch and silently destroy both -- the
    # paper-doll degraded to flat cut-outs with no error.
    manifest = cm.load_manifest("nope.json")
    cm.add_character(manifest, "rakdisc-proudmoore", _profile())
    cm.record_style_result(manifest, "rakdisc-proudmoore", "one_piece", "v1.png")

    entry = manifest["characters"]["rakdisc-proudmoore"]["styles"]["one_piece"]
    entry["layers"] = [{"name": f"layer{i}", "file": f"layer{i}.png"}
                      for i in range(5)]
    entry["canvas"] = {"width": 1024, "height": 1024}

    cm.record_style_result(manifest, "rakdisc-proudmoore", "one_piece", "v2.png")

    regen = manifest["characters"]["rakdisc-proudmoore"]["styles"]["one_piece"]
    assert regen["board"] == "v2.png"
    assert regen["version"] == 2
    assert len(regen["layers"]) == 5, "regen destroyed the art pipeline's layers"
    assert regen["canvas"] == {"width": 1024, "height": 1024}

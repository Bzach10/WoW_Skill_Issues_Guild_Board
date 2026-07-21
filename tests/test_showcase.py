"""Character art resolution — one resolver, new style only.

The bug these pin: the trial cards used the new restyle art while the
full-profile view and the crew deck still rendered the old paper-doll
layers, so opening a character showed art in the previous style.
"""

import pytest

from guild_board import showcase


LEGACY = [
    "cast/rakdisc-proudmoore/one_piece/body.png",
    "cast/rakdisc-proudmoore/one_piece/face.png",
    "cast/_trial/rakdisc.png",
    "cast/_trial/healyeah_alt.png",
    "cast/rakdisc/scene1_raidhall_w025.png",
    "cast/floofwall/floofwall_tavern_w025.png",
    "cast/healyeah/healyeah_dragonflight_v2_w030.png",
    "cast/rakdisc/board.png",
    "cast/rakdisc/composite.png",
]

NEW = [
    "cast/rakdisc/rakdisc_anime_final.png",
    "cast/floofwall/floofwall_anime_final.png",
    "cast/healyeah/healyeah_anime_final.png",
]


@pytest.mark.parametrize("path", LEGACY)
def test_every_known_legacy_path_is_refused(path):
    assert showcase.is_legacy_art(path) is True


@pytest.mark.parametrize("path", NEW)
def test_the_restyle_art_is_accepted(path):
    assert showcase.is_legacy_art(path) is False


def test_legacy_art_is_refused_even_when_it_exists_on_disk(tmp_path, monkeypatch):
    """A hard floor: purging old art must not depend on the old files
    having been deleted."""
    from PIL import Image
    legacy = tmp_path / "one_piece" / "body.png"
    legacy.parent.mkdir(parents=True)
    Image.new("RGBA", (8, 8)).save(legacy)
    assert showcase._usable(str(legacy)) is None


def test_a_config_override_cannot_smuggle_in_legacy_art(monkeypatch):
    """Even an explicit officer override is refused if it points at the
    old style — otherwise 'purged' is only a convention."""
    cfg = {"showcase": {"scenes": {"rakdisc": "cast/_trial/rakdisc.png"}}}
    art = showcase.character_art("rakdisc", cfg)
    assert art["src"] is None or "_trial" not in art["src"]


def test_a_manifest_pointing_at_layers_is_ignored():
    """Layer sets are the old paper-doll art; the manifest must not be
    able to route them onto the page."""
    manifest = {"active_style": "one_piece", "characters": {"rakdisc-proudmoore": {
        "name": "Rakdisc",
        "styles": {"one_piece": {"board": "cast/rakdisc-proudmoore/one_piece/board.png",
                                 "layers": [{"slot": "body",
                                             "src": "cast/rakdisc-proudmoore/one_piece/body.png"}]}},
    }}}
    assert showcase._manifest_art("rakdisc", manifest) is None


def test_a_manifest_scene_entry_is_used_when_the_roster_lands(tmp_path):
    """As the roster generation delivers, each character wires in from
    cast_manifest.json with no code change."""
    from PIL import Image
    art = tmp_path / "newguy_anime_final.png"
    Image.new("RGB", (600, 800)).save(art)          # 3:4
    manifest = {"active_style": "anime", "characters": {"newguy-realm": {
        "name": "Newguy",
        "styles": {"anime": {"scene": str(art).replace("\\", "/")}},
    }}}
    resolved = showcase.character_art("newguy", manifest=manifest)
    assert resolved["src"] is not None
    assert resolved["pending"] is False
    assert resolved["fills"] is True


# ------------------------------------------------------- aspect handling

def test_three_four_art_fills_the_frame(tmp_path):
    from PIL import Image
    art = tmp_path / "x_anime_final.png"
    Image.new("RGB", (900, 1200)).save(art)         # exactly 0.75
    assert showcase.image_aspect(str(art)) == pytest.approx(0.75)
    cfg = {"showcase": {"scenes": {"x": str(art).replace("\\", "/")}}}
    assert showcase.character_art("x", cfg)["fills"] is True


def test_off_spec_art_does_not_claim_to_fill(tmp_path):
    """The current trial art is 0.68 and 1.33 — it must be contained, not
    cropped, until the roster lands at a consistent 3:4."""
    from PIL import Image
    art = tmp_path / "y_anime_final.png"
    Image.new("RGB", (1600, 1200)).save(art)        # 1.33 landscape
    cfg = {"showcase": {"scenes": {"y": str(art).replace("\\", "/")}}}
    assert showcase.character_art("y", cfg)["fills"] is False


def test_missing_art_is_pending_not_broken():
    art = showcase.character_art("nobody-at-all")
    assert art["pending"] is True
    assert art["src"] is None
    assert art["fills"] is False


def test_an_unreadable_image_does_not_raise(tmp_path):
    bad = tmp_path / "z_anime_final.png"
    bad.write_text("not a png", encoding="utf-8")
    assert showcase.image_aspect(str(bad)) is None
    cfg = {"showcase": {"scenes": {"z": str(bad).replace("\\", "/")}}}
    assert showcase.character_art("z", cfg)["fills"] is False


# ------------------------------------------------------- roster wiring

def test_roster_cards_grow_as_art_lands(tmp_path):
    from PIL import Image
    art = tmp_path / "a_anime_final.png"
    Image.new("RGB", (900, 1200)).save(art)
    crew = [{"slug": "a", "name": "A"}, {"slug": "b", "name": "B"}]
    cfg = {"showcase": {"scenes": {"a": str(art).replace("\\", "/")}}}
    cards = showcase.build_roster_cards(crew, {}, cfg)
    assert [c["slug"] for c in cards] == ["a"]      # B has no art yet


@pytest.mark.parametrize("broken", [
    None, {}, {"characters": None}, {"characters": {"x": "nope"}},
    {"characters": {"x": {"name": "X", "styles": "nope"}}},
    {"characters": {"x": {"name": "X", "styles": {"s": None}}}},
])
def test_a_malformed_manifest_never_raises(broken):
    art = showcase.character_art("x", manifest=broken)
    assert art["pending"] in (True, False)

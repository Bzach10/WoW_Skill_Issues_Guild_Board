"""Integration with the art pipeline's cast_manifest.json.

The manifest is owned by the pipeline session; we only read it. These
tests pin the contract we build against, and — just as important — that
every way it can be incomplete degrades instead of breaking the board.
"""


import pytest

from guild_board import crew

FIX = "tests/fixtures/cast"


def manifest(active_style="one_piece", styles_available=None):
    """A manifest shaped exactly like the pipeline's contract, pointed at
    the transparent fixture cut-outs."""
    return {
        "active_style": active_style,
        "styles_available": styles_available or ["one_piece", "watercolor"],
        "characters": {
            "rakdisc": {
                "name": "Rakdisc", "realm": "bleeding-hollow",
                "race": "Nightborne", "class": "Priest", "spec": "Discipline",
                "gender": "Female", "role": "healer",
                "transmog_fingerprint": "abc123",
                "render_url": "https://render.example/rakdisc.png",
                "styles": {
                    "one_piece": {
                        "board": f"{FIX}/rakdisc/one_piece/board.png",
                        "forms": {"light": f"{FIX}/rakdisc/one_piece/light.png",
                                  "shadow": f"{FIX}/rakdisc/one_piece/shadow.png"},
                        "version": 3, "generated_at": "2026-07-20T12:00:00Z"},
                    "watercolor": {
                        "board": f"{FIX}/rakdisc/watercolor/board.png",
                        "forms": {}, "version": 1,
                        "generated_at": "2026-07-20T13:00:00Z"},
                },
                "history": [],
            },
            "amrevenge": {
                "name": "Amrevenge", "realm": "bleeding-hollow",
                "race": "Orc", "class": "Hunter", "spec": "Beast Mastery",
                "gender": "Male", "role": "dps",
                "styles": {
                    "one_piece": {
                        "board": f"{FIX}/amrevenge/one_piece/board.png",
                        "forms": {}, "version": 2,
                        "generated_at": "2026-07-20T12:30:00Z"},
                },
                "history": [],
            },
        },
    }


SCORES = {"rakdisc": 3529.2, "amrevenge": 3908.1}


# ------------------------------------------------------- style resolution

def test_active_style_comes_from_the_manifest():
    assert crew.resolve_style(manifest()) == "one_piece"


def test_style_is_not_hardcoded_flipping_active_style_reskins_the_cast():
    built = crew.build_crew({}, {}, season_scores=SCORES,
                            manifest=manifest(active_style="watercolor"))
    rak = next(m for m in built if m["slug"] == "rakdisc")
    assert "/watercolor/" in rak["art"]
    assert rak["style_used"] == "watercolor"


def test_theme_yml_can_override_the_active_style():
    theme = {"crew": {"style": "watercolor"}}
    assert crew.resolve_style(manifest(), theme) == "watercolor"


def test_explicit_override_beats_everything():
    theme = {"crew": {"style": "watercolor"}}
    assert crew.resolve_style(manifest(), theme, override="one_piece") == "one_piece"


def test_character_missing_the_active_style_borrows_one_they_have():
    """Flipping active_style before every character is regenerated must
    leave a full deck, not a row of silhouettes."""
    built = crew.build_crew({}, {}, season_scores=SCORES,
                            manifest=manifest(active_style="watercolor"))
    amr = next(m for m in built if m["slug"] == "amrevenge")
    assert amr["art_is_real"] is True
    assert amr["style_used"] == "one_piece"
    assert amr["style_is_fallback"] is True


def test_missing_active_style_key_falls_back_to_first_available():
    m = manifest()
    del m["active_style"]
    assert crew.resolve_style(m) == "one_piece"


# ------------------------------------------------------- art resolution

def test_real_cutouts_replace_the_placeholder():
    built = crew.build_crew({}, {}, season_scores=SCORES, manifest=manifest())
    rak = next(m for m in built if m["slug"] == "rakdisc")
    assert rak["art_is_real"] is True
    assert rak["art"].endswith("rakdisc/one_piece/board.png")
    assert rak["art_version"] == 3


def test_forms_drive_the_shadowform_art_swap():
    built = crew.build_crew({}, {}, season_scores=SCORES, manifest=manifest())
    rak = next(m for m in built if m["slug"] == "rakdisc")
    assert rak["has_shadowform"] is True
    assert rak["light_art"].endswith("light.png")
    assert rak["shadow_art"].endswith("shadow.png")


def test_opaque_art_in_the_manifest_is_rejected():
    """The pipeline pointing at a render that is not actually cut out
    must NOT paste a white rectangle onto the ship."""
    m = manifest()
    m["characters"]["opaqueguy"] = {
        "name": "Opaqueguy", "class": "Warrior", "spec": "Fury",
        "styles": {"one_piece": {
            "board": f"{FIX}/opaqueguy/one_piece/board.png", "version": 1}},
    }
    built = crew.build_crew({}, {}, season_scores=dict(SCORES, opaqueguy=100.0),
                            manifest=m)
    guy = next(x for x in built if x["slug"] == "opaqueguy")
    assert guy["art_is_real"] is False
    assert "crew_slot.png" in guy["art"]


def test_missing_file_on_disk_degrades_to_placeholder():
    m = manifest()
    m["characters"]["rakdisc"]["styles"]["one_piece"]["board"] = "cast/nope/gone.png"
    m["characters"]["rakdisc"]["styles"]["one_piece"]["forms"] = {}
    m["characters"]["rakdisc"]["styles"].pop("watercolor")
    built = crew.build_crew({}, {}, season_scores=SCORES, manifest=m)
    rak = next(x for x in built if x["slug"] == "rakdisc")
    assert rak["art_is_real"] is False


# ------------------------------------------------------- roles

def test_roles_come_from_the_manifest_and_counts_fill_in():
    built = crew.build_crew({}, {}, season_scores=SCORES, manifest=manifest())
    counts = crew.role_counts(built)
    assert counts["healer"] >= 1 and counts["dps"] >= 1
    rak = next(m for m in built if m["slug"] == "rakdisc")
    assert rak["role"] == "healer"
    assert rak["race"] == "Nightborne"


def test_spec_derives_the_role_when_the_manifest_declares_none():
    m = manifest()
    del m["characters"]["rakdisc"]["role"]
    built = crew.build_crew({}, {}, season_scores=SCORES, manifest=m)
    rak = next(x for x in built if x["slug"] == "rakdisc")
    assert rak["role"] == "healer"      # Discipline


def test_a_nonsense_declared_role_is_not_trusted():
    m = manifest()
    m["characters"]["rakdisc"]["role"] = "battlemaster"
    built = crew.build_crew({}, {}, season_scores=SCORES, manifest=m)
    rak = next(x for x in built if x["slug"] == "rakdisc")
    assert rak["role"] == "healer"      # derived from Discipline instead


def test_manifest_outranks_the_derived_fallback():
    m = manifest()
    m["characters"]["brewzleeh"] = {
        "name": "Brewzleeh", "class": "Monk", "spec": "Brewmaster",
        "styles": {},
    }
    built = crew.build_crew({}, {}, season_scores=dict(SCORES, brewzleeh=3685.8),
                            manifest=m)
    brew = next(x for x in built if x["slug"] == "brewzleeh")
    assert brew["role"] == "tank"       # real spec beats the derived entry
    assert brew["source"] == "manifest"


# ------------------------------------------------------- fail-open

@pytest.mark.parametrize("broken", [
    {},
    {"characters": None},
    {"characters": {"x": "not a dict"}},
    {"active_style": 42, "characters": {}},
    {"characters": {"rakdisc": {"name": "Rakdisc", "styles": "nope"}}},
    {"characters": {"rakdisc": {"name": "Rakdisc", "styles": {"one_piece": None}}}},
])
def test_a_malformed_manifest_never_breaks_the_deck(broken):
    built = crew.build_crew({}, {}, season_scores=SCORES, manifest=broken)
    assert built, "the deck must still stand up"
    assert all(m["art"] for m in built), "every member needs some art slot"


def test_missing_manifest_file_is_not_an_error(tmp_path):
    assert crew.load_manifest(str(tmp_path / "nope.json")) == {}


def test_manifest_that_is_not_an_object_is_ignored(tmp_path):
    path = tmp_path / "cast_manifest.json"
    path.write_text("[1,2,3]", encoding="utf-8")
    assert crew.load_manifest(str(path)) == {}


# ------------------------------------------------------- scenes

def test_scenes_have_defaults_for_every_island_kind():
    scenes = crew.resolve_scenes({})
    assert crew.scene_for_island({"id": "x", "kind": "dungeon"}, scenes)["key"] == "dungeon"
    assert crew.scene_for_island({"id": "x", "kind": "raid_boss"}, scenes)["key"] == "raid_boss"


def test_theme_yml_can_define_a_per_island_scene():
    scenes = crew.resolve_scenes(
        {"crew": {"scenes": {"grim-batol": {"tint": "#8a3b1f"}}}})
    scene = crew.scene_for_island({"id": "grim-batol", "kind": "dungeon"}, scenes)
    assert scene["tint"] == "#8a3b1f"
    assert scene["key"] == "grim-batol"


def test_a_scene_image_that_is_not_on_disk_is_dropped():
    """A broken path must fall back to the tint, never render a broken tile."""
    scenes = crew.resolve_scenes(
        {"crew": {"scenes": {"dungeon": {"image": "assets/nope_missing.png",
                                         "tint": "#123456"}}}})
    assert scenes["dungeon"]["image"] is None
    assert scenes["dungeon"]["tint"] == "#123456"


@pytest.mark.parametrize("broken", [
    {"crew": {"scenes": "not a mapping"}},
    {"crew": {"scenes": {"dungeon": "not a mapping"}}},
    {"crew": "not a mapping"},
])
def test_broken_scene_config_falls_back(broken):
    scenes = crew.resolve_scenes(broken)
    assert "dungeon" in scenes and "raid_boss" in scenes

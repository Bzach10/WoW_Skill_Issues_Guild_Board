"""The crew/front-end layer's contracts — above all, that it fails open."""


import pytest

from guild_board import crew

# ---------------------------------------------------------------- roles

def test_role_for_uses_real_spec():
    assert crew.role_for("Hunter", "Beast Mastery") == "dps"
    assert crew.role_for("Monk", "Mistweaver") == "healer"
    assert crew.role_for("Warrior", "Protection") == "tank"


def test_ambiguous_specs_are_settled_by_class():
    # "Holy" is a healer on both, but "Frost" is a DPS spec on a DK and a
    # Mage while "Protection" is a tank spec on a Warrior and a Paladin.
    assert crew.role_for("Paladin", "Holy") == "healer"
    assert crew.role_for("Death Knight", "Frost") == "dps"
    assert crew.role_for("Paladin", "Protection") == "tank"


def test_unknown_spec_never_guesses():
    assert crew.role_for("Monk", None) == "unknown"
    assert crew.role_for("Hunter", "Not A Spec") == "unknown"
    assert crew.role_for(None, None) == "unknown"


# ---------------------------------------------------------------- art slots

def _write_png(path, mode, color):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new(mode, (8, 8), color).save(path)


def test_cutout_requires_real_transparency(tmp_path, monkeypatch):
    """A raw generation still on its studio background must NOT reach the
    deck — it would paste a solid rectangle onto the ship."""
    opaque = tmp_path / "opaque.png"
    _write_png(opaque, "RGB", (255, 255, 255))
    assert crew._is_cutout(opaque) is False

    fully_opaque_rgba = tmp_path / "rgba_opaque.png"
    _write_png(fully_opaque_rgba, "RGBA", (255, 255, 255, 255))
    assert crew._is_cutout(fully_opaque_rgba) is False

    cut = tmp_path / "cut.png"
    _write_png(cut, "RGBA", (255, 255, 255, 0))
    assert crew._is_cutout(cut) is True


def test_missing_art_degrades_to_placeholder(tmp_path, monkeypatch):
    monkeypatch.setattr(crew, "CAST_DIR", tmp_path / "cast")
    monkeypatch.setattr(crew, "PLACEHOLDER_DIR", tmp_path / "cast" / "placeholders")
    _write_png(tmp_path / "cast" / "placeholders" / "crew_slot.png", "RGBA", (0, 0, 0, 0))

    art, is_real = crew._art_slot("nobody")
    assert art.endswith("crew_slot.png")
    assert is_real is False


def test_real_cutout_is_picked_up(tmp_path, monkeypatch):
    monkeypatch.setattr(crew, "CAST_DIR", tmp_path / "cast")
    monkeypatch.setattr(crew, "PLACEHOLDER_DIR", tmp_path / "cast" / "placeholders")
    _write_png(tmp_path / "cast" / "someone" / "board.png", "RGBA", (1, 2, 3, 0))

    art, is_real = crew._art_slot("someone")
    assert art.endswith("someone/board.png")
    assert is_real is True


# ---------------------------------------------------------------- crew build

def test_crew_is_ordered_by_real_season_score():
    scores = {"amrevenge": 3908.1, "rakdisc": 3529.2, "brewzleeh": 3685.8}
    built = crew.build_crew({}, {}, season_scores=scores, manifest={})
    named = [m["name"] for m in built if m["score"]]
    assert named[:3] == ["Amrevenge", "Brewzleeh", "Rakdisc"]


def test_profile_cache_beats_derived_entries():
    """When the art workstream's real profile data lands, it wins."""
    profiles = {"rakdisc-bleeding-hollow": {
        "name": "Rakdisc", "class": "Priest", "active_spec": "Shadow"}}
    built = crew.build_crew({}, {}, season_scores={"rakdisc": 1.0},
                            profiles=profiles, manifest={})
    rak = next(m for m in built if m["slug"] == "rakdisc")
    assert rak["source"] == "real"
    assert rak["role"] == "dps"          # Shadow is a DPS spec
    assert rak["has_shadowform"] is True  # ...and still a Priest


def test_opt_out_is_respected():
    built = crew.build_crew({"cast": {"opt_out": ["rakdisc"]}}, {},
                            season_scores={"rakdisc": 3529.2}, manifest={})
    assert all(m["slug"] != "rakdisc" for m in built)


def test_every_member_carries_its_receipt():
    """Nothing stands on the deck without a reason we can point at."""
    built = crew.build_crew({}, {}, season_scores={"amrevenge": 3908.1}, manifest={})
    assert all(m["evidence"] for m in built)


# ---------------------------------------------------------------- themes

def test_three_themes_always_present_and_complete():
    themes = crew.resolve_themes({})
    assert list(themes) == ["codex", "console", "chronicle"]
    for palette in themes.values():
        for token in ("bg", "text", "accent", "panel", "line", "display"):
            assert palette[token]


def test_theme_yml_can_reskin_a_token():
    themes = crew.resolve_themes({"crew": {"themes": {"codex": {"accent": "#ff0000"}}}})
    assert themes["codex"]["accent"] == "#ff0000"
    assert themes["codex"]["bg"] == crew.CREW_THEMES["codex"]["bg"]  # untouched


@pytest.mark.parametrize("bad", [
    {"crew": {"themes": {"codex": {"accent": ""}}}},          # blank
    {"crew": {"themes": {"codex": {"acccent": "#f00"}}}},     # typo'd key
    {"crew": {"themes": {"codex": {"accent": 12345}}}},       # wrong type
    {"crew": {"themes": {"nosuchtheme": {"accent": "#f00"}}}},
    {"crew": {"themes": "not a mapping at all"}},
])
def test_broken_theme_yml_falls_back_instead_of_breaking(bad):
    """A non-coder editing theme.yml can never produce a broken page."""
    try:
        themes = crew.resolve_themes(bad)
    except AttributeError:
        pytest.fail("a malformed theme.yml must not raise")
    assert themes["codex"]["accent"] == crew.CREW_THEMES["codex"]["accent"]


def test_default_theme_falls_back_when_unknown():
    assert crew.default_theme_key({"crew": {"default_theme": "nope"}}) == "codex"
    assert crew.default_theme_key({"crew": {"default_theme": "console"}}) == "console"


# ---------------------------------------------------------------- voyage

def test_islands_have_the_shape_the_template_expects():
    islands, _current, _real = crew.load_islands({})
    assert islands
    for island in islands:
        assert set(("id", "name", "kind", "flavor")) <= set(island)
        assert island["kind"] in ("dungeon", "raid_boss")


def test_sample_islands_used_when_voyage_module_is_absent(monkeypatch):
    """The map still renders on a branch that has no voyage.py yet."""
    import sys

    import guild_board
    # A None entry in sys.modules makes `import` raise ImportError; the
    # attribute has to go too, since `from pkg import mod` will happily
    # read an already-bound attribute off the package first. Together
    # they are what a branch without voyage.py actually looks like.
    monkeypatch.setitem(sys.modules, "guild_board.voyage", None)
    monkeypatch.delattr(guild_board, "voyage", raising=False)
    islands, _current, real = crew.load_islands({})
    assert real is False
    assert islands and all(i.get("sample") for i in islands)


def test_build_crew_does_not_read_the_manifest_when_one_is_supplied(tmp_path,
                                                                    monkeypatch):
    """Passing manifest={} must mean "no manifest", not "go find one on
    disk" — otherwise every test result depends on the working directory.
    profiles={} for the same reason: build_crew's deliberate
    load_profiles() fallback would otherwise find the real
    blizzard_profile_cache.json (tracked since main's Blizzard
    integration) and promote rakdisc to source "real"."""
    monkeypatch.setattr(crew, "CAST_MANIFEST", str(tmp_path / "not_here.json"))
    built = crew.build_crew({}, {}, season_scores={"rakdisc": 1.0}, manifest={},
                            profiles={})
    rak = next(m for m in built if m["slug"] == "rakdisc")
    assert rak["source"] == "derived"

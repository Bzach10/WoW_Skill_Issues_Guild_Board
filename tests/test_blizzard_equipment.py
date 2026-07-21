"""Offline tests for the Blizzard /equipment fetch.

No network. Payloads mirror the real shape of
/profile/wow/character/{realm}/{name}/equipment.

Why this endpoint matters: the character-media render is only a picture.
Per-slot item + transmog appearance is the sole structured path from a
character's real gear to art layers — without it the pipeline falls back to
a hardcoded generic kit.
"""

import pytest

from guild_board import blizzard


def _slot(slot_type, item_id, name, subclass="Cloth", transmog=None,
          item_class="Armor", quality="Epic"):
    entry = {
        "slot": {"type": slot_type, "name": slot_type.title()},
        "item": {"id": item_id},
        "name": name,
        "quality": {"type": quality.upper(), "name": quality},
        "item_class": {"name": item_class},
        "item_subclass": {"name": subclass},
        "inventory_type": {"type": slot_type, "name": slot_type.title()},
    }
    if transmog:
        entry["transmog"] = {
            "item": {"id": transmog[0], "name": transmog[1]},
            "display_string": f"Transmogrified to: {transmog[1]}",
        }
    return entry


EQUIPMENT_PAYLOAD = {
    "equipped_items": [
        _slot("HEAD", 111, "Real Hood"),
        _slot("SHOULDER", 222, "Real Mantle"),
        _slot("CHEST", 333, "Real Robe",
              transmog=(9333, "Fancy Xmog Robe")),
        _slot("LEGS", 444, "Real Leggings"),
        _slot("FEET", 555, "Real Slippers"),
        _slot("HANDS", 666, "Real Gloves"),
        _slot("BACK", 777, "Real Cloak"),
        _slot("MAIN_HAND", 888, "Real Staff",
              subclass="Staff", item_class="Weapon"),
        # Not visible on the model — must be dropped.
        _slot("NECK", 999, "Real Amulet", subclass="Miscellaneous"),
        _slot("FINGER_1", 1010, "Real Ring", subclass="Miscellaneous"),
        _slot("TRINKET_1", 1111, "Real Trinket", subclass="Miscellaneous"),
    ]
}


@pytest.fixture
def fake_equipment(monkeypatch):
    def fake_get(token, region, path, params):
        assert path.endswith("/equipment")
        return EQUIPMENT_PAYLOAD
    monkeypatch.setattr(blizzard, "_get", fake_get)


def test_fetch_equipment_returns_visible_slots_only(fake_equipment):
    items = blizzard.fetch_character_equipment("tok", "us", "proudmoore", "Rakdisc")
    slots = {i["slot"] for i in items}
    assert "NECK" not in slots and "FINGER_1" not in slots and "TRINKET_1" not in slots
    assert {"HEAD", "SHOULDER", "CHEST", "LEGS", "FEET", "HANDS", "BACK",
            "MAIN_HAND"} == slots


def test_transmog_appearance_wins_over_the_equipped_item(fake_equipment):
    """The whole point: art must render what the gear LOOKS like."""
    items = blizzard.fetch_character_equipment("tok", "us", "proudmoore", "Rakdisc")
    chest = next(i for i in items if i["slot"] == "CHEST")
    assert chest["item_id"] == 333            # what they wear
    assert chest["transmog_item_id"] == 9333  # what it looks like
    assert chest["appearance_item_id"] == 9333
    assert chest["appearance_item_name"] == "Fancy Xmog Robe"


def test_untransmogged_slot_falls_back_to_the_real_item(fake_equipment):
    items = blizzard.fetch_character_equipment("tok", "us", "proudmoore", "Rakdisc")
    legs = next(i for i in items if i["slot"] == "LEGS")
    assert legs["transmog_item_id"] is None
    assert legs["appearance_item_id"] == 444
    assert legs["appearance_item_name"] == "Real Leggings"


def test_armor_weight_is_set_for_armor_and_none_for_weapons(fake_equipment):
    items = blizzard.fetch_character_equipment("tok", "us", "proudmoore", "Rakdisc")
    chest = next(i for i in items if i["slot"] == "CHEST")
    weapon = next(i for i in items if i["slot"] == "MAIN_HAND")
    assert chest["armor_weight"] == "Cloth"
    assert weapon["item_subclass"] == "Staff"
    assert weapon["armor_weight"] is None  # a staff is not an armour weight


def test_equipment_failure_returns_empty_not_raise(monkeypatch):
    """One unreadable character must not abort a roster refresh."""
    def boom(*a, **kw):
        raise blizzard.requests.ConnectionError("network down")
    monkeypatch.setattr(blizzard, "_get", boom)
    assert blizzard.fetch_character_equipment("tok", "us", "r", "n") == []


def test_private_or_missing_equipment_returns_empty(monkeypatch):
    monkeypatch.setattr(blizzard, "_get", lambda *a, **kw: None)
    assert blizzard.fetch_character_equipment("tok", "us", "r", "n") == []


# --- dominant_armor_weight

def test_dominant_armor_weight_ignores_the_always_cloth_cloak():
    """A plate wearer's cloak is still Cloth; counting it naively would
    misclassify anyone with few armour slots read."""
    equipment = [
        {"slot": "CHEST", "armor_weight": "Plate"},
        {"slot": "LEGS", "armor_weight": "Plate"},
        {"slot": "BACK", "armor_weight": "Cloth"},
    ]
    assert blizzard.dominant_armor_weight(equipment) == "Plate"


def test_dominant_armor_weight_uses_majority_of_core_slots():
    equipment = [
        {"slot": "CHEST", "armor_weight": "Mail"},
        {"slot": "LEGS", "armor_weight": "Mail"},
        {"slot": "FEET", "armor_weight": "Mail"},
        {"slot": "HANDS", "armor_weight": "Leather"},  # a levelling oddity
    ]
    assert blizzard.dominant_armor_weight(equipment) == "Mail"


def test_dominant_armor_weight_is_none_without_core_slots():
    assert blizzard.dominant_armor_weight([]) is None
    assert blizzard.dominant_armor_weight(None) is None
    assert blizzard.dominant_armor_weight(
        [{"slot": "MAIN_HAND", "armor_weight": None}]) is None


# --- integration into the cached profile

def test_profile_carries_equipment_and_armor_weight(monkeypatch):
    """End-to-end shape: what lands in blizzard_profile_cache.json."""
    def fake_get(token, region, path, params):
        if path.endswith("/equipment"):
            return EQUIPMENT_PAYLOAD
        if path.endswith("/specializations"):
            return {"active_specialization": {"name": "Discipline"}}
        if path.endswith("/character-media"):
            return {"assets": [{"key": "main-raw", "value": "https://r/x.png"}]}
        return {"name": "Rakdisc", "gender": {"name": "Female"},
                "race": {"name": "Nightborne"},
                "character_class": {"name": "Priest"}}

    monkeypatch.setattr(blizzard, "_get", fake_get)
    profile = blizzard.fetch_character_profile("tok", "us", "proudmoore", "Rakdisc")

    assert profile["armor_weight"] == "Cloth"
    assert len(profile["equipment"]) == 8
    chest = next(i for i in profile["equipment"] if i["slot"] == "CHEST")
    assert chest["appearance_item_id"] == 9333


def test_manifest_carries_equipment_through(monkeypatch):
    """The art pipeline reads the manifest, so equipment must survive
    add_character — not just live in the profile cache."""
    from guild_board import cast_manifest

    manifest = {"active_style": None, "styles_available": [], "characters": {}}
    profile = {
        "name": "Rakdisc", "realm": "proudmoore", "race": "Nightborne",
        "class": "Priest", "active_spec": "Discipline", "gender": "Female",
        "equipment": [{"slot": "CHEST", "armor_weight": "Cloth",
                       "appearance_item_id": 9333}],
        "armor_weight": "Cloth",
    }
    cast_manifest.add_character(manifest, "rakdisc-proudmoore", profile)
    entry = manifest["characters"]["rakdisc-proudmoore"]
    assert entry["armor_weight"] == "Cloth"
    assert entry["equipment"][0]["appearance_item_id"] == 9333


def test_manifest_defaults_equipment_to_empty_for_old_profiles():
    """Profiles cached before this endpoint existed must not crash or look
    like the character is wearing nothing on purpose."""
    from guild_board import cast_manifest

    manifest = {"active_style": None, "styles_available": [], "characters": {}}
    cast_manifest.add_character(manifest, "old-char", {"name": "Old"})
    entry = manifest["characters"]["old-char"]
    assert entry["equipment"] == []
    assert entry["armor_weight"] is None

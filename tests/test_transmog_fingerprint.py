"""Offline tests for guild_board.transmog_fingerprint.

The fingerprint gates GPU regeneration, so it has two failure modes that
cost real money in opposite directions: under-sensitivity leaves stale art
on the board forever, over-sensitivity re-renders the whole cast for no
visible change. Both are covered here.
"""

from guild_board.transmog_fingerprint import (
    ART_INPUT_FIELDS,
    compute_transmog_fingerprint,
)

BASE = {
    "name": "Rakdisc",
    "realm": "proudmoore",
    "race": "Nightborne",
    "class": "Priest",
    "gender": "Female",
    "active_spec": "Discipline",
    "transmog_render_url": "https://render.worldofwarcraft.com/us/a-main-raw.png",
}


def _fp(**overrides):
    return compute_transmog_fingerprint({**BASE, **overrides})


def test_fingerprint_is_stable_for_identical_input():
    assert _fp() == _fp()


def test_fingerprint_changes_when_transmog_url_changes():
    assert _fp() != _fp(transmog_render_url="https://render.worldofwarcraft.com/us/b-main-raw.png")


# --- under-sensitivity: these all feed build_prompt(), so all must regenerate

def test_fingerprint_changes_on_respec():
    """Regression: the URL-only fingerprint never moved on a spec change, so
    a respecced character kept art built from their old spec's prompt."""
    assert _fp() != _fp(active_spec="Shadow")


def test_fingerprint_changes_on_race_change():
    assert _fp() != _fp(race="Void Elf")


def test_fingerprint_changes_on_class_change():
    assert _fp() != _fp(**{"class": "Mage"})


def test_fingerprint_changes_on_gender_change():
    assert _fp() != _fp(gender="Male")


# --- over-sensitivity: nothing outside ART_INPUT_FIELDS may move it

def test_fingerprint_ignores_fields_generation_does_not_use():
    """Regression: the old no-URL path hashed the entire profile dict, so
    incidental churn triggered a full regeneration."""
    assert _fp() == _fp(name="Renamed", realm="another-realm",
                        role="healer", last_login="2026-07-20")


def test_fingerprint_accepts_manifest_spec_alias():
    """cast_manifest stores "spec"; the Blizzard profile uses "active_spec".
    The same character must fingerprint identically through either shape."""
    from_profile = compute_transmog_fingerprint(BASE)
    manifest_shape = {k: v for k, v in BASE.items() if k != "active_spec"}
    manifest_shape["spec"] = BASE["active_spec"]
    assert compute_transmog_fingerprint(manifest_shape) == from_profile


# --- degradation

def test_fingerprint_without_url_still_distinguishes_characters():
    """Two different characters both missing a render URL must not collide."""
    a = compute_transmog_fingerprint({"race": "Pandaren", "class": "Monk"})
    b = compute_transmog_fingerprint({"race": "Dracthyr", "class": "Evoker"})
    assert a and b and a != b


def test_fingerprint_changes_when_a_missing_url_arrives():
    """Gaining a render URL means the IP-Adapter reference is now available,
    which changes the art — so it must regenerate."""
    without = compute_transmog_fingerprint({k: v for k, v in BASE.items()
                                            if k != "transmog_render_url"})
    assert without != _fp()


def test_fingerprint_handles_none_and_empty_profile():
    assert compute_transmog_fingerprint(None)
    assert compute_transmog_fingerprint({})
    assert compute_transmog_fingerprint(None) == compute_transmog_fingerprint({})


def test_art_input_fields_matches_build_prompt_inputs():
    """If build_prompt() starts reading another profile field, this test is
    the reminder to add it to ART_INPUT_FIELDS."""
    assert set(ART_INPUT_FIELDS) == {
        "transmog_render_url", "race", "class", "gender", "active_spec"}

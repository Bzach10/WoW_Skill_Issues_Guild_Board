"""Regression tests for roster entry -> (name, realm) splitting.

The bug these lock down: blizzard.py and voyage.py used rsplit("-", 1),
which splits on the LAST hyphen. Roster entries are "name-realm-slug"
and most realm slugs contain hyphens, so "dathar-area-52" became
name="dathar-area", realm="52" — a 400/404 at both APIs. Both callers
treat a non-200 as "skip this character", so 65 of the 135 real roster
members vanished with no error logged.
"""

import pytest

from guild_board import blizzard
from guild_board.config import split_name_realm

# Realm slugs taken verbatim from the project's real roster_cache.json.
REAL_ROSTER_CASES = [
    ("aiime-bleeding-hollow", "aiime", "bleeding-hollow"),
    ("dathar-area-52", "dathar", "area-52"),
    ("beroben-emerald-dream", "beroben", "emerald-dream"),
    ("glinkz-wyrmrest-accord", "glinkz", "wyrmrest-accord"),
    ("kibli-lightnings-blade", "kibli", "lightnings-blade"),
    ("kitez-cenarion-circle", "kitez", "cenarion-circle"),
    ("obstorm-earthen-ring", "obstorm", "earthen-ring"),
    # Single-token realms — these worked even with the old rsplit, so they
    # are exactly the ones that masked the bug.
    ("rakdisc-proudmoore", "rakdisc", "proudmoore"),
    ("floofwall-queldorei", "floofwall", "queldorei"),
    ("healyeah-queldorei", "healyeah", "queldorei"),
]


@pytest.mark.parametrize("entry,expected_name,expected_realm", REAL_ROSTER_CASES)
def test_split_name_realm_uses_first_hyphen(entry, expected_name, expected_realm):
    assert split_name_realm(entry) == (expected_name, expected_realm)


@pytest.mark.parametrize("entry,expected_name,expected_realm", REAL_ROSTER_CASES)
def test_split_disagrees_with_rsplit_exactly_on_hyphenated_realms(
        entry, expected_name, expected_realm):
    """Documents the old behaviour so nobody 'simplifies' back to rsplit."""
    old = tuple(part.strip() for part in entry.rsplit("-", 1))
    new = split_name_realm(entry)
    if expected_realm.count("-"):
        assert old != new, f"{entry}: rsplit should mangle a hyphenated realm"
    else:
        assert old == new, f"{entry}: single-token realm is unaffected"


def test_split_name_realm_falls_back_to_default_realm():
    assert split_name_realm("solo", default_realm="bleeding-hollow") == (
        "solo", "bleeding-hollow")


def test_split_name_realm_handles_empty_entry():
    assert split_name_realm("", default_realm="x") == ("", "x")
    assert split_name_realm(None) == ("", "")


def test_split_name_realm_strips_whitespace():
    assert split_name_realm("  dathar - area-52 ") == ("dathar", "area-52")


class _Recorder:
    """Captures the (realm, name) pairs fetch_roster_profiles asks for."""

    def __init__(self):
        self.calls = []

    def __call__(self, token, region, realm_slug, character_name):
        self.calls.append((realm_slug, character_name))
        return {"name": character_name, "realm": realm_slug,
                "race": "Orc", "class": "Warrior"}


def test_fetch_roster_profiles_requests_correct_realm(monkeypatch):
    """The end-to-end shape of the bug: a hyphenated-realm roster entry must
    reach the Blizzard client as ("area-52", "dathar"), not ("52", "dathar-area").
    """
    recorder = _Recorder()
    monkeypatch.setattr(blizzard, "fetch_character_profile", recorder)

    profiles = blizzard.fetch_roster_profiles(
        "tok", "us", ["dathar-area-52", "aiime-bleeding-hollow"])

    assert recorder.calls == [
        ("area-52", "dathar"),
        ("bleeding-hollow", "aiime"),
    ]
    assert set(profiles) == {"dathar-area-52", "aiime-bleeding-hollow"}


def test_fetch_roster_profiles_logs_when_characters_are_dropped(monkeypatch, caplog):
    """A silent drop is what let the bug live; missing profiles must be logged."""
    monkeypatch.setattr(blizzard, "fetch_character_profile",
                        lambda *a, **kw: None)

    with caplog.at_level("WARNING"):
        profiles = blizzard.fetch_roster_profiles(
            "tok", "us", ["dathar-area-52", "aiime-bleeding-hollow"])

    assert profiles == {}
    assert "2 of 2" in caplog.text


def test_fetch_roster_profiles_is_quiet_when_everything_resolves(monkeypatch, caplog):
    monkeypatch.setattr(blizzard, "fetch_character_profile", _Recorder())

    with caplog.at_level("WARNING"):
        blizzard.fetch_roster_profiles("tok", "us", ["dathar-area-52"])

    assert "unavailable" not in caplog.text

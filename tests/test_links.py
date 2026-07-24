"""Per-player profile links.

The bug these pin: the guild is cross-realm. `guild.realm_slug` is
bleeding-hollow, but 95 of the 135 cached members (70%, across 37 realms)
are somewhere else. Building every link from the guild realm produced
URLs for characters that do not exist — verified against Raider.io's API,
where the guild-realm form returns 400 "Could not find requested
character" and the real realm returns the character.
"""

import pytest

from guild_board import links

ROSTER = [
    "rakdisc-proudmoore",
    "amrevenge-stormrage",
    "floofwall-queldorei",
    "tommybravoo-bleeding-hollow",
    "aiime-bleeding-hollow",
]


def test_realm_comes_from_the_roster_not_the_guild():
    index = links.realm_index(ROSTER)
    assert index["rakdisc"] == "proudmoore"
    assert index["amrevenge"] == "stormrage"
    assert index["tommybravoo"] == "bleeding-hollow"


def test_the_reported_bug_rakdisc_no_longer_points_at_the_guild_realm():
    index = links.realm_index(ROSTER)
    url = links.character_url("Rakdisc", index, region="us",
                              guild_realm="bleeding-hollow")
    assert url == "https://www.warcraftlogs.com/character/us/proudmoore/rakdisc"
    assert "bleeding-hollow" not in url


def test_on_realm_players_are_unaffected():
    index = links.realm_index(ROSTER)
    url = links.character_url("Tommybravoo", index, guild_realm="bleeding-hollow")
    assert url.endswith("/bleeding-hollow/tommybravoo")


def test_raiderio_links_use_the_same_realm():
    index = links.realm_index(ROSTER)
    url = links.character_url("rakdisc", index, site="raiderio")
    assert url == "https://raider.io/characters/us/proudmoore/rakdisc"


def test_region_is_honoured():
    index = links.realm_index(ROSTER)
    assert "/eu/" in links.character_url("rakdisc", index, region="EU")


def test_name_matching_is_case_insensitive():
    index = links.realm_index(ROSTER)
    for spelling in ("Rakdisc", "RAKDISC", "rakdisc", " Rakdisc "):
        assert links.character_url(spelling, index).endswith("/proudmoore/rakdisc")


# ---------------------------------------------------------------- gaps

def test_a_player_with_no_roster_entry_gets_no_link():
    """Phyrthepali holds a real parse record but is not in the roster
    cache. A guessed link is what produced the blank page in the first
    place, so we would rather emit nothing."""
    index = links.realm_index(ROSTER)
    assert links.character_url("phyrthepali", index) is None


def test_guild_realm_is_used_only_when_explicitly_offered():
    index = links.realm_index(ROSTER)
    assert links.character_url("phyrthepali", index) is None
    assert links.character_url("phyrthepali", index,
                               guild_realm="bleeding-hollow") is not None


def test_unresolved_surfaces_the_gap():
    index = links.realm_index(ROSTER)
    assert links.unresolved(["Rakdisc", "Phyrthepali", "Nobody"], index) == \
        ["nobody", "phyrthepali"]


def test_duplicate_names_on_two_realms_do_not_silently_flip():
    index = links.realm_index(["beroben-emerald-dream", "beroben-queldorei"])
    assert index["beroben"] == "emerald-dream"   # first wins, deterministically


# ---------------------------------------------------------------- fail-open

@pytest.mark.parametrize("roster", [
    None, [], ["no-dash-entry"], [""], [None, 42], ["-onlyrealm"], ["onlyname-"],
])
def test_a_broken_roster_cache_never_raises(roster):
    index = links.realm_index(roster)
    assert isinstance(index, dict)
    assert links.profile_urls(roster) == {} or all(
        v.startswith("http") for v in links.profile_urls(roster).values())


def test_empty_name_yields_no_link():
    assert links.character_url("", {"x": "y"}) is None
    assert links.character_url(None, {"x": "y"}) is None


def test_profile_urls_covers_the_whole_roster():
    urls = links.profile_urls(ROSTER, region="us")
    assert set(urls) == {"rakdisc", "amrevenge", "floofwall",
                         "tommybravoo", "aiime"}
    assert urls["rakdisc"].endswith("/proudmoore/rakdisc")

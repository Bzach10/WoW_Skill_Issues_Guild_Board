"""Player profile pages — a real permalink per member.

These are also the durable fix for the blank-link bug: the board now owns
a destination for every player, and the external links are outbound
options that only appear when we can build a correct one.
"""

from guild_board import profiles

BOARD_STATE = {
    "season_scores": {"amrevenge": 3908.1, "rakdisc": 3529.2, "shadoxii": 3692.2},
    "baseline": {"season_scores": {"rakdisc": 3500.0, "amrevenge": 3908.1}},
    "streaks": {"rakdisc": 3},
    "records": {
        "highest_timed_key": {"name": "amrevenge", "level": 20,
                              "dungeon": "Pit of Saron", "new": False},
        "best_hps_parse": {"name": "Phyrthepali", "parse": 96,
                           "boss": "Imperator Averzian", "spec": "Holy",
                           "cls": "Paladin", "new": True},
    },
}
CFG = {"guild": {"region": "us", "realm_slug": "bleeding-hollow"}}
ROSTER = ["rakdisc-proudmoore", "amrevenge-stormrage", "shadoxii-illidan"]


def member(slug, name=None, role="healer", **extra):
    base = {"slug": slug, "name": name or slug.title(), "role": role,
            "role_label": role.title(), "cls": "", "spec": "", "race": "",
            "catchphrase": None, "art_is_real": False,
            "doll": {"mode": "placeholder", "layers": [], "canvas": {"w": 832, "h": 1216}}}
    base.update(extra)
    return base


def test_profile_paths_are_stable_permalinks():
    assert profiles.profile_path("rakdisc") == "p/rakdisc.html"
    assert profiles.profile_href("rakdisc") == "p/rakdisc.html"
    assert profiles.profile_href("rakdisc", from_profile=True) == "../p/rakdisc.html"


def test_score_rank_and_delta_come_from_real_board_state():
    p = profiles.build_profile(member("rakdisc"), BOARD_STATE, CFG, ROSTER)
    assert p["score"] == 3529.2
    assert p["rank"] == 3 and p["field"] == 3
    assert p["delta"] == "+29.2"
    assert p["streak"] == 3


def test_no_delta_when_the_score_has_not_moved():
    p = profiles.build_profile(member("amrevenge", role="dps"), BOARD_STATE, CFG, ROSTER)
    assert p["delta"] is None


def test_records_are_attributed_to_the_holder_only():
    amr = profiles.build_profile(member("amrevenge", role="dps"), BOARD_STATE, CFG, ROSTER)
    assert [r["label"] for r in amr["records"]] == ["Highest timed key"]
    assert amr["records"][0]["value"] == "+20"
    assert "Pit of Saron" in amr["records"][0]["detail"]

    rak = profiles.build_profile(member("rakdisc"), BOARD_STATE, CFG, ROSTER)
    assert rak["records"] == []


def test_record_holder_matching_is_case_insensitive():
    """board_state stores 'Phyrthepali' but slugs are lowercase."""
    p = profiles.build_profile(member("phyrthepali"), BOARD_STATE, CFG, ROSTER)
    assert [r["label"] for r in p["records"]] == ["Best HPS parse"]
    assert p["records"][0]["fresh"] is True


def test_external_links_use_the_players_real_realm():
    p = profiles.build_profile(member("rakdisc"), BOARD_STATE, CFG, ROSTER)
    assert p["realm"] == "proudmoore"
    assert "/proudmoore/rakdisc" in p["wcl_url"]
    assert "/proudmoore/rakdisc" in p["rio_url"]
    assert p["realm_unknown"] is False


def test_an_unresolved_realm_yields_no_external_links_but_still_a_page():
    """Phyrthepali holds a real record but has no roster entry. The page
    must still exist — it just says so instead of guessing."""
    p = profiles.build_profile(member("phyrthepali"), BOARD_STATE, CFG, ROSTER)
    assert p["realm_unknown"] is True
    assert p["wcl_url"] is None and p["rio_url"] is None
    assert p["records"], "their real record still shows"


def test_a_member_with_no_data_at_all_still_gets_a_profile():
    p = profiles.build_profile(member("nobody", role="unknown"), {}, {}, [])
    assert p["name"] == "Nobody"
    assert p["score"] is None and p["rank"] is None
    assert p["records"] == []
    assert p["realm_unknown"] is True


def test_build_all_covers_the_whole_deck():
    crew = [member("rakdisc"), member("amrevenge", role="dps"), member("shadoxii", role="unknown")]
    out = profiles.build_all(crew, BOARD_STATE, CFG, ROSTER)
    assert [p["slug"] for p in out] == ["rakdisc", "amrevenge", "shadoxii"]
    assert all(p["name"] for p in out)


def test_missing_board_state_sections_do_not_raise():
    for broken in ({}, {"season_scores": None}, {"records": None},
                   {"baseline": None}, {"streaks": "nope"}):
        p = profiles.build_profile(member("rakdisc"), broken, CFG, ROSTER)
        assert p["slug"] == "rakdisc"

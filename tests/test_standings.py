"""The Standings — board-parity competition data (data floor)."""

from guild_board import standings


BOARD = {
    "standing": {"realm": 49, "region": 2219, "world": 6855},
    "season_scores": {"amrevenge": 3908.1, "tommybravoo": 3686.3, "buchalter": 3207.9},
    "baseline": {"season_scores": {"amrevenge": 3908.1, "tommybravoo": 3667.7,
                                   "buchalter": 3207.9}},
    "streaks": {"buchalter": 6, "amrevenge": 1},
    "records": {
        "highest_timed_key": {"name": "amrevenge", "level": 20, "dungeon": "Pit of Saron"},
        "best_dps_parse": {"name": "Amrevenge", "parse": 97, "boss": "Salhadaar", "spec": "BM"},
        "best_hps_parse": {"name": "Phyrthepali", "parse": 96, "boss": "Averzian"},
    },
}
VOYAGE = {
    "raid_progression": {"tier-mn-1": {"summary": "3/9 M", "total_bosses": 9,
                         "normal_bosses_killed": 0, "heroic_bosses_killed": 5,
                         "mythic_bosses_killed": 3}},
    "dungeons": {
        "Pit of Saron": {"level": 20, "name": "Amrevenge", "realm": "stormrage",
                         "score": 487.9, "clear_time_ms": 1550434},
        "Skyreach": {"level": 18, "name": "Rakdisc", "realm": "proudmoore",
                     "score": 470.0, "clear_time_ms": 1600000},
    },
}


def test_season_ladder_ranks_and_climb_and_attendance():
    s = standings.build(BOARD, VOYAGE)
    assert s["season_ladder"][0]["name"] == "Amrevenge" and s["season_ladder"][0]["rank"] == 1
    assert s["biggest_climb"]["name"] == "Tommybravoo"
    assert round(s["biggest_climb"]["delta"], 1) == 18.6
    assert s["iron_attendance"]["name"] == "Buchalter" and s["iron_attendance"]["streak"] == 6


def test_real_raid_progression_by_difficulty():
    s = standings.build(BOARD, VOYAGE)
    assert s["raid"]["mythic"] == 3 and s["raid"]["heroic"] == 5 and s["raid"]["total"] == 9


def test_guild_best_keys_sort_by_level_and_keep_cross_realm_holder():
    s = standings.build(BOARD, VOYAGE)
    keys = s["dungeon_keys"]
    assert keys[0]["level"] == 20 and keys[0]["dungeon"] == "Pit of Saron"
    # cross-realm holders are preserved, not flattened to the guild realm
    assert keys[1]["holder"] == "Rakdisc" and keys[1]["realm"] == "Proudmoore"
    assert keys[0]["time"] == "25:50"


def test_parses_fall_back_to_the_season_record_without_web_stats():
    s = standings.build(BOARD, VOYAGE)
    assert s["parses"]["dps"]["source"] == "record"
    assert s["parses"]["dps"]["rows"][0]["value"] == 97
    assert s["has_web_stats"] is False


def test_web_stats_supply_the_full_parse_ladder_when_present():
    ws = {"top_dps": [{"name": "A", "value": 99}, {"name": "B", "value": 95}]}
    s = standings.build(BOARD, VOYAGE, web_stats=ws)
    assert s["parses"]["dps"]["source"] == "wcl"
    assert len(s["parses"]["dps"]["rows"]) == 2
    assert s["has_web_stats"] is True

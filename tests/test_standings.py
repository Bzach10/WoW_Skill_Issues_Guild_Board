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


ROSTER = ["amrevenge-stormrage", "tommybravoo-bleeding-hollow", "buchalter-area-52"]


def test_a_parse_holder_missing_from_the_roster_is_still_rendered():
    """Regression: an off-roster parse holder must NOT be suppressed.

    Phyrthepali is a real Holy Paladin in the guild with a real 96 on
    Imperator Averzian, but he is missing from competition.json's roster
    pull. A revision that dropped off-roster rows erased his record from
    the front page. Absence from a derived roster means the roster is
    incomplete, not that the person is fake.
    """
    s = standings.build(BOARD, VOYAGE, roster=ROSTER)
    assert s["parses"]["hps"]["rows"][0]["name"] == "Phyrthepali"
    assert s["parses"]["hps"]["rows"][0]["value"] == 96
    assert s["parses"]["hps"]["source"] == "record"


def test_web_stats_rows_are_not_roster_filtered_either():
    ws = {"top_hps": [{"name": "Phyrthepali", "value": 96},
                      {"name": "Amrevenge", "value": 88}]}
    s = standings.build(BOARD, VOYAGE, web_stats=ws, roster=ROSTER)
    assert [r["name"] for r in s["parses"]["hps"]["rows"]] == ["Phyrthepali", "Amrevenge"]


def test_roster_mismatch_is_logged_not_silent():
    """The mismatch must reach whoever runs the build.

    Asserted against the logger directly and independently of global logging
    config, so a `logging.disable()` anywhere else cannot make this pass or
    fail spuriously.
    """
    import logging as _logging
    records = []

    class _Grab(_logging.Handler):
        def emit(self, r):
            records.append(r.getMessage())

    log = _logging.getLogger("guild_board.standings")
    h = _Grab()
    prev_level, prev_disable = log.level, _logging.root.manager.disable
    log.addHandler(h)
    log.setLevel(_logging.WARNING)
    _logging.disable(_logging.NOTSET)
    try:
        standings.build(BOARD, VOYAGE, roster=ROSTER)
    finally:
        log.removeHandler(h)
        log.setLevel(prev_level)
        _logging.disable(prev_disable)
    assert any("Phyrthepali" in m and "not in the roster" in m for m in records)


def test_no_roster_supplied_keeps_the_old_behaviour():
    s = standings.build(BOARD, VOYAGE)
    assert s["parses"]["hps"]["rows"][0]["value"] == 96

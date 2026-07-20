"""Offline tests for guild_board.voyage: the island data model is built
from real, already-used data (raiderio.DUNGEON_NAME_FIXES + board_state
records) — these tests pin that it never invents content."""

import json

from guild_board import voyage
from guild_board.raiderio import DUNGEON_NAME_FIXES


def test_build_islands_covers_every_real_dungeon_and_raid_boss():
    islands = voyage.build_islands()
    names = {isl["name"] for isl in islands}
    for real_dungeon in DUNGEON_NAME_FIXES.values():
        assert real_dungeon in names
    for boss in voyage.RAID_BOSSES:
        assert boss in names
    assert len(islands) == len(DUNGEON_NAME_FIXES) + len(voyage.RAID_BOSSES)


def test_build_islands_kinds_are_correct():
    islands = voyage.build_islands()
    dungeon_kinds = {isl["kind"] for isl in islands if isl["name"] in DUNGEON_NAME_FIXES.values()}
    boss_kinds = {isl["kind"] for isl in islands if isl["name"] in voyage.RAID_BOSSES}
    assert dungeon_kinds == {"dungeon"}
    assert boss_kinds == {"raid_boss"}


def test_current_island_defaults_to_first_dungeon():
    assert voyage.current_island_id({}) == voyage.build_islands()[0]["id"]


def test_current_island_honors_config_override():
    islands = voyage.build_islands()
    target = next(isl for isl in islands if isl["kind"] == "raid_boss")
    cfg = {"voyage": {"current_island": target["id"]}}
    assert voyage.current_island_id(cfg) == target["id"]


def test_current_island_ignores_unknown_override():
    cfg = {"voyage": {"current_island": "not-a-real-island"}}
    assert voyage.current_island_id(cfg) == voyage.build_islands()[0]["id"]


def test_fetch_raid_island_data_matches_real_record():
    board_state = {
        "records": {
            "best_dps_parse": {"name": "Amrevenge", "parse": 97,
                                "boss": "Fallen-King Salhadaar",
                                "spec": "BeastMastery", "cls": "Hunter"},
            "best_hps_parse": {"name": "Phyrthepali", "parse": 96,
                                "boss": "Imperator Averzian",
                                "spec": "Holy", "cls": "Paladin"},
        }
    }
    result = voyage.fetch_raid_island_data(board_state, "Fallen-King Salhadaar")
    assert result["name"] == "Amrevenge"
    assert result["role"] == "dps"


def test_fetch_raid_island_data_none_when_no_record_for_that_boss():
    board_state = {"records": {"best_dps_parse": {"boss": "Some Other Boss"}}}
    assert voyage.fetch_raid_island_data(board_state, "Vorasius") is None


def test_fetch_dungeon_island_data_uses_roster_and_public_raiderio(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    with open(tmp_path / "roster_cache.json", "w", encoding="utf-8") as f:
        json.dump({"last_updated": "2026-07-20T00:00:00+00:00",
                   "members": ["Rakdisc-Proudmoore"]}, f)

    def fake_get(url, params=None, timeout=None):
        class Resp:
            status_code = 200
            def json(self):
                return {
                    "name": "Rakdisc", "class": "Priest",
                    "mythic_plus_weekly_highest_level_runs": [
                        {"dungeon": "Grim Batol", "mythic_level": 12,
                         "num_keystone_upgrades": 2, "spec": "Discipline"},
                    ],
                }
        return Resp()

    monkeypatch.setattr("requests.get", fake_get)

    cfg = {"guild": {"region": "us"}, "roster_cache": {"enabled": True, "file": "roster_cache.json"}}
    result = voyage.fetch_dungeon_island_data(cfg, "Grim Batol")
    assert result["name"] == "Rakdisc"
    assert result["level"] == 12

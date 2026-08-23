"""Offline tests for the website data layers (guild_board.web_data).

Pure functions, fixture-driven — no network. These lock the JSON shapes
the front-end builds against, so a shape change that would break the UI
fails here first.
"""

import pytest

from guild_board import season, web_data


@pytest.fixture(autouse=True)
def _pin_season_one(monkeypatch):
    """Every fixture in this file is Season-1 data (Pit of Saron, Fallen-King
    Salhadaar, season-mn-1). CURRENT_SEASON resolves from the clock at import,
    so from the S2 flip (2026-08-18 15:00Z) these shapes would otherwise fail
    on the date; pin the season the fixtures describe."""
    monkeypatch.setattr(season, "CURRENT_SEASON", season.season_by_slug("season-mn-1"))

# A trimmed board_state with a baseline, so week-over-week diffs are real.
BOARD_STATE = {
    "last_updated": "2026-07-20T12:00:00+00:00",
    "streaks_week": "2026-07-14",
    "standing": {"realm": 49, "region": 2219, "world": 6855},
    "season_scores": {"amrevenge": 3908.1, "tommybravoo": 3686.3,
                      "rakdisc": 3529.2, "newbie": 1500.0},
    "streaks": {"tommybravoo": 2, "amrevenge": 1},
    "records": {
        "highest_timed_key": {"name": "amrevenge", "level": 20,
                              "dungeon": "Pit of Saron",
                              "spec": "Beast Mastery Hunter", "new": True},
        "best_dps_parse": {"name": "Amrevenge", "parse": 97,
                           "boss": "Fallen-King Salhadaar", "spec": "BeastMastery",
                           "cls": "Hunter", "new": False},
        "best_hps_parse": {"name": "Phyrthepali", "parse": 96,
                           "boss": "Imperator Averzian", "spec": "Holy",
                           "cls": "Paladin", "new": False},
    },
    "baseline": {
        "standing": {"world": 6854},
        "season_scores": {"amrevenge": 3908.1, "tommybravoo": 3667.7,
                          "rakdisc": 3529.2},  # newbie absent -> new face
        "records": {
            "highest_timed_key": {"name": "amrevenge", "level": 18,
                                  "dungeon": "Skyreach"},
            "best_dps_parse": {"name": "Amrevenge", "parse": 97,
                               "boss": "Fallen-King Salhadaar"},
            "best_hps_parse": {"name": "Phyrthepali", "parse": 96,
                               "boss": "Imperator Averzian"},
        },
    },
}


# --- Layer 1: recap ribbon

def test_recap_surfaces_new_key_record_first():
    ribbon = web_data.build_recap_ribbon(BOARD_STATE)
    assert ribbon["beats"], "expected at least one beat"
    top = ribbon["beats"][0]
    assert top["kind"] == "biggest_key"
    assert top["emphasis"] == "record"   # level rose 18 -> 20
    assert top["is_new"] is True


def test_recap_detects_biggest_climber():
    ribbon = web_data.build_recap_ribbon(BOARD_STATE)
    climber = next(b for b in ribbon["beats"] if b["kind"] == "biggest_climber")
    assert climber["subject"] == "Tommybravoo"
    assert climber["value"] == 18.6   # 3686.3 - 3667.7


def test_recap_flags_new_ladder_face():
    ribbon = web_data.build_recap_ribbon(BOARD_STATE)
    newbie = next(b for b in ribbon["beats"] if b["kind"] == "new_on_ladder")
    assert "Newbie" in newbie["detail"]


def test_recap_standing_slip_is_reported_with_direction():
    ribbon = web_data.build_recap_ribbon(BOARD_STATE)
    move = next(b for b in ribbon["beats"] if b["kind"] == "standing_move")
    assert "slipped" in move["detail"]   # world 6854 -> 6855

def test_recap_parse_detail_has_no_double_paren():
    ribbon = web_data.build_recap_ribbon(BOARD_STATE)
    for b in ribbon["beats"]:
        assert "))" not in b["detail"]


def test_recap_includes_transmog_beat_when_changes_present():
    changes = {"changed": [{"slug": "rakdisc-proudmoore", "name": "Rakdisc"}]}
    # max_beats raised so the trim doesn't hide the generated beat behind the
    # six higher-priority record/standing beats this fixture already yields.
    ribbon = web_data.build_recap_ribbon(BOARD_STATE, transmog_changes=changes,
                                         max_beats=20)
    beat = next(b for b in ribbon["beats"] if b["kind"] == "transmog")
    assert beat["value"] == 1 and "Rakdisc" in beat["detail"]


def test_recap_trims_to_max_beats():
    ribbon = web_data.build_recap_ribbon(BOARD_STATE, max_beats=3)
    assert len(ribbon["beats"]) == 3
    # Records survive the trim ahead of normal beats.
    assert ribbon["beats"][0]["emphasis"] == "record"


def test_recap_survives_empty_board_state():
    ribbon = web_data.build_recap_ribbon({})
    assert ribbon["beats"] == []
    assert ribbon["schema_version"] == web_data.SCHEMA_VERSION


# --- Layer 2: records leaderboard

def test_leaderboard_ranks_by_score_descending():
    lb = web_data.build_records_leaderboard(BOARD_STATE)
    ranks = [r["rank"] for r in lb["ladder"]]
    scores = [r["score"] for r in lb["ladder"]]
    assert ranks == sorted(ranks)
    assert scores == sorted(scores, reverse=True)
    assert lb["ladder"][0]["name"] == "Amrevenge"


def test_leaderboard_row_carries_all_sort_keys():
    lb = web_data.build_records_leaderboard(BOARD_STATE)
    row = next(r for r in lb["ladder"] if r["key"] == "tommybravoo")
    assert row["delta_week"] == 18.6
    assert row["streak_weeks"] == 2
    assert set(lb["sortable_by"]) == {"score", "delta_week", "streak_weeks", "rank"}


def test_leaderboard_headline_records_normalised():
    lb = web_data.build_records_leaderboard(BOARD_STATE)
    ids = {r["id"] for r in lb["headline_records"]}
    assert ids == {"highest_timed_key", "best_dps_parse", "best_hps_parse"}
    key = next(r for r in lb["headline_records"] if r["id"] == "highest_timed_key")
    assert key["holder"] == "Amrevenge" and key["value"] == 20


def test_leaderboard_marks_new_member():
    lb = web_data.build_records_leaderboard(BOARD_STATE)
    assert next(r for r in lb["ladder"] if r["key"] == "newbie")["is_new"] is True


# --- Layer 3: guild achievements

def test_achievements_degrade_without_data():
    ga = web_data.build_guild_achievements(None)
    assert ga["available"] is False
    assert ga["status"] == "pending_credentials"
    assert ga["trophies"] == []


def test_achievements_parse_real_payload():
    payload = {
        "total_quantity": 1234,
        "achievements": [
            {"achievement": {"id": 15001, "name": "Ahead of the Curve: Imperator Averzian"},
             "completed_timestamp": 1_770_000_000_000,
             "criteria": {"is_completed": True, "child_criteria": [{}, {}]}},
        ],
    }
    ga = web_data.build_guild_achievements(payload)
    assert ga["available"] is True and ga["total_points"] == 1234
    t = ga["trophies"][0]
    assert t["id"] == 15001
    assert t["completed_at"].startswith("20")   # ms -> ISO
    assert t["criteria"]["child_count"] == 2


# --- Layer 4: island completion

def _dungeon_bests(**over):
    base = {"Pit of Saron": {"level": 20, "timed": True, "by": "Amrevenge"},
            "Maisara Caverns": {"level": 16, "timed": False, "by": "Rakdisc"}}
    base.update(over)
    return base


RAID_PROG = {"tier-mn-1": {"summary": "3/9 M", "mythic_bosses_killed": 3,
                           "heroic_bosses_killed": 5, "normal_bosses_killed": 0}}


def test_island_completion_uses_verified_season_pool():
    ic = web_data.build_island_completion(_dungeon_bests(), RAID_PROG,
                                          BOARD_STATE["records"])
    names = {i["name"] for i in ic["dungeons"]["islands"]}
    assert names == season.dungeon_names()   # all 8 Midnight S1 dungeons
    assert ic["dungeons"]["total"] == 8


def test_dungeon_status_reflects_timed_attempted_locked():
    ic = web_data.build_island_completion(_dungeon_bests(), RAID_PROG,
                                          BOARD_STATE["records"])
    by_name = {i["name"]: i for i in ic["dungeons"]["islands"]}
    assert by_name["Pit of Saron"]["status"] == "conquered"
    assert by_name["Maisara Caverns"]["status"] == "attempted"
    assert by_name["Skyreach"]["status"] == "locked"
    assert ic["dungeons"]["conquered"] == 1


def test_raid_boss_confirmed_vs_inferred():
    ic = web_data.build_island_completion(_dungeon_bests(), RAID_PROG,
                                          BOARD_STATE["records"])
    by_name = {i["name"]: i for i in ic["raid"]["islands"]}
    # In board records, so exactly confirmed:
    assert by_name["Fallen-King Salhadaar"]["kill_confirmed"] is True
    assert by_name["Imperator Averzian"]["kill_confirmed"] is True
    # Within the kill count but not in records -> inferred:
    vorasius = by_name["Vorasius"]
    assert vorasius["status"] == "conquered"
    assert vorasius["inferred_from_progress"] is True
    # Beyond the 5 killed -> locked:
    assert by_name["Midnight Falls"]["status"] == "locked"


def test_raid_exposes_per_difficulty_counts():
    ic = web_data.build_island_completion(_dungeon_bests(), RAID_PROG,
                                          BOARD_STATE["records"])
    assert ic["raid"]["killed_by_difficulty"] == {
        "normal": 0, "heroic": 5, "mythic": 3}
    assert ic["raid"]["bosses_killed"] == 5


def test_island_completion_empty_inputs_are_all_locked():
    ic = web_data.build_island_completion()
    assert ic["dungeons"]["conquered"] == 0
    assert all(i["status"] == "locked" for i in ic["dungeons"]["islands"])


# --- Layer 5: transmog changes

MANIFEST = {"characters": {
    "rakdisc-proudmoore": {"name": "Rakdisc", "class": "Priest",
                           "transmog_fingerprint": "AAA"},
    "floofwall-queldorei": {"name": "Floofwall", "class": "Monk",
                            "transmog_fingerprint": "BBB"},
}}


def test_transmog_first_run_reports_nothing_changed_and_seeds_baseline():
    out = web_data.build_transmog_changes(MANIFEST, snapshot=None)
    assert out["is_first_run"] is True
    assert out["changed"] == []
    assert out["snapshot"] == {"rakdisc-proudmoore": "AAA",
                               "floofwall-queldorei": "BBB"}


def test_transmog_detects_a_changed_look():
    prior = {"rakdisc-proudmoore": "OLD", "floofwall-queldorei": "BBB"}
    out = web_data.build_transmog_changes(MANIFEST, snapshot=prior)
    assert out["changed_count"] == 1
    change = out["changed"][0]
    assert change["name"] == "Rakdisc"
    assert change["before_fingerprint"] == "OLD"
    assert change["after_fingerprint"] == "AAA"


def test_transmog_unchanged_look_is_not_reported():
    prior = {"rakdisc-proudmoore": "AAA", "floofwall-queldorei": "BBB"}
    out = web_data.build_transmog_changes(MANIFEST, snapshot=prior)
    assert out["changed_count"] == 0


def test_transmog_new_character_is_not_a_change():
    prior = {"rakdisc-proudmoore": "AAA"}   # floofwall is new since snapshot
    out = web_data.build_transmog_changes(MANIFEST, snapshot=prior)
    assert out["changed_count"] == 0
    assert [c["slug"] for c in out["new_characters"]] == ["floofwall-queldorei"]


# --- Assembler

def test_build_site_data_assembles_all_five_layers():
    site = web_data.build_site_data(
        board_state=BOARD_STATE, manifest=MANIFEST,
        dungeon_bests=_dungeon_bests(), raid_progression=RAID_PROG)
    for layer in ("recap_ribbon", "records_leaderboard", "guild_achievements",
                  "island_completion", "transmog_changes"):
        assert layer in site
        assert site[layer]["schema_version"] == web_data.SCHEMA_VERSION
    assert site["season"]["slug"] == "season-mn-1"


def test_build_site_data_degrades_with_no_inputs():
    site = web_data.build_site_data()
    assert site["guild_achievements"]["available"] is False
    assert site["records_leaderboard"]["ladder"] == []
    assert site["island_completion"]["dungeons"]["conquered"] == 0


def test_parity_map_covers_every_discord_field():
    """The data parity floor: every weekly-board field has a website home."""
    site = web_data.build_site_data(board_state=BOARD_STATE)
    parity = site["parity"]
    fields = {f["field"] for f in parity["fields"]}
    # The Discord board's headline fields must all be mapped.
    for required in ("guild_standing", "mplus_weekly_keys", "mplus_season_scores",
                     "raid_progression", "top_dps_parses", "most_deaths",
                     "roast_of_the_week", "guild_achievements"):
        assert required in fields
    assert parity["summary"]["total"] == len(parity["fields"])
    # With a real board_state, standing + M+ keys are live, not pending.
    by = {f["field"]: f["state"] for f in parity["fields"]}
    assert by["guild_standing"] == "live"

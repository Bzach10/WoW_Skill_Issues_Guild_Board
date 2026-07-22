"""Tests for the competition data layer (the WANTED BOARD).

No network — build_competition is pure and _normalize_character is fed
fixture payloads shaped like real Raider.io responses.
"""

from guild_board.competition import (
    _normalize_character,
    build_competition,
    canonical_role,
)


def _char(name, key, cls, spec, role, score, delta_base=None, runs=None):
    return {
        "name": name, "realm": "r", "key": key, "class": cls, "spec": spec,
        "role": role, "score": score,
        "scores_by_role": {"dps": score if role == "DPS" else 0,
                           "healer": score if role == "Healer" else 0,
                           "tank": score if role == "Tank" else 0},
        "best_runs": runs or [], "ranks": {"realm_overall": 100},
    }


FETCHED = {"characters": [
    _char("Amrevenge", "amrevenge-stormrage", "Hunter", "Beast Mastery Hunter", "DPS", 3908.1),
    _char("Tommybravoo", "tommybravoo-bleeding-hollow", "DK", "Unholy DK", "DPS", 3753.4),
    _char("Shadoxii", "shadoxii-illidan", "Monk", "Mistweaver Monk", "Healer", 3692.2),
    _char("Floofwall", "floofwall-queldorei", "Monk", "Brewmaster Monk", "Tank", 3484.3),
    _char("Rakdisc", "rakdisc-proudmoore", "Priest", "Discipline Priest", "Healer", 3529.2),
    _char("Newbie", "newbie-area-52", "Mage", "Frost Mage", "DPS", 1500.0),
]}

BOARD_STATE = {
    "last_updated": "2026-07-20T12:00:00+00:00",
    "records": {"best_dps_parse": {"name": "Amrevenge", "parse": 97,
                                   "boss": "Fallen-King Salhadaar",
                                   "spec": "BeastMastery", "cls": "Hunter"}},
    "baseline": {"season_scores": {"amrevenge": 3908.1, "tommybravoo": 3600.0,
                                   "shadoxii": 3692.2, "floofwall": 3484.3,
                                   "rakdisc": 3529.2}},  # newbie absent -> new
}


# --- role normalization (the bug that hid every healer)

def test_canonical_role_maps_raiderio_healing_to_healer():
    assert canonical_role("HEALING") == "Healer"
    assert canonical_role("TANK") == "Tank"
    assert canonical_role("DPS") == "DPS"
    assert canonical_role("") == ""


def test_normalize_character_canonicalizes_role():
    rec = _normalize_character("rakdisc-proudmoore", {
        "name": "Rakdisc", "class": "Priest", "active_spec_name": "Discipline",
        "active_spec_role": "HEALING",
        "mythic_plus_scores_by_season": [{"scores": {"all": 3529.2, "healer": 3529.2}}],
        "mythic_plus_best_runs": [], "mythic_plus_ranks": {}})
    assert rec["role"] == "Healer"
    assert rec["score"] == 3529.2


def test_by_role_buckets_healers_from_raw_healing_cache():
    """A cache written with raw 'HEALING' must still bucket as Healer."""
    raw = {"characters": [_char("H", "h-r", "Priest", "Disc", "HEALING", 3000.0)]}
    comp = build_competition(raw, {})
    assert len(comp["rankings"]["by_role"]["Healer"]) == 1


# --- rankings

def test_overall_ranked_by_score_top5_flagged():
    comp = build_competition(FETCHED, BOARD_STATE)
    overall = comp["rankings"]["overall"]
    assert [r["name"] for r in overall[:3]] == ["Amrevenge", "Tommybravoo", "Shadoxii"]
    assert overall[0]["rank"] == 1
    assert all(r["top5"] for r in overall[:5])
    assert not overall[5]["top5"]           # 6th is not top 5
    assert comp["rankings"]["top5"][0]["name"] == "Amrevenge"


def test_by_role_and_by_class_rank_within_group():
    comp = build_competition(FETCHED, BOARD_STATE)
    healers = comp["rankings"]["by_role"]["Healer"]
    assert [h["name"] for h in healers] == ["Shadoxii", "Rakdisc"]
    assert healers[0]["rank"] == 1 and healers[1]["rank"] == 2
    monks = comp["rankings"]["by_class"]["Monk"]
    assert {m["name"] for m in monks} == {"Shadoxii", "Floofwall"}


# --- movement

def test_movement_biggest_gain_and_new_to_board():
    comp = build_competition(FETCHED, BOARD_STATE)
    mv = comp["movement"]
    assert mv["biggest_gain"]["name"] == "Tommybravoo"   # +153.4
    assert mv["biggest_gain"]["delta_week"] == 153.4
    assert [n["name"] for n in mv["new_to_board"]] == ["Newbie"]
    assert all(c["delta_week"] > 0 for c in mv["climbers"])


# --- browsable detail

def test_every_character_has_full_browsable_detail():
    runs = [{"dungeon": "Pit of Saron", "short": "POS", "level": 20,
             "timed": True, "upgrades": 1, "score": 492.2,
             "clear_ms": 1, "par_ms": 2}]
    fetched = {"characters": [_char("A", "a-r", "Hunter", "BM Hunter", "DPS",
                                    3908.1, runs=runs)]}
    comp = build_competition(fetched, BOARD_STATE)
    a = comp["characters"][0]
    # Full detail, not just a summary line.
    assert a["best_runs"][0]["dungeon"] == "Pit of Saron"
    assert a["best_runs"][0]["timed"] is True
    assert a["scores_by_role"]["dps"] == 3908.1
    assert a["ranks"]["realm_overall"] == 100
    assert a["rank"] == 1 and a["top5"] is True


def test_parse_enrichment_from_board_records_only():
    comp = build_competition(FETCHED, BOARD_STATE)
    amr = next(c for c in comp["characters"] if c["name"] == "Amrevenge")
    assert amr["parse"]["best"] == 97
    assert amr["parse"]["source"] == "board_state"
    # Someone with no record has no invented parse.
    assert next(c for c in comp["characters"] if c["name"] == "Newbie")["parse"] is None
    assert comp["parses"]["available"] == "partial"


# --- degradation

def test_build_competition_empty_is_valid_and_unavailable():
    comp = build_competition(None, None)
    assert comp["available"] is False
    assert comp["character_count"] == 0
    assert comp["rankings"]["overall"] == []
    assert comp["movement"]["biggest_gain"] is None


def test_normalize_character_handles_missing_data():
    assert _normalize_character("x-y", None) is None
    rec = _normalize_character("ghost-realm", {"name": "Ghost"})
    assert rec["score"] == 0 and rec["best_runs"] == []


def test_best_runs_sorted_by_score_desc():
    data = {"name": "A", "class": "Hunter", "active_spec_role": "DPS",
            "mythic_plus_best_runs": [
                {"dungeon": "Low", "mythic_level": 10, "num_keystone_upgrades": 1, "score": 100},
                {"dungeon": "High", "mythic_level": 20, "num_keystone_upgrades": 1, "score": 500}],
            "mythic_plus_scores_by_season": [{"scores": {"all": 600}}]}
    rec = _normalize_character("a-r", data)
    assert [r["dungeon"] for r in rec["best_runs"]] == ["High", "Low"]
    assert rec["best_runs"][0]["timed"] is True

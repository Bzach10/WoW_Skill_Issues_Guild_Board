"""The three fields the pipeline fetched and dropped, and the keying bug
that would have paid them to the wrong person.

Every one of these locks a fact that was true and undelivered before this
lane, so a regression is a test failure and not a discovery six weeks later
in a ledger:

  * `completed_at`   -- in every Raider.io run object we already fetch, and
                        dropped by the normalizer. Without it "you timed a
                        key THIS WEEK" is not a measurable statement.
  * `keystone_run_id`-- same payload, same drop. It is the ONLY handle on
                        who else was in the run (mythic-plus/run-details).
  * `attendance`     -- computed for the whole season by the Most Improved
                        sweep "at zero extra API cost" by its own comment,
                        then collapsed to one integer per name and discarded.

  * and the keying: `streaks` and `deaths` are keyed on a BARE NAME because
    Warcraft Logs has no realms, while the roster carries TWO characters
    called Beroben. test_ambiguous_bare_name_is_never_resolved_to_a_guess is
    the test that would have caught it.

No network: fixtures only.
"""

import json

import pytest

from guild_board import competition, state, web_data
from guild_board.config import index_roster_by_name, resolve_character_key

# The live collision, verbatim from roster_cache.json.
ROSTER = [
    "amrevenge-stormrage", "tommybravoo-bleeding-hollow",
    "beroben-emerald-dream", "beroben-queldorei", "healmates-bleeding-hollow",
]


def _rio_run(**over):
    """A Raider.io run object in its real shape (18 keys upstream; the ones
    this pipeline reads plus the two it used to drop)."""
    run = {
        "dungeon": "Pit of Saron", "short_name": "POS", "mythic_level": 20,
        "num_keystone_upgrades": 1, "score": 492.24,
        "clear_time_ms": 1456281, "par_time_ms": 1800999,
        "completed_at": "2026-07-16T02:41:19.000Z",
        "keystone_run_id": 42508722,
    }
    run.update(over)
    return run


def _profile(best=None, recent=None):
    return {
        "name": "Amrevenge", "realm": "Stormrage", "class": "Hunter",
        "active_spec_name": "Beast Mastery", "active_spec_role": "DPS",
        "mythic_plus_scores_by_season": [{"scores": {"all": 3908.1, "dps": 3908.1,
                                                     "healer": 0, "tank": 0}}],
        "mythic_plus_ranks": {},
        "mythic_plus_best_runs": best or [],
        "mythic_plus_recent_runs": recent or [],
    }


# --- 1. THE CLOCK AND THE RUN ID -----------------------------------------

def test_recent_runs_ride_the_same_request():
    """One call per character, not two. `fields` is a single comma-joined
    list, so the recent-runs list is free."""
    assert "mythic_plus_recent_runs" in competition.RAIDERIO_FIELDS
    assert competition.RAIDERIO_FIELDS.count("mythic_plus") == 4  # one request


def test_best_runs_carry_the_clock_and_the_run_id():
    rec = competition._normalize_character(
        "amrevenge-stormrage", _profile(best=[_rio_run()]))
    run = rec["best_runs"][0]
    assert run["completed_at"] == "2026-07-16T02:41:19.000Z"
    assert run["keystone_run_id"] == 42508722
    # and the eight fields that were already delivered are untouched
    assert run["dungeon"] == "Pit of Saron" and run["level"] == 20
    assert run["timed"] is True and run["upgrades"] == 1
    assert run["score"] == 492.2
    assert run["clear_ms"] == 1456281 and run["par_ms"] == 1800999
    assert run["short"] == "POS"


def test_completed_at_is_raiderio_s_own_string_never_restamped():
    """Carried verbatim. Re-parsing it here would bake this machine's
    timezone into a week boundary the consumer has to compute itself."""
    rec = competition._normalize_character(
        "amrevenge-stormrage",
        _profile(recent=[_rio_run(completed_at="2026-07-16T02:41:19.000Z")]))
    assert rec["recent_runs"][0]["completed_at"] == "2026-07-16T02:41:19.000Z"


def test_recent_runs_are_delivered_newest_first():
    rec = competition._normalize_character("amrevenge-stormrage", _profile(recent=[
        _rio_run(keystone_run_id=1, completed_at="2026-07-10T00:00:00.000Z"),
        _rio_run(keystone_run_id=2, completed_at="2026-07-19T00:00:00.000Z"),
        _rio_run(keystone_run_id=3, completed_at="2026-07-14T00:00:00.000Z"),
    ]))
    assert [r["keystone_run_id"] for r in rec["recent_runs"]] == [2, 3, 1]


def test_a_run_with_no_clock_sorts_last_instead_of_raising():
    rec = competition._normalize_character("amrevenge-stormrage", _profile(recent=[
        _rio_run(keystone_run_id=1, completed_at=None),
        _rio_run(keystone_run_id=2, completed_at="2026-07-19T00:00:00.000Z"),
    ]))
    assert [r["keystone_run_id"] for r in rec["recent_runs"]] == [2, 1]
    assert rec["recent_runs"][1]["completed_at"] is None


def test_runs_are_deduped_by_run_id():
    """The id is the run's identity. A consumer that fans out one
    run-details request per row must not pay for the same run twice."""
    rec = competition._normalize_character("amrevenge-stormrage", _profile(recent=[
        _rio_run(keystone_run_id=42508722),
        _rio_run(keystone_run_id=42508722, dungeon="Pit of Saron"),
        _rio_run(keystone_run_id=42611904, dungeon="Skyreach"),
    ]))
    assert [r["keystone_run_id"] for r in rec["recent_runs"]] == [42611904, 42508722] \
        or sorted(r["keystone_run_id"] for r in rec["recent_runs"]) == [42508722, 42611904]
    assert len(rec["recent_runs"]) == 2


def test_runs_without_an_id_are_all_kept():
    """None is not an identity: collapsing every id-less run into one would
    DELETE real runs. Better a visible duplicate than a silent deletion."""
    rec = competition._normalize_character("amrevenge-stormrage", _profile(recent=[
        _rio_run(keystone_run_id=None, dungeon="A"),
        _rio_run(keystone_run_id=None, dungeon="B"),
    ]))
    assert len(rec["recent_runs"]) == 2
    assert all(r["keystone_run_id"] is None for r in rec["recent_runs"])


def test_a_string_run_id_becomes_an_int_so_dedup_still_works():
    rec = competition._normalize_character("amrevenge-stormrage", _profile(recent=[
        _rio_run(keystone_run_id="42508722"),
        _rio_run(keystone_run_id=42508722),
    ]))
    assert len(rec["recent_runs"]) == 1
    assert rec["recent_runs"][0]["keystone_run_id"] == 42508722


def test_a_junk_run_id_lands_as_none_not_an_exception():
    rec = competition._normalize_character(
        "amrevenge-stormrage", _profile(best=[_rio_run(keystone_run_id="n/a")]))
    assert rec["best_runs"][0]["keystone_run_id"] is None


def test_build_competition_defaults_recent_runs_for_a_pre_change_cache():
    """competition_cache.json written before this lane has no recent_runs.
    The delivered shape must still be uniform on the first run after."""
    old = {"name": "Amrevenge", "key": "amrevenge-stormrage", "realm": "Stormrage",
           "class": "Hunter", "spec": "Beast Mastery Hunter", "role": "DPS",
           "score": 3908.1, "scores_by_role": {"dps": 3908.1, "healer": 0, "tank": 0},
           "best_runs": [], "ranks": {}}
    built = competition.build_competition({"characters": [old]})
    assert built["characters"][0]["recent_runs"] == []


# --- 2. ATTENDANCE, PERSISTED AND DELIVERED ------------------------------

ATTENDANCE_SWEEP = {
    "weeks": {"amrevenge": {"2026-07-14", "2026-07-07"},
              "beroben": {"2026-07-14"}},
    "scanned": {"2026-07-07", "2026-07-14"},
    "all": {"2026-06-30", "2026-07-07", "2026-07-14"},
}


def test_sets_from_the_sweep_become_sorted_lists():
    block = state.attendance_for_state(ATTENDANCE_SWEEP)
    assert block["weeks"]["amrevenge"] == ["2026-07-07", "2026-07-14"]
    assert block["scanned"] == ["2026-07-07", "2026-07-14"]
    assert block["all"] == ["2026-06-30", "2026-07-07", "2026-07-14"]
    json.dumps(block)   # the whole point: it has to survive a JSON dump


def test_an_empty_sweep_is_none_not_an_empty_season():
    assert state.attendance_for_state(None) is None
    assert state.attendance_for_state({"weeks": {}}) is None


def test_attendance_reaches_board_state(tmp_path):
    path = str(tmp_path / "board_state.json")
    state.save_board_state({"realm": 49}, [(3908.1, "Amrevenge", "BM")],
                           streaks={"amrevenge": 2}, path=path,
                           streaks_week="2026-07-14",
                           attendance=ATTENDANCE_SWEEP)
    saved = json.loads(open(path, encoding="utf-8").read())
    assert saved["attendance"]["weeks"]["amrevenge"] == ["2026-07-07", "2026-07-14"]


def test_a_run_that_read_no_logs_does_not_erase_the_last_one_that_did(tmp_path):
    """Same rule as the week block: an empty sweep is a gap in the
    measurement, not a season in which nobody raided."""
    path = str(tmp_path / "board_state.json")
    state.save_board_state({"realm": 49}, [], path=path,
                           streaks_week="2026-07-14",
                           attendance=ATTENDANCE_SWEEP)
    state.save_board_state({"realm": 49}, [], path=path,
                           streaks_week="2026-07-21", attendance=None)
    saved = json.loads(open(path, encoding="utf-8").read())
    assert saved["attendance"]["weeks"]["amrevenge"] == ["2026-07-07", "2026-07-14"]


BOARD_STATE = {
    "last_updated": "2026-07-20T12:00:00+00:00",
    "streaks_week": "2026-07-14",
    "streaks": {"amrevenge": 2, "beroben": 2, "healmates": 3, "longgone": 1},
    "attendance": {
        "weeks": {"amrevenge": ["2026-07-07", "2026-07-14"],
                  "beroben": ["2026-07-14"],
                  "healmates": ["2026-06-30", "2026-07-14"]},
        "scanned": ["2026-06-30", "2026-07-07", "2026-07-14"],
        "all": ["2026-06-23", "2026-06-30", "2026-07-07", "2026-07-14"],
    },
    "week": {"label": "2026-07-14", "kills": 6, "pulls": 54,
             "deaths_total": 50, "deaths": {"amrevenge": 30, "beroben": 20}},
}


def test_attendance_is_delivered_keyed_on_the_character_key():
    week = web_data.build_weekly_board(BOARD_STATE, roster=ROSTER)
    assert week["attendance"]["amrevenge-stormrage"] == ["2026-07-07", "2026-07-14"]
    assert week["attendance"]["healmates-bleeding-hollow"] == ["2026-06-30", "2026-07-14"]
    assert all("-" in key for key in week["attendance"]), (
        "a bare name is not an identity")
    assert week["keyed_against_roster"] is True


def test_coverage_names_the_unknown_weeks():
    """A week the guild logged but whose details were never read is UNKNOWN.
    An absence in one of those is not evidence that someone skipped raid."""
    week = web_data.build_weekly_board(BOARD_STATE, roster=ROSTER)
    assert week["attendance_coverage"]["weeks_unknown"] == ["2026-06-23"]
    assert week["attendance_coverage"]["characters"] == 2   # beroben is unkeyed
    assert week["attendance_coverage"]["source_names"] == 3


# --- 3. THE BEROBEN COLLISION --------------------------------------------

def test_the_roster_index_keeps_both_berobens():
    index = index_roster_by_name(ROSTER)
    assert index["beroben"] == ["beroben-emerald-dream", "beroben-queldorei"]
    assert index["amrevenge"] == ["amrevenge-stormrage"]


def test_ambiguous_bare_name_is_never_resolved_to_a_guess():
    """THE regression test. Two real people share the name Beroben. Any
    resolver that returns one of them -- first sorted, highest scored, most
    recently seen -- credits the wrong person silently and forever."""
    index = index_roster_by_name(ROSTER)
    key, reason = resolve_character_key("Beroben", index)
    assert key is None
    assert reason == "ambiguous"


def test_unambiguous_and_unknown_names_resolve_as_expected():
    index = index_roster_by_name(ROSTER)
    assert resolve_character_key("Amrevenge", index) == ("amrevenge-stormrage", "")
    assert resolve_character_key("amrevenge-stormrage", index) == (
        "amrevenge-stormrage", "")     # already a key
    assert resolve_character_key("nobody", index) == (None, "unknown")
    assert resolve_character_key("", index) == (None, "unknown")


def test_the_collision_ships_as_a_named_seam_not_a_credited_guess():
    week = web_data.build_weekly_board(BOARD_STATE, roster=ROSTER)
    assert "beroben-emerald-dream" not in week["attendance"]
    assert "beroben-queldorei" not in week["attendance"]
    assert {"name": "beroben", "reason": "ambiguous"} in week["attendance_unresolved"]
    assert {"name": "beroben", "reason": "ambiguous"} in week["streaks_unresolved"]
    assert {"name": "beroben", "reason": "ambiguous"} in week["deaths_unresolved"]


def test_a_departed_name_is_reported_not_dropped():
    week = web_data.build_weekly_board(BOARD_STATE, roster=ROSTER)
    assert {"name": "longgone", "reason": "unknown"} in week["streaks_unresolved"]


def test_streaks_and_deaths_gain_keyed_siblings():
    week = web_data.build_weekly_board(BOARD_STATE, roster=ROSTER)
    assert week["streaks_by_key"]["amrevenge-stormrage"] == 2
    assert week["deaths_by_key"]["amrevenge-stormrage"] == 30
    assert all("-" in key for key in week["streaks_by_key"])
    assert all("-" in key for key in week["deaths_by_key"])


def test_the_bare_name_maps_are_left_alone_for_the_current_consumer():
    """Additive on purpose. The live site reads weekly_board.streaks today;
    replacing it here would break the surface before the consumer lane has
    switched. The site retires these -- this lane does not."""
    week = web_data.build_weekly_board(BOARD_STATE, roster=ROSTER)
    assert week["streaks"] == BOARD_STATE["streaks"]
    assert week["deaths"] == BOARD_STATE["week"]["deaths"]


def test_no_roster_means_empty_keyed_maps_and_says_so_out_loud():
    """A consumer must be able to tell "could not key" from "nobody raided"."""
    week = web_data.build_weekly_board(BOARD_STATE)
    assert week["keyed_against_roster"] is False
    assert week["attendance"] == {} and week["streaks_by_key"] == {}
    assert week["attendance_unresolved"] == []
    assert week["streaks"], "the bare-name map still carries the facts"


def test_the_weekly_board_still_degrades_without_a_board_state():
    week = web_data.build_weekly_board(None, roster=ROSTER)
    assert week["available"] is False
    assert week["attendance"] == {}
    assert week["attendance_coverage"]["weeks_scanned"] == []


# --- 4. THE BUNDLE GATE ---------------------------------------------------

@pytest.fixture()
def _validate():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "validate_bundle",
        Path(__file__).resolve().parents[1] / "scripts" / "validate_bundle.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_validate_bundle_refuses_a_bare_name_in_a_keyed_map(_validate):
    report = _validate.Report()
    _validate.check_character_keying(
        {"weekly_board": {"attendance": {"beroben": ["2026-07-14"]},
                          "keyed_against_roster": True}}, report)
    assert report.errors, "a bare name in weekly_board.attendance must refuse"
    assert "bare name" in report.errors[0][1]


def test_validate_bundle_refuses_keys_that_cannot_have_come_from_a_roster(_validate):
    report = _validate.Report()
    _validate.check_character_keying(
        {"weekly_board": {"attendance": {"amrevenge-stormrage": []},
                          "keyed_against_roster": False}}, report)
    assert report.errors


def test_validate_bundle_warns_but_passes_on_an_honest_seam(_validate):
    report = _validate.Report()
    _validate.check_character_keying(
        {"weekly_board": {
            "attendance": {"amrevenge-stormrage": ["2026-07-14"]},
            "keyed_against_roster": True,
            "attendance_unresolved": [{"name": "beroben", "reason": "ambiguous"}],
        }}, report)
    assert not report.errors
    assert any("more than one roster character" in msg for _, msg in report.warnings)


# --- 5. THE THREE FIELDS, IN THE COMMITTED FIXTURE BUNDLE -----------------

def _sample(name):
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "samples" / f"{name}.sample.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_fixture_bundle_carries_the_clock_and_the_run_id():
    chars = _sample("competition")["characters"]
    runs = [r for c in chars for r in (c.get("best_runs") or [])
            + (c.get("recent_runs") or [])]
    assert runs, "regenerate: python scripts/build_sample_site_data.py"
    assert all("completed_at" in r and "keystone_run_id" in r for r in runs)
    assert any(r["keystone_run_id"] for r in runs)
    assert any(r["completed_at"] for r in runs)


def test_fixture_bundle_carries_attendance_keyed_by_character():
    week = _sample("weekly_board")
    assert week["attendance"], "regenerate: python scripts/build_sample_site_data.py"
    assert all("-" in key for key in week["attendance"])
    assert week["keyed_against_roster"] is True


def test_fixture_bundle_carries_the_collision_so_nobody_meets_it_in_production():
    week = _sample("weekly_board")
    assert {"name": "beroben", "reason": "ambiguous"} in week["attendance_unresolved"]


def test_the_fixture_bundle_passes_the_keying_gate(_validate):
    report = _validate.Report()
    _validate.check_character_keying({"weekly_board": _sample("weekly_board")}, report)
    assert not report.errors, report.errors

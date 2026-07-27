"""Two-way roster truth: refresh_competition.apply_membership + the departed
ledger's ride through build_competition and validate_bundle.

Owner directive (2026-07-27): membership is the LIVE guild roster — new
members added, leavers moved to a retained `departed` ledger, and nobody
who is not presently in the guild enters the sweep. The invariants under
test, in the project's own language:

  * never delete: a leaver keeps their last-known record + departed_at;
  * departed_at is the run that first OBSERVED the absence, and it stays
    stable across later runs (no clock creep);
  * a member who reappears leaves the ledger (crawl lag is reversible);
  * an empty or suspiciously small live roster REFUSES the update rather
    than mass-departing the guild (the Phyrthepali lesson, inverted);
  * a live member with no character page yet is still a member — carried
    as a real-data stub in the deliberate unscored state, never dropped.

Everything runs offline; no network is touched.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from refresh_competition import (  # noqa: E402
    MembershipGuard,
    _member_stub,
    apply_membership,
    verify_departures,
)

from guild_board.competition import build_competition  # noqa: E402

NOW = "2026-07-27T12:00:00+00:00"
EARLIER = "2026-07-20T12:00:00+00:00"


def _live(*keys):
    return {k: {"name": k.split("-", 1)[0].title(),
                "realm_slug": k.split("-", 1)[1], "realm": None,
                "rank": 5, "class": "Mage", "spec": "Arcane", "role": "dps"}
            for k in keys}


def _cached(key, score=1000.0):
    return {"name": key.split("-", 1)[0].title(), "key": key,
            "realm_slug": key.split("-", 1)[1], "class": "Mage",
            "spec": "Arcane", "role": "dps", "score": score}


# ---------------------------------------------------------------------------
# apply_membership — pure
# ---------------------------------------------------------------------------

def test_new_member_joins_the_sweep():
    old = {"characters": [_cached("stayer-proudmoore")]}
    roster, membership, departed = apply_membership(
        old, _live("stayer-proudmoore", "newbie-stormrage"), NOW)
    assert "newbie-stormrage" in roster
    assert membership["member_count"] == 2
    assert departed == []


def test_leaver_moves_to_the_ledger_with_last_known_data():
    old = {"characters": [_cached("stayer-proudmoore"),
                          _cached("leaver-dalaran", score=2222.2)]}
    roster, _, departed = apply_membership(old, _live("stayer-proudmoore"), NOW)
    assert roster == ["stayer-proudmoore"]
    assert len(departed) == 1
    row = departed[0]
    assert row["key"] == "leaver-dalaran"
    assert row["score"] == 2222.2          # last-known data retained
    assert row["departed_at"] == NOW       # first observed THIS run


def test_departed_at_is_stable_across_runs():
    old = {"characters": [_cached("stayer-proudmoore")],
           "departed": [{**_cached("leaver-dalaran"), "departed_at": EARLIER}]}
    _, _, departed = apply_membership(old, _live("stayer-proudmoore"), NOW)
    assert departed[0]["departed_at"] == EARLIER


def test_returning_member_leaves_the_ledger():
    old = {"characters": [],
           "departed": [{**_cached("returner-dalaran"), "departed_at": EARLIER}]}
    roster, _, departed = apply_membership(old, _live("returner-dalaran"), NOW)
    assert departed == []
    assert roster == ["returner-dalaran"]


def test_wcl_only_names_do_not_enter_the_sweep():
    # roster_cache retention is not membership: the sweep is exactly the
    # live guild, so a name only WCL remembers stays out.
    old = {"characters": [_cached("member-proudmoore")]}
    roster, _, _ = apply_membership(old, _live("member-proudmoore"), NOW)
    assert roster == ["member-proudmoore"]


def test_empty_live_roster_is_refused():
    with pytest.raises(MembershipGuard):
        apply_membership({"characters": [_cached("a-b")]}, {}, NOW)


def test_mass_departure_is_refused():
    old = {"characters": [_cached(f"member{i}-proudmoore") for i in range(10)]}
    with pytest.raises(MembershipGuard):
        apply_membership(old, _live("member0-proudmoore"), NOW,
                         min_fraction=0.5)


def test_first_run_with_no_previous_cache_accepts_any_size():
    roster, membership, departed = apply_membership({}, _live("solo-dalaran"), NOW)
    assert roster == ["solo-dalaran"]
    assert departed == []
    assert membership["source"] == "raider.io guild roster"


# ---------------------------------------------------------------------------
# verify_departures — a second source before anyone is ledgered
# ---------------------------------------------------------------------------

def _ledger_row(key, departed_at=NOW, **extra):
    return {**_cached(key), "departed_at": departed_at, **extra}


def test_profile_still_in_guild_reinstates_the_member():
    confirmed, reinstated = verify_departures(
        [_ledger_row("crawlgap-dalaran")], NOW,
        checker=lambda k: ("present", "Skill Issues"))
    assert confirmed == []
    assert reinstated == ["crawlgap-dalaran"]


def test_confirmed_leaver_is_annotated_with_the_evidence():
    confirmed, reinstated = verify_departures(
        [_ledger_row("leaver-dalaran")], NOW,
        checker=lambda k: ("left", "Some Other Guild"))
    assert reinstated == []
    check = confirmed[0]["departure_check"]
    assert check["status"] == "left"
    assert check["guild"] == "Some Other Guild"
    assert check["checked_at"] == NOW


def test_deleted_character_is_confirmed_gone():
    confirmed, _ = verify_departures(
        [_ledger_row("erased-dalaran")], NOW, checker=lambda k: ("gone", None))
    assert confirmed[0]["departure_check"]["status"] == "gone"


def test_unverifiable_new_candidate_stays_a_member():
    # Unverifiable is not evidence of leaving: a NEW candidate the profile
    # check cannot reach today is reinstated and re-examined next run.
    confirmed, reinstated = verify_departures(
        [_ledger_row("flaky-dalaran", departed_at=NOW)], NOW,
        checker=lambda k: ("unknown", None))
    assert confirmed == []
    assert reinstated == ["flaky-dalaran"]


def test_unverifiable_standing_ledger_row_stays_ledgered():
    # An OLD ledger row is standing state, not a fresh conclusion — an
    # unreachable profile keeps it, unannotated, for the next run.
    confirmed, reinstated = verify_departures(
        [_ledger_row("gone-dalaran", departed_at=EARLIER)], NOW,
        checker=lambda k: ("unknown", None))
    assert reinstated == []
    assert confirmed[0]["departed_at"] == EARLIER
    assert "departure_check" not in confirmed[0]


def test_already_annotated_rows_are_not_rechecked():
    calls = []

    def checker(key):
        calls.append(key)
        return ("left", "Elsewhere")

    row = _ledger_row("settled-dalaran", departed_at=EARLIER,
                      departure_check={"method": "raider.io character profile",
                                       "status": "left", "guild": "Elsewhere",
                                       "checked_at": EARLIER})
    confirmed, reinstated = verify_departures([row], NOW, checker)
    assert calls == []
    assert confirmed == [row]
    assert reinstated == []


# ---------------------------------------------------------------------------
# _member_stub — real data only, deliberate unscored state
# ---------------------------------------------------------------------------

def test_member_stub_carries_roster_facts_and_no_invented_score():
    stub = _member_stub("fresh-emerald-dream",
                        {"name": "Fresh", "realm_slug": "emerald-dream",
                         "realm": "Emerald Dream", "class": "Druid",
                         "spec": "Balance", "role": "dps"})
    assert stub["key"] == "fresh-emerald-dream"
    assert stub["realm_slug"] == "emerald-dream"
    assert stub["class"] == "Druid"
    assert stub["score"] == 0              # normalizes to "no score yet"
    assert stub["best_runs"] == []
    assert stub["ranks"]["realm_overall"] is None


# ---------------------------------------------------------------------------
# build_competition — the ledger rides the envelope
# ---------------------------------------------------------------------------

def test_envelope_carries_departed_and_membership():
    fetched = {
        "characters": [_cached("stayer-proudmoore")],
        "departed": [{**_cached("leaver-dalaran"), "departed_at": NOW}],
        "membership": {"source": "raider.io guild roster", "as_of": NOW,
                       "member_count": 1},
    }
    comp = build_competition(fetched)
    assert comp["departed_count"] == 1
    assert comp["departed"][0]["key"] == "leaver-dalaran"
    assert comp["membership"]["member_count"] == 1
    # A departed character is never also a member row.
    assert all(c["key"] != "leaver-dalaran" for c in comp["characters"])


def test_envelope_without_ledger_is_additive_and_empty():
    comp = build_competition({"characters": [_cached("stayer-proudmoore")]})
    assert comp["departed"] == []
    assert comp["departed_count"] == 0
    assert comp["membership"] is None

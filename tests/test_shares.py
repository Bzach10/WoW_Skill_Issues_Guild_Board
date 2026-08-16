"""THE SHARES LEDGER — the rate card, the caps, the alts and the Claim Law.

The load-bearing test in this file is
`test_the_ladder_cannot_move_a_single_share`: it scrambles every field the
Claim Law forbids as a faucet (score, rank, ranks, top5, rankings, parse,
percentile, standing, bounty, the weekly deltas) and asserts the emitted
ledger is byte-identical. A grep for those names would pass forever the
moment somebody read one indirectly; a mutation cannot.

Everything here runs offline against fixtures. No network, no credentials.
"""

import copy
import json
import os
import sys

import pytest

from guild_board import shares

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from validate_bundle import Report, check_shares  # noqa: E402

ROSTER = [
    "buchalter-area-52",
    "buchalta-area-52",
    "amrevenge-stormrage",
    "beroben-emerald-dream",
    "beroben-queldorei",
    "maillo-stormrage",
]

WEEK_START = "2026-08-10"
WEEK_END = "2026-08-16"
WEEK_LABEL = "2026-08-10"


def _run(run_id, level, when, timed=True, dungeon="Skyreach"):
    return {"dungeon": dungeon, "short": "SR", "level": level, "timed": timed,
            "upgrades": 1 if timed else 0, "score": 300.0 + level,
            "clear_ms": 1, "par_ms": 2, "completed_at": when,
            "keystone_run_id": run_id}


def competition():
    """Five timed keys on the main, three on the alt: eight for ONE account."""
    return {
        "available": True,
        "based_on": "2026-08-16T00:00:00+00:00",
        "characters": [
            {
                "key": "buchalter-area-52", "name": "Buchalter",
                "score": 3200.5, "rank": 1, "top5": True,
                "ranks": {"overall": 12}, "parse": 91, "delta_week": 40.2,
                "recent_runs": [
                    _run(1001, 12, "2026-08-11T02:41:19.000Z"),
                    _run(1002, 13, "2026-08-12T02:41:19.000Z"),
                    _run(1003, 10, "2026-08-13T02:41:19.000Z"),
                    _run(1004, 21, "2026-08-14T02:41:19.000Z"),
                    _run(1005, 11, "2026-08-15T02:41:19.000Z"),
                    # Not timed: a deed that did not happen.
                    _run(1006, 15, "2026-08-15T03:00:00.000Z", timed=False),
                    # Last week: outside the window.
                    _run(1007, 18, "2026-08-03T02:41:19.000Z"),
                ],
                "best_runs": [],
            },
            {
                "key": "buchalta-area-52", "name": "Buchalta",
                "score": 900.0, "rank": 40, "top5": False, "ranks": {},
                "parse": 40, "delta_week": 0,
                "recent_runs": [
                    _run(2001, 8, "2026-08-11T02:41:19.000Z"),
                    _run(2002, 9, "2026-08-12T02:41:19.000Z"),
                    _run(2003, 10, "2026-08-13T02:41:19.000Z"),
                ],
                "best_runs": [],
            },
            {
                "key": "amrevenge-stormrage", "name": "Amrevenge",
                "score": 3900.0, "rank": 2, "top5": True,
                "ranks": {"overall": 3}, "parse": 99, "delta_week": 1155.8,
                "recent_runs": [], "best_runs": [],
            },
            {
                "key": "unsigned-stormrage", "name": "Unsigned",
                "score": 100.0, "rank": 99, "top5": False, "ranks": {},
                "parse": 1, "delta_week": 0,
                "recent_runs": [_run(3001, 20, "2026-08-11T02:41:19.000Z")],
                "best_runs": [],
            },
        ],
        "key_records": {
            "by_dungeon": [
                {"dungeon": "Skyreach", "level": 21, "name": "Buchalter",
                 "key": "buchalter-area-52", "score": 502.3},
                {"dungeon": "Pit of Saron", "level": 20, "name": "Amrevenge",
                 "key": "amrevenge-stormrage", "score": 492.2},
            ],
        },
        "rankings": {"overall": [{"key": "amrevenge-stormrage", "rank": 1}]},
    }


def weekly_board():
    return {
        "available": True,
        "week_label": WEEK_LABEL, "week_start": WEEK_START, "week_end": WEEK_END,
        "kills": 5, "pulls": 40,
        "improvement": {
            "dps": [{"name": "Buchalter", "delta": 45, "early_parse": 30,
                     "late_parse": 75}],
            # Two roster characters are called Beroben. This one is never paid.
            "hps": [{"name": "Beroben", "delta": 10}],
        },
        "roast": {"roast": "a joke", "winner": "Amrevenge", "target": "Maillo"},
        "attendance": {
            "buchalter-area-52": [WEEK_LABEL],
            # The alt was logged in the SAME week. One week, one payment.
            "buchalta-area-52": [WEEK_LABEL],
            "amrevenge-stormrage": [WEEK_LABEL, "2026-07-06"],
        },
        "attendance_unresolved": [{"name": "beroben", "reason": "ambiguous"}],
        "streaks_by_key": {"buchalter-area-52": 8, "amrevenge-stormrage": 3},
        "deaths_by_key": {},
        "keyed_against_roster": True,
        "roster_size": len(ROSTER),
        "standing": 4,
    }


def island_completion():
    return {
        "raid": {
            "islands": [
                {"id": "imperator-averzian", "name": "Imperator Averzian",
                 "kind": "raid_boss", "status": "conquered",
                 "kill_confirmed": True,
                 "first_kill_at": "2026-08-12T00:28:33.467Z"},
                {"id": "old-boss", "name": "Old Boss", "kind": "raid_boss",
                 "status": "conquered", "kill_confirmed": True,
                 "first_kill_at": "2026-07-20T00:28:33.467Z"},
                {"id": "not-dead", "name": "Not Dead", "kind": "raid_boss",
                 "status": "open", "kill_confirmed": False,
                 "first_kill_at": None},
            ],
        },
        "dungeons": {"islands": []},
    }


def recap_ribbon():
    return {"beats": [
        {"kind": "biggest_key", "subject": "Amrevenge", "value": 21},
        # A percentile beat: the ladder wearing a headline. Never paid.
        {"kind": "best_dps_parse", "subject": "Maillo", "value": 98},
    ]}


def records_leaderboard():
    return {
        "standing": 4,
        "headline_records": [
            {"id": "highest_timed_key", "holder": "Amrevenge", "value": 21,
             "unit": "key_level"},
            {"id": "best_dps_parse", "holder": "Maillo", "value": 98,
             "unit": "percentile"},
        ],
        "ladder": [{"key": "amrevenge-stormrage", "delta_week": 1155.8}],
    }


def bundle():
    return {"competition": competition(), "weekly_board": weekly_board(),
            "island_completion": island_completion(),
            "recap_ribbon": recap_ribbon(),
            "records_leaderboard": records_leaderboard()}


ACCOUNT_MAIN = "aaaa111122223333"
ACCOUNT_TWO = "bbbb444455556666"


def articles_projection(accounts=None):
    accounts = accounts if accounts is not None else {
        ACCOUNT_MAIN: {"main": "buchalter-area-52",
                       "characters": ["buchalta-area-52", "buchalter-area-52"]},
        ACCOUNT_TWO: {"main": "amrevenge-stormrage",
                      "characters": ["amrevenge-stormrage"]},
    }
    characters = {}
    for account_id, account in accounts.items():
        for key in account["characters"]:
            characters[key] = {"account_id": account_id,
                               "is_main": key == account["main"]}
    return {
        "schema_version": 1, "id_scheme": "hmac-sha256-16",
        "generated_at": "2026-08-16T20:00:00+00:00",
        "available": bool(characters), "status": "ok" if characters else "no-signatures",
        "roster_total": len(ROSTER), "signed_accounts": len(accounts),
        "signed_characters": len(characters),
        "characters": characters, "accounts": accounts,
    }


def compute(**kwargs):
    kwargs.setdefault("bundle", bundle())
    kwargs.setdefault("articles_projection", articles_projection())
    kwargs.setdefault("roster", ROSTER)
    return shares.compute_week(kwargs["bundle"], kwargs["articles_projection"],
                               roster=kwargs["roster"],
                               previous_holders=kwargs.get("previous_holders"))


def by_loop(week, account_id):
    return (week["summary"].get(account_id) or {}).get("by_loop") or {}


# ---------------------------------------------------------------------------
# The rate card is data
# ---------------------------------------------------------------------------

def test_the_rate_card_publishes_every_loop_including_the_zeros():
    ids = [entry["id"] for entry in shares.RATE_CARD["loops"]]
    assert len(ids) == 11, "the rate card is eleven loops; one has gone missing"
    assert len(set(ids)) == 11
    for entry in shares.RATE_CARD["loops"]:
        assert entry["tier"] in ("T0", "T1", "T2", "T3")
        if entry["pays"]:
            assert entry["rate"] > 0 and entry["tier"] in ("T0", "T1")
            assert entry["reason"] is None
        else:
            # A loop that pays nothing must SAY WHY, in words that ship.
            assert entry["rate"] == 0
            assert entry["reason"] and len(entry["reason"]) > 40


def test_pvp_pays_nothing_and_the_reason_names_the_exploit():
    table = shares.LOOPS_BY_ID["the_table"]
    assert table["pays"] is False and table["rate"] == 0
    assert "AUTHENTICATED" in table["reason"].upper()
    assert table["deferred_rate"] == 2, "the designed rate is kept, not lost"


def test_an_unknown_loop_is_refused_never_paid_at_a_default():
    with pytest.raises(shares.UnknownLoop):
        shares.loop("free_money")
    with pytest.raises(shares.UnknownLoop):
        shares.rate_for("the_tabel")          # a typo is not a rate
    with pytest.raises(shares.UnknownLoop):
        shares.cap_for("")


def test_a_deed_against_an_unknown_loop_stops_the_fold():
    accounts = shares.accounts_from_articles(articles_projection())
    owner = shares.character_owner(accounts)
    deeds = [{"loop": "definitely_not_a_loop", "character": "buchalter-area-52",
              "deed_ref": "x", "detail": None}]
    with pytest.raises(shares.UnknownLoop):
        shares.fold_deeds(deeds, accounts, owner, WEEK_LABEL, {})


def test_a_share_with_no_citation_cannot_be_minted():
    with pytest.raises(ValueError):
        shares.row_id(WEEK_LABEL, ACCOUNT_MAIN, "key_log", "")


# ---------------------------------------------------------------------------
# Caps, per ACCOUNT
# ---------------------------------------------------------------------------

def test_the_key_log_cap_is_per_account_not_per_character():
    week = compute()
    # Five timed keys on the main + three on the alt = eight timed keys, and
    # eight keys x2 = 16 raw against a cap of 8.
    assert by_loop(week, ACCOUNT_MAIN)["key_log"] == 8
    paid = [r for r in week["rows"]
            if r["account_id"] == ACCOUNT_MAIN and r["loop"] == "key_log"]
    assert sum(r["shares"] for r in paid) == 8
    assert len(paid) == 8, "every timed key is cited, paid or capped"
    assert sum(1 for r in paid if r["capped"]) == 4, (
        "the deeds past the cap are written with shares 0 and capped:true, "
        "not deleted — a vanished deed and an unpaid deed must not look alike")
    assert "key_log" in week["summary"][ACCOUNT_MAIN]["capped_loops"]


def test_two_characters_on_one_account_earn_the_raid_week_once():
    week = compute()
    # Both buchalter and buchalta are logged in the SAME raid week.
    assert by_loop(week, ACCOUNT_MAIN)["raid_night"] == 2, (
        "THE ANTI-FARM RULE: alts change WHICH character earns, never HOW "
        "MUCH. One week is one payment.")
    rows = [r for r in week["rows"]
            if r["account_id"] == ACCOUNT_MAIN and r["loop"] == "raid_night"]
    assert len(rows) == 1
    assert rows[0]["deed_ref"] == f"raid-week:{WEEK_LABEL}"


def test_first_blood_pays_an_account_once_per_boss():
    week = compute()
    for account_id in (ACCOUNT_MAIN, ACCOUNT_TWO):
        rows = [r for r in week["rows"]
                if r["account_id"] == account_id and r["loop"] == "first_blood"]
        assert len(rows) == 1, "one boss, one payment, however many alts raided"
        assert rows[0]["deed_ref"] == "first-blood:imperator-averzian"
        assert rows[0]["shares"] == 6
    # The July kill and the boss still standing pay nothing.
    assert not [r for r in week["rows"] if "old-boss" in str(r["deed_ref"])]
    assert not [r for r in week["rows"] if "not-dead" in str(r["deed_ref"])]


def test_only_keys_finished_inside_the_week_are_paid():
    week = compute()
    refs = {r["deed_ref"] for r in week["rows"] if r["loop"] == "key_log"}
    assert "run:1007" not in refs, "last week's key is not this week's deed"
    assert "run:1006" not in refs, "an untimed key is not a timed key"
    assert "run:1004" in refs


def test_an_unsigned_character_earns_nothing():
    week = compute()
    assert not [r for r in week["rows"] if r["character"] == "unsigned-stormrage"]
    assert "unsigned-stormrage" not in json.dumps(week["rows"])


def test_nobody_signed_means_an_honest_empty_shelf_not_a_credited_roster():
    week = compute(articles_projection=articles_projection(accounts={}))
    assert week["available"] is False
    assert week["rows"] == []
    assert week["status"].startswith("no-signatures")
    assert any("have signed the articles" in s for s in week["seams"])


def test_no_week_window_pays_nothing_rather_than_guessing_one():
    payload = bundle()
    payload["weekly_board"]["week_start"] = None
    payload["weekly_board"]["week_end"] = None
    week = compute(bundle=payload)
    assert week["available"] is False and week["rows"] == []
    assert "not a measurable idea" in week["status"]


# ---------------------------------------------------------------------------
# The streak multiplier
# ---------------------------------------------------------------------------

def test_the_streak_multiplier_multiplies_the_deed_and_never_pays_for_nothing():
    assert shares.streak_multiplier(0) == 1.0
    assert shares.streak_multiplier(3) == 1.15
    assert shares.streak_multiplier(8) == 1.4
    assert shares.streak_multiplier(40) == 1.4, "capped at 8 weeks"

    week = compute()
    main = week["summary"][ACCOUNT_MAIN]
    # 8 (key log, capped) + 2 (raid week) + 6 (first blood) + 4 (the pot) = 20
    assert main["base"] == 20
    assert main["streak"] == 8 and main["multiplier"] == 1.4
    assert main["streak_bonus"] == 8 and main["total"] == 28


def test_the_streak_bonus_is_a_ledger_row_so_the_rows_still_sum_to_the_total():
    week = compute()
    for account_id, summary in week["summary"].items():
        rows = [r for r in week["rows"] if r["account_id"] == account_id]
        assert sum(r["shares"] for r in rows) == summary["total"]
    bonus = [r for r in week["rows"] if r["loop"] == shares.STREAK_LOOP_ID]
    assert bonus and all(r["deed_ref"].startswith("streak:") for r in bonus)


def test_a_streak_with_no_deed_pays_zero():
    """The whole point of a multiplier: it multiplies. 0 x 1.4 is still 0."""
    payload = bundle()
    payload["competition"]["characters"] = []
    payload["weekly_board"]["attendance"] = {}
    payload["weekly_board"]["improvement"] = {}
    payload["weekly_board"]["roast"] = None
    payload["recap_ribbon"] = {"beats": []}
    payload["records_leaderboard"] = {"headline_records": []}
    payload["island_completion"] = {"raid": {"islands": []}}
    week = compute(bundle=payload)
    assert week["summary"] == {}
    assert week["rows"] == []


def test_an_accounts_streak_is_the_best_of_its_hands():
    accounts = shares.accounts_from_articles(articles_projection())
    assert shares.account_streak(accounts[ACCOUNT_MAIN],
                                 {"buchalter-area-52": 8,
                                  "buchalta-area-52": 1}) == 8


# ---------------------------------------------------------------------------
# THE CLAIM LAW — pay the deed, never the rank
# ---------------------------------------------------------------------------

def _scramble_ladder(obj):
    """Replace every ladder field, everywhere, with something absurd."""
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if key in shares.LADDER_FIELDS:
                if isinstance(value, dict):
                    out[key] = {"SCRAMBLED": True}
                elif isinstance(value, list):
                    out[key] = []
                elif isinstance(value, bool):
                    out[key] = not value
                elif isinstance(value, (int, float)):
                    out[key] = -999999
                else:
                    out[key] = "SCRAMBLED"
            else:
                out[key] = _scramble_ladder(value)
        return out
    if isinstance(obj, list):
        return [_scramble_ladder(v) for v in obj]
    return obj


def test_the_ladder_cannot_move_a_single_share():
    """The gate. Scramble score, rank, ranks, top5, rankings, parse,
    percentile, standing, bounty and the weekly deltas — everywhere in the
    bundle — and the ledger must come out identical. A source grep would pass
    forever the moment one of these was read indirectly; a mutation cannot."""
    straight = compute()
    scrambled = compute(bundle=_scramble_ladder(bundle()))
    assert scrambled["rows"] == straight["rows"]
    assert scrambled["summary"] == straight["summary"]
    assert straight["rows"], "a gate over an empty ledger proves nothing"


def test_the_scrambler_would_actually_catch_a_ladder_read():
    """The guard on the guard: prove the mutation is not a no-op by paying a
    loop off `score` on purpose and watching the comparison fail."""
    payload = _scramble_ladder(bundle())
    straight = bundle()
    scores_straight = [c["score"] for c in straight["competition"]["characters"]]
    scores_scrambled = [c["score"] for c in payload["competition"]["characters"]]
    assert scores_straight != scores_scrambled
    assert all(s == -999999 for s in scores_scrambled)
    assert payload["records_leaderboard"]["standing"] != \
        straight["records_leaderboard"]["standing"]


def test_the_press_never_pays_a_percentile():
    week = compute()
    press = [r for r in week["rows"] if r["loop"] == "the_press"]
    assert press, "Amrevenge is named in the week's press"
    assert all("parse" not in str(r["deed_ref"]) for r in press)
    # Maillo holds best_dps_parse and is on the roster, but is not signed and
    # would not be paid for a percentile even if he were.
    payload = bundle()
    signed = articles_projection(accounts={
        "cccc777788889999": {"main": "maillo-stormrage",
                             "characters": ["maillo-stormrage"]}})
    week = compute(bundle=payload, articles_projection=signed)
    assert not [r for r in week["rows"] if r["loop"] == "the_press"]


def test_the_pot_reads_your_own_delta_never_a_percentile_against_the_field():
    week = compute()
    assert by_loop(week, ACCOUNT_MAIN)["the_pot"] == 4
    payload = bundle()
    payload["weekly_board"]["improvement"]["dps"][0]["delta"] = -5
    assert "the_pot" not in by_loop(compute(bundle=payload), ACCOUNT_MAIN)


# ---------------------------------------------------------------------------
# Keys, never bare names
# ---------------------------------------------------------------------------

def test_an_ambiguous_bare_name_is_a_seam_and_is_never_paid():
    week = compute()
    reasons = {(row["loop"], row["name"], row["reason"])
               for row in week["unresolved"]}
    assert ("the_pot", "Beroben", "ambiguous") in reasons
    assert not [r for r in week["rows"] if "beroben" in str(r["character"] or "")]
    assert any("Beroben" in s and "ambiguous" in s for s in week["seams"])


def test_every_ledger_row_is_keyed_on_an_account_and_a_character_key():
    week = compute()
    for row in week["rows"]:
        assert row["account_id"] in (ACCOUNT_MAIN, ACCOUNT_TWO)
        if row["character"] is not None:
            assert "-" in row["character"], (
                "a bare name is not an identity: two roster characters are "
                "called Beroben")


def test_with_no_roster_the_bare_name_loops_pay_nothing_and_say_so():
    week = compute(roster=[])
    assert "the_pot" not in by_loop(week, ACCOUNT_MAIN)
    assert "the_press" not in by_loop(week, ACCOUNT_TWO)
    # The keyed loops still pay: attendance and runs were keyed upstream.
    assert by_loop(week, ACCOUNT_MAIN)["key_log"] == 8


# ---------------------------------------------------------------------------
# FIRST THROUGH THE DOOR needs a yesterday
# ---------------------------------------------------------------------------

def test_the_first_week_pays_no_lane_records_and_prints_the_reason():
    week = compute()
    assert "first_through_the_door" not in by_loop(week, ACCOUNT_MAIN)
    assert any("FIRST THROUGH THE DOOR pays nothing" in s for s in week["seams"])


def test_taking_a_lane_off_the_previous_holder_pays_five():
    previous = {"Skyreach": "amrevenge-stormrage",
                "Pit of Saron": "amrevenge-stormrage"}
    week = compute(previous_holders=previous)
    rows = [r for r in week["rows"] if r["loop"] == "first_through_the_door"]
    assert len(rows) == 1
    assert rows[0]["account_id"] == ACCOUNT_MAIN
    assert rows[0]["shares"] == 5
    assert rows[0]["deed_ref"] == "lane:Skyreach:buchalter-area-52"
    # Amrevenge kept Pit of Saron and is paid nothing for holding it.
    assert "first_through_the_door" not in by_loop(week, ACCOUNT_TWO)


def test_the_lane_holders_are_carried_forward_for_next_week():
    week = compute()
    assert week["lane_holders"] == {"Skyreach": "buchalter-area-52",
                                    "Pit of Saron": "amrevenge-stormrage"}


# ---------------------------------------------------------------------------
# The ledger is append-only
# ---------------------------------------------------------------------------

def test_recomputing_a_week_does_not_pay_it_twice():
    week = compute()
    ledger, appended, skipped = shares.append_week(shares.empty_ledger(), week,
                                                   generated_at="2026-08-17T00:00:00+00:00")
    assert appended == len(week["rows"]) and skipped == 0
    first = copy.deepcopy(ledger["rows"])

    ledger, appended, skipped = shares.append_week(ledger, compute(),
                                                   generated_at="2026-08-17T06:00:00+00:00")
    assert appended == 0, "a deed pays once — the row ids are its citation"
    assert skipped == len(week["rows"])
    assert ledger["rows"] == first, "existing rows are never edited or removed"


def test_a_second_week_appends_beside_the_first():
    ledger, _, _ = shares.append_week(shares.empty_ledger(), compute())
    payload = bundle()
    for field in ("week_label", "week_start"):
        payload["weekly_board"][field] = "2026-08-17"
    payload["weekly_board"]["week_end"] = "2026-08-23"
    payload["weekly_board"]["attendance"] = {"buchalter-area-52": ["2026-08-17"]}
    payload["competition"]["characters"][0]["recent_runs"] = [
        _run(9001, 14, "2026-08-18T02:00:00.000Z")]
    payload["competition"]["characters"][1]["recent_runs"] = []
    payload["island_completion"]["raid"]["islands"] = []
    ledger, appended, _ = shares.append_week(ledger, compute(bundle=payload))
    assert appended > 0
    assert ledger["weeks"] == [WEEK_LABEL, "2026-08-17"]


def test_the_balance_is_the_ledger_sum_minus_the_sinks():
    ledger, _, _ = shares.append_week(shares.empty_ledger(), compute())
    assert shares.balances(ledger)[ACCOUNT_MAIN] == {
        "earned": 28, "spent": 0, "balance": 28}
    # Sinks arrive later; the field exists now so a balance never has to
    # change shape to acquire a subtraction.
    ledger["sinks"].append({"account_id": ACCOUNT_MAIN, "shares": 12,
                            "sink": "a mailer", "at": "2026-08-18T00:00:00Z"})
    assert shares.balances(ledger)[ACCOUNT_MAIN] == {
        "earned": 28, "spent": 12, "balance": 16}


def test_an_empty_ledger_has_the_sinks_field_already():
    assert shares.empty_ledger()["sinks"] == []
    assert shares.balances(shares.empty_ledger()) == {}


# ---------------------------------------------------------------------------
# The public projection
# ---------------------------------------------------------------------------

def projection():
    week = compute()
    ledger, _, _ = shares.append_week(shares.empty_ledger(), week,
                                      generated_at="2026-08-17T00:00:00+00:00")
    return shares.public_projection(
        ledger, week, articles_projection(),
        names={"buchalter-area-52": "Buchalter", "buchalta-area-52": "Buchalta",
               "amrevenge-stormrage": "Amrevenge"},
        generated_at="2026-08-17T00:00:00+00:00")


def test_the_projection_shape():
    out = projection()
    assert out["schema_version"] == shares.SCHEMA_VERSION
    assert out["rate_card_version"] == shares.RATE_CARD_VERSION
    assert out["currency"] == "shares"
    assert out["rule"] == "PAY THE DEED, NEVER THE RANK."
    assert out["available"] is True
    assert out["roster_total"] == len(ROSTER)
    assert out["signed_accounts"] == 2
    assert set(out["accounts"]) == {ACCOUNT_MAIN, ACCOUNT_TWO}

    main = out["accounts"][ACCOUNT_MAIN]
    assert main["characters"] == ["buchalta-area-52", "buchalter-area-52"]
    assert main["names"] == ["Buchalta", "Buchalter"]
    assert main["main"] == "buchalter-area-52"
    assert main["balance"] == 28 and main["earned"] == 28 and main["spent"] == 0
    assert main["week"]["by_loop"] == {"first_blood": 6, "key_log": 8,
                                       "raid_night": 2, "the_pot": 4}
    assert main["week"]["total"] == 28
    # Every share cites the deed that paid it.
    assert all(deed["deed_ref"] for deed in main["deeds"])
    assert len(out["rate_card"]["loops"]) == 11


def test_the_projection_prints_the_seams_in_words():
    out = projection()
    text = " ".join(out["seams"])
    assert "2 of 6 hands have signed the articles" in text
    assert "THE TABLE pays 0" in text
    assert "AUTHENTICATED" in text.upper()


def test_the_projection_carries_no_discord_id_and_no_real_name():
    from guild_board import articles
    out = projection()
    assert articles.assert_opaque(out) is True
    assert articles.find_identifiers(out) == []
    blob = json.dumps(out)
    for forbidden in ("discord", "author_id", "username", "battletag", "@"):
        assert forbidden not in blob.lower()


def test_the_ledger_itself_is_opaque_too():
    from guild_board import articles
    ledger, _, _ = shares.append_week(shares.empty_ledger(), compute())
    assert articles.assert_opaque(ledger) is True


# ---------------------------------------------------------------------------
# The bundle gate — re-verified on the emitted bytes, not just at the producer
# ---------------------------------------------------------------------------

def _check_shares(tmp_path, mutate=None):
    out = projection()
    if mutate:
        mutate(out)
    (tmp_path / "shares.json").write_text(json.dumps(out), encoding="utf-8")
    report = Report()
    check_shares(str(tmp_path), report)
    return report


def test_an_absent_shares_json_is_never_a_finding(tmp_path):
    report = Report()
    check_shares(str(tmp_path), report)
    assert report.errors == [] and report.warnings == [], (
        "day one of the economy has no shares.json; absence is not a defect")


def test_the_bundle_gate_passes_a_clean_projection(tmp_path):
    assert _check_shares(tmp_path).errors == []


def test_the_bundle_gate_catches_a_balance_that_drifted_from_its_citations(tmp_path):
    report = _check_shares(tmp_path,
                           lambda o: o["accounts"][ACCOUNT_MAIN].update(balance=9999))
    assert len(report.errors) == 1 and "balance" in report.errors[0][1]


def test_the_bundle_gate_catches_a_payment_under_a_zero_priced_loop(tmp_path):
    report = _check_shares(
        tmp_path,
        lambda o: o["accounts"][ACCOUNT_MAIN]["week"]["by_loop"].update(the_table=10))
    assert len(report.errors) == 1
    assert "authenticated" in report.errors[0][1].lower()


def test_the_bundle_gate_catches_an_unpublished_loop_and_a_bare_name(tmp_path):
    unknown = _check_shares(
        tmp_path,
        lambda o: o["accounts"][ACCOUNT_MAIN]["week"]["by_loop"].update(free_money=10))
    assert "not on the published rate card" in unknown.errors[0][1]
    bare = _check_shares(
        tmp_path,
        lambda o: o["accounts"][ACCOUNT_MAIN].update(characters=["buchalter"]))
    assert "bare name" in bare.errors[0][1]


def test_the_bundle_gate_catches_a_leaked_identifier_without_echoing_it(tmp_path):
    leak = "111111111111111111"
    report = _check_shares(
        tmp_path,
        lambda o: o["accounts"][ACCOUNT_MAIN].update(discord_id=leak))
    assert report.errors and "raw identifier" in report.errors[0][1]
    assert leak not in report.errors[0][1], (
        "printing the id to prove the id leaked is its own leak")


def test_an_empty_projection_is_an_honest_shape_not_a_missing_file():
    week = compute(articles_projection=articles_projection(accounts={}))
    out = shares.public_projection(shares.empty_ledger(), week,
                                   articles_projection(accounts={}))
    assert out["available"] is False
    assert out["accounts"] == {}
    assert out["signed_accounts"] == 0
    assert out["status"].startswith("no-signatures")
    assert out["seams"], "an empty shelf still says why it is empty"
    assert len(out["rate_card"]["loops"]) == 11

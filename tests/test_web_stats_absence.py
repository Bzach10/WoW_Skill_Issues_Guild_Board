"""A missing parse ladder must say why, not render a bare em-dash.

A *missing* web_stats.json is ambiguous — it looks the same whether the
pipeline never ran, crashed, or ran fine against a source with no parses.
The site rendered that ambiguity as "—" under Top Tank, while the page
footer claimed the ladders "populate automatically from the daily data
refresh", which is false when the credentials that would populate them
are unset. These pin the honest behaviour.
"""

import json

from guild_board.standings import _parses
from guild_board.web_stats import absence_payload, dump_web_stats


def test_absence_is_written_to_disk_not_silently_skipped(tmp_path):
    out = tmp_path / "web_stats.json"
    # still False: callers and CI keep their "did we get parses?" semantics
    assert dump_web_stats({"best_dps": {}, "best_hps": {}, "best_tanks": {}},
                          path=str(out)) is False
    assert out.exists(), "the absence itself is a fact worth recording"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["available"] is False
    assert "WCL_CLIENT_ID" in data["reason"]
    assert data["top_dps"] == [] and data["top_tanks"] == []


def test_absence_reason_distinguishes_no_run_from_no_parses():
    assert "not queried" in absence_payload(None)["reason"]
    assert "no parse pools" in absence_payload({"best_dps": {}})["reason"]


def test_empty_ladder_carries_the_reason_through_to_the_template():
    board_state = {"records": {
        "best_dps_parse": {"name": "Amrevenge", "parse": 97,
                           "boss": "Fallen-King Salhadaar", "spec": "BeastMastery"},
        "best_hps_parse": {"name": "Phyrthepali", "parse": 96,
                           "boss": "Imperator Averzian", "spec": "Holy"},
    }}
    web_stats = json.loads(json.dumps(absence_payload({"best_dps": {}})))

    parses = _parses(board_state, web_stats)

    # the two roles with a season record still render it
    assert parses["dps"]["rows"][0]["name"] == "Amrevenge"
    assert parses["hps"]["rows"][0]["name"] == "Phyrthepali"
    # the role with nothing explains itself instead of showing a dash
    assert parses["tanks"]["rows"] == []
    assert "WCL_CLIENT_ID" in parses["tanks"]["unavailable_reason"]


def test_reason_falls_back_when_there_is_no_web_stats_file_at_all():
    parses = _parses({"records": {}}, None)
    assert parses["tanks"]["rows"] == []
    assert parses["tanks"]["unavailable_reason"]

"""Cameo history / cameo debt (ARC-09)."""

import json

from guild_board import featured


BOARD = {"records": {
    "highest_timed_key": {"name": "Amrevenge"},
    "best_dps_parse": {"name": "Amrevenge"},
    "best_hps_parse": {"name": "Phyrthepali"},
}}
ROAST_CFG = {"sections": {"roast_of_the_week": {
    "winner": "Rakdaddy", "target": "Healmates", "roast": "Healmates Sucks"}}}
CREW = [
    {"slug": "amrevenge", "name": "Amrevenge", "role": "dps"},
    {"slug": "phyrthepali", "name": "Phyrthepali", "role": "healer"},
    {"slug": "healmates", "name": "Healmates", "role": "healer"},
    {"slug": "buchalter", "name": "Buchalter", "role": "dps"},
]


def test_this_week_gathers_record_holders_and_roast_names():
    week = featured.this_week(BOARD, ROAST_CFG)
    assert set(week) == {"amrevenge", "phyrthepali", "rakdaddy", "healmates"}
    assert "roast" in week["healmates"]
    assert "recap" in week["amrevenge"]


def test_without_a_feed_this_week_is_the_only_evidence():
    debt = featured.cameo_debt(CREW, BOARD, ROAST_CFG, path="does-not-exist.json")
    assert debt["have_feed"] is False
    # Amrevenge/Phyrthepali/Healmates featured this week; Buchalter not
    spotlight = {x["slug"] for x in debt["spotlight"]}
    assert spotlight == {"amrevenge", "phyrthepali", "healmates"}
    assert any(x["slug"] == "buchalter" for x in debt["never"])


def test_with_a_feed_debt_ranks_by_accumulated_features(tmp_path):
    feed = tmp_path / "featured_history.json"
    feed.write_text(json.dumps({"members": {
        "amrevenge": {"features": 5, "last_featured": "2026-07-01"},
        "healmates": {"features": 1, "last_featured": "2026-06-01"},
    }}), encoding="utf-8")
    debt = featured.cameo_debt(CREW, BOARD, ROAST_CFG, path=str(feed))
    assert debt["have_feed"] is True
    assert [x["slug"] for x in debt["featured"]] == ["amrevenge", "healmates"]
    never = {x["slug"] for x in debt["never"]}
    assert never == {"phyrthepali", "buchalter"}     # no feed entry = never


def test_emit_week_writes_the_shared_shape(tmp_path):
    out = tmp_path / "featured_this_week.json"
    featured.emit_week(BOARD, ROAST_CFG, out=out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "week_of" in data
    assert set(data["featured"]) == {"amrevenge", "phyrthepali", "rakdaddy", "healmates"}

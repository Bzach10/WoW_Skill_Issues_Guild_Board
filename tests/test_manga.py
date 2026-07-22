"""The weekly two-panel manga strip (ANIM-08)."""

from guild_board import manga


BOARD = {
    "records": {
        "highest_timed_key": {"name": "amrevenge", "level": 20, "dungeon": "Pit of Saron"},
        "best_hps_parse": {"name": "phyrthepali", "parse": 96, "boss": "Imperator Averzian"},
    }
}
ROAST_CFG = {"sections": {"roast_of_the_week": {
    "roast": "Healmates Sucks", "winner": "Rakdaddy", "target": "Healmates"}}}


def test_headline_then_roast_is_narration_then_speech():
    strip = manga.strip(BOARD, ROAST_CFG, stills=["a.jpg", "b.jpg"])
    assert strip is not None
    p1, p2 = strip["panels"]
    assert p1["kind"] == "narration"
    assert p1["who"] == "Amrevenge" and "+20" in p1["text"]
    assert p2["kind"] == "speech"           # a real quote earns the bubble
    assert p2["text"] == "Healmates Sucks"
    assert p2["who"] == "Rakdaddy" and p2["target"] == "Healmates"


def test_stills_are_assigned_and_cycled():
    one = manga.strip(BOARD, ROAST_CFG, stills=["only.jpg"])
    assert [p["still"] for p in one["panels"]] == ["only.jpg", "only.jpg"]
    two = manga.strip(BOARD, ROAST_CFG, stills=["a.jpg", "b.jpg"])
    assert [p["still"] for p in two["panels"]] == ["a.jpg", "b.jpg"]


def test_without_a_roast_the_second_panel_falls_back_to_narration():
    strip = manga.strip(BOARD, cfg={}, stills=["a.jpg"])
    p2 = strip["panels"][1]
    assert p2["kind"] == "narration"
    assert p2["who"] == "Phyrthepali" and "96" in p2["text"]


def test_no_records_means_no_strip():
    assert manga.strip({}, cfg={}) is None
    assert manga.strip({"records": {}}, cfg={}) is None

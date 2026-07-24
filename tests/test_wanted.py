"""The Wanted Board — bounty leaderboard from board_state (ARC / headline)."""

from guild_board import wanted


CREW = [
    {"slug": "amrevenge", "name": "Amrevenge", "role": "dps", "cls": "Hunter",
     "spec": "Beast Mastery", "score": 3908.1, "art": {"src": "a.jpg"}},
    {"slug": "shadoxii", "name": "Shadoxii", "role": "healer", "cls": "Monk",
     "spec": "Mistweaver", "score": 3692.2, "art": {"src": "s.jpg"}},
    {"slug": "brewzleeh", "name": "Brewzleeh", "role": "tank", "cls": "Monk",
     "spec": "Brewmaster", "score": 3685.8, "art": {"src": "b.jpg"}},
    {"slug": "nobody", "name": "Nobody", "role": "dps", "cls": "Rogue",
     "spec": "Sublety", "score": None, "art": {"src": None}},
]
BOARD = {
    "season_scores": {"amrevenge": 3908.1, "shadoxii": 3692.2, "brewzleeh": 3685.8},
    "baseline": {"season_scores": {"amrevenge": 3908.1, "shadoxii": 3680.0,
                                   "brewzleeh": 3685.8}},
    "streaks": {"amrevenge": 1, "brewzleeh": 4},
    "records": {
        "highest_timed_key": {"name": "amrevenge", "level": 20},
        "best_dps_parse": {"name": "Amrevenge", "parse": 97},
        "best_hps_parse": {"name": "Shadoxii", "parse": 96},
    },
}


def test_ranks_descend_by_score_and_bounty_scales_the_score():
    b = wanted.board(CREW, BOARD)
    top = b["entries"][0]
    assert top["slug"] == "amrevenge" and top["rank"] == 1
    assert top["bounty"] == int(round(3908.1 * wanted.BERRY_PER_POINT))
    assert [e["rank"] for e in b["top5"]] == [1, 2, 3]


def test_unscored_crew_sink_below_and_carry_no_rank():
    b = wanted.board(CREW, BOARD)
    last = b["entries"][-1]
    assert last["slug"] == "nobody" and last["rank"] is None
    assert last["bounty"] is None and last["pending"] is True


def test_record_holders_get_titles():
    b = wanted.board(CREW, BOARD)
    by = {e["slug"]: e for e in b["entries"]}
    assert any("Deepest Key" in t for t in by["amrevenge"]["titles"])
    assert any("Sharpest Parse" in t for t in by["amrevenge"]["titles"])
    assert any("Kept Us Alive" in t for t in by["shadoxii"]["titles"])


def test_biggest_climb_and_longest_streak_surface():
    b = wanted.board(CREW, BOARD)
    assert b["biggest_climb"]["slug"] == "shadoxii"     # +12.2
    assert round(b["biggest_climb"]["delta"], 1) == 12.2
    assert b["longest_streak"]["slug"] == "brewzleeh"   # 4 weeks


def test_counts():
    b = wanted.board(CREW, BOARD)
    assert b["ranked_count"] == 3
    assert b["total_count"] == 4

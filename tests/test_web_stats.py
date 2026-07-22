"""web_stats.json writer — shape and fail-open behavior."""

import json

from guild_board.web_stats import build_payload, dump_web_stats


def _stats():
    return {
        "best_dps": {
            "Amrevenge": {"parse": 99.6, "boss": "Nexus-King Salhadaar", "spec": "BeastMastery"},
            "Shadoxii": {"parse": 87.0, "boss": "Dimensius", "spec": "Mistweaver"},
        },
        "best_hps": {
            "Healyeah": {"parse": 92.2, "boss": "Dimensius", "spec": "Holy"},
        },
        "best_tanks": {},
        "difficulty": 5,
    }


def test_payload_rows_carry_name_value_detail_ranked():
    p = build_payload(_stats())
    assert [r["name"] for r in p["top_dps"]] == ["Amrevenge", "Shadoxii"]
    top = p["top_dps"][0]
    assert top["value"] == 100  # 99.6 rounds; the site appends the % sign
    assert top["detail"] == "Nexus-King Salhadaar · BeastMastery"
    assert p["top_hps"][0]["name"] == "Healyeah"
    assert p["top_tanks"] == []  # empty ladder present, site falls back per-ladder


def test_no_stats_writes_nothing(tmp_path):
    out = tmp_path / "web_stats.json"
    assert dump_web_stats(None, path=str(out)) is False
    assert dump_web_stats({"best_dps": {}, "best_hps": {}, "best_tanks": {}},
                          path=str(out)) is False
    assert not out.exists()


def test_dump_round_trips(tmp_path):
    out = tmp_path / "web_stats.json"
    assert dump_web_stats(_stats(), path=str(out)) is True
    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data) == {"top_dps", "top_hps", "top_tanks", "difficulty"}
    assert data["top_dps"][0]["name"] == "Amrevenge"

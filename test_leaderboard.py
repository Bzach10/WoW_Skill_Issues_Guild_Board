#!/usr/bin/env python3
"""Offline sanity tests for leaderboard.py — no network or API keys needed.

Run with:  python3 test_leaderboard.py
"""

from datetime import datetime, timezone

import leaderboard as lb


def test_deduper():
    d = lb.FightDeduper()
    # Same pull logged by two people: 20s clock skew, 5s duration diff -> duplicate
    assert d.check_and_add(3009, 4, False, 1_000_000, 240_000) is False
    assert d.check_and_add(3009, 4, False, 1_020_000, 245_000) is True
    # Rapid re-pull 50s later with very different duration -> distinct
    assert d.check_and_add(3009, 4, False, 1_050_000, 30_000) is False
    # Same timing but different boss -> distinct
    assert d.check_and_add(3010, 4, False, 1_000_000, 240_000) is False
    # Wipe vs kill at similar time -> distinct
    assert d.check_and_add(3009, 4, True, 1_010_000, 242_000) is False


def test_report_sort_key():
    primary = {"owner": {"name": "MainLogger"}, "startTime": 0, "endTime": 100}
    long_log = {"owner": {"name": "Backup"}, "startTime": 0, "endTime": 10_000}
    short_log = {"owner": {"name": "Backup"}, "startTime": 0, "endTime": 500}
    ordered = sorted([short_log, long_log, primary],
                     key=lambda r: lb.report_sort_key(r, "mainlogger"))
    assert ordered[0] is primary          # preferred uploader wins
    assert ordered[1] is long_log         # then longest report
    assert ordered[2] is short_log


def test_apply_roster_filters():
    original = lb.fetch_guild_member_names
    lb.fetch_guild_member_names = lambda token, cfg: {"rakell", "optout"}
    try:
        cfg = {
            "guild": {},
            "filters": {
                "guild_members_only": True,
                "always_include": ["Trialguy"],
                "always_exclude": ["Optout"],
            },
        }
        stats = {
            "best_dps": {"Rakell": 1, "Randompug": 2, "Trialguy": 3, "Optout": 4},
            "best_hps": {"Somepughealer": 1},
            "deaths": {"Rakell": 5, "Randompug": 9},
            "participants": {"Rakell": None, "Randompug": None, "Trialguy": None},
        }
        out = lb.apply_roster_filters(None, cfg, stats)
        assert set(out["best_dps"]) == {"Rakell", "Trialguy"}
        assert out["best_hps"] == {}
        assert set(out["deaths"]) == {"Rakell"}
        assert set(out["participants"]) == {"Rakell", "Trialguy"}

        # Default config: everyone shows
        cfg_default = {"guild": {}, "filters": {"guild_members_only": False}}
        stats2 = {"best_dps": {"Rakell": 1, "Randompug": 2},
                  "best_hps": {}, "deaths": {}, "participants": {}}
        out2 = lb.apply_roster_filters(None, cfg_default, stats2)
        assert set(out2["best_dps"]) == {"Rakell", "Randompug"}
    finally:
        lb.fetch_guild_member_names = original


def test_detect_zone():
    cfg = {"rankings": {"zone_id": 0}}
    reports = [
        {"startTime": 100, "zone": {"id": 42, "name": "Old Raid"}},
        {"startTime": 200, "zone": {"id": 44, "name": "Current Raid"}},
        {"startTime": 300, "zone": None},
    ]
    zone_id, zone_name = lb.detect_zone(cfg, reports)
    assert zone_id == 44 and zone_name == "Current Raid"
    # Explicit override wins
    zone_id, zone_name = lb.detect_zone({"rankings": {"zone_id": 99}}, reports)
    assert zone_id == 99


def test_formatting():
    assert lb.fmt_amount(1_850_000) == "1.85M"
    assert lb.fmt_amount(12_400) == "12K"
    assert lb.fmt_amount(950) == "950"
    assert lb.slugify_server("Mal'Ganis") == "malganis"
    assert lb.slugify_server({"name": "Area 52"}) == "area-52"
    assert lb.slugify_server(None) is None


def test_build_embed():
    cfg = {
        "guild": {"name": "Test Guild"},
        "raid": {"difficulty": "heroic"},
        "top_n": 5,
        "roast_of_the_week": {"winner": "Rakell", "target": "the resto druid",
                              "roast": "Your HoTs have more downtime than the servers."},
    }
    stats = {
        "best_dps": {"Rakell": {"parse": 94.2, "amount": 1_850_000,
                                "boss": "Some Boss", "spec": "Enhancement", "cls": "Shaman"}},
        "best_hps": {},
        "deaths": {"Rakell": 7},
        "pulls": 30,
        "kills": 6,
    }
    standing = {"realm": 7, "region": 413, "world": 1842}
    leaders = [{"name": "Rakell", "spec": "Enhancement",
                "realm_rank": 14, "region_rank": 892, "best_avg": 91.3}]
    now = datetime.now(timezone.utc)
    embed = lb.build_embed(cfg, stats, standing, leaders, "Current Raid",
                           None, now, now, no_logs=False)
    field_names = [f["name"] for f in embed["fields"]]
    assert any("Guild Standing" in n for n in field_names)
    assert any("Top DPS" in n for n in field_names)
    assert any("Realm Rank Leaders" in n for n in field_names)
    assert any("Graveyard" in n for n in field_names)
    assert any("Roast" in n for n in field_names)
    assert "Realm **#7**" in embed["fields"][0]["value"]
    assert "6 kills / 30 pulls" in embed["footer"]["text"]
    # Discord embed field values must stay under 1024 chars
    assert all(len(f["value"]) <= 1024 for f in embed["fields"])


def test_no_logs_notice():
    cfg = {
        "guild": {"name": "Test Guild"},
        "raid": {"difficulty": "heroic"},
        "top_n": 5,
        "lookback_days": 7,
        "sections": {
            "no_logs_notice": {
                "enabled": True,
                "message": "No logs for {lookback_days} days"
            }
        }
    }
    # Test with no_logs=True
    field = lb.format_no_logs_notice(cfg, None, None, None, None, None, no_logs=True)
    assert field is not None
    assert "No logs for 7 days" in field["value"]
    
    # Test with no_logs=False
    field = lb.format_no_logs_notice(cfg, None, None, None, None, None, no_logs=False)
    assert field is None


def test_modular_sections():
    cfg = {
        "guild": {"name": "Test Guild"},
        "raid": {"difficulty": "heroic"},
        "top_n": 5,
        "lookback_days": 7,
        "sections": {
            "roast_of_the_week": {
                "order": 10,
                "enabled": True,
                "winner": "Rakell",
                "roast": "Test roast"
            },
            "no_logs_notice": {
                "order": 1,
                "enabled": True,
                "message": "No logs"
            }
        }
    }
    stats = {
        "best_dps": {},
        "best_hps": {},
        "deaths": {},
        "pulls": 0,
        "kills": 0,
    }
    now = datetime.now(timezone.utc)
    embed = lb.build_embed(cfg, stats, None, None, None, None, now, now, no_logs=True)
    field_names = [f["name"] for f in embed["fields"]]
    # no_logs_notice should come before roast_of_the_week due to order
    notice_idx = next(i for i, n in enumerate(field_names) if "No Logs" in n)
    roast_idx = next(i for i, n in enumerate(field_names) if "Roast" in n)
    assert notice_idx < roast_idx


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  PASS  {t.__name__}")
    print(f"\nAll {len(tests)} tests passed.")

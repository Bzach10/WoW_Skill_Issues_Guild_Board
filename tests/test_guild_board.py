import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

import requests

from guild_board import board_image
from guild_board import config as gb_config
from guild_board import dedup, discord as gb_discord, discord_inputs, filters, formatters, main, wcl


def test_deduper():
    d = dedup.FightDeduper()
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
                     key=lambda r: dedup.report_sort_key(r, "mainlogger"))
    assert ordered[0] is primary
    assert ordered[1] is long_log
    assert ordered[2] is short_log


def test_slugify_server():
    assert gb_config.slugify_server("Mal'Ganis") == "malganis"
    assert gb_config.slugify_server({"name": "Area 52"}) == "area-52"
    assert gb_config.slugify_server(None) is None


def test_clean_spec_name():
    assert gb_config.clean_spec_name("Enhancement", "Shaman") == "Enhancement Shaman"
    assert gb_config.clean_spec_name({"name": "Frost", "class_id": 8}) == "Frost Mage"


def test_get_class_color():
    assert gb_config.get_class_color("Shaman") == "#0070DE"
    assert gb_config.get_class_color("Enhancement Shaman") == "#0070DE"
    # Case-insensitive spec strings and abbreviations
    assert gb_config.get_class_color("Unholy DK") == "#C41E3A"
    assert gb_config.get_class_color("beastmastery hunter") == "#ABD473"
    # "Demon Hunter" must not fall through to "Hunter"
    assert gb_config.get_class_color("Havoc Demon Hunter") == "#A330C9"
    assert gb_config.get_class_color("") == "#CCCCCC"


def test_roster_cache(tmp_path):
    cfg = {"roster_cache": {"enabled": True, "file": str(tmp_path / "roster.json")}}
    path = gb_config.save_roster_cache(cfg, ["Rakell-Area52", "Bud-BleedingHollow"])
    members, _ = gb_config.load_roster_cache(cfg)
    assert members == ["Bud-BleedingHollow", "Rakell-Area52"]


def test_apply_roster_filters(tmp_path):
    original = filters.fetch_guild_member_names
    filters.fetch_guild_member_names = lambda token, cfg: {"rakell", "optout"}
    try:
        cfg = {
            "guild": {},
            "roster_cache": {"file": str(tmp_path / "no_cache.json")},
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
        out = filters.apply_roster_filters(None, cfg, stats)
        assert set(out["best_dps"]) == {"Rakell", "Trialguy"}
        assert out["best_hps"] == {}
        assert set(out["deaths"]) == {"Rakell"}
        assert set(out["participants"]) == {"Rakell", "Trialguy"}
    finally:
        filters.fetch_guild_member_names = original


def test_formatting_helpers():
    assert formatters.fmt_amount(1_850_000) == "1.85M"
    assert formatters.fmt_amount(12_400) == "12K"
    assert formatters.fmt_amount(950) == "950"


def test_rank_lines_parses():
    cfg = {"guild": {"name": "Test", "realm_slug": "bleeding-hollow", "region": "us"}}
    best = {
        "Rakell": {"parse": 94.2, "amount": 1_850_000, "boss": "Some Boss", "spec": "Enhancement", "cls": "Shaman", "report_code": "abc123"},
    }
    value = formatters.rank_lines_parses(best, 5, "DPS", cfg)
    assert "Rakell" in value
    assert "94%" in value
    assert "Some Boss" in value
    assert "warcraftlogs.com" in value


def test_rank_lines_deaths():
    value = formatters.rank_lines_deaths({"Rakell": 5, "Bud": 3}, 2)
    assert "Rakell" in value
    assert "5 deaths" in value


def test_rank_lines_leaders():
    cfg = {"guild": {"name": "Test", "realm_slug": "bleeding-hollow", "region": "us"}}
    leaders = [{"name": "Rakell", "spec": "Enhancement", "realm_rank": 14, "region_rank": 892, "best_avg": 91.3}]
    value = formatters.rank_lines_leaders(leaders, 5, cfg)
    assert "Rakell" in value
    assert "Realm **#14**" in value
    assert "warcraftlogs.com" in value


def test_rank_lines_leaders_with_boss():
    cfg = {"guild": {"name": "Test", "realm_slug": "bleeding-hollow", "region": "us"}}
    leaders = [{"name": "Rakell", "spec": "Enhancement", "realm_rank": 1, "boss": "Chimaerus"}]
    value = formatters.rank_lines_leaders(leaders, 5, cfg)
    assert "Rakell" in value
    assert "Realm **#1**" in value
    assert "on Chimaerus" in value


def test_rank_lines_mplus():
    cfg = {"guild": {"name": "Test", "realm_slug": "bleeding-hollow", "region": "us"}}
    results = [(18, "Mists of Tirna Scithe", "Rakell", "Enhancement Shaman", True)]
    value = formatters.rank_lines_mplus(results, 5, cfg)
    assert "+18" in value
    assert "Rakell" in value
    assert "raider.io" in value


def test_build_embed():
    cfg = {
        "guild": {"name": "Test Guild", "realm_slug": "bleeding-hollow", "region": "us"},
        "raid": {"difficulty": "heroic"},
        "top_n": 5,
        "lookback_days": 7,
        "roast_of_the_week": {"winner": "Rakell", "target": "the resto druid", "roast": "Your HoTs have more downtime than the servers."},
        "sections": {},
    }
    stats = {
        "best_dps": {"Rakell": {"parse": 94.2, "amount": 1_850_000, "boss": "Some Boss", "spec": "Enhancement", "cls": "Shaman", "report_code": "abc"}},
        "best_hps": {},
        "deaths": {"Rakell": 7},
        "pulls": 30,
        "kills": 6,
    }
    standing = {"realm": 7, "region": 413, "world": 1842}
    leaders = [{"name": "Rakell", "spec": "Enhancement", "realm_rank": 14, "region_rank": 892, "best_avg": 91.3}]
    now = datetime.now(timezone.utc)
    embed = formatters.build_embed(cfg, stats, standing, leaders, "Current Raid", None, None, None, now, now, no_logs=False)
    field_names = [f["name"] for f in embed["fields"]]
    assert any("Guild Standing" in n for n in field_names)
    assert any("Top DPS" in n for n in field_names)
    assert any("Realm Rank Leaders" in n for n in field_names)
    assert any("Graveyard" in n for n in field_names)
    assert any("Roast" in n for n in field_names)
    assert "Realm #7" in embed["fields"][0]["value"]
    assert "6 kills / 30 pulls" in embed["footer"]["text"]
    assert all(len(f["value"]) <= 1024 for f in embed["fields"])


def test_build_embed_modular_sections():
    cfg = {
        "guild": {"name": "Test Guild", "realm_slug": "bleeding-hollow", "region": "us"},
        "raid": {"difficulty": "heroic"},
        "top_n": 3,
        "lookback_days": 7,
        "display": {"layout": "two_column"},
        "sections": {
            "announcement": {"order": 0, "enabled": True, "title": "📢 Announcement", "text": "Test announcement"},
            "no_logs_notice": {"order": 1, "enabled": True, "message": "No logs"},
            "raid_header": {"order": 2, "enabled": True, "type": "section_header", "title": "Raid", "icon": "⚔️"},
            "mplus_header": {"order": 3, "enabled": True, "type": "section_header", "title": "Mythic Plus", "icon": "🗝️"},
            "guild_achievement_header": {"order": 4, "enabled": True, "type": "section_header", "title": "Guild Achievements", "icon": "🏆"},
            "overall_realm_rank": {"order": 5, "enabled": True},
            "roast_of_the_week": {"order": 6, "enabled": True, "winner": "Rakell", "roast": "Test roast"},
        },
    }
    stats = {"best_dps": {}, "best_hps": {}, "deaths": {}, "pulls": 0, "kills": 0}
    standing = {"realm": 7, "region": 413, "world": 1842}
    now = datetime.now(timezone.utc)
    embed = formatters.build_embed(cfg, stats, standing, None, None, None, None, None, now, now, no_logs=True)
    field_names = [f["name"] for f in embed["fields"]]
    # Announcement first, then two columns, then guild achievements, then roast
    assert "Announcement" in field_names[0]
    assert "Raid" in field_names[1]
    assert "Mythic Plus" in field_names[2]
    assert "Guild Achievements" in field_names[3]
    assert any("Overall Realm Rank" in n for n in field_names)
    assert "Roast" in field_names[-1]
    # No logs notice should appear inside the Raid column
    assert "No logs" in embed["fields"][1]["value"]
    assert all(len(f["value"]) <= 1024 for f in embed["fields"])


def test_announcement():
    cfg = {
        "guild": {"name": "Test"},
        "sections": {"announcement": {"enabled": True, "title": "📢 Announcement", "text": "Hello guild!"}},
    }
    field = formatters.format_announcement(cfg, None, None, None, None, None, None, None, None)
    assert field is not None
    assert field["name"] == "📢 Announcement"
    assert "Hello guild!" in field["value"]
    assert field["inline"] is False

    cfg["sections"]["announcement"]["enabled"] = False
    assert formatters.format_announcement(cfg, None, None, None, None, None, None, None, None) is None


def test_overall_realm_rank():
    cfg = {
        "guild": {"name": "Test", "realm_slug": "bleeding-hollow", "region": "us"},
        "sections": {"overall_realm_rank": {"enabled": True}},
    }
    standing = {"realm": 7, "region": 413, "world": 1842}
    field = formatters.format_overall_realm_rank(cfg, None, standing, None, None, None, None, None, None)
    assert field is not None
    assert "Overall Realm Rank" in field["name"]
    assert "Realm #7" in field["value"]
    assert formatters.format_overall_realm_rank(cfg, None, None, None, None, None, None, None, None) is None


def test_mplus_season_score_formatting():
    cfg = {
        "guild": {"name": "Test", "realm_slug": "bleeding-hollow", "region": "us"},
        "top_n": 3,
        "sections": {"mplus_season_scores": {"enabled": True}},
    }
    scores = [
        (2834.5, "Gravykin", "Protection"),
        (2710.0, "Buchalter", "Frost"),
        (2500.0, "Rakell", "Enhancement"),
    ]
    field = formatters.format_mplus_season_scores(cfg, None, None, None, None, None, scores, None, False)
    assert field is not None
    assert "Season-Long M+ Scores" in field["name"]
    assert "Gravykin" in field["value"]
    assert "2834" in field["value"] or "2835" in field["value"]


def test_main_loads_weekly_state(tmp_path):
    cfg = {"lookback_days": 7, "guild": {"name": "Test", "realm_slug": "a", "region": "us"}}
    state = {"roast_of_the_week": {"roast": "State roast", "winner": "Bud"}}
    merged = main._merge_state(cfg, state)
    assert merged["roast_of_the_week"]["roast"] == "State roast"


DAY_MS = 86_400_000


def _sample(day, parse, amount=100_000, spec="Frost", cls="Mage"):
    return {"ts": day * DAY_MS, "parse": parse, "amount": amount, "spec": spec, "cls": cls}


def test_compute_improvement_ranks_by_parse_gain():
    history = {
        "Improver": [_sample(0, 20, 90_000), _sample(10, 35), _sample(30, 60, 140_000)],
        "Steady": [_sample(0, 50), _sample(30, 52)],
        "Decliner": [_sample(0, 80), _sample(30, 40)],
        "OneNight": [_sample(0, 10), _sample(1, 90)],  # span too short
        "NewGuy": [_sample(30, 70)],  # single data point
    }
    results = wcl.compute_improvement(history, min_span_days=14)
    names = [r["name"] for r in results]
    assert names[0] == "Improver"
    assert "Decliner" not in names   # negative gains are not an award
    assert "OneNight" not in names   # needs 2+ weeks between first and last log
    assert "NewGuy" not in names
    top = results[0]
    assert top["early_parse"] == 20
    assert top["late_parse"] == 60
    assert top["delta"] == 40
    assert top["early_amount"] == 90_000
    assert top["late_amount"] == 140_000


def test_compute_improvement_uses_best_of_early_window():
    # Baseline is their best early form, not a single lucky low log
    history = {
        "Player": [_sample(0, 55), _sample(1, 30), _sample(40, 70)],
    }
    results = wcl.compute_improvement(history, min_span_days=14)
    assert results[0]["early_parse"] == 55
    assert results[0]["delta"] == 15


def test_name_filter_unions_live_and_cached_roster(tmp_path):
    """WCL's live roster drifts; cached members must not vanish off the board."""
    cache_file = tmp_path / "roster.json"
    gb_config.save_roster_cache({"roster_cache": {"file": str(cache_file)}},
                                ["Healmates-Korgath", "Healyeah-Queldorei"])
    original = filters.fetch_guild_member_names
    filters.fetch_guild_member_names = lambda token, cfg: {"rakell"}  # live roster lost the healers
    try:
        cfg = {
            "guild": {},
            "roster_cache": {"file": str(cache_file)},
            "filters": {"guild_members_only": True},
        }
        keep = filters.make_name_filter(None, cfg)
        assert keep("Rakell")
        assert keep("Healmates")     # rescued by the cache
        assert keep("healyeah")
        assert not keep("Randompug")
    finally:
        filters.fetch_guild_member_names = original


def test_resolve_roster_refreshes_stale_cache(tmp_path, monkeypatch):
    import guild_board.wcl as wcl_mod
    cache_file = tmp_path / "roster.json"
    cfg = {
        "guild": {"realm_slug": "bleeding-hollow"},
        "roster_cache": {"enabled": True, "file": str(cache_file), "max_age_days": 7},
        "sections": {"mplus": {"enabled": True, "auto_fetch_roster": True, "roster": []}},
    }
    # Write a stale cache (9 days old)
    stale = {"last_updated": (datetime.now(timezone.utc) - timedelta(days=9)).isoformat(),
             "members": ["oldguy-bleeding-hollow"]}
    cache_file.write_text(json.dumps(stale))

    monkeypatch.setattr(wcl_mod, "fetch_guild_member_roster",
                        lambda token, cfg: [("newguy", "bleeding-hollow")])
    roster, fetched = gb_config.resolve_roster(cfg, token="tok", section_name="mplus")
    assert fetched is True
    # New member fetched AND old member kept (union)
    assert "newguy-bleeding-hollow" in roster
    assert "oldguy-bleeding-hollow" in roster

    # Fresh cache now: no re-fetch
    monkeypatch.setattr(wcl_mod, "fetch_guild_member_roster",
                        lambda token, cfg: (_ for _ in ()).throw(AssertionError("should not fetch")))
    roster2, fetched2 = gb_config.resolve_roster(cfg, token="tok", section_name="mplus")
    assert fetched2 is False
    assert set(roster2) == set(roster)


def test_fill_missing_parses_applies_roster_filter():
    stats = {"best_dps": {"A": {"parse": 1}}, "best_hps": {}, "difficulty": 5}

    def collector(token, cfg, reports, difficulty):
        return {}, {"Pughealer": {"parse": 80, "difficulty": difficulty},
                    "Guildhealer": {"parse": 60, "difficulty": difficulty}}

    keep = lambda name: name.lower() == "guildhealer"
    out = wcl.fill_missing_parses(None, {}, [], stats, collector=collector, keep=keep)
    assert set(out["best_hps"]) == {"Guildhealer"}


def test_spec_class_keys():
    assert board_image._spec_class_keys("Frost", "Mage") == ("frost", "mage")
    assert board_image._spec_class_keys("Brewmaster Monk", "") == ("brewmaster", "monk")
    assert board_image._spec_class_keys("Unholy DK", "") == ("unholy", "deathknight")
    assert board_image._spec_class_keys("Havoc DH", "") == ("havoc", "demonhunter")
    assert board_image._spec_class_keys("BeastMastery Hunter", "") == ("beastmastery", "hunter")
    assert board_image._spec_class_keys("Unholy", "Death Knight") == ("unholy", "deathknight")
    assert board_image._spec_class_keys("", "Priest") == ("", "priest")
    # Unknown spec still resolves the class for the fallback icon
    assert board_image._spec_class_keys("Devourer DH", "")[1] == "demonhunter"
    # Spec-only strings infer the class when the spec is unambiguous
    assert board_image._spec_class_keys("Augmentation", "") == ("augmentation", "evoker")
    assert board_image._spec_class_keys("Demonology", "") == ("demonology", "warlock")
    assert board_image._spec_class_keys("Brewmaster", "") == ("brewmaster", "monk")
    # Ambiguous spec alone stays classless (no wrong icon)
    assert board_image._spec_class_keys("Frost", "") == ("frost", "")


def test_row_icon_prefers_spec_then_class(monkeypatch):
    fetched = []

    def fake_fetch(name):
        fetched.append(name)
        return ("img", "mask") if name.startswith("classicon") else None

    monkeypatch.setattr(board_image, "_fetch_icon", fake_fetch)
    icon = board_image._row_icon({"spec": "Frost", "cls": "Mage"})
    # Tried the spec icon first, fell back to the class icon
    assert fetched == ["spell_frost_frostbolt02", "classicon_mage"]
    assert icon == ("img", "mask")
    assert board_image._row_icon({"spec": "", "cls": ""}) is None


def test_board_state_round_trip(tmp_path, monkeypatch):
    from guild_board import state as gb_state
    path = str(tmp_path / "board_state.json")
    gb_state.save_board_state(
        {"realm": 163, "region": 7924, "stale": True, "world": None},
        [(3880, "Amrevenge", "BM Hunter"), (3692, "Shadoxii", "MW Monk")],
        path=path)
    loaded = gb_state.load_board_state(path)
    assert loaded["standing"] == {"realm": 163, "region": 7924}   # stale/None stripped
    assert loaded["season_scores"] == {"amrevenge": 3880, "shadoxii": 3692}
    assert gb_state.load_board_state(str(tmp_path / "missing.json")) == {}


def test_hero_tiles_rank_deltas_and_stale():
    stats = {"kills": 1, "pulls": 13, "deaths": {"A": 3}}
    prev = {"standing": {"realm": 166, "region": 8018}}
    tiles = board_image._hero_tiles(stats, {"realm": 163, "region": 8020}, prev)
    by_label = {t[0]: t for t in tiles}
    assert by_label["REALM RANK"][2] == "▲3"     # climbed 3 -> green up
    assert by_label["REGION RANK"][2] == "▼2"    # dropped 2 -> down
    # Stale standing: labeled, no delta arrows
    tiles = board_image._hero_tiles(stats, {"realm": 163, "stale": True}, prev)
    labels = [t[0] for t in tiles]
    assert any("LAST WK" in label for label in labels)
    assert all(t[2] == "" for t in tiles)


def test_season_score_rows_deltas_and_new():
    scores = [(3880, "Amrevenge", "BM Hunter"), (3692, "Shadoxii", "MW Monk")]
    prev = {"shadoxii": 3650}
    rows = board_image._season_score_rows(scores, 5, prev)
    assert rows[0]["value_suffix"] == "NEW"           # Amrevenge debuts
    assert rows[1]["value_suffix"] == "▲42"      # Shadoxii gained 42
    # First-ever board (no history): no badges at all
    rows = board_image._season_score_rows(scores, 5, {})
    assert "value_suffix" not in rows[0]


def test_death_rows_show_per_pull_rate():
    rows = board_image._death_rows({"Maillo": 14}, 5, {}, pulls=13)
    assert rows[0]["detail"] == "1.1 per pull"
    rows = board_image._death_rows({"Maillo": 14}, 5, {}, pulls=0)
    assert rows[0]["detail"] == ""


def test_mplus_week_rows_only_timed():
    results = [
        (20, "Pit of Saron", "Amrevenge", "Beast Mastery Hunter", False),  # depleted
        (18, "Skyreach", "Brewzleeh", "Windwalker Monk", True),
        (16, "Skyreach", "Healmates", "Holy Priest", True),
    ]
    rows = board_image._mplus_week_rows(results, 5)
    names = [r["name"] for r in rows]
    assert names == ["Brewzleeh", "Healmates"]   # the depleted +20 is out
    assert all("over time" not in (r["detail"] or "") for r in rows)


def test_detect_zone_skips_mplus_season_zones():
    reports = [
        {"zone": {"id": 44, "name": "Verdant Spire"}, "startTime": 100},
        {"zone": {"id": 45, "name": "Mythic+ Season 1"}, "startTime": 200},  # newest, but M+
    ]
    zone_id, zone_name = wcl.detect_zone({}, reports)
    assert zone_id == 44
    assert zone_name == "Verdant Spire"
    # If M+ logs are ALL we have, fall back to them rather than nothing
    only_mplus = [{"zone": {"id": 45, "name": "Mythic+ Season 1"}, "startTime": 200}]
    assert wcl.detect_zone({}, only_mplus)[0] == 45
    # Config override still wins
    assert wcl.detect_zone({"rankings": {"zone_id": 99}}, reports)[0] == 99


def test_merge_improvement_keeps_best_gain_per_player():
    mythic = [{"name": "Tommy", "delta": 29, "difficulty": 5}]
    heroic = [
        {"name": "tommy", "delta": 12, "difficulty": 4},   # worse gain, same player
        {"name": "Maillo", "delta": 22, "difficulty": 4},
        {"name": "Nokori", "delta": 8, "difficulty": 4},
    ]
    merged = wcl.merge_improvement(mythic, heroic)
    names = [e["name"] for e in merged]
    assert names == ["Tommy", "Maillo", "Nokori"]
    assert merged[0]["difficulty"] == 5   # kept the mythic (bigger) gain


def test_empty_sections_show_placeholder(tmp_path):
    """Enabled-but-empty sections keep their title with a placeholder row."""
    from PIL import Image
    cfg = _image_board_cfg()
    stats = _image_board_stats()
    stats["best_hps"] = {}   # no healing parses at all
    now = datetime.now(timezone.utc)
    out = board_image.generate_board_image(
        cfg, stats, None, [], None,
        [], [], [], now - timedelta(days=7), now,
        output_path=str(tmp_path / "board.png"),
        improvement={"dps": [], "hps": []},
        mplus_weekly={"dps": {}, "hps": {}})
    assert Image.open(out).width == board_image.WIDTH
    # Section builders keep titles with placeholder text rows
    raid, mplus = board_image._build_columns(cfg, stats, [], [], [], [], False,
                                             mplus_weekly={"dps": {}, "hps": {}})
    titles = [s["title"] for s in raid + mplus]
    assert "TOP HEALING PARSES" in titles
    assert "TOP M+ DPS THIS WEEK" in titles
    healing = next(s for s in raid if s["title"] == "TOP HEALING PARSES")
    assert healing["rows"][0].get("text")
    left, right = board_image._build_seasonal(cfg, [], [], {"dps": [], "hps": []})
    seasonal_titles = [s["title"] for s in left + right]
    assert "MOST IMPROVED DPS" in seasonal_titles
    assert "MOST IMPROVED HEALERS" in seasonal_titles


def test_extract_parses_carries_keystone_level():
    blob = {"data": [{
        "fightID": 7,
        "encounter": {"name": "Pit of Saron"},
        "roles": {"dps": {"characters": [
            {"name": "Brewzleeh", "rankPercent": 82, "amount": 190_000, "spec": "Windwalker", "class": "Monk"},
        ]}},
    }]}
    best = {}
    wcl.extract_parses(blob, "dps", best, fight_levels={7: 18})
    assert best["Brewzleeh"]["key_level"] == 18
    # Without a level map the field is simply None
    best2 = {}
    wcl.extract_parses(blob, "dps", best2)
    assert best2["Brewzleeh"]["key_level"] is None


def test_fill_missing_parses_uses_lower_difficulty():
    stats = {
        "best_dps": {"Rakell": {"parse": 90, "difficulty": 5}},
        "best_hps": {},
        "difficulty": 5,
    }

    def fake_collector(token, cfg, reports, difficulty):
        if difficulty == 4:
            return {}, {"Healmates": {"parse": 60, "difficulty": 4}}
        return {}, {}

    out = wcl.fill_missing_parses(None, {}, [], stats, collector=fake_collector)
    assert out["best_dps"]["Rakell"]["difficulty"] == 5      # untouched
    assert out["best_hps"]["Healmates"]["difficulty"] == 4   # heroic fallback, labeled
    assert out["difficulty"] == 5                             # week stays mythic


def test_fill_missing_parses_skips_when_present():
    stats = {"best_dps": {"A": {"parse": 1}}, "best_hps": {"B": {"parse": 2}}, "difficulty": 5}

    def exploding_collector(*args):
        raise AssertionError("should not be called")

    out = wcl.fill_missing_parses(None, {}, [], stats, collector=exploding_collector)
    assert out is stats


def _snowflake_for_ms(ms):
    return str((ms - discord_inputs.DISCORD_EPOCH_MS) << 22)


def _roast_msg(msg_id_ms, content, votes, author="Rakdaddy", bot=False, mentions=None):
    return {
        "id": _snowflake_for_ms(msg_id_ms),
        "content": content,
        "author": {"username": author, "bot": bot},
        "reactions": [{"emoji": {"name": "\U0001F525"}, "count": votes}] if votes else [],
        "mentions": mentions or [],
    }


def test_fetch_top_roast_picks_most_voted(monkeypatch):
    week_start = 1_000_000_000_000
    messages = [
        _roast_msg(week_start + 5000, "mid roast", 2),
        _roast_msg(week_start + 6000, "<@42> heals like a boss mod", 7,
                   mentions=[{"username": "Healmates"}]),
        _roast_msg(week_start - 5000, "old roast from last week", 50),  # outside window
        _roast_msg(week_start + 7000, "bot spam", 99, bot=True),
    ]
    monkeypatch.setattr(discord_inputs, "_collect_messages", lambda *a, **k: messages)
    top = discord_inputs.fetch_top_roast("token", "123", week_start)
    assert top["votes"] == 7
    assert top["winner"] == "Rakdaddy"
    assert top["target"] == "Healmates"
    assert top["roast"] == "Healmates heals like a boss mod"


def test_fetch_top_roast_respects_min_votes(monkeypatch):
    week_start = 1_000_000_000_000
    messages = [_roast_msg(week_start + 5000, "unloved roast", 1)]
    monkeypatch.setattr(discord_inputs, "_collect_messages", lambda *a, **k: messages)
    assert discord_inputs.fetch_top_roast("token", "123", week_start, min_votes=3) is None
    assert discord_inputs.fetch_top_roast("token", "123", week_start, min_votes=1)["votes"] == 1


def test_fetch_top_roast_unvoted_fallback(monkeypatch):
    """With min_votes 1, a fresh roast nobody reacted to still wins (newest first)."""
    week_start = 1_000_000_000_000
    messages = [
        _roast_msg(week_start + 5000, "first unloved roast", 0, author="Early"),
        _roast_msg(week_start + 9000, "newest unloved roast", 0, author="Late"),
    ]
    monkeypatch.setattr(discord_inputs, "_collect_messages", lambda *a, **k: messages)
    top = discord_inputs.fetch_top_roast("token", "123", week_start, min_votes=1)
    assert top is not None
    assert top["winner"] == "Late"
    assert top["votes"] == 0


def test_fetch_top_roast_scans_multiple_channels(monkeypatch):
    week_start = 1_000_000_000_000
    per_channel = {
        "111": [_roast_msg(week_start + 5000, "channel one roast", 1, author="One")],
        "222": [_roast_msg(week_start + 6000, "channel two roast", 4, author="Two")],
    }
    monkeypatch.setattr(discord_inputs, "_collect_messages",
                        lambda token, cid, **k: per_channel[cid])
    top = discord_inputs.fetch_top_roast("token", ["111", "222"], week_start)
    assert top["winner"] == "Two"
    assert top["votes"] == 4


def test_fetch_latest_announcement_skips_bots(monkeypatch):
    messages = [
        {"id": "3", "content": "", "author": {"username": "Empty"}},
        {"id": "2", "content": "posted by a bot", "author": {"username": "Bot", "bot": True}},
        {"id": "1", "content": "Raid moved to 8pm Tuesday!", "author": {"username": "GMBoss"}},
    ]
    monkeypatch.setattr(discord_inputs, "_get_messages", lambda *a, **k: messages)
    ann = discord_inputs.fetch_latest_announcement("token", "123")
    assert ann["text"] == "Raid moved to 8pm Tuesday!"
    assert ann["author"] == "GMBoss"


class _FakeResp:
    def __init__(self, status_code=200, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json = json_data or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


def _webhook_cfg():
    return {"guild": {"name": "Test", "realm_slug": "bleeding-hollow", "region": "us"}}


def test_post_to_discord_sends_with_components_param(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return _FakeResp(200)

    monkeypatch.setattr(gb_discord.requests, "post", fake_post)
    gb_discord.post_to_discord("https://discord.test/hook", {"title": "x"}, cfg=_webhook_cfg())

    assert len(calls) == 1
    url, kwargs = calls[0]
    # Channel webhooks only accept link buttons with this query parameter
    assert "with_components=true" in url
    assert kwargs["json"]["components"][0]["components"][0]["label"] == "Guild Logs"


def test_post_to_discord_retries_without_components_on_400(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        if len(calls) == 1:
            return _FakeResp(400, text='{"code": 50035}')
        return _FakeResp(200)

    monkeypatch.setattr(gb_discord.requests, "post", fake_post)
    resp = gb_discord.post_to_discord("https://discord.test/hook", {"title": "x"}, cfg=_webhook_cfg())

    assert resp.status_code == 200
    assert len(calls) == 2
    second_url, second_kwargs = calls[1]
    assert "with_components" not in second_url
    assert "components" not in second_kwargs["json"]


def test_post_to_discord_no_components_without_cfg(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return _FakeResp(200)

    monkeypatch.setattr(gb_discord.requests, "post", fake_post)
    gb_discord.post_to_discord("https://discord.test/hook", {"title": "x"})

    url, kwargs = calls[0]
    assert "with_components" not in url
    assert "components" not in kwargs["json"]


def _image_board_cfg():
    return {
        "guild": {"name": "Test Guild", "realm_slug": "bleeding-hollow", "region": "us"},
        "raid": {"enabled": True, "difficulty": "mythic"},
        "top_n": 3,
        "lookback_days": 7,
        "display": {"layout": "image_board", "icons": False},  # no network in tests
        "sections": {
            "raid_header": {"title": "Raid"},
            "mplus_header": {"title": "Mythic Plus"},
            "roast_of_the_week": {"enabled": True, "winner": "Rakdaddy", "target": "Healmates", "roast": "Test roast"},
        },
    }


def _image_board_stats():
    return {
        "best_dps": {"Rakell": {"parse": 94.2, "amount": 1_850_000, "boss": "Some Boss, the Long Title", "spec": "Enhancement", "cls": "Shaman", "report_code": "abc"}},
        "best_hps": {"Healmates": {"parse": 58.0, "amount": 134_000, "boss": "Some Boss", "spec": "Holy", "cls": "Priest", "report_code": "abc"}},
        "deaths": {"Rakell": 7, "Healmates": 1},
        "participants": {},
        "pulls": 21,
        "kills": 1,
        "difficulty": 5,
    }


def test_generate_board_image(tmp_path):
    from PIL import Image
    cfg = _image_board_cfg()
    standing = {"realm": 163, "region": 7924}
    leaders = [{"name": "Rakell", "spec": "Enhancement Shaman", "realm_rank": 1, "region_rank": 892, "best_avg": 91.3, "boss": "Some Boss"}]
    mplus = [(17, "Skyreach", "brewzleeh", "Brewmaster Monk", True)]
    scores = [(2834.5, "Gravykin", "Protection Paladin")]
    parses = [(473, "Pit of Saron", "shadoxii", "Mistweaver Monk", False)]
    improvement = {
        "dps": [{"name": "Rakell", "spec": "Enhancement", "cls": "Shaman",
                 "early_parse": 20, "late_parse": 60, "early_amount": 90_000,
                 "late_amount": 140_000, "delta": 40}],
        "hps": [{"name": "Healmates", "spec": "Holy", "cls": "Priest",
                 "early_parse": 30, "late_parse": 58, "early_amount": 100_000,
                 "late_amount": 134_000, "delta": 28}],
    }
    mplus_weekly = {
        "dps": {"Brewzleeh": {"parse": 82, "spec": "Windwalker", "cls": "Monk",
                              "amount": 190_000, "boss": "Pit of Saron", "difficulty": 10}},
        "hps": {"Healmates": {"parse": 66, "spec": "Holy", "cls": "Priest",
                              "amount": 90_000, "boss": "Skyreach", "difficulty": 10}},
    }
    now = datetime.now(timezone.utc)
    out = board_image.generate_board_image(
        _image_board_cfg(), _image_board_stats(), standing, leaders, "Some Raid",
        mplus, scores, parses, now - timedelta(days=7), now,
        output_path=str(tmp_path / "board.png"), improvement=improvement,
        mplus_weekly=mplus_weekly)
    img = Image.open(out)
    assert img.width == board_image.WIDTH
    assert img.height > 500


def test_generate_board_image_no_data(tmp_path):
    from PIL import Image
    now = datetime.now(timezone.utc)
    out = board_image.generate_board_image(
        _image_board_cfg(), None, None, None, None,
        None, None, None, now - timedelta(days=7), now, no_logs=True,
        output_path=str(tmp_path / "board.png"))
    img = Image.open(out)
    assert img.width == board_image.WIDTH


def test_build_image_embed():
    cfg = _image_board_cfg()
    cfg["sections"]["announcement"] = {"enabled": True, "text": "Hello guild!"}
    now = datetime.now(timezone.utc)
    embed = formatters.build_image_embed(cfg, _image_board_stats(), now - timedelta(days=7), now)
    assert embed["image"]["url"] == "attachment://board.png"
    assert "Hello guild!" in embed["description"]
    assert "Raid week:" in embed["description"]
    # singular kill, plural pulls
    assert "1 kill / 21 pulls" in embed["footer"]["text"]
    assert "fields" not in embed


def test_build_board_image_layout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = _image_board_cfg()
    cfg["raid"]["enabled"] = False
    now = datetime.now(timezone.utc)
    embed, image_path = main.build_board(cfg, start_dt=now - timedelta(days=7), end_dt=now, preview=True)
    assert image_path == "board.png"
    assert os.path.exists(tmp_path / "board.png")
    assert embed["image"]["url"] == "attachment://board.png"


def test_main_preview_writes_html(tmp_path):
    cfg = {
        "lookback_days": 7,
        "guild": {"name": "Test", "realm_slug": "bleeding-hollow", "region": "us"},
        "raid": {"enabled": False, "difficulty": "heroic"},
        "top_n": 5,
        "sections": {"progress_image": {"enabled": False}},
    }
    now = datetime.now(timezone.utc)
    embed, _ = main.build_board(cfg, start_dt=now - timedelta(days=7), end_dt=now, preview=True)
    assert "title" in embed
    assert "Test" in embed["title"]

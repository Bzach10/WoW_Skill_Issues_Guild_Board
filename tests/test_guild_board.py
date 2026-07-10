import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from guild_board import board_image
from guild_board import config as gb_config
from guild_board import dedup, filters, formatters, main


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


def test_apply_roster_filters():
    original = filters.fetch_guild_member_names
    filters.fetch_guild_member_names = lambda token, cfg: {"rakell", "optout"}
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


def _image_board_cfg():
    return {
        "guild": {"name": "Test Guild", "realm_slug": "bleeding-hollow", "region": "us"},
        "raid": {"enabled": True, "difficulty": "mythic"},
        "top_n": 3,
        "lookback_days": 7,
        "display": {"layout": "image_board"},
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
    now = datetime.now(timezone.utc)
    out = board_image.generate_board_image(
        _image_board_cfg(), _image_board_stats(), standing, leaders, "Some Raid",
        mplus, scores, parses, now - timedelta(days=7), now,
        output_path=str(tmp_path / "board.png"))
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

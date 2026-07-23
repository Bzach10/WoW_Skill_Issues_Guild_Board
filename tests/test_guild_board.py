import json
import os
from datetime import datetime, timedelta, timezone

import pytest
import requests

from guild_board import board_image, dedup, discord_inputs, filters, formatters, main, wcl
from guild_board import config as gb_config
from guild_board import discord as gb_discord


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


def test_deduper_tolerance_boundaries():
    # Exactly at the 60s start / 15s duration tolerance -> still a duplicate
    d = dedup.FightDeduper()
    assert d.check_and_add(3009, 4, False, 1_000_000, 240_000) is False
    assert d.check_and_add(3009, 4, False, 1_060_000, 255_000) is True

    # 1ms past either tolerance -> distinct
    d = dedup.FightDeduper()
    assert d.check_and_add(3009, 4, False, 1_000_000, 240_000) is False
    assert d.check_and_add(3009, 4, False, 1_060_001, 255_000) is False

    d = dedup.FightDeduper()
    assert d.check_and_add(3009, 4, False, 1_000_000, 240_000) is False
    assert d.check_and_add(3009, 4, False, 1_060_000, 255_001) is False


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
    gb_config.save_roster_cache(cfg, ["Rakell-Area52", "Bud-BleedingHollow"])
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
    assert any("Boss Ranks" in n for n in field_names)
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
    # two_column is retired: sections render single-column in config order
    assert "Announcement" in field_names[0]
    assert any("No Logs" in n for n in field_names)
    assert any("Raid" in n for n in field_names)
    assert any("Mythic Plus" in n for n in field_names)
    assert any("Guild Achievements" in n for n in field_names)
    assert any("Overall Realm Rank" in n for n in field_names)
    assert "Roast" in field_names[-1]
    assert all(f["inline"] is False for f in embed["fields"])
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


def test_load_config_rejects_placeholder_guild(tmp_path):
    cfg_file = tmp_path / "config.yml"
    cfg_file.write_text('guild:\n  name: "Your Guild Name"\n', encoding="utf-8")
    with pytest.raises(SystemExit):
        gb_config.load_config(str(cfg_file))
    cfg_file.write_text('guild:\n  name: "Real Guild"\n', encoding="utf-8")
    assert gb_config.load_config(str(cfg_file))["guild"]["name"] == "Real Guild"


def test_theme_art_banners(tmp_path):
    from PIL import Image
    art = Image.new("RGB", (800, 1000), (70, 40, 25))
    art_path = tmp_path / "art.png"
    art.save(art_path)
    now = datetime.now(timezone.utc)

    cfg = _image_board_cfg()
    plain = board_image.generate_board_image(
        cfg, _image_board_stats(), None, None, None, None, None, None,
        now - timedelta(days=7), now, output_path=str(tmp_path / "plain.png"))
    plain_h = Image.open(plain).height

    cfg = _image_board_cfg()
    cfg["display"]["theme_art"] = str(art_path)
    themed = board_image.generate_board_image(
        cfg, _image_board_stats(), None, None, None, None, None, None,
        now - timedelta(days=7), now, output_path=str(tmp_path / "themed.png"))
    themed_h = Image.open(themed).height
    # Header banner + info strip + footer banner grow the canvas substantially
    assert themed_h > plain_h + 500

    # Missing art file: renders the plain board rather than crashing
    cfg["display"]["theme_art"] = str(tmp_path / "missing.png")
    out = board_image.generate_board_image(
        cfg, _image_board_stats(), None, None, None, None, None, None,
        now - timedelta(days=7), now, output_path=str(tmp_path / "fallback.png"))
    assert Image.open(out).height == plain_h


def test_board_animation_gif(tmp_path):
    from PIL import Image, ImageChops
    art = Image.new("RGB", (800, 1000), (70, 40, 25))
    art_path = tmp_path / "art.png"
    art.save(art_path)
    cfg = _image_board_cfg()
    cfg["display"]["theme_art"] = str(art_path)   # flames need the themed bands
    now = datetime.now(timezone.utc)
    out = board_image.generate_board_animation(
        cfg, _image_board_stats(), None, None, None, None, None, None,
        now - timedelta(days=7), now, False,
        output_path=str(tmp_path / "board.gif"), frames=10)
    assert out and out.endswith(".gif")
    gif = Image.open(out)
    assert getattr(gif, "n_frames", 1) == 10

    # Bands animate; the data columns must stay pixel-identical between
    # frames (no shimmer). Compare frame 3 against frame 0.
    gif.seek(0)
    f0 = gif.convert("RGB")
    gif.seek(3)
    f3 = gif.convert("RGB")
    diff = ImageChops.difference(f0, f3)
    assert diff.getbbox() is not None   # something is actually animating
    mid = diff.crop((0, board_image.HEADER_ART_H + 10, f0.width,
                     f0.height - board_image.FOOTER_ART_H - 10))
    assert mid.getbbox() is None        # ...but only inside the bands


def test_html_board_context_and_template():
    """The HTML renderer builds a full context and the template renders it
    (no browser needed — Playwright capture is exercised in CI runs)."""
    from guild_board import html_board
    now = datetime.now(timezone.utc)
    cfg = _image_board_cfg()
    ctx = html_board.build_context(
        cfg, _image_board_stats(), None, None, "Voidspire", None, None, None,
        now - timedelta(days=7), now)
    assert ctx["columns"][0]["title"] == "RAID"
    assert ctx["wipes"] == ctx["pulls"] - _image_board_stats()["kills"]
    assert len(ctx["header_embers"]) == 26
    html = html_board.render_html(ctx)
    assert "GRAVEYARD CAMPERS MEMORIAL" in html
    assert "GIT GUD" in html
    assert "Voidspire" in html
    assert "Gambling Debt" in html
    assert "data-count" in html and "__setPhase" in html
    assert ctx["debt"] > 137_000   # compounds weekly, never shrinks
    # every animation in the template must divide the GIF loop so any
    # frame count loops seamlessly
    import re
    for dur in re.findall(r"animation(?:-duration)?:\s*\.?([\d.]+)s", html):
        period_ms = float(dur) * 1000 * 2   # alternate direction => 2x period
        assert html_board.LOOP_MS % int(period_ms) in (0, html_board.LOOP_MS), dur


def test_html_board_falls_back_without_browser(monkeypatch, tmp_path):
    """Any renderer failure returns None so main falls back to Pillow."""
    from guild_board import html_board
    monkeypatch.setattr(html_board, "render_html",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    now = datetime.now(timezone.utc)
    out = html_board.generate_board_html(
        _image_board_cfg(), _image_board_stats(), None, None, None, None, None,
        None, now - timedelta(days=7), now,
        output_path=str(tmp_path / "board.png"))
    assert out is None


def test_watermark_renders(tmp_path):
    from PIL import Image
    cfg = _image_board_cfg()
    cfg["display"]["watermark"] = True
    now = datetime.now(timezone.utc)
    out = board_image.generate_board_image(
        cfg, _image_board_stats(), None, None, None, None, None, None,
        now - timedelta(days=7), now, output_path=str(tmp_path / "board.png"))
    assert Image.open(out).width == board_image.WIDTH


def test_advance_streaks():
    from guild_board.state import advance_streaks
    prev = {"brewzleeh": 2, "ghost": 4}
    streaks = advance_streaks(prev, {"Brewzleeh", "Newguy", ""})
    assert streaks == {"brewzleeh": 3, "newguy": 1}   # absentee "ghost" reset


def test_update_records_tracks_and_flags_new():
    from guild_board.state import update_records
    stats = {"best_dps": {"Rakdisc": {"parse": 70, "boss": "Rotmire", "spec": "Shadow", "cls": "Priest", "difficulty": 5}},
             "best_hps": {}}
    mplus = [(18, "Pit of Saron", "Brewzleeh", "Windwalker Monk", True)]
    records = update_records({}, stats, mplus)
    assert records["highest_timed_key"]["level"] == 18
    assert records["highest_timed_key"]["new"] is True
    assert records["best_dps_parse"]["new"] is True

    # Next week: a lower key does NOT displace the record, flags reset
    records2 = update_records(records, {"best_dps": {}, "best_hps": {}},
                              [(16, "Skyreach", "Healmates", "Holy Priest", True)])
    assert records2["highest_timed_key"]["level"] == 18
    assert records2["highest_timed_key"]["new"] is False
    assert records2["best_dps_parse"]["new"] is False

    # A bigger key breaks it
    records3 = update_records(records2, None, [(20, "Skyreach", "Amrevenge", "BM Hunter", True)])
    assert records3["highest_timed_key"]["level"] == 20
    assert records3["highest_timed_key"]["new"] is True


def test_update_records_season_sweep_beats_weekly():
    from guild_board.state import update_records
    weekly_stats = {"best_dps": {"Rakdisc": {"parse": 70, "boss": "Rotmire", "spec": "Shadow", "cls": "Priest", "difficulty": 5}},
                    "best_hps": {}}
    season_bests = {"dps": {"name": "Pyro", "parse": 95, "boss": "Old Boss", "spec": "Fire", "cls": "Mage", "difficulty": 5},
                    "hps": None}
    season_key = {"name": "Amrevenge", "level": 21, "dungeon": "Pit of Saron", "spec": "BM Hunter"}
    records = update_records({}, weekly_stats, None,
                             season_parses=season_bests, season_key=season_key)
    # The 95% from three weeks ago outranks this week's 70%
    assert records["best_dps_parse"]["name"] == "Pyro"
    assert records["best_dps_parse"]["parse"] == 95
    assert records["highest_timed_key"]["level"] == 21


def test_best_timed_run_picks_highest_timed():
    from guild_board.raiderio import _best_timed_run
    runs = [
        {"mythic_level": 22, "score": 500, "num_keystone_upgrades": 0},  # depleted
        {"mythic_level": 19, "score": 470, "num_keystone_upgrades": 1},
        {"mythic_level": 19, "score": 480, "num_keystone_upgrades": 2},
    ]
    best = _best_timed_run(runs)
    assert best["mythic_level"] == 19 and best["score"] == 480
    assert _best_timed_run([{"mythic_level": 20, "num_keystone_upgrades": 0}]) is None


def test_streak_bits_and_closest_race():
    streaks = {"brewzleeh": 3, "healmates": 1}
    rows = board_image._mplus_week_rows(
        [(18, "Skyreach", "Brewzleeh", "Windwalker Monk", True),
         (16, "Skyreach", "Healmates", "Holy Priest", True)], 5, streaks)
    assert "3w streak" in rows[0]["detail"]
    assert "streak" not in rows[1]["detail"]   # 1 week is not a streak

    races = board_image._closest_races([(3880, "Amrevenge", ""), (3692, "Shadoxii", ""),
                                        (3686, "Brewzleeh", "")])
    # Tightest rivalry first, then the next ones
    assert "Brewzleeh trails Shadoxii by just 6" in races[0]
    assert "Shadoxii trails Amrevenge by 188" in races[1]
    assert board_image._closest_races([(100, "Solo", "")]) == []


def test_record_rows_render():
    records = {
        "highest_timed_key": {"name": "Brewzleeh", "level": 18, "dungeon": "Pit of Saron",
                              "spec": "Windwalker Monk", "new": True},
        "best_dps_parse": {"name": "Rakdisc", "parse": 70, "boss": "Rotmire",
                           "spec": "Shadow", "cls": "Priest", "difficulty": 5, "new": False},
    }
    rows = board_image._record_rows(records)
    assert rows[0]["value"] == "+18"
    assert rows[0]["value_suffix"] == "NEW"
    assert rows[1]["value"] == "70%"
    assert "value_suffix" not in rows[1]
    assert "Mythic Rotmire" in rows[1]["detail"]


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
    assert rows[0]["value"] == "1.1/pull"          # red rate up front
    assert rows[0]["value_suffix"] == "14 total"   # grey total beside it
    rows = board_image._death_rows({"Maillo": 14}, 5, {}, pulls=0)
    assert rows[0]["value"] == "14 deaths"         # no pulls -> plain count
    assert "value_suffix" not in rows[0]


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
    seasonal_mp, seasonal_guild = board_image._build_seasonal(cfg, [], [], {"dps": [], "hps": []})
    mp_titles = [s["title"] for s in seasonal_mp]
    guild_titles = [s["title"] for s in seasonal_guild]
    assert "SEASON M+ SCORES" in mp_titles
    # Most Improved lives in the Seasonal Guild column
    assert "MOST IMPROVED DPS" in guild_titles
    assert "MOST IMPROVED HEALERS" in guild_titles
    # Placeholder rows keep the section shape even with no qualifiers
    imp = next(s for s in seasonal_guild if s["title"] == "MOST IMPROVED DPS")
    assert imp["rows"][0].get("text")


def test_report_detail_cache(monkeypatch):
    calls = []

    def fake_gql(token, query, variables):
        calls.append(variables)
        return {"reportData": {"report": {"fights": []}}}

    monkeypatch.setattr(wcl, "gql", fake_gql)
    monkeypatch.setattr(wcl.time, "sleep", lambda s: None)
    wcl.clear_report_cache()
    wcl.fetch_report_detail("tok", "abc", 5)
    wcl.fetch_report_detail("tok", "abc", 5)   # cached — no second API call
    wcl.fetch_report_detail("tok", "abc", 4)   # different difficulty — new call
    wcl.fetch_report_detail("tok", "xyz", 5)
    assert len(calls) == 3
    wcl.clear_report_cache()
    wcl.fetch_report_detail("tok", "abc", 5)
    assert len(calls) == 4


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


# --- theming, modules, awards, mobile companion -----------------------------------


def test_theme_defaults_merge_and_fail_open(tmp_path):
    from guild_board import theme as theme_mod
    # missing file -> full defaults
    t = theme_mod.load_theme(str(tmp_path / "missing.yml"))
    assert t["header"]["sign_text"] == "GIT GUD"
    # partial file -> overrides win, untouched keys keep defaults
    custom = tmp_path / "theme.yml"
    custom.write_text("colors:\n  accent: '#123456'\nheader:\n  sign_text: 'NO WIPES'\n",
                      encoding="utf-8")
    t2 = theme_mod.load_theme(str(custom))
    assert t2["colors"]["accent"] == "#123456"
    assert t2["header"]["sign_text"] == "NO WIPES"
    assert t2["colors"]["background"] == "#111217"
    # broken YAML -> defaults, never an exception
    broken = tmp_path / "broken.yml"
    broken.write_text("colors: [unclosed", encoding="utf-8")
    assert theme_mod.load_theme(str(broken))["header"]["sign_text"] == "GIT GUD"


def test_theme_module_resolution_falls_back():
    from guild_board import theme as theme_mod
    mods = theme_mod.resolve_templates({"board": {"header": "no_such_module", "footer": "simple"}})
    assert mods["header_template"] == "headers/stone_torchlight.html.j2"
    assert mods["footer_template"] == "footers/simple.html.j2"
    assert mods["footer_h"] == theme_mod.FOOTER_HEIGHTS["simple"]


def test_weekly_awards_rotate_and_rank():
    from guild_board.awards import weekly_awards
    stats = {"deaths": {"Alba": 3, "Bryn": 0}, "participants": ["Alba", "Bryn", "Cyd"],
             "pulls": 20, "best_dps": {}, "best_hps": {}}
    streaks = {"alba": 5, "bryn": 3, "cyd": 1}
    scores = [(3000, "Alba", "Holy Priest"), (2500, "Bryn", "Fire Mage")]
    previous = {"season_scores": {"alba": 2900, "bryn": 2510}}
    kwargs = dict(stats=stats, streaks=streaks, season_scores=scores, previous=previous)
    secs = weekly_awards(0, per_week=2, **kwargs)
    assert len(secs) == 2
    assert secs[0]["title"].endswith("ATTENDANCE")
    assert secs[0]["rows"][0]["name"] == "Alba"
    # rotation: an odd week leads with the other award
    secs2 = weekly_awards(1, per_week=2, **kwargs)
    assert secs2[0]["title"].endswith("BIGGEST CLIMB")
    # climb: only positive gains, largest first
    climb = secs2[0]
    assert climb["rows"][0]["name"] == "Alba" and climb["rows"][0]["value"] == "+100"
    # the retired Ironman award never appears
    assert not any("IRONMAN" in s["title"] for s in secs + secs2)


def test_alt_header_footer_modules_render(tmp_path):
    from guild_board import html_board
    theme_file = tmp_path / "theme.yml"
    theme_file.write_text("board:\n  header: banner\n  footer: simple\n", encoding="utf-8")
    cfg = _image_board_cfg()
    cfg["display"]["theme_file"] = str(theme_file)
    now = datetime.now(timezone.utc)
    ctx = html_board.build_context(
        cfg, _image_board_stats(), None, None, "Voidspire", None, None, None,
        now - timedelta(days=7), now)
    assert ctx["header_template"] == "headers/banner.html.j2"
    html = html_board.render_html(ctx)
    assert "TEST GUILD" in html                 # banner carries the guild name
    assert "CAMPERS MEMORIAL" not in html       # simple footer has no memorial
    assert "GIT GUD" not in html                # no hanging sign either


def test_headline_priorities():
    from guild_board.html_board import _headline
    records = {"best_dps_parse": {"name": "Rakell", "parse": 99.0, "boss": "Chimaerus", "new": True}}
    assert "NEW GUILD RECORD" in _headline(None, None, None, records)
    standing, previous = {"realm": 49}, {"standing": {"realm": 52}}
    assert _headline(None, standing, previous, None) == "REALM RANK #49 — UP 3 THIS WEEK"
    assert "GO AGANE" in _headline({"kills": 2, "pulls": 30}, None, None, None)
    assert _headline({"kills": 0, "pulls": 0}, None, None, None) is None


def test_mobile_template_renders():
    from guild_board import html_board
    now = datetime.now(timezone.utc)
    ctx = html_board.build_context(
        _image_board_cfg(), _image_board_stats(), {"realm": 49}, None, "Voidspire",
        None, None, None, now - timedelta(days=7), now)
    html = html_board.render_html(ctx, template="mobile.html.j2")
    assert "TEST GUILD" in html
    assert 'width:1080px' in html
    assert "ROAST OF THE WEEK" in html


def test_tldr_lines():
    from guild_board.formatters import tldr_lines
    lines = tldr_lines(_image_board_stats(), {"realm": 49})
    assert any("Top DPS" in l and "Rakell" in l for l in lines)
    assert any("#49" in l for l in lines)
    assert tldr_lines(None, None) == []


def test_debt_card_theme_driven():
    from guild_board.html_board import _debt_card
    card = _debt_card({"footer": {"debt": {"enabled": True, "principal": 1000,
                                           "weekly_rate_pct": 10.0,
                                           "lines": ["Binds on !roll", "Ledger|Unique",
                                                     "Equip: Loses gold."]}}}, 2)
    assert card["amount"] == 1210
    assert card["lines"][1] == {"left": "Ledger", "right": "Unique", "green": False}
    assert card["lines"][2]["green"] is True
    assert _debt_card({"footer": {"debt": {"enabled": False}}}, 5) is None


# --- tank sections & boss-ranks relocation ----------------------------------------


def test_tank_sections_and_boss_ranks_move():
    from guild_board import html_board
    cfg = _image_board_cfg()
    stats = _image_board_stats()
    stats["best_tanks"] = {"Brewz": {"parse": 88.0, "amount": 90_000, "boss": "Some Boss",
                                     "spec": "Brewmaster", "cls": "Monk"}}
    leaders = [{"name": "Rakell", "spec": "Enhancement Shaman", "realm_rank": 1,
                "region_rank": 892, "best_avg": 91.3, "boss": "Some Boss"}]
    mplus_weekly = {"dps": {}, "hps": {},
                    "tanks": {"Brewz": {"parse": 90.0, "amount": 80_000, "boss": "Skyreach",
                                        "spec": "Brewmaster", "cls": "Monk", "key_level": 18}}}
    now = datetime.now(timezone.utc)
    ctx = html_board.build_context(
        cfg, stats, None, leaders, "Voidspire", None, None, None,
        now - timedelta(days=7), now, mplus_weekly=mplus_weekly)
    raid_titles = [s["title"] for s in ctx["columns"][0]["sections"]]
    mplus_titles = [s["title"] for s in ctx["columns"][1]["sections"]]
    guild_titles = [s["title"] for s in ctx["columns"][3]["sections"]]
    assert "TOP PARSES · ALL ROLES" in raid_titles
    assert "TOP M+ TANKS THIS WEEK" in mplus_titles
    assert "WEEKLY BOSS RANKS" not in raid_titles      # moved out of raid...
    assert guild_titles[0] == "WEEKLY BOSS RANKS"      # ...to lead Seasonal Guild
    # the all-roles ladder ranks by parse across DPS/HPS/tanks, tagged by role
    overall = next(s for s in ctx["columns"][0]["sections"] if s["title"] == "TOP PARSES · ALL ROLES")
    assert overall["rows"][0]["name"] == "Rakell"          # 94.2 DPS
    assert overall["rows"][1]["name"] == "Brewz"           # 88.0 tank beats 58.0 healer
    assert overall["rows"][1]["detail_bits"][0] == "Tank"


def test_collect_parses_only_returns_tanks(monkeypatch):
    blob = {"data": [{"encounter": {"name": "Some Boss"}, "fightID": 1, "roles": {
        "tanks": {"characters": [{"name": "Brewz", "rankPercent": 77.0, "amount": 50_000,
                                  "spec": "Brewmaster", "class": "Monk"}]},
        "dps": {"characters": [{"name": "Rakell", "rankPercent": 90.0, "amount": 150_000,
                                "spec": "Enhancement", "class": "Shaman"}]},
        "healers": {"characters": []},
    }}]}
    monkeypatch.setattr(wcl, "fetch_report_detail",
                        lambda token, code, difficulty: {"dps": blob, "hps": blob, "fights": []})
    dps, hps, tanks = wcl.collect_parses_only("tok", {}, [{"code": "abc"}], 5)
    assert tanks["Brewz"]["parse"] == 77.0
    assert dps["Rakell"]["parse"] == 90.0
    assert tanks["Brewz"]["difficulty"] == 5


# --- responsive web board ---------------------------------------------------------


def test_web_template_renders_responsive():
    from guild_board import html_board
    now = datetime.now(timezone.utc)
    ctx = html_board.build_context(
        _image_board_cfg(), _image_board_stats(), {"realm": 49}, None, "Voidspire",
        None, None, None, now - timedelta(days=7), now)
    html = html_board.render_html(ctx, template="web.html.j2")
    assert 'name="viewport"' in html            # phone scaling enabled
    assert "TEST GUILD" in html
    assert "auto-fit" in html                   # columns reflow with the screen
    assert "ROAST OF THE WEEK" in html


def test_generate_web_board_writes_file(tmp_path):
    from guild_board.html_board import generate_web_board
    now = datetime.now(timezone.utc)
    out = generate_web_board(
        _image_board_cfg(), _image_board_stats(), None, None, "Voidspire",
        None, None, None, now - timedelta(days=7), now,
        output_path=str(tmp_path / "site" / "index.html"))
    assert out and os.path.exists(out)


def test_link_buttons_include_web_board():
    cfg = {"guild": {"name": "Test", "realm_slug": "bleeding-hollow", "region": "us"},
           "display": {"web_board": {"url": "https://example.github.io/board/"}}}
    rows = gb_discord._build_link_buttons(cfg)
    labels = [b["label"] for b in rows[0]["components"]]
    assert any("Web Board" in l for l in labels)
    cfg["display"] = {}
    labels = [b["label"] for b in gb_discord._build_link_buttons(cfg)[0]["components"]]
    assert not any("Web Board" in l for l in labels)


def test_tldr_matches_rendered_rows():
    """The post text derives from the exact rows the board renders."""
    from guild_board import html_board
    now = datetime.now(timezone.utc)
    stats = _image_board_stats()
    stats["best_tanks"] = {"Brewz": {"parse": 88.0, "amount": 90_000, "boss": "Some Boss",
                                     "spec": "Brewmaster", "cls": "Monk"}}
    ctx = html_board.build_context(
        _image_board_cfg(), stats, {"realm": 49}, None, "Voidspire",
        None, None, None, now - timedelta(days=7), now)
    tldr = html_board.LAST_TLDR
    assert any("Rakell" in l and "94%" in l for l in tldr)      # top DPS row verbatim
    assert any("Top tank" in l and "Brewz" in l and "88%" in l for l in tldr)
    assert any("#49" in l for l in tldr)
    assert ctx["tldr"] == tldr


def test_raid_attendance_streaks():
    from guild_board.state import raid_attendance_streaks
    previous = {"streaks": {"alba": 4, "bryn": 2}}
    stats = {"participants": {"Alba": None}, "best_dps": {"Cyd": {}},
             "best_hps": {}, "best_tanks": {}}
    out = raid_attendance_streaks(previous, stats)
    assert out == {"alba": 5, "cyd": 1}          # attendee ticks, newcomer starts, absentee drops
    # a no-logs week carries streaks forward instead of wiping them
    assert raid_attendance_streaks(previous, None) == previous["streaks"]
    assert raid_attendance_streaks(None, None) == {}


def test_raid_attendance_streaks_once_per_week():
    """Reposting the board in the same raid week must NOT inflate streaks —
    the bug that gave players +1 'week' per manual rerun."""
    from guild_board.state import raid_attendance_streaks
    stats = {"participants": {"Alba": None}, "best_dps": {}, "best_hps": {}, "best_tanks": {}}
    previous = {"streaks": {"alba": 4}, "streaks_week": "2026-W30"}
    # same week, second/third/tenth post: unchanged
    assert raid_attendance_streaks(previous, stats, week_label="2026-W30") == {"alba": 4}
    # a NEW week advances once
    assert raid_attendance_streaks(previous, stats, week_label="2026-W31") == {"alba": 5}
    # legacy state without a stored week still advances (then gets guarded)
    assert raid_attendance_streaks({"streaks": {"alba": 4}}, stats,
                                   week_label="2026-W30") == {"alba": 5}


def test_image_embed_title_links_to_web_board():
    cfg = {"guild": {"name": "Test Guild", "realm_slug": "x", "region": "us"},
           "raid": {"difficulty": "mythic"}, "lookback_days": 7, "sections": {},
           "display": {"web_board": {"enabled": True, "url": "https://x.github.io/b/"}}}
    now = datetime.now(timezone.utc)
    embed = formatters.build_image_embed(cfg, None, now, now)
    assert embed["url"] == "https://x.github.io/b/"
    cfg["display"]["web_board"]["enabled"] = False
    assert "url" not in formatters.build_image_embed(cfg, None, now, now)


def test_parse_records_self_correct_from_season_sweep():
    """A stale inflated percentile (early-bracket ~100%) must fall back to
    the sweep's CURRENT value instead of being immortalized."""
    from guild_board.state import update_records
    previous = {"best_dps_parse": {"name": "Tommybravoo", "parse": 100,
                                   "boss": "Chimaerus", "spec": "Unholy",
                                   "cls": "DeathKnight", "difficulty": 5, "new": False}}
    sweep = {"dps": {"name": "Tommybravoo", "parse": 59, "boss": "Chimaerus",
                     "spec": "Unholy", "cls": "DeathKnight", "difficulty": 5},
             "hps": None}
    records = update_records(previous, {"best_dps": {}, "best_hps": {}},
                             None, season_parses=sweep)
    assert records["best_dps_parse"]["parse"] == 59      # corrected DOWN
    assert records["best_dps_parse"]["new"] is False     # a correction is not news
    # without a sweep, the stored record is carried forward (fail-safe)
    records2 = update_records(previous, {"best_dps": {}, "best_hps": {}}, None)
    assert records2["best_dps_parse"]["parse"] == 100


# --- self-healing integrity layer -------------------------------------------------


def test_integrity_heals_rows_and_hero():
    from guild_board import integrity
    ctx = {
        "columns": [{"sections": [{"title": "TOP DPS PARSES", "rows": [
            {"name": "Glitch", "value": "140%", "color": "rgb(0,112,222)", "spec": "Enh"},
            {"name": "Grey", "value": "80%", "color": "rgb(235,236,240)", "spec": "Holy"},
        ]}]}],
        "hero_tiles": [{"label": "KILLS", "value": "6"}],
        "pulls": 54, "wipes": 99,
    }
    msgs = integrity.run_all(context=ctx)
    assert ctx["columns"][0]["sections"][0]["rows"][0]["value"] == "100%"   # clamped
    assert ctx["wipes"] == 48                                              # healed math
    assert any("grey-name" in m for m in msgs)


def test_integrity_heals_records_and_standing():
    from guild_board import integrity
    records = {"best_dps_parse": {"name": "X", "parse": 250},
               "best_hps_parse": {"name": "Y", "parse": 100},
               "highest_timed_key": {"name": "Z", "level": 20}}
    standing = {"realm": 49, "region": "garbage", "world": -3}
    msgs = integrity.run_all(records=records, standing=standing)
    assert records["best_dps_parse"]["parse"] == 100          # clamped
    assert any("exactly 100%" in m for m in msgs)             # artifact flagged
    assert standing == {"realm": 49}                          # bad ranks dropped
    # a clean build produces zero noise
    assert integrity.run_all(records={"highest_timed_key": {"level": 18}},
                             standing={"realm": 10}) == []


def test_integrity_cli_on_state_file(tmp_path, monkeypatch):
    import json as _json
    import subprocess
    import sys
    state = {"records": {"best_dps_parse": {"name": "A", "parse": 59}},
             "standing": {"realm": 49}}
    monkeypatch.chdir(tmp_path)
    (tmp_path / "board_state.json").write_text(_json.dumps(state), encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "guild_board.integrity"],
                       capture_output=True, text=True,
                       cwd=tmp_path, env={**os.environ, "PYTHONPATH": os.path.dirname(os.path.dirname(os.path.abspath(main.__file__)))})
    assert r.returncode == 0
    assert "0 needing attention" in r.stdout


# --- repost-proof week anchoring & baselines --------------------------------------


def test_raid_week_label_anchors_to_tuesday_reset():
    from guild_board.state import raid_week_label
    tz = timezone.utc
    # Tuesday 13:00 UTC (the scheduled post, pre-reset) belongs to the PRIOR week
    assert raid_week_label(datetime(2026, 7, 21, 13, 0, tzinfo=tz)) == "2026-07-14"
    # Tuesday 16:00 UTC (post-reset) starts the new week
    assert raid_week_label(datetime(2026, 7, 21, 16, 0, tzinfo=tz)) == "2026-07-21"
    # Sunday and Monday reposts stay in the same raid week (ISO week would split them)
    assert raid_week_label(datetime(2026, 7, 19, 22, 0, tzinfo=tz)) == "2026-07-14"
    assert raid_week_label(datetime(2026, 7, 20, 22, 0, tzinfo=tz)) == "2026-07-14"


def test_baseline_survives_reposts(tmp_path, monkeypatch):
    from guild_board.state import baselines_view, load_board_state, save_board_state
    monkeypatch.chdir(tmp_path)
    path = str(tmp_path / "board_state.json")
    # week 1 final post
    save_board_state({"realm": 52}, [(3838, "Amrevenge", "BM")], streaks={},
                     records={}, path=path, streaks_week="2026-07-07")
    # week 2, first post: baseline rolls to week 1's finals
    save_board_state({"realm": 49}, [(3908, "Amrevenge", "BM")], streaks={},
                     records={}, path=path, streaks_week="2026-07-14")
    view = baselines_view(load_board_state(path))
    assert view["standing"] == {"realm": 52}
    assert view["season_scores"] == {"amrevenge": 3838}
    # week 2, REPOST: baseline must not move — deltas stay vs week 1
    save_board_state({"realm": 49}, [(3908, "Amrevenge", "BM")], streaks={},
                     records={}, path=path, streaks_week="2026-07-14")
    view = baselines_view(load_board_state(path))
    assert view["standing"] == {"realm": 52}          # ▲3 survives the repost
    assert view["season_scores"] == {"amrevenge": 3838}  # ▲70 survives the repost


def test_record_new_badge_survives_repost():
    from guild_board.state import update_records
    sweep = {"dps": {"name": "Amrevenge", "parse": 97, "boss": "Salhadaar",
                     "spec": "BM", "cls": "Hunter", "difficulty": 4}, "hps": None}
    baseline = {"best_dps_parse": {"name": "Old", "parse": 90}}
    first = update_records({}, {"best_dps": {}, "best_hps": {}}, None,
                           season_parses=sweep, baseline_records=baseline)
    assert first["best_dps_parse"]["new"] is True
    # repost: prev now holds the 97, but the badge is judged vs LAST WEEK
    again = update_records(first, {"best_dps": {}, "best_hps": {}}, None,
                           season_parses=sweep, baseline_records=baseline)
    assert again["best_dps_parse"]["new"] is True     # still this week's news


def test_integrity_flags_streak_inflation():
    from datetime import date
    from datetime import timedelta as td

    from guild_board import integrity
    state = {"streaks": {"amrevenge": 15},
             "streaks_started": (date.today() - td(days=14)).isoformat()}
    msgs = []
    integrity.check_streaks(state, msgs)
    assert any("inflation" in m for m in msgs)
    ok_state = {"streaks": {"amrevenge": 2},
                "streaks_started": (date.today() - td(days=21)).isoformat()}
    msgs2 = []
    integrity.check_streaks(ok_state, msgs2)
    assert msgs2 == []


def test_streaks_from_attendance_season_derivation():
    from guild_board.state import streaks_from_attendance
    scanned = {"2026-06-30", "2026-07-07", "2026-07-14"}
    # regular: attended all three -> 3; missed the middle -> 1
    att = {"amrevenge": {"2026-06-30", "2026-07-07", "2026-07-14"},
           "newguy": {"2026-07-14"},
           "flaky": {"2026-06-30", "2026-07-14"}}
    streaks, started = streaks_from_attendance(att, scanned, scanned)
    assert streaks == {"amrevenge": 3, "newguy": 1, "flaky": 1}
    assert started == "2026-06-30"
    # a guild-wide skipped week (no reports at all) is neutral, not a break
    skip_scanned = {"2026-06-30", "2026-07-14"}
    streaks2, _ = streaks_from_attendance(
        {"amrevenge": {"2026-06-30", "2026-07-14"}}, skip_scanned, skip_scanned)
    assert streaks2 == {"amrevenge": 2}
    # a raided-but-unscanned (trimmed) week stops the count honestly
    streaks3, _ = streaks_from_attendance(
        {"amrevenge": {"2026-06-30", "2026-07-14"}},
        {"2026-06-30", "2026-07-14"},
        {"2026-06-30", "2026-07-07", "2026-07-14"})
    assert streaks3 == {"amrevenge": 1}
    # absent from the latest raid week -> no current streak
    streaks4, _ = streaks_from_attendance(
        {"ghost": {"2026-06-30"}}, scanned, scanned)
    assert streaks4 == {}


def test_web_role_filter_uses_whole_words():
    """'Unholy' must never match the 'holy' healer keyword.

    The filter/search/archive JS lives in ONE shared partial that every
    web layout includes, so the check belongs there."""
    tpl = open("guild_board/templates/web/_interactive.html.j2", encoding="utf-8").read()
    assert "tokens.indexOf(w)" in tpl          # whole-word membership
    assert "tags.indexOf(w)" not in tpl        # the substring bug is gone


def test_every_web_layout_includes_the_interactive_partial():
    """A new layout must not silently ship without role filters, player
    search and the week archive — they come from the shared partial."""
    from pathlib import Path
    layouts = [p for p in Path("guild_board/templates/web").glob("*.html.j2")
               if not p.name.startswith("_")]
    assert layouts, "no web layouts found"
    for path in layouts:
        body = path.read_text(encoding="utf-8")
        assert "web/_interactive.html.j2" in body, f"{path.name} drops the interactive layer"
        # the DOM contract the partial drives
        assert 'id="filters"' in body and 'id="search"' in body, f"{path.name} misses filter hooks"
        assert "data-name=" in body and "data-tags=" in body, f"{path.name} misses row hooks"


def test_web_layout_resolution_fails_open():
    """A typo'd board.web_layout must degrade to the shipped poster
    layout, never to a blank or missing template."""
    from guild_board import theme as theme_mod
    assert theme_mod.resolve_templates(
        {"board": {"web_layout": "ember_terminal"}}
    )["web_layout_template"] == "web/ember_terminal.html.j2"
    for bad in ("no_such_layout", "", None):
        assert theme_mod.resolve_templates(
            {"board": {"web_layout": bad}}
        )["web_layout_template"] == "web/poster.html.j2"
    # absent key entirely -> still the default
    assert theme_mod.resolve_templates({})["web_layout_template"] == "web/poster.html.j2"


def test_resolve_modules_fails_open():
    """A theme can rotate modules in and out, and every bad value in the
    modules block degrades instead of breaking the page."""
    from guild_board import theme as theme_mod

    # no modules block at all -> the shipped set, in the shipped order
    default = theme_mod.resolve_modules({})
    assert default["order"] == ["roast", "debt", "graveyard", "item"]

    resolved = theme_mod.resolve_modules({"modules": {
        "order": ["graveyard", "nonsense", "roast", "motd"],
        "graveyard": {"style": "arch", "title": "THE PLOTS"},
        "roast": {"style": "not_a_real_style"},
        "debt": {"enabled": False},
        "item": {"art": "assets/definitely_missing_art.png"},
    }})
    # unknown key dropped; motd is not a panel; declared order respected
    assert resolved["order"] == ["graveyard", "roast"]
    # a disabled module is gone from the order entirely
    assert "debt" not in resolved["order"]
    assert resolved["by_key"]["debt"]["enabled"] is False
    # unknown frame style degrades to unframed rather than emitting junk
    assert resolved["by_key"]["roast"]["style"] == "none"
    assert resolved["by_key"]["graveyard"]["style"] == "arch"
    assert resolved["by_key"]["graveyard"]["title"] == "THE PLOTS"
    # missing art is cleared, not rendered as a broken background
    assert resolved["by_key"]["item"]["art"] is None
    # a non-list order falls back rather than raising
    assert theme_mod.resolve_modules({"modules": {"order": "roast"}})["order"]


def test_modules_honour_the_older_footer_switches():
    """Guilds that already set footer.debt.enabled / titles keep their
    settings without having to learn the new modules block."""
    from guild_board import theme as theme_mod
    resolved = theme_mod.resolve_modules({
        "footer": {"debt": {"enabled": False, "title": "Old Debt Title"},
                   "graveyard": {"title": "OLD GRAVEYARD"}},
    })
    assert resolved["by_key"]["debt"]["enabled"] is False
    assert resolved["by_key"]["graveyard"]["title"] == "OLD GRAVEYARD"


def test_retiring_a_module_removes_it_from_every_layout(tmp_path):
    """Turning a module off in theme.yml must actually drop it from the
    rendered page — on all four layouts."""
    from guild_board import html_board
    theme_file = tmp_path / "theme.yml"
    theme_file.write_text(
        "modules:\n"
        "  order: [roast]\n"
        "  debt: {enabled: false}\n"
        "  graveyard: {enabled: false}\n"
        "  motd: {enabled: false}\n",
        encoding="utf-8")
    cfg = _image_board_cfg()
    cfg["display"] = dict(cfg.get("display") or {}, theme_file=str(theme_file))
    now = datetime.now(timezone.utc)
    base = html_board.build_context(
        cfg, _image_board_stats(), {"realm": 49}, None, "Voidspire",
        None, None, None, now - timedelta(days=7), now)
    assert base["motd"] == ""
    for layout in ("poster", "chronicle", "ember_terminal", "codex"):
        ctx = dict(base, web_layout_template=f"web/{layout}.html.j2")
        page = html_board.render_html(ctx, template="web.html.j2").upper()
        assert "GAMBLING DEBT" not in page, f"{layout} still shows the retired debt card"
        # the graveyard MODULE's caption — "Graveyard Campers" alone also
        # appears as a most-deaths section title in the ranking data
        assert "PLOTS ASSIGNED BY" not in page, f"{layout} still shows the retired graveyard"
        assert "ROAST OF THE WEEK" in page, f"{layout} lost the module that stayed enabled"


def test_every_web_layout_renders_the_culture_slots():
    """The gambling debt, the graveyard, the roast and the MOTD are
    load-bearing guild culture — a layout may restyle them but must not
    quietly drop them."""
    from guild_board import html_board
    now = datetime.now(timezone.utc)
    base = html_board.build_context(
        _image_board_cfg(), _image_board_stats(), {"realm": 49}, None, "Voidspire",
        None, None, None, now - timedelta(days=7), now)
    from markupsafe import escape
    for layout in ("poster", "chronicle", "ember_terminal", "codex"):
        ctx = dict(base, web_layout_template=f"web/{layout}.html.j2")
        page = html_board.render_html(ctx, template="web.html.j2")
        upper = page.upper()
        # the quip rotates weekly, so compare the escaped form of whichever
        # one this week's index landed on
        assert str(escape(ctx["motd"])) in page, f"{layout} drops the MOTD"
        assert "ROAST OF THE WEEK" in upper, f"{layout} drops the roast"
        if layout != "poster":      # poster predates these two on the web
            assert "GAMBLING DEBT" in upper, f"{layout} drops the debt card"
            assert "GRAVEYARD" in upper, f"{layout} drops the graveyard"


# --- webhook delivery: multi-file + rate-limit retry ------------------------------


def test_webhook_multifile_and_429_retry(tmp_path, monkeypatch):
    """The post survives a 429 (retry once) and attaches board + mobile as
    files[0]/files[1] — the exact multipart shape Discord requires."""
    calls = []

    class Resp:
        def __init__(self, code):
            self.status_code = code
            self.text = ""
        def json(self):
            return {"retry_after": 0.01}
        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(response=self)

    monkeypatch.setattr(gb_discord.requests, "post",
                        lambda url, **kw: (calls.append((url, kw)), Resp(429 if len(calls) == 1 else 200))[1])
    monkeypatch.setattr(gb_discord.time, "sleep", lambda s: None)
    board = tmp_path / "board.gif"; board.write_bytes(b"gif")
    mobile = tmp_path / "mobile.png"; mobile.write_bytes(b"png")
    gb_discord.post_to_discord("https://discord.test/hook", {"title": "t"},
                               image_path=str(board), extra_image_paths=[str(mobile)])
    assert len(calls) == 2                                  # 429, then success
    url, kw = calls[1]
    assert set(kw["files"]) == {"files[0]", "files[1]"}     # both images attached
    assert kw["files"]["files[0]"][2] == "image/gif"        # mime follows extension
    assert "payload_json" in kw["data"]


def test_webhook_skips_missing_extra_files(monkeypatch):
    """A vanished mobile companion must not break the post."""
    seen = {}

    class Resp:
        status_code = 200
        text = ""
        def raise_for_status(self):
            pass

    monkeypatch.setattr(gb_discord.requests, "post",
                        lambda url, **kw: (seen.update(kw), Resp())[1])
    gb_discord.post_to_discord("https://discord.test/hook", {"title": "t"},
                               image_path="does_not_exist.png",
                               extra_image_paths=["also_missing.png"])
    assert "files" not in seen                              # clean JSON post instead
    assert seen["json"]["embeds"][0]["title"] == "t"


# --- theme plumbing: font URLs, merge semantics, custom module heights -------------


def test_font_css_url_respects_display_weights():
    from guild_board import theme as theme_mod
    # single-weight family (e.g. Rye): exactly the declared axis, no fake weights
    url = theme_mod.font_css_url({"fonts": {"display": "Rye", "display_weights": "400",
                                            "body": "Inter"}})
    assert "family=Rye:wght@400&" in url
    # empty weights -> plain family request (Google serves its default)
    url2 = theme_mod.font_css_url({"fonts": {"display": "Special Elite",
                                             "display_weights": "", "body": "Inter"}})
    assert "family=Special+Elite&" in url2 and ":wght@&" not in url2
    # defaults keep the shipped Cinzel axes
    assert "family=Cinzel:wght@700;900&" in theme_mod.font_css_url({})


def test_theme_deep_merge_replaces_lists_wholesale():
    from guild_board.theme import _deep_merge
    base = {"motd_quips": ["a", "b", "c"], "colors": {"accent": "#111", "red": "#e00"}}
    out = _deep_merge(base, {"motd_quips": ["only-me"], "colors": {"accent": "#222"}})
    assert out["motd_quips"] == ["only-me"]          # lists replace, never append
    assert out["colors"] == {"accent": "#222", "red": "#e00"}   # dicts merge key-wise
    assert base["motd_quips"] == ["a", "b", "c"]     # base is never mutated


def test_resolve_templates_honors_custom_heights():
    from guild_board import theme as theme_mod
    mods = theme_mod.resolve_templates({"board": {"header": "banner", "footer": "graveyard",
                                                  "header_height": 240, "footer_height": 500}})
    assert mods["header_h"] == 240                   # custom overrides the built-in map
    assert mods["footer_total"] == 500 + theme_mod.FOOTER_EXTRA
    defaults = theme_mod.resolve_templates({})
    assert defaults["header_h"] == theme_mod.HEADER_HEIGHTS["stone_torchlight"]


# --- ink-on-paper poster mode -----------------------------------------------------


def test_ink_darkens_screen_colors_for_paper():
    from guild_board.html_board import _ink
    # class colors keep their hue at ink weight
    assert _ink("rgb(171,212,115)") == "rgb(88,110,59)"      # hunter green -> ink green
    assert _ink("rgb(196,30,58)") == "rgb(101,15,30)"        # DK red -> deep maroon
    # whitish (Priest) becomes dark sepia, not washed gray
    assert _ink("rgb(255,255,255)") == "rgb(52,44,34)"
    assert _ink("rgb(235,236,240)") == "rgb(52,44,34)"
    # non-rgb strings pass through untouched
    assert _ink("#abc123") == "#abc123"
    assert _ink(None) is None


def test_poster_mode_renders_ink_names(tmp_path):
    from guild_board import html_board
    # must be a REAL file: the integrity asset guard heals missing poster
    # paths back to None (which would legitimately disable ink mode)
    theme_file = tmp_path / "theme.yml"
    theme_file.write_text(
        "backgrounds:\n  poster: 'assets/generated/wanted_parchment.png'\n",
        encoding="utf-8")
    cfg = _image_board_cfg()
    cfg["display"]["theme_file"] = str(theme_file)
    now = datetime.now(timezone.utc)
    ctx = html_board.build_context(
        cfg, _image_board_stats(), None, None, "Voidspire", None, None, None,
        now - timedelta(days=7), now)
    html = html_board.render_html(ctx)
    web = html_board.render_html(ctx, template="web.html.j2")
    # Rakell is a Shaman: screen rgb(0,112,222) must print as ink rgb(0,58,115)
    for surface in (html, web):
        assert "rgb(0,58,115)" in surface
    # and without a poster, the screen color is used verbatim
    cfg2 = _image_board_cfg()
    ctx2 = html_board.build_context(
        cfg2, _image_board_stats(), None, None, "Voidspire", None, None, None,
        now - timedelta(days=7), now)
    assert "rgb(0,112,222)" in html_board.render_html(ctx2)


def test_integrity_heals_missing_theme_assets():
    from guild_board import integrity
    theme = {"backgrounds": {
        "header": "assets/does_not_exist.png",      # heals to shipped default
        "middle": "assets/theme_art.png",           # exists — untouched
        "poster": "assets/generated/gone.png",      # no default — cleared
    }}
    msgs = []
    integrity.check_theme_assets(theme, msgs)
    assert theme["backgrounds"]["header"] == "assets/wall_header.png"
    assert theme["backgrounds"]["middle"] == "assets/theme_art.png"
    assert theme["backgrounds"]["poster"] is None
    assert len(msgs) == 2
    # clean theme produces zero noise
    ok = {"backgrounds": {"middle": "assets/theme_art.png"}}
    assert integrity.run_all(theme=ok) == []


def test_custom_board_template_module(tmp_path, monkeypatch):
    """board_templates/ modules are found first and render end-to-end —
    the guild-facing 'make your own header' feature from CUSTOMIZING.md."""
    from guild_board import html_board
    from guild_board import theme as theme_mod
    guild_dir = tmp_path / "board_templates"
    (guild_dir / "headers").mkdir(parents=True)
    (guild_dir / "headers" / "mine.html.j2").write_text(
        "<div class='hdr'>CUSTOM HEADER FOR {{ guild_name.upper() }}</div>",
        encoding="utf-8")
    monkeypatch.setattr(theme_mod, "GUILD_TEMPLATE_DIR", guild_dir)
    theme_file = tmp_path / "theme.yml"
    theme_file.write_text("board:\n  header: mine\n  header_height: 111\n",
                          encoding="utf-8")
    cfg = _image_board_cfg()
    cfg["display"]["theme_file"] = str(theme_file)
    now = datetime.now(timezone.utc)
    ctx = html_board.build_context(
        cfg, _image_board_stats(), None, None, "Voidspire", None, None, None,
        now - timedelta(days=7), now)
    assert ctx["header_template"] == "headers/mine.html.j2"
    assert ctx["header_h"] == 111                     # custom GIF band height honored
    html = html_board.render_html(ctx)
    assert "CUSTOM HEADER FOR TEST GUILD" in html     # guild module actually rendered
    assert "GIT GUD" not in html                      # built-in header fully replaced


def test_weekly_awards_fail_open(monkeypatch):
    """A crashing award builder is skipped, never sinks the board."""
    from guild_board import awards as awards_mod

    def boom(**_):
        raise RuntimeError("award exploded")

    def fine(**_):
        return [{"name": "Alba", "detail": "ok", "value": "1"}]

    monkeypatch.setattr(awards_mod, "AWARD_POOL",
                        [("WEEKLY AWARD · BOOM", boom), ("WEEKLY AWARD · FINE", fine)])
    secs = awards_mod.weekly_awards(0, per_week=2, streaks={"alba": 3})
    assert [s["title"] for s in secs] == ["WEEKLY AWARD · FINE"]
    assert secs[0]["rows"][0]["name"] == "Alba"

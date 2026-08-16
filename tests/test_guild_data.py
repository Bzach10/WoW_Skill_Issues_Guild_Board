"""Tests for the guild-level Blizzard fetch (achievements + activity) and
its flow into layers 3 & 4.

No network. These lock the two things the credentialed Action must deliver:
a populated trophy hall (layer 3) and authoritative per-boss raid kills
that upgrade island completion from inferred to confirmed (layer 4).
"""

from guild_board import blizzard, season, web_data

# The producers match achievements and raid progression against whatever
# season is CURRENT, so these fixtures are built from that season's own
# roster. Pinning them to S1 literals would turn the suite red the instant
# the season flips (2026-08-18T15:00Z) with nobody having touched code.
_BOSSES = season.boss_names()
BOSS_FIRST, BOSS_SECOND, BOSS_LAST = _BOSSES[0], _BOSSES[1], _BOSSES[-1]
RAID_SLUG = season.CURRENT_SEASON["raid"]["slug"]

GUILD_ACHIEVEMENTS = {
    "total_quantity": 1655,
    "achievements": [
        {"achievement": {"id": 15001, "name": f"Ahead of the Curve: {BOSS_FIRST}"},
         "completed_timestamp": 1_772_500_000_000,
         "criteria": {"is_completed": True, "child_criteria": [{}, {}]}},
        {"achievement": {"id": 15003, "name": BOSS_SECOND},
         "completed_timestamp": 1_773_000_000_000,
         "criteria": {"is_completed": True, "child_criteria": []}},
        {"achievement": {"id": 15010, "name": "Midnight Keystone Master: Season One"},
         "completed_timestamp": 1_775_000_000_000, "criteria": None},
    ],
}


# --- blizzard.py fetch layer

def test_fetch_guild_achievements_hits_correct_path(monkeypatch):
    seen = {}

    def fake_get(token, region, path, params):
        seen["path"] = path
        seen["namespace"] = params.get("namespace")
        return GUILD_ACHIEVEMENTS

    monkeypatch.setattr(blizzard, "_get", fake_get)
    out = blizzard.fetch_guild_achievements("tok", "us", "bleeding-hollow", "Skill Issues")
    assert out is GUILD_ACHIEVEMENTS
    assert seen["path"] == "/data/wow/guild/bleeding-hollow/skill-issues/achievements"
    # Guild endpoints live under /data/ but require the profile-{region} namespace.
    assert seen["namespace"] == "profile-us"


def test_fetch_guild_activity_hits_correct_path(monkeypatch):
    seen = {}
    monkeypatch.setattr(blizzard, "_get",
                        lambda t, r, path, p: seen.setdefault("path", path) or {"activities": []})
    blizzard.fetch_guild_activity("tok", "us", "bleeding-hollow", "Skill Issues")
    assert seen["path"] == "/data/wow/guild/bleeding-hollow/skill-issues/activity"


def test_guild_slug_matches_pipeline_slug_rule():
    assert blizzard._guild_slug("Skill Issues") == "skill-issues"
    assert blizzard._guild_slug("Kel'Thuzad's Chosen") == "kelthuzads-chosen"


def test_fetch_guild_fails_soft_to_none(monkeypatch):
    def boom(*a, **kw):
        raise blizzard.requests.ConnectionError("down")
    monkeypatch.setattr(blizzard, "_get", boom)
    assert blizzard.fetch_guild_achievements("t", "us", "r", "G") is None


# --- guild cache load/save/refresh

def test_guild_cache_round_trips(tmp_path):
    cfg = {"blizzard": {"guild_cache_file": str(tmp_path / "g.json")}}
    blizzard.save_guild_cache(cfg, {"achievements": GUILD_ACHIEVEMENTS, "activity": {"x": 1}})
    loaded, updated = blizzard.load_guild_cache(cfg)
    assert loaded["achievements"] == GUILD_ACHIEVEMENTS
    assert loaded["activity"] == {"x": 1}
    assert updated  # timestamp written


def test_load_guild_cache_missing_is_empty():
    loaded, updated = blizzard.load_guild_cache(
        {"blizzard": {"guild_cache_file": "does-not-exist.json"}})
    assert loaded == {} and updated is None


def test_refresh_guild_cache_gated_off_without_enable():
    out, changed = blizzard.refresh_guild_cache({"blizzard": {"enabled": False}})
    assert changed is False


def test_refresh_guild_cache_gated_off_without_secrets(monkeypatch):
    monkeypatch.delenv("BLIZZARD_CLIENT_ID", raising=False)
    monkeypatch.delenv("BLIZZARD_CLIENT_SECRET", raising=False)
    out, changed = blizzard.refresh_guild_cache({"blizzard": {"enabled": True}})
    assert changed is False


def test_refresh_guild_cache_writes_when_credentialed(tmp_path, monkeypatch):
    cfg = {"blizzard": {"enabled": True, "guild_cache_file": str(tmp_path / "g.json")},
           "guild": {"region": "us", "realm_slug": "bleeding-hollow", "name": "Skill Issues"}}
    monkeypatch.setenv("BLIZZARD_CLIENT_ID", "x")
    monkeypatch.setenv("BLIZZARD_CLIENT_SECRET", "y")
    monkeypatch.setattr(blizzard, "get_blizzard_token", lambda a, b: "tok")
    monkeypatch.setattr(blizzard, "fetch_guild_data",
                        lambda *a, **kw: {"achievements": GUILD_ACHIEVEMENTS, "activity": None})
    out, changed = blizzard.refresh_guild_cache(cfg, max_age_days=0)
    assert changed is True
    assert out["achievements"] == GUILD_ACHIEVEMENTS


def test_refresh_guild_cache_keeps_old_on_empty_response(tmp_path, monkeypatch):
    """A transient empty response must not blank a good cache."""
    cfg = {"blizzard": {"enabled": True, "guild_cache_file": str(tmp_path / "g.json")},
           "guild": {"region": "us", "realm_slug": "bh", "name": "G"}}
    blizzard.save_guild_cache(cfg, {"achievements": GUILD_ACHIEVEMENTS, "activity": None})
    monkeypatch.setenv("BLIZZARD_CLIENT_ID", "x")
    monkeypatch.setenv("BLIZZARD_CLIENT_SECRET", "y")
    monkeypatch.setattr(blizzard, "get_blizzard_token", lambda a, b: "tok")
    monkeypatch.setattr(blizzard, "fetch_guild_data",
                        lambda *a, **kw: {"achievements": None, "activity": None})
    out, changed = blizzard.refresh_guild_cache(cfg, max_age_days=0)
    assert changed is False
    assert out["achievements"] == GUILD_ACHIEVEMENTS  # preserved


# --- layer 4 upgrade: inferred -> confirmed

def test_extract_raid_boss_kills_matches_by_name():
    kills = web_data.extract_raid_boss_kills(GUILD_ACHIEVEMENTS)
    # Both bosses named in achievements are found with their kill dates.
    assert BOSS_FIRST in kills
    assert BOSS_SECOND in kills
    assert kills[BOSS_FIRST].startswith("20")
    # A boss with no matching achievement is absent (not falsely confirmed).
    assert BOSS_LAST not in kills


def test_island_completion_upgrades_to_guild_achievements():
    kills = web_data.extract_raid_boss_kills(GUILD_ACHIEVEMENTS)
    ic = web_data.build_island_completion(
        raid_progression={RAID_SLUG: {"summary": f"3/{len(_BOSSES)} M",
                                      "mythic_bosses_killed": 3}},
        confirmed_boss_kills=kills)
    assert ic["raid"]["detail_source"] == "guild_achievements"
    by_name = {b["name"]: b for b in ic["raid"]["islands"]}
    # Confirmed with a real first-kill date, not inferred.
    imp = by_name[BOSS_FIRST]
    assert imp["kill_confirmed"] is True
    assert imp["inferred_from_progress"] is False
    assert imp["first_kill_at"].startswith("20")
    # A boss NOT in achievements is locked, not inferred, once we have
    # the authoritative list.
    assert by_name[BOSS_LAST]["status"] == "locked"


def test_island_completion_falls_back_to_inferred_without_achievements():
    ic = web_data.build_island_completion(
        raid_progression={RAID_SLUG: {"mythic_bosses_killed": 3, "heroic_bosses_killed": 5}})
    assert ic["raid"]["detail_source"] == "raid_progression_count"
    by_name = {b["name"]: b for b in ic["raid"]["islands"]}
    assert by_name[BOSS_SECOND]["inferred_from_progress"] is True


def test_build_site_data_threads_achievements_into_both_layers():
    site = web_data.build_site_data(guild_achievements=GUILD_ACHIEVEMENTS)
    assert site["guild_achievements"]["available"] is True
    assert site["guild_achievements"]["trophy_count"] == 3
    assert site["island_completion"]["raid"]["detail_source"] == "guild_achievements"
    # Pinned to S1 explicitly: GUILD_ACHIEVEMENTS above is S1 data, so this
    # asserts the roster that fixture belongs to, not whichever season the
    # clock happens to resolve to.
    assert season.SEASON_MN_1["raid"]["bosses"][0]["name"] == "Imperator Averzian"

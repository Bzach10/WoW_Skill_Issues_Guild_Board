"""Season identity resolves itself from the clock.

The point of these tests is that nobody has to remember 2026-08-18. The
module is asked what season it is at a given instant and answers from the
authored data; these pin both sides of that instant, the CI/dispatch
override, and the S2 content that was verified live against raider.io on
2026-08-16 (see the module docstring for the endpoints).
"""

import importlib
from datetime import datetime, timezone

import pytest

from guild_board import season as season_mod

# The instant raider.io ends season-mn-1 (us) and starts season-mn-2.
FLIP = "2026-08-18T15:00:00Z"


# ---------------------------------------------------------------------------
# the flip — both sides of the date
# ---------------------------------------------------------------------------

def test_before_the_flip_is_season_one():
    # The owner said "we're in season 2" on 2026-08-16. Raider.io disagreed
    # by two days, and the board follows raider.io, not the announcement.
    assert season_mod.season_for("2026-08-16T00:00:00Z")["slug"] == "season-mn-1"
    assert season_mod.season_for("2026-08-18T14:59:59Z")["slug"] == "season-mn-1"


def test_at_and_after_the_flip_is_season_two():
    assert season_mod.season_for(FLIP)["slug"] == "season-mn-2"
    assert season_mod.season_for("2026-08-18T15:00:01Z")["slug"] == "season-mn-2"
    assert season_mod.season_for("2027-01-01T00:00:00Z")["slug"] == "season-mn-2"


def test_the_seasons_abut_exactly_so_nothing_straddles():
    # S1's end and S2's start are the same instant: no gap where the board
    # has no season, no overlap where it has two.
    assert season_mod.SEASON_MN_1["ends_utc"] == season_mod.SEASON_MN_2["starts_utc"]
    assert season_mod.SEASON_MN_2["starts_utc"] == FLIP


def test_season_for_accepts_datetimes_naive_and_aware():
    aware = datetime(2026, 8, 18, 15, 0, tzinfo=timezone.utc)
    naive = datetime(2026, 8, 18, 15, 0)
    assert season_mod.season_for(aware)["slug"] == "season-mn-2"
    assert season_mod.season_for(naive)["slug"] == "season-mn-2"


def test_before_any_season_falls_back_to_the_earliest():
    assert season_mod.season_for("2020-01-01T00:00:00Z")["slug"] == "season-mn-1"


# ---------------------------------------------------------------------------
# the override — CI/dispatch pins, and refuses a typo
# ---------------------------------------------------------------------------

def test_env_override_pins_the_season(monkeypatch):
    monkeypatch.setenv(season_mod.SEASON_SLUG_ENV, "season-mn-1")
    assert season_mod._resolve_current()["slug"] == "season-mn-1"
    monkeypatch.setenv(season_mod.SEASON_SLUG_ENV, "season-mn-2")
    assert season_mod._resolve_current()["slug"] == "season-mn-2"


def test_unknown_override_raises_rather_than_falling_back(monkeypatch):
    monkeypatch.setenv(season_mod.SEASON_SLUG_ENV, "season-mn-9")
    with pytest.raises(ValueError, match="season-mn-9"):
        season_mod._resolve_current()


def test_blank_override_is_ignored(monkeypatch):
    monkeypatch.setenv(season_mod.SEASON_SLUG_ENV, "   ")
    assert season_mod._resolve_current() is season_mod.season_for()


def test_the_override_reaches_module_level_current_season(monkeypatch):
    """The pin has to survive `import season; season.CURRENT_SEASON` — that
    is the only shape every consumer uses."""
    monkeypatch.setenv(season_mod.SEASON_SLUG_ENV, "season-mn-2")
    try:
        reloaded = importlib.reload(season_mod)
        assert reloaded.CURRENT_SEASON["slug"] == "season-mn-2"
        assert reloaded.CURRENT_SEASON_SLUG == "season-mn-2"
        # S2 is the last season on the books, so there is no successor yet.
        assert reloaded.NEXT_SEASON is None
        assert reloaded.NEXT_SEASON_SLUG is None
    finally:
        monkeypatch.delenv(season_mod.SEASON_SLUG_ENV, raising=False)
        importlib.reload(season_mod)


# ---------------------------------------------------------------------------
# the module-level values every consumer reads
# ---------------------------------------------------------------------------

def test_current_season_is_resolved_not_hand_edited():
    assert season_mod.CURRENT_SEASON in season_mod.SEASONS
    assert season_mod.CURRENT_SEASON is season_mod.season_for()
    assert season_mod.CURRENT_SEASON_SLUG == season_mod.CURRENT_SEASON["slug"]


def test_next_season_follows_current():
    assert season_mod.next_season_after(season_mod.SEASON_MN_1) is season_mod.SEASON_MN_2
    assert season_mod.next_season_after(season_mod.SEASON_MN_2) is None


def test_seasons_are_ordered_by_start():
    starts = [season_mod._parse_utc(s["starts_utc"]) for s in season_mod.SEASONS]
    assert starts == sorted(starts)


def test_season_by_slug():
    assert season_mod.season_by_slug("season-mn-2") is season_mod.SEASON_MN_2
    assert season_mod.season_by_slug("nope") is None


# ---------------------------------------------------------------------------
# S2 content — verified live 2026-08-16, pinned here so drift is loud
# ---------------------------------------------------------------------------

def test_season_two_raid_matches_live_static_data():
    raid = season_mod.SEASON_MN_2["raid"]
    assert raid["slug"] == "the-venomous-abyss"
    assert raid["raid_id"] == 16915
    assert raid["starts_utc"] == FLIP
    assert [b["slug"] for b in raid["bosses"]] == [
        "nekzali-the-soulcoiler", "entombed-sentinels", "the-lost-explorers",
        "vashnik-the-malignant", "sszorak", "the-twin-fangs",
        "the-coiled-altar", "ulatek"]
    assert [b["order"] for b in raid["bosses"]] == list(range(1, 9))


def test_season_two_boss_seven_is_the_coiled_altar():
    """Regression pin. The pre-authored draft named this boss "Zul'jan";
    raider.io says The Coiled Altar (encounter 197169). The parse sweep
    resolves WCL zones by boss NAME, so a wrong name is a failed match,
    not a cosmetic typo."""
    seventh = season_mod.SEASON_MN_2["raid"]["bosses"][6]
    assert seventh["name"] == "The Coiled Altar"
    assert seventh["slug"] == "the-coiled-altar"


def test_season_two_dungeon_pool_is_a_full_swap():
    s1 = {d["slug"] for d in season_mod.SEASON_MN_1["dungeons"]}
    s2 = {d["slug"] for d in season_mod.SEASON_MN_2["dungeons"]}
    assert len(s1) == len(s2) == 8
    assert s1 & s2 == set()


def test_season_two_has_its_bonus_raid():
    """refresh_parses tolerates an absent extra_raids by doing nothing at
    all — silently. The Tidebound Grotto is confirmed live (raid 16671,
    starting at the same instant Sporefall ends), so the sweep must cover
    it rather than quietly skipping a raid the guild is running."""
    extras = {r["slug"]: r for r in season_mod.SEASON_MN_2["extra_raids"]}
    assert extras["the-tidebound-grotto"]["raid_id"] == 16671
    assert extras["the-tidebound-grotto"]["bosses"][0]["name"] == "Nymrissa Wavecaller"


def test_every_season_carries_the_shape_consumers_index_into():
    # web_data/competition/build_site_data index these keys without .get().
    for entry in season_mod.SEASONS:
        assert entry["dungeons"] and entry["raid"]["bosses"]
        assert entry["raid"]["display_name"]
        assert set(season_mod.dungeon_names(entry)) == {
            d["name"] for d in entry["dungeons"]}
        assert season_mod.boss_names(entry)[0] == entry["raid"]["bosses"][0]["name"]

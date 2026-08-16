"""Guard the committed samples/ bundle against drift.

The front-end builds against samples/*.sample.json without running the
backend, so those files must (a) stay valid JSON, (b) match the current
SCHEMA_VERSION, and (c) still be regenerable from the current producers.
If someone changes a producer shape without regenerating the sample, this
fails and points them at scripts/build_sample_site_data.py.
"""

import importlib.util
import json
from pathlib import Path

import pytest

from guild_board import web_data

REPO = Path(__file__).resolve().parents[1]
SAMPLES = REPO / "samples"
LAYERS = ("recap_ribbon", "records_leaderboard", "weekly_board",
          "guild_achievements",
          "island_completion", "transmog_changes", "guild_pulse", "competition",
          "parses")


def _load(name):
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))


def test_sample_bundle_exists():
    assert (SAMPLES / "site_data.sample.json").exists(), (
        "run scripts/build_sample_site_data.py")


def test_sample_envelope_has_all_layers_at_current_schema():
    site = _load("site_data.sample.json")
    assert site["_sample"] is True
    assert site["schema_version"] == web_data.SCHEMA_VERSION
    for layer in LAYERS:
        assert layer in site
        assert site[layer]["schema_version"] == web_data.SCHEMA_VERSION


@pytest.mark.parametrize("layer", LAYERS)
def test_each_per_layer_sample_matches_the_envelope(layer):
    site = _load("site_data.sample.json")
    standalone = _load(f"{layer}.sample.json")
    # The standalone file adds a _sample flag; otherwise it must equal the
    # embedded layer, so the front-end can fetch either and get the same data.
    standalone.pop("_sample", None)
    # generated_at is a timestamp set per call; ignore it in the comparison.
    a, b = dict(standalone), dict(site[layer])
    a.pop("generated_at", None)
    b.pop("generated_at", None)
    assert a == b


def test_sample_is_regenerable_from_current_producers():
    """Re-run the generator in-process and confirm the committed sample still
    matches (ignoring timestamps). Catches a producer change that was not
    reflected back into the committed bundle."""
    spec = importlib.util.spec_from_file_location(
        "gen", REPO / "scripts" / "build_sample_site_data.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)

    fresh = web_data.build_site_data(
        board_state=gen.BOARD_STATE, manifest=gen.MANIFEST,
        dungeon_bests=gen.DUNGEON_BESTS, raid_progression=gen.RAID_PROGRESSION,
        guild_achievements=gen.GUILD_ACHIEVEMENTS,
        transmog_snapshot=gen.TRANSMOG_SNAPSHOT, pulse_items=gen.PULSE_ITEMS,
        competition_fetched=gen.COMPETITION_FETCHED,
        parses_fetched=gen.PARSES_FETCHED,
        difficulty_scale=gen.PARSES_DIFFICULTY_SCALE,
        # The same pin the generator uses. Without it this rebuilds the S1
        # fixtures against whatever season the clock resolves to, and goes
        # red on the rollover date with nobody having touched the code.
        season=gen.SAMPLE_SEASON)
    committed = _load("site_data.sample.json")

    for layer in LAYERS:
        f, c = dict(fresh[layer]), dict(committed[layer])
        f.pop("generated_at", None)
        c.pop("generated_at", None)
        # snapshot bookkeeping in transmog is deterministic; keep it in the compare
        assert f == c, (f"samples/{layer}.sample.json is stale — "
                        f"run scripts/build_sample_site_data.py")


def test_sample_exercises_populated_states():
    """The whole point of the sample is to show non-empty UI states."""
    site = _load("site_data.sample.json")
    assert site["guild_achievements"]["available"] is True
    assert site["guild_achievements"]["trophy_count"] >= 1
    assert site["island_completion"]["dungeons"]["conquered"] >= 1
    statuses = {i["status"] for i in site["island_completion"]["dungeons"]["islands"]}
    assert {"conquered", "attempted", "locked"} <= statuses  # all three shown
    assert site["transmog_changes"]["changed_count"] >= 1
    assert site["records_leaderboard"]["ladder"]
    assert site["guild_pulse"]["available"] is True
    assert site["guild_pulse"]["item_count"] >= 1
    # The pulse sample must never leak a numeric user id.
    assert "999" not in repr(site["guild_pulse"]["items"])
    comp = site["competition"]
    assert comp["available"] is True
    assert comp["character_count"] >= 5
    assert comp["rankings"]["top5"][0]["rank"] == 1
    # All three role buckets present and healers actually bucketed.
    assert comp["rankings"]["by_role"]["Healer"]
    # Parses populated and merged into competition by full name-realm key.
    parses = site["parses"]
    assert parses["available"] is True
    assert parses["character_count"] >= 1
    assert all("-" in key for key in parses["characters"])  # never bare names
    merged = {c["key"]: c for c in comp["characters"]}
    for key in parses["characters"]:
        assert merged[key]["parse"]["source"] == "wcl_zone_rankings"
        assert merged[key]["parse"]["best"] == parses["characters"][key]["best_perf_avg"]

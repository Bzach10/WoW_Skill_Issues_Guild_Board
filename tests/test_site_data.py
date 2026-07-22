"""The web-data contract consumer (site_data.py)."""

import json

from guild_board import site_data


def _write(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_live_layer_wins_over_sample(tmp_path):
    live = tmp_path / "web_data"
    samp = tmp_path / "samples"
    live.mkdir()
    samp.mkdir()
    _write(live / "guild_achievements.json",
           {"schema_version": 1, "available": True, "total_points": 999})
    _write(samp / "guild_achievements.sample.json",
           {"schema_version": 1, "_sample": True, "total_points": 1})
    got = site_data.layer("guild_achievements", live_dir=live, sample_dir=samp)
    assert got["total_points"] == 999
    assert got["_from_sample"] is False


def test_falls_back_to_sample_and_flags_it(tmp_path):
    live = tmp_path / "web_data"
    samp = tmp_path / "samples"
    samp.mkdir()
    _write(samp / "recap_ribbon.sample.json",
           {"schema_version": 1, "_sample": True, "beats": []})
    got = site_data.layer("recap_ribbon", live_dir=live, sample_dir=samp)
    assert got is not None and got["_from_sample"] is True


def test_wrong_schema_version_is_refused(tmp_path):
    samp = tmp_path / "samples"
    samp.mkdir()
    _write(samp / "island_completion.sample.json",
           {"schema_version": 999, "dungeons": {}})
    assert site_data.layer("island_completion",
                           live_dir=tmp_path / "none", sample_dir=samp) is None


def test_absent_layer_is_none_not_an_error(tmp_path):
    assert site_data.layer("transmog_changes",
                           live_dir=tmp_path / "a", sample_dir=tmp_path / "b") is None


def test_unknown_layer_name_raises():
    try:
        site_data.layer("not_a_layer")
    except ValueError:
        return
    raise AssertionError("expected ValueError for an unknown layer")

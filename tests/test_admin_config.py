"""The local admin panel's config round-trip.

The panel is a LOCAL tool; these pin that it edits only its own keys and
never corrupts the rest of config.yml."""
import yaml
from guild_board import admin_config


def _write(tmp_path, data):
    p = tmp_path / "config.yml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(p)


def test_save_preserves_unrelated_keys(tmp_path):
    path = _write(tmp_path, {"guild": {"name": "Skill Issues", "region": "us"},
                             "raid": {"difficulty": "mythic"}})
    admin_config.save({"theme": "console", "scrim": 90}, path)
    cfg = yaml.safe_load(open(path, encoding="utf-8"))
    assert cfg["guild"]["name"] == "Skill Issues"      # untouched
    assert cfg["raid"]["difficulty"] == "mythic"       # untouched
    assert cfg["crew"]["default_theme"] == "console"
    assert cfg["panel"]["scrim"] == 90


def test_bad_values_are_rejected_not_written(tmp_path):
    path = _write(tmp_path, {})
    admin_config.save({"theme": "not-a-theme", "scrim": 5000,
                       "sections": ["bogus"], "hidden": ["nope"]}, path)
    cfg = yaml.safe_load(open(path, encoding="utf-8"))
    assert (cfg.get("crew") or {}).get("default_theme") is None   # bad theme skipped
    assert (cfg.get("panel") or {}).get("scrim") is None          # out-of-range skipped
    assert (cfg.get("panel") or {}).get("hidden") == []           # unknown section dropped


def test_rotation_round_trips(tmp_path):
    path = _write(tmp_path, {})
    admin_config.save({"rotation": {7: "silvermoon_city", 99: "bad"}}, path)
    cfg = yaml.safe_load(open(path, encoding="utf-8"))
    assert cfg["scenery"]["rotation"][7] == "silvermoon_city"
    assert 99 not in cfg["scenery"]["rotation"]


def test_current_settings_has_defaults():
    s = admin_config.current_settings({})
    assert s["theme"] == "codex"
    assert s["scrim"] == 93
    assert s["sections"] == admin_config.SECTIONS

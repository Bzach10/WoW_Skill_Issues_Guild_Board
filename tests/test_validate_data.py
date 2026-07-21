"""Offline tests for scripts/validate_data.py.

No network: the --live cross-check is exercised with a stubbed requests
module. These assert the validator actually *fails* on the defect classes
it was written for — a validator that always passes is worse than none.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "validate_data", REPO_ROOT / "scripts" / "validate_data.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validate_data = _load_validator()


@pytest.fixture
def report():
    return validate_data.Report(quiet=True)


def _write_manifest(tmp_path, characters, active="one_piece",
                    available=("one_piece",)):
    path = tmp_path / "cast_manifest.json"
    path.write_text(json.dumps({
        "active_style": active,
        "styles_available": list(available),
        "characters": characters,
    }), encoding="utf-8")
    return str(path)


def _character(**overrides):
    base = {
        "name": "Rakdisc", "realm": "proudmoore", "race": "Nightborne",
        "class": "Priest", "spec": "Discipline", "gender": "Female",
        "role": "healer", "render_url": "https://example.com/a-main-raw.png",
        "transmog_fingerprint": "deadbeef", "history": [],
        "styles": {},
    }
    base.update(overrides)
    return base


# --- roster checks

def test_roster_check_flags_hyphen_in_character_name(report, monkeypatch):
    """The signature of the rsplit bug: a hyphen ends up in the name."""
    monkeypatch.setattr(validate_data, "load_roster_cache",
                        lambda cfg: (["dathar-area-52"], "now"))
    # Simulate the broken splitter to prove the check catches it.
    monkeypatch.setattr(validate_data, "split_name_realm",
                        lambda e, default_realm=None: tuple(e.rsplit("-", 1)))
    validate_data.check_roster({}, report)
    assert any("wrong hyphen" in msg for _, msg in report.errors)


def test_roster_check_passes_on_correct_split(report, monkeypatch):
    monkeypatch.setattr(validate_data, "load_roster_cache",
                        lambda cfg: (["dathar-area-52", "aiime-bleeding-hollow"], "now"))
    validate_data.check_roster({}, report)
    assert report.errors == []


# --- manifest checks

def test_manifest_check_flags_missing_image(tmp_path, report):
    path = _write_manifest(tmp_path, {"rakdisc-proudmoore": _character(
        styles={"one_piece": {"board": "cast/nope/board.png", "version": 1,
                              "generated_at": "now", "forms": {}}})})
    validate_data.check_manifest(report, manifest_path=path)
    assert any("missing file" in msg for _, msg in report.errors)


def test_manifest_check_resolves_paths_against_the_manifest_dir(tmp_path, report):
    """Paths are repo-relative; resolving them against cwd or the script
    location reported every image missing from a git worktree."""
    board = tmp_path / "cast" / "rak" / "board.png"
    board.parent.mkdir(parents=True)
    board.write_bytes(b"png")
    path = _write_manifest(tmp_path, {"rakdisc-proudmoore": _character(
        styles={"one_piece": {"board": "cast/rak/board.png", "version": 1,
                              "generated_at": "now", "forms": {}}})})
    validate_data.check_manifest(report, manifest_path=path)
    assert report.errors == []


def test_manifest_check_flags_missing_required_field(tmp_path, report):
    char = _character()
    del char["role"]
    path = _write_manifest(tmp_path, {"rakdisc-proudmoore": char})
    validate_data.check_manifest(report, manifest_path=path)
    assert any("missing required field 'role'" in msg for _, msg in report.errors)


def test_manifest_check_flags_active_style_with_no_art(tmp_path, report):
    path = _write_manifest(tmp_path, {"rakdisc-proudmoore": _character()},
                           active="ghibli", available=("one_piece",))
    validate_data.check_manifest(report, manifest_path=path)
    assert any("not in styles_available" in msg for _, msg in report.errors)


def test_manifest_check_warns_on_empty_render_url(tmp_path, report):
    path = _write_manifest(tmp_path, {"floofwall-queldorei": _character(render_url="")})
    validate_data.check_manifest(report, manifest_path=path)
    assert any("empty render_url" in msg for _, msg in report.warnings)
    assert report.errors == []  # a warning, not a failure


# --- live cross-check

class _FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def _stub_requests(monkeypatch, response):
    import types
    fake = types.SimpleNamespace(
        get=lambda *a, **kw: response,
        RequestException=Exception)
    monkeypatch.setitem(sys.modules, "requests", fake)


def test_live_check_flags_spec_drift(report, monkeypatch):
    """The real finding this was built on: a character respecced and the
    local manifest went stale."""
    _stub_requests(monkeypatch, _FakeResponse(200, {
        "race": "Dracthyr", "class": "Evoker",
        "active_spec_name": "Preservation", "gender": "male"}))
    manifest = {"characters": {"healyeah-queldorei": _character(
        name="Healyeah", realm="queldorei", race="Dracthyr",
        spec="Augmentation", gender="Male", **{"class": "Evoker"})}}
    monkeypatch.setattr(validate_data.time, "sleep", lambda s: None)
    validate_data.check_live(manifest, {"guild": {"region": "us"}}, report)
    assert any("spec is 'Augmentation' locally but 'Preservation'" in msg
               for _, msg in report.errors)


def test_live_check_flags_deleted_character(report, monkeypatch):
    _stub_requests(monkeypatch, _FakeResponse(404))
    manifest = {"characters": {"gone-proudmoore": _character()}}
    monkeypatch.setattr(validate_data.time, "sleep", lambda s: None)
    validate_data.check_live(manifest, {"guild": {"region": "us"}}, report)
    assert any("HTTP 404" in msg for _, msg in report.errors)


def test_live_check_is_silent_when_everything_matches(report, monkeypatch):
    _stub_requests(monkeypatch, _FakeResponse(200, {
        "race": "Nightborne", "class": "Priest",
        "active_spec_name": "Discipline", "gender": "female"}))
    manifest = {"characters": {"rakdisc-proudmoore": _character()}}
    monkeypatch.setattr(validate_data.time, "sleep", lambda s: None)
    validate_data.check_live(manifest, {"guild": {"region": "us"}}, report)
    assert report.errors == []


# --- exit contract

def test_report_exit_code_is_zero_for_warnings_only(report):
    report.warn("x", "just a warning")
    assert report.dump() == 0


def test_report_exit_code_is_one_for_errors(report):
    report.error("x", "a real problem")
    assert report.dump() == 1

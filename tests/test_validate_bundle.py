"""scripts/validate_bundle.py: the cross-layer bundle gate.

Fixtures are the committed sample bundle (samples/*.sample.json), which the
lockstep guard already keeps identical to what the real producers emit -- so
a pass here is a pass on real producer output, and every failure case is an
injected copy of the real 2026-07-23 defect class.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from validate_bundle import LAYERS, validate_bundle  # noqa: E402

SAMPLES = os.path.join(ROOT, "samples")


def _stage(tmp_path):
    """Copy the sample bundle into tmp_path under production names."""
    for name in LAYERS + ("site_data",):
        with open(os.path.join(SAMPLES, f"{name}.sample.json"),
                  encoding="utf-8") as f:
            obj = json.load(f)
        with open(os.path.join(tmp_path, f"{name}.json"), "w",
                  encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
    return str(tmp_path)


def _rewrite(tmp_path, name, mutate):
    path = os.path.join(tmp_path, f"{name}.json")
    with open(path, encoding="utf-8") as f:
        obj = json.load(f)
    mutate(obj)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def _sections(report):
    return {section for section, _ in report.errors}


def test_sample_bundle_passes(tmp_path):
    report = validate_bundle(_stage(tmp_path))
    assert not report.errors, report.errors


def test_missing_layer_is_presence_error(tmp_path):
    d = _stage(tmp_path)
    os.remove(os.path.join(d, "recap_ribbon.json"))
    assert "presence" in _sections(validate_bundle(d))


def test_partial_copy_is_parity_error(tmp_path):
    # The 2026-07-23 failure: one standalone layer from a different build
    # than the site_data envelope.
    d = _stage(tmp_path)
    _rewrite(d, "competition", lambda c: c.update(ranked_count=(c.get("ranked_count") or 0) + 1))
    assert "parity" in _sections(validate_bundle(d))


def test_score_drift_is_competition_error(tmp_path):
    d = _stage(tmp_path)

    def drift(comp):
        comp["rankings"]["overall"][0]["score"] = 9999.9

    _rewrite(d, "competition", drift)
    _rewrite(d, "site_data", lambda s: drift(s["competition"]))
    assert "competition" in _sections(validate_bundle(d))


def test_stale_climber_is_weekly_error(tmp_path):
    # The exact recap defect: a biggest_climber beat contradicting the
    # ladder's own delta_week column.
    d = _stage(tmp_path)

    def stale(recap):
        recap["beats"].append({
            "kind": "biggest_climber", "headline": "+18.6 score",
            "detail": "Somebodyelse climbed the most this week",
            "subject": "Somebodyelse", "value": 18.6,
            "emphasis": "normal", "is_new": False})
        recap["beat_count"] = len(recap["beats"])

    _rewrite(d, "recap_ribbon", stale)
    _rewrite(d, "site_data", lambda s: stale(s["recap_ribbon"]))
    assert "weekly" in _sections(validate_bundle(d))


def test_split_weekly_stamps_is_stamps_error(tmp_path):
    d = _stage(tmp_path)
    _rewrite(d, "recap_ribbon",
             lambda r: r.update(based_on="1999-01-01T00:00:00+00:00"))
    _rewrite(d, "site_data",
             lambda s: s["recap_ribbon"].update(based_on="1999-01-01T00:00:00+00:00"))
    assert "stamps" in _sections(validate_bundle(d))


def test_weekly_board_stamp_must_match_other_weekly_layers(tmp_path):
    d = _stage(tmp_path)
    old = "1999-01-01T00:00:00+00:00"
    _rewrite(d, "weekly_board", lambda w: w.update(based_on=old))
    _rewrite(d, "site_data",
             lambda s: s["weekly_board"].update(based_on=old))
    assert "stamps" in _sections(validate_bundle(d))


def test_mixed_vintage_is_coherence_error(tmp_path):
    d = _stage(tmp_path)
    old = "1999-01-01T00:00:00+00:00"
    _rewrite(d, "competition", lambda c: c.update(based_on=old))
    _rewrite(d, "site_data",
             lambda s: s["competition"].update(based_on=old))
    assert "coherence" in _sections(validate_bundle(d))


@pytest.mark.parametrize(
    ("target", "seconds", "is_error"),
    [
        ("site_data", 1800, False),
        ("site_data", 1801, True),
        ("competition", 1801, True),
        ("island_completion", 1801, True),
        ("records_leaderboard", 1801, True),
        ("parses", 1801, True),
    ],
)
def test_coherence_window_boundaries_across_stamped_layers(
        tmp_path, target, seconds, is_error):
    d = _stage(tmp_path)
    base = datetime(2026, 8, 5, tzinfo=timezone.utc)
    base_stamp = base.isoformat()
    later = (base + timedelta(seconds=seconds)).isoformat()

    _rewrite(d, "site_data", lambda s: s.update(generated_at=base_stamp))
    for layer in ("island_completion", "records_leaderboard", "parses"):
        _rewrite(d, layer, lambda obj: obj.update(generated_at=base_stamp))
        _rewrite(d, "site_data",
                 lambda s, name=layer: s[name].update(generated_at=base_stamp))
    _rewrite(d, "competition", lambda c: c.update(based_on=base_stamp))
    _rewrite(d, "site_data",
             lambda s: s["competition"].update(based_on=base_stamp))

    if target == "site_data":
        _rewrite(d, "site_data", lambda s: s.update(generated_at=later))
    elif target == "competition":
        _rewrite(d, target, lambda obj: obj.update(based_on=later))
        _rewrite(d, "site_data",
                 lambda s: s[target].update(based_on=later))
    else:
        _rewrite(d, target, lambda obj: obj.update(generated_at=later))
        _rewrite(d, "site_data",
                 lambda s: s[target].update(generated_at=later))

    sections = _sections(validate_bundle(d))
    assert ("coherence" in sections) is is_error


def test_gate_runs_standalone_without_pytest(tmp_path):
    # The script form is what the daily workflow calls; it must work with
    # nothing but the stdlib.
    import subprocess
    d = _stage(tmp_path)
    proc = subprocess.run([sys.executable,
                           os.path.join(ROOT, "scripts", "validate_bundle.py"), d],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "bundle ok" in proc.stdout


if __name__ == "__main__":
    # Mirror the credentials gate: runnable without pytest installed.
    raise SystemExit(pytest.main([__file__, "-q"]))

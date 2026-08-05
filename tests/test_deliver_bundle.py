"""Atomic consumer delivery regressions."""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from deliver_bundle import deliver  # noqa: E402
from validate_bundle import LAYERS  # noqa: E402


def _stage_samples(path):
    path.mkdir()
    for name in (*LAYERS, "site_data"):
        shutil.copy2(ROOT / "samples" / f"{name}.sample.json",
                     path / f"{name}.json")


def test_absent_optional_sidecar_removes_stale_consumer_copy(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "consumer"
    _stage_samples(source)
    destination.mkdir()
    (source / "weekly_board.json").unlink()
    (destination / "weekly_board.json").write_text(
        '{"week_label":"last-week"}', encoding="utf-8")

    assert deliver(str(source), str(destination)) == 0
    assert not (destination / "weekly_board.json").exists()
    assert (destination / "DELIVERY.json").exists()

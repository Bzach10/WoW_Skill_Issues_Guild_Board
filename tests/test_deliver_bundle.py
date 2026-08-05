"""Atomic consumer delivery regressions."""

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from deliver_bundle import deliver  # noqa: E402
from validate_bundle import LAYERS  # noqa: E402


def _stage_samples(path):
    path.mkdir()
    for name in (*LAYERS, "site_data"):
        shutil.copy2(ROOT / "samples" / f"{name}.sample.json",
                     path / f"{name}.json")


@pytest.mark.parametrize("filename", ["weekly_board.json", "raid_kills.json"])
def test_absent_optional_sidecar_removes_stale_consumer_copy(
        tmp_path, filename):
    source = tmp_path / "source"
    destination = tmp_path / "consumer"
    _stage_samples(source)
    destination.mkdir()
    optional_source = source / filename
    if optional_source.exists():
        optional_source.unlink()
    (destination / filename).write_text(
        '{"week_label":"last-week"}', encoding="utf-8")

    assert deliver(str(source), str(destination)) == 0
    assert not (destination / filename).exists()
    assert (destination / "DELIVERY.json").exists()

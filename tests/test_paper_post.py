"""THE PAPER IS THE POST -- the swap, and the gate that guards it.

Every test here is OFFLINE. The shot itself is mocked (a browser and a live
website are not test dependencies); what IS exercised for real is the part
that can silently lose data:

  * the parity gate, against a saved snapshot of the paper's own rendered
    text (tests/fixtures/board_page_text.txt), including the case that
    matters -- a datum that has left the sheet must FAIL;
  * the renderer switch: `renderer: paper` posts the paper's photographs,
    `classic` (or an absent key) leaves the old path untouched;
  * fail-closed on parity, fail-open on everything else.
"""

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from guild_board import html_board, main, paper_shot

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "parity_manifest.yml"
SNAPSHOT = REPO / "tests" / "fixtures" / "board_page_text.txt"


def _manifest():
    with open(MANIFEST, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _snapshot():
    return SNAPSHOT.read_text(encoding="utf-8")


# --- the manifest itself ----------------------------------------------------

def test_manifest_is_checked_in_and_well_formed():
    m = _manifest()
    assert m["kept"], "parity_manifest.yml lists no kept data"
    for entry in m["kept"]:
        for field in ("datum", "was", "page", "anchor", "expect"):
            assert entry.get(field) is not None, f"{entry.get('datum')}: no {field}"
        assert entry["page"] in (1, 2, 3, 4), entry["datum"]
    names = [e["datum"] for e in m["kept"]]
    assert len(names) == len(set(names)), "duplicate datum in the manifest"


def test_dropped_data_are_recorded_with_a_reason():
    """The owner's grant is a decision, and a decision that is not written
    down is a bug report waiting to happen."""
    m = _manifest()
    assert m["dropped"], "nothing recorded as dropped"
    for entry in m["dropped"]:
        assert entry.get("datum") and entry.get("was") and entry.get("why")
        assert len(entry["why"]) > 40, f"{entry['datum']}: reason is too thin"


def test_load_parity_manifest_missing_file_returns_none(tmp_path):
    assert paper_shot.load_parity_manifest(str(tmp_path / "nope.yml")) is None


# --- the gate, against the real paper ---------------------------------------

def test_every_kept_datum_is_on_the_saved_paper():
    missing, checked = paper_shot.check_parity(_snapshot(), _manifest())
    assert checked >= 20, f"only {checked} data checked -- the manifest thinned out"
    assert not missing, ("the paper no longer carries: "
                         + ", ".join(e["datum"] for e in missing))


def test_a_vanished_datum_fails_the_gate():
    """The only failure this swap can introduce is a paper that quietly stops
    printing something. Prove the gate actually catches it."""
    # every case (the index to departments names it in lower case too)
    text = re.sub(r"the season ladder", "the something else", _snapshot(),
                  flags=re.I)
    missing, _ = paper_shot.check_parity(text, _manifest())
    assert [e["datum"] for e in missing] == ["season_mplus_scores"]


def test_pending_berths_are_reported_but_never_enforced():
    manifest = {"kept": [
        {"datum": "not_here_yet", "expect": "a string that is not on the sheet",
         "pending": True},
        {"datum": "must_be_here", "expect": "The Season Ladder"},
    ]}
    missing, checked = paper_shot.check_parity(_snapshot(), manifest)
    assert checked == 2
    assert not missing


def test_empty_page_text_fails_every_enforced_datum():
    missing, _ = paper_shot.check_parity("", _manifest())
    enforced = [e for e in _manifest()["kept"] if not e.get("pending")]
    assert len(missing) == len(enforced)


# --- the renderer switch ----------------------------------------------------

def _cfg(renderer=None):
    cfg = {
        "lookback_days": 7,
        "guild": {"name": "Test", "realm_slug": "bleeding-hollow", "region": "us"},
        "raid": {"enabled": False, "difficulty": "heroic"},
        "top_n": 5,
        "display": {"layout": "image_board", "renderer": "pillow",
                    "web_board": {"enabled": False},
                    "paper_url": "http://example.invalid/board/"},
        "sections": {"progress_image": {"enabled": False}},
    }
    if renderer:
        cfg["renderer"] = renderer
    return cfg


def _window():
    now = datetime.now(timezone.utc)
    return now - timedelta(days=7), now


def _fake_shot(tmp_path):
    names = ("weekly_post_front.png", "weekly_post_fold.png",
             "weekly_post_ladder.png")
    for n in names:
        (tmp_path / n).write_bytes(b"\x89PNG\r\n\x1a\n")
    return {"front": str(tmp_path / names[0]),
            "fold": str(tmp_path / names[1]),
            "ladder": str(tmp_path / names[2]),
            "manifest": {"shots": {}}, "parity": {"checked": 24, "missing": []}}


def test_paper_renderer_posts_the_papers_photographs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = {}

    def fake(url=None, out_dir=".", manifest=None):
        calls["url"] = url
        calls["manifest"] = manifest
        return _fake_shot(tmp_path)

    monkeypatch.setattr(paper_shot, "shoot_paper", fake)
    monkeypatch.setattr(paper_shot, "load_parity_manifest", lambda *a, **k: _manifest())
    start, end = _window()
    embed, image_path = main.build_board(_cfg("paper"), start_dt=start, end_dt=end,
                                         dry_run=True)
    # the teaser leads the post -- it is the one Discord shows at embed width
    assert os.path.basename(image_path) == "weekly_post_fold.png"
    assert embed["image"]["url"] == "attachment://weekly_post_fold.png"
    assert calls["url"] == "http://example.invalid/board/"
    assert calls["manifest"]["kept"]


def test_paper_renderer_still_renders_the_web_twin(tmp_path, monkeypatch):
    """The post LINKS the web board, so the paper path must keep publishing it.

    `renderer: paper` sets image_path before the classic block and skips it --
    and the web twin used to be rendered inside that block. The published site
    and its week archive froze at 2026-07-28 for three editions while every
    Tuesday post kept pointing the guild at them."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(paper_shot, "shoot_paper", lambda **k: _fake_shot(tmp_path))
    monkeypatch.setattr(paper_shot, "load_parity_manifest", lambda *a, **k: _manifest())
    rendered = []
    monkeypatch.setattr(html_board, "generate_web_board",
                        lambda *a, **k: rendered.append(a) or "site/index.html")
    cfg = _cfg("paper")
    cfg["display"]["web_board"] = {"enabled": True}
    start, end = _window()
    main.build_board(cfg, start_dt=start, end_dt=end, dry_run=True)
    assert rendered, "renderer: paper skipped the web board render"


def test_classic_renderer_leaves_the_old_path_alone(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def boom(*a, **k):
        raise AssertionError("classic must never reach for the paper")

    monkeypatch.setattr(paper_shot, "shoot_paper", boom)
    start, end = _window()
    _, image_path = main.build_board(_cfg("classic"), start_dt=start, end_dt=end,
                                     preview=True, dry_run=True)
    assert os.path.basename(image_path) == "board.png"


def test_absent_renderer_key_is_classic(tmp_path, monkeypatch):
    """A caller who hands build_board a bare cfg never reaches the network."""
    monkeypatch.chdir(tmp_path)

    def boom(*a, **k):
        raise AssertionError("an unset renderer must not shoot the paper")

    monkeypatch.setattr(paper_shot, "shoot_paper", boom)
    start, end = _window()
    _, image_path = main.build_board(_cfg(), start_dt=start, end_dt=end,
                                     preview=True, dry_run=True)
    assert os.path.basename(image_path) == "board.png"


def test_a_broken_shot_falls_back_to_classic(tmp_path, monkeypatch):
    """FAIL OPEN on a browser or network fault: the guild still gets a board."""
    monkeypatch.chdir(tmp_path)

    def broken(*a, **k):
        raise RuntimeError("chromium fell over")

    monkeypatch.setattr(paper_shot, "shoot_paper", broken)
    monkeypatch.setattr(paper_shot, "load_parity_manifest", lambda *a, **k: _manifest())
    start, end = _window()
    _, image_path = main.build_board(_cfg("paper"), start_dt=start, end_dt=end,
                                     dry_run=True)
    assert os.path.basename(image_path) == "board.png"


def test_a_parity_failure_stops_the_post(tmp_path, monkeypatch):
    """FAIL CLOSED on parity: posting a paper that lost a datum is the one
    outcome worse than not posting."""
    monkeypatch.chdir(tmp_path)

    def gone(*a, **k):
        raise paper_shot.ParityFailure("1 kept datum(s) vanished: season_mplus_scores")

    monkeypatch.setattr(paper_shot, "shoot_paper", gone)
    monkeypatch.setattr(paper_shot, "load_parity_manifest", lambda *a, **k: _manifest())
    start, end = _window()
    with pytest.raises(paper_shot.ParityFailure):
        main.build_board(_cfg("paper"), start_dt=start, end_dt=end,
                         dry_run=True)


def test_shipped_config_selects_the_paper():
    with open(REPO / "config.yml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    assert cfg.get("renderer") == "paper"
    assert (cfg.get("display") or {}).get("paper_url", "").startswith("https://")


# --- the attachment budget --------------------------------------------------

def test_fit_leaves_a_small_capture_untouched(tmp_path):
    from PIL import Image
    p = tmp_path / "small.png"
    Image.new("RGB", (40, 40), (200, 195, 180)).save(p)
    before = p.read_bytes()
    assert paper_shot._fit(p) == 1.0
    assert p.read_bytes() == before


def test_fit_steps_an_oversized_capture_down(tmp_path, monkeypatch):
    from PIL import Image
    p = tmp_path / "big.png"
    Image.new("RGB", (900, 900), (10, 10, 10)).save(p)
    monkeypatch.setattr(paper_shot, "BUDGET", 1)     # nothing can fit
    assert paper_shot._fit(p) == paper_shot.STEPS[-1]
    with Image.open(p) as im:
        assert im.width < 900


# --- the state commit outlives a failed publish -----------------------------

def test_web_publish_cannot_take_the_state_commit_down_with_it():
    """A website that will not publish must not cost us board_state.json.

    2026-08-25: WEB_BOARD_TOKEN expired, the publish step failed, GitHub
    skipped every later step -- so the run posted the board to Discord and
    then discarded the state it was computed from. Records, streaks and the
    week boundary all read from that file next Tuesday."""
    wf = yaml.safe_load(
        (REPO / ".github" / "workflows" / "weekly-board.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["post-board"]["steps"]
    names = [s.get("name", "") for s in steps]
    publish = next(i for i, n in enumerate(names) if "Publish web board" in n)
    commit = next(i for i, n in enumerate(names) if "Commit roster cache" in n)
    assert publish < commit, "the publish step no longer precedes the commit step"
    assert steps[publish].get("continue-on-error") is True, (
        "the web publish must be continue-on-error, or a failed push skips "
        "the state commit that follows it")

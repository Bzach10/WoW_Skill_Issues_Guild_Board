"""Offline tests for guild_board.transmog_fingerprint."""

from guild_board.transmog_fingerprint import compute_transmog_fingerprint


def test_fingerprint_stable_for_same_url():
    profile = {"transmog_render_url": "https://example.com/a.png"}
    assert compute_transmog_fingerprint(profile) == compute_transmog_fingerprint(profile)


def test_fingerprint_changes_when_url_changes():
    fp1 = compute_transmog_fingerprint({"transmog_render_url": "https://example.com/a.png"})
    fp2 = compute_transmog_fingerprint({"transmog_render_url": "https://example.com/b.png"})
    assert fp1 != fp2


def test_fingerprint_falls_back_without_url():
    fp = compute_transmog_fingerprint({"name": "Rakdisc", "race": "Nightborne"})
    assert fp  # non-empty, doesn't crash without a render URL


def test_fingerprint_handles_none_profile():
    assert compute_transmog_fingerprint(None)  # doesn't raise

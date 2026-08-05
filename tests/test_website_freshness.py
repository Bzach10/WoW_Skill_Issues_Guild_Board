from scripts.check_website_freshness import is_fresh


def test_freshness_accepts_same_or_newer_deployment():
    expected = {"generated_at": "2026-08-05T02:46:58+00:00"}
    assert is_fresh(
        {"source_generated_at": "2026-08-05T02:46:58Z"}, expected)
    assert is_fresh(
        {"source": {"generated_at": "2026-08-05T03:00:00+00:00"}}, expected)


def test_freshness_rejects_stale_or_unversioned_deployment():
    expected = {"generated_at": "2026-08-05T02:46:58+00:00"}
    assert not is_fresh({"generated_at": "2026-08-02T00:00:00Z"}, expected)
    assert not is_fresh({"status": "ok"}, expected)

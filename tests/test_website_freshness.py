import pytest

from scripts.check_website_freshness import _validate_url, is_fresh


def test_freshness_requires_exact_deployed_bundle_bytes():
    expected = b'{"generated_at":"2026-08-05T02:46:58+00:00"}'
    assert is_fresh(expected, expected)
    assert not is_fresh(
        b'{"generated_at":"2026-08-05T03:00:00+00:00"}', expected)


def test_health_endpoint_must_be_absolute_https():
    _validate_url("https://example.test/data/site_data.json")
    with pytest.raises(ValueError):
        _validate_url("http://example.test/data/site_data.json")
    with pytest.raises(ValueError):
        _validate_url("file:///etc/passwd")

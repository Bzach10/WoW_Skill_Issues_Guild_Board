"""Offline tests for the Blizzard character-profile scaffolding.

No network calls: every requests.get/post is monkeypatched. Mirrors the
fake-response style already used for WCL/Discord tests in
tests/test_guild_board.py.
"""

import json

from guild_board import blizzard


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise blizzard.requests.HTTPError(f"status {self.status_code}")


def test_get_blizzard_token_posts_client_credentials(monkeypatch):
    captured = {}

    def fake_post(url, data=None, auth=None, timeout=None):
        captured["url"] = url
        captured["data"] = data
        captured["auth"] = auth
        return FakeResponse(200, {"access_token": "tok-123"})

    monkeypatch.setattr(blizzard.requests, "post", fake_post)
    token = blizzard.get_blizzard_token("cid", "csecret")

    assert token == "tok-123"
    assert captured["url"] == blizzard.BLIZZARD_TOKEN_URL
    assert captured["data"] == {"grant_type": "client_credentials"}
    assert captured["auth"] == ("cid", "csecret")


def test_fetch_character_profile_happy_path(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        if url.endswith("/character-media"):
            return FakeResponse(200, {"assets": [
                {"key": "avatar", "value": "https://example.com/avatar.jpg"},
                {"key": "main-raw", "value": "https://example.com/main-raw.jpg"},
            ]})
        if url.endswith("/specializations"):
            return FakeResponse(200, {
                "active_specialization": {"name": "Discipline"},
            })
        return FakeResponse(200, {
            "name": "Rakdisc",
            "gender": {"type": "FEMALE", "name": "Female"},
            "race": {"name": "Nightborne"},
            "character_class": {"name": "Priest"},
        })

    monkeypatch.setattr(blizzard.requests, "get", fake_get)
    profile = blizzard.fetch_character_profile("tok", "us", "proudmoore", "Rakdisc")

    assert profile["name"] == "Rakdisc"
    assert profile["gender"] == "Female"
    assert profile["race"] == "Nightborne"
    assert profile["class"] == "Priest"
    assert profile["active_spec"] == "Discipline"
    assert profile["avatar_render_url"] == "https://example.com/avatar.jpg"
    assert profile["transmog_render_url"] == "https://example.com/main-raw.jpg"


def test_fetch_character_profile_missing_returns_none_not_raise(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return FakeResponse(404, {})

    monkeypatch.setattr(blizzard.requests, "get", fake_get)
    profile = blizzard.fetch_character_profile("tok", "us", "proudmoore", "Nobody")

    assert profile is None


def test_fetch_character_profile_network_error_returns_none(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        raise blizzard.requests.ConnectionError("boom")

    monkeypatch.setattr(blizzard.requests, "get", fake_get)
    profile = blizzard.fetch_character_profile("tok", "us", "proudmoore", "Rakdisc")

    assert profile is None


def test_fetch_roster_profiles_skips_failures_and_lowercases_keys(monkeypatch):
    def fake_fetch(token, region, realm, name):
        if name == "Rakdisc":
            return {"name": "Rakdisc", "realm": realm}
        return None

    monkeypatch.setattr(blizzard, "fetch_character_profile", fake_fetch)
    profiles = blizzard.fetch_roster_profiles(
        "tok", "us", ["Rakdisc-Proudmoore", "Ghost-Proudmoore", "noDashEntry"])

    assert list(profiles.keys()) == ["rakdisc-proudmoore"]


def test_refresh_profile_cache_noop_when_disabled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BLIZZARD_CLIENT_ID", "cid")
    monkeypatch.setenv("BLIZZARD_CLIENT_SECRET", "csecret")

    def boom(*a, **k):
        raise AssertionError("should never call Blizzard when disabled")

    monkeypatch.setattr(blizzard, "get_blizzard_token", boom)
    cfg = {"blizzard": {"enabled": False}, "guild": {"region": "us"}}

    cached, changed = blizzard.refresh_profile_cache(cfg, ["Rakdisc-Proudmoore"])

    assert changed is False
    assert cached == {}


def test_refresh_profile_cache_noop_without_creds(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BLIZZARD_CLIENT_ID", raising=False)
    monkeypatch.delenv("BLIZZARD_CLIENT_SECRET", raising=False)

    def boom(*a, **k):
        raise AssertionError("should never call Blizzard without creds")

    monkeypatch.setattr(blizzard, "get_blizzard_token", boom)
    cfg = {"blizzard": {"enabled": True}, "guild": {"region": "us"}}

    cached, changed = blizzard.refresh_profile_cache(cfg, ["Rakdisc-Proudmoore"])

    assert changed is False
    assert cached == {}


def test_refresh_profile_cache_fetches_merges_and_saves(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BLIZZARD_CLIENT_ID", "cid")
    monkeypatch.setenv("BLIZZARD_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(blizzard, "get_blizzard_token", lambda cid, cs: "tok")
    monkeypatch.setattr(blizzard, "fetch_roster_profiles",
                         lambda token, region, roster: {
                             "rakdisc-proudmoore": {
                                 "name": "Rakdisc", "realm": "proudmoore",
                                 "gender": "Female", "race": "Nightborne",
                                 "class": "Priest", "active_spec": "Discipline",
                                 "transmog_render_url": "https://example.com/main-raw.jpg",
                             }
                         })
    cfg = {"blizzard": {"enabled": True, "cache_file": "blizzard_profile_cache.json"},
           "guild": {"region": "us"}}

    merged, changed = blizzard.refresh_profile_cache(cfg, ["Rakdisc-Proudmoore"])

    assert changed is True
    assert merged["rakdisc-proudmoore"]["race"] == "Nightborne"

    with open(tmp_path / "blizzard_profile_cache.json", encoding="utf-8") as f:
        on_disk = json.load(f)
    assert "last_updated" in on_disk
    assert on_disk["characters"]["rakdisc-proudmoore"]["class"] == "Priest"

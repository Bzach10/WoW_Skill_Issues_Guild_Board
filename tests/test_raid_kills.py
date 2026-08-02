"""Offline tests for the per-boss raid kill sweep (raiderio.collect_raid_boss_kills).

No network: every request is answered by a fake session. What these pin is the
one distinction the whole layer rests on — an answered "no kill" (HTTP 200,
empty body) is DATA, and an unanswered question is IGNORANCE that must degrade
the payload instead of masquerading as a negative.
"""

import pytest

from guild_board import raiderio

SEASON = {
    "raid": {
        "slug": "tier-mn-1",
        "display_name": "Voidspire Sanctum",
        "bosses": [
            {"order": 1, "name": "Imperator Averzian", "slug": "imperator-averzian"},
            {"order": 2, "name": "Vorasius", "slug": "vorasius"},
        ],
    },
}

CFG = {"guild": {"name": "Skill Issues", "realm_slug": "bleeding-hollow",
                 "region": "us"}}


class FakeResponse:
    def __init__(self, status_code=200, body=None, bad_json=False):
        self.status_code = status_code
        self._body = {} if body is None else body
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._body


class FakeApi:
    """Answers boss-kill requests from a {(boss, difficulty): response} map,
    defaulting to an honest 'not killed'."""

    def __init__(self, answers=None, default=None):
        self.answers = answers or {}
        self.default = default if default is not None else FakeResponse()
        self.calls = []
        self.headers = []

    def __call__(self, url, params, timeout=30, headers=None):
        assert url == raiderio.RAIDERIO_BOSS_KILL_URL
        key = (params["boss"], params["difficulty"])
        self.calls.append(key)
        self.headers.append(headers)
        answer = self.answers.get(key, self.default)
        return answer.pop(0) if isinstance(answer, list) else answer


@pytest.fixture
def api(monkeypatch):
    fake = FakeApi()
    monkeypatch.setattr(raiderio, "_rio_request", fake)
    return fake


def _kill(defeated_at):
    return FakeResponse(body={"kill": {"defeatedAt": defeated_at,
                                       "isSuccess": True}})


def test_every_boss_and_difficulty_is_asked(api):
    payload = raiderio.collect_raid_boss_kills(CFG, SEASON)
    assert len(api.calls) == 2 * len(raiderio.KILL_DIFFICULTIES)
    assert payload["available"] is True
    assert payload["status"] == "ok"
    assert payload["raid"]["slug"] == "tier-mn-1"
    assert [b["slug"] for b in payload["bosses"]] == ["imperator-averzian", "vorasius"]


def test_the_endpoint_is_called_with_a_real_user_agent(api):
    raiderio.collect_raid_boss_kills(CFG, SEASON)
    assert all(h["User-Agent"] == raiderio.BOSS_KILL_USER_AGENT for h in api.headers)


def test_a_kill_carries_its_date_and_counts_once(api):
    api.answers[("vorasius", "mythic")] = _kill("2026-07-20T00:50:00.000Z")
    api.answers[("vorasius", "heroic")] = _kill("2026-07-14T02:00:00.000Z")
    payload = raiderio.collect_raid_boss_kills(CFG, SEASON)
    vorasius = payload["bosses"][1]
    assert vorasius["kills"]["mythic"]["defeated_at"] == "2026-07-20T00:50:00.000Z"
    assert vorasius["kills"]["heroic"]["defeated_at"] == "2026-07-14T02:00:00.000Z"
    assert payload["killed_by_difficulty"] == {"normal": 0, "heroic": 1, "mythic": 1}


def test_an_empty_body_is_a_real_no_kill_not_a_gap(api):
    payload = raiderio.collect_raid_boss_kills(CFG, SEASON)
    assert payload["available"] is True                 # the sweep is complete
    assert all(b["kills"] == {} for b in payload["bosses"])
    assert payload["killed_by_difficulty"] == {"normal": 0, "heroic": 0, "mythic": 0}
    assert "unresolved" not in payload


def test_one_unanswered_pair_makes_the_whole_payload_unavailable(api):
    api.answers[("vorasius", "mythic")] = FakeResponse(status_code=500)
    api.answers[("imperator-averzian", "mythic")] = _kill("2026-07-20T00:28:00.000Z")
    payload = raiderio.collect_raid_boss_kills(CFG, SEASON)
    assert payload["available"] is False
    assert payload["status"] == "partial_fetch"
    assert payload["unresolved"] == ["vorasius/mythic"]
    # The kills it DID see are still reported -- the flag, not amputation, is
    # what stops a consumer trusting an incomplete sweep.
    assert payload["bosses"][0]["kills"]["mythic"]["defeated_at"]


def test_a_total_outage_degrades_rather_than_raising(api):
    api.default = FakeResponse(status_code=503)
    payload = raiderio.collect_raid_boss_kills(CFG, SEASON)
    assert payload["available"] is False
    assert payload["status"] == "unavailable"
    assert len(payload["unresolved"]) == 2 * len(raiderio.KILL_DIFFICULTIES)


def test_a_network_fault_never_escapes(api, monkeypatch):
    import requests

    def boom(*_a, **_kw):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(raiderio, "_rio_request", boom)
    payload = raiderio.collect_raid_boss_kills(CFG, SEASON)
    assert payload["available"] is False
    assert payload["status"] == "unavailable"


def test_a_transient_5xx_is_retried_and_can_recover(api):
    api.answers[("vorasius", "mythic")] = [FakeResponse(status_code=502),
                                           _kill("2026-07-20T00:50:00.000Z")]
    payload = raiderio.collect_raid_boss_kills(CFG, SEASON)
    assert payload["available"] is True
    assert payload["bosses"][1]["kills"]["mythic"]["defeated_at"]


def test_a_rejected_question_is_not_retried(api):
    api.answers[("vorasius", "mythic")] = FakeResponse(status_code=400)
    raiderio.collect_raid_boss_kills(CFG, SEASON)
    assert api.calls.count(("vorasius", "mythic")) == 1


def test_an_unparseable_body_is_ignorance_not_a_no_kill(api):
    api.default = FakeResponse(bad_json=True)
    payload = raiderio.collect_raid_boss_kills(CFG, SEASON)
    assert payload["available"] is False
    assert all(b["kills"] == {} for b in payload["bosses"])

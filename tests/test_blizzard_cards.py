"""Offline tests for the trading-card data limb (guild_board/blizzard_cards.py).

No network: the whole endpoint sweep is served by one fake session keyed on
the path suffix, in the same fake-response style as tests/test_blizzard.py.

What these pin down is the HONESTY behaviour, because that is what a card
face depends on: a failed endpoint leaves a named seam instead of a zero, an
unreadable character is dropped rather than half-invented, and the slimmers
never manufacture a figure the payload did not carry.
"""

import json

from guild_board import blizzard_cards as bc


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise bc.requests.HTTPError(f"status {self.status_code}")


PAYLOADS = {
    "": {
        "name": "Aiime", "id": 42, "level": 80,
        "race": {"name": "Goblin"}, "gender": {"name": "Female"},
        "character_class": {"name": "Shaman", "id": 7},
        "active_spec": {"name": "Restoration"},
        "faction": {"name": "Horde"},
        "active_title": {"name": "%s the Kingslayer"},
        "guild": {"name": "Skill Issues", "realm": {"name": "Bleeding Hollow"}},
        "achievement_points": 14520,
        "equipped_item_level": 662, "average_item_level": 664,
        "last_login_timestamp": 1753000000000,
    },
    "/specializations": {
        "active_specialization": {"name": "Restoration"},
        "specializations": [{"specialization": {"name": "Restoration"}},
                            {"specialization": {"name": "Elemental"}}],
        "active_hero_talent_tree": {"name": "Farseer"},
    },
    "/character-media": {"assets": [
        {"key": "avatar", "value": "https://render/avatar.jpg"},
        {"key": "main-raw", "value": "https://render/main-raw.png"},
    ]},
    "/equipment": {"equipped_items": [
        {"slot": {"type": "HEAD"}, "name": "Stormcaller's Crown",
         "item": {"id": 111}, "quality": {"name": "Epic"},
         "level": {"value": 668, "display_string": "Item Level 668"},
         "item_subclass": {"name": "Mail"},
         "enchantments": [{"display_string": "Enchanted: Wisdom"}],
         "sockets": [{"item": {"name": "Ruby"}}]},
        {"slot": {"type": "TABARD"}, "name": "Guild Tabard",
         "level": {"value": 1}},
    ]},
    "/statistics": {
        "health": 9_400_000, "power": 250_000, "power_type": {"name": "Mana"},
        "intellect": {"value": 61_000}, "stamina": {"value": 470_000},
        "melee_crit": {"value": 31.4}, "spell_haste": {"value": 22.7},
        "mastery": {"value": 18.2}, "versatility": 9.1,
        "armor": {"value": 21_000}, "avoidance": {"value": 3.2},
        "spell_power": 55_000,
    },
    "/achievements": {
        "total_points": 14520, "total_quantity": 1802,
        "achievements": [
            {"achievement": {"name": "Cutting Edge: Nerub-ar Palace"},
             "completed_timestamp": 1752000000000},
            {"achievement": {"name": "Keystone Master: Season Three"},
             "completed_timestamp": 1753000000000},
            {"achievement": {"name": "Loremaster"},
             "completed_timestamp": 1600000000000},
        ],
    },
    "/achievements/statistics": {"categories": [
        {"name": "Character", "statistics": [
            {"name": "Total deaths", "quantity": 4211.0},
            {"name": "Quests completed", "quantity": 9876.0},
        ], "sub_categories": [
            {"name": "Deaths", "statistics": [
                {"name": "Deaths from falling", "quantity": 143.0}]},
        ]},
        {"name": "Social", "statistics": [{"name": "Total hugs", "quantity": 12.0}]},
    ]},
    "/titles": {
        "active_title": {"name": "%s the Kingslayer"},
        "titles": [{"name": "%s the Kingslayer"}, {"name": "Battlelord %s"}],
    },
    "/mythic-keystone-profile": {
        "seasons": [{"id": 13}, {"id": 14}],
        "current_period": {"period": {"id": 999}, "best_runs": [{}, {}]},
        "current_mythic_rating": {"rating": 3120.4},
    },
    "/mythic-keystone-profile/season/14": {
        "season": {"id": 14}, "mythic_rating": {"rating": 3120.4},
        "best_runs": [
            {"dungeon": {"name": "Ara-Kara"}, "keystone_level": 18,
             "is_completed_within_time": True,
             "mythic_rating": {"rating": 210.5},
             "completed_timestamp": 1753000000000, "duration": 1_500_000,
             "keystone_affixes": [{"name": "Tyrannical"}]},
            {"dungeon": {"name": "City of Threads"}, "keystone_level": 21,
             "is_completed_within_time": False,
             "mythic_rating": {"rating": 190.0}},
        ],
    },
    "/professions": {
        "primaries": [{"profession": {"name": "Alchemy"}, "tiers": [
            {"tier": {"name": "Khaz Algar Alchemy"}, "skill_points": 100,
             "max_skill_points": 100, "known_recipes": [{}, {}, {}]}]}],
        "secondaries": [{"profession": {"name": "Fishing"}, "tiers": [
            {"tier": {"name": "Khaz Algar Fishing"}, "skill_points": 25,
             "max_skill_points": 100}]}],
    },
    "/collections/mounts": {"mounts": [{}] * 312},
    "/collections/pets": {"pets": [
        {"name": "Mr. Bigglesworth", "level": 25, "quality": {"name": "Rare"}},
        {"name": "Squeaky", "level": 3},
    ]},
    "/pvp-summary": {"honor_level": 42, "honorable_kills": 8123, "brackets": [
        {"href": "https://us.api.blizzard.com/.../pvp-bracket/3v3?namespace=x"}]},
    "/encounters/raids": {"expansions": [
        {"expansion": {"name": "Legion"}, "instances": [
            {"instance": {"name": "Nighthold"}, "modes": [
                {"difficulty": {"name": "Heroic"},
                 "progress": {"completed_count": 30, "total_count": 10}}]}]},
        {"expansion": {"name": "The War Within"}, "instances": [
            {"instance": {"name": "Liberation of Undermine"}, "modes": [
                {"difficulty": {"name": "Mythic"},
                 "progress": {"completed_count": 4, "total_count": 8}},
                {"difficulty": {"name": "Heroic"},
                 "progress": {"completed_count": 8, "total_count": 8}}]}]},
    ]},
    "/encounters/dungeons": {"expansions": [
        {"instances": [{"modes": [
            {"progress": {"completed_count": 640}}]}]}]},
}

BASE = "/profile/wow/character/bleeding-hollow/aiime"


def install_fake(monkeypatch, missing=()):
    """Serve PAYLOADS by path suffix; anything in `missing` 404s."""
    class FakeSession:
        def get(self, url, params=None, headers=None, timeout=None):
            suffix = url.split(BASE, 1)[1] if BASE in url else "?"
            if suffix in missing:
                return FakeResponse(404, {})
            if suffix not in PAYLOADS:
                return FakeResponse(404, {})
            return FakeResponse(200, PAYLOADS[suffix])

    monkeypatch.setattr(bc, "_session", lambda: FakeSession())


def test_full_record_carries_every_block(monkeypatch):
    install_fake(monkeypatch)
    report = {}
    rec = bc.fetch_card_record("tok", "us", "bleeding-hollow", "Aiime", report)

    assert rec["seams"] == []
    assert rec["identity"]["level"] == 80
    assert rec["identity"]["item_level_equipped"] == 662
    assert rec["identity"]["guild"] == "Skill Issues"
    assert rec["identity"]["last_login"].startswith("2025-")
    assert rec["spec"]["known"] == ["Elemental", "Restoration"]
    assert rec["media"]["render"].endswith("main-raw.png")
    assert rec["stats"]["health"] == 9_400_000
    assert rec["stats"]["secondary"]["critical_strike"] == 31.4
    assert rec["stats"]["defense"]["armor"] == 21_000
    assert rec["history"]["points"] == 14520
    assert rec["titles"]["count"] == 2
    assert rec["craft"]["primaries"][0]["skill"] == 100
    assert rec["mounts"]["count"] == 312
    assert rec["pets"]["best"]["name"] == "Mr. Bigglesworth"
    assert rec["pvp"]["brackets"] == ["3v3"]
    assert rec["dungeons"]["dungeon_kills_total"] == 640
    # Every request is tallied, so the run can report a measured inventory.
    assert report["character/equipment"] == {"ok": 1}


def test_gear_line_keeps_only_real_slots_and_reads_upgrades(monkeypatch):
    install_fake(monkeypatch)
    rec = bc.fetch_card_record("tok", "us", "bleeding-hollow", "Aiime")
    gear = rec["gear"]

    # TABARD is not a card slot; HEAD is.
    assert [i["slot"] for i in gear["items"]] == ["HEAD"]
    assert gear["items"][0]["item_level_display"] == "Item Level 668"
    assert gear["items"][0]["enchant"] == "Enchanted: Wisdom"
    assert gear["items"][0]["gems"] == ["Ruby"]
    assert gear["slots_enchanted"] == 1
    assert gear["sockets_gemmed"] == 1
    assert gear["best_piece"]["name"] == "Stormcaller's Crown"


def test_history_picks_notables_and_the_latest_earned(monkeypatch):
    install_fake(monkeypatch)
    rec = bc.fetch_card_record("tok", "us", "bleeding-hollow", "Aiime")
    names = [a["name"] for a in rec["history"]["notable"]]

    assert "Cutting Edge: Nerub-ar Palace" in names
    assert "Keystone Master: Season Three" in names
    assert "Loremaster" not in names          # real, but not a card signal
    assert rec["history"]["most_recent"]["name"] == "Keystone Master: Season Three"


def test_weird_numbers_are_curated_by_name_not_zero_filled(monkeypatch):
    install_fake(monkeypatch)
    rec = bc.fetch_card_record("tok", "us", "bleeding-hollow", "Aiime")
    values = rec["record"]["values"]

    assert values["deaths"] == 4211
    assert values["deaths_from_falling"] == 143
    assert values["quests_completed"] == 9876
    assert values["hugs"] == 12
    # A statistic this account has never recorded is ABSENT, never 0.
    assert "fish_caught" not in values


def test_keystone_season_is_fetched_for_the_latest_season_only(monkeypatch):
    install_fake(monkeypatch)
    report = {}
    rec = bc.fetch_card_record("tok", "us", "bleeding-hollow", "Aiime", report)

    assert rec["keystone_season"]["season_id"] == 14
    assert rec["keystone_season"]["highest_level"] == 21
    assert rec["keystone_season"]["timed_count"] == 1
    assert report["character/mythic-keystone-profile/season"] == {"ok": 1}


def test_raid_totals_span_the_career_but_detail_is_current_expansion(monkeypatch):
    install_fake(monkeypatch)
    rec = bc.fetch_card_record("tok", "us", "bleeding-hollow", "Aiime")

    assert rec["raids"]["boss_kills_total"] == 42          # 30 + 4 + 8
    assert rec["raids"]["latest_expansion"] == "The War Within"
    assert [i["instance"] for i in rec["raids"]["latest_instances"]] == \
        ["Liberation of Undermine"]


def test_a_failed_endpoint_becomes_a_named_seam_not_a_zero(monkeypatch):
    install_fake(monkeypatch, missing=("/statistics", "/professions"))
    rec = bc.fetch_card_record("tok", "us", "bleeding-hollow", "Aiime")

    assert "stats" in rec["seams"]
    assert "craft" in rec["seams"]
    assert "stats" not in rec
    assert "craft" not in rec
    assert rec["identity"]["level"] == 80        # the rest of the card survives


def test_an_unreadable_character_is_dropped_whole(monkeypatch):
    install_fake(monkeypatch, missing=("",))
    assert bc.fetch_card_record("tok", "us", "bleeding-hollow", "Aiime") is None


def test_no_keystone_season_is_a_seam(monkeypatch):
    """A character who has never run a key this expansion gets an honest gap
    on the keystone line, and costs one request fewer."""
    monkeypatch.setitem(PAYLOADS, "/mythic-keystone-profile",
                        {"seasons": [], "current_period": {}})
    install_fake(monkeypatch)
    report = {}
    rec = bc.fetch_card_record("tok", "us", "bleeding-hollow", "Aiime", report)

    assert "keystone_season" in rec["seams"]
    assert "character/mythic-keystone-profile/season" not in report


def test_refresh_is_a_clean_noop_without_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv("BLIZZARD_CLIENT_ID", raising=False)
    monkeypatch.delenv("BLIZZARD_CLIENT_SECRET", raising=False)
    cfg = {"blizzard": {"enabled": True,
                        "card_cache_file": str(tmp_path / "cards.json")}}
    chars, changed, report = bc.refresh_card_cache(cfg, ["aiime-bleeding-hollow"])
    assert (chars, changed, report) == ({}, False, {})


def test_cache_is_byte_stable_and_carries_the_inventory(tmp_path):
    cfg = {"blizzard": {"enabled": True,
                        "card_cache_file": str(tmp_path / "cards.json")}}
    chars = {"aiime-bleeding-hollow": {"identity": {"level": 80}, "seams": []}}
    bc.save_card_cache(cfg, chars, {"character": {"ok": 1}}, "us")
    first = (tmp_path / "cards.json").read_text(encoding="utf-8")
    bc.save_card_cache(cfg, chars, {"character": {"ok": 1}}, "us")
    second = (tmp_path / "cards.json").read_text(encoding="utf-8")

    payload = json.loads(first)
    # Only last_updated may differ between two saves of identical data.
    assert json.loads(second)["characters"] == payload["characters"]
    assert payload["schema_version"] == bc.CARD_CACHE_VERSION
    blocks = {e["block"] for e in payload["endpoints"]}
    assert {"identity", "gear", "stats", "history", "keystone_season"} <= blocks

"""build_site_data.carry_forward_raid — last-good semantics for the raid
block.

2026-07-27 incident: Raider.io's guild-profile endpoint 500'd (mid
guild-split churn), _fetch_guild_progression failed open to {}, and the
rebuild committed a raid block with every kill count at zero. The zeros were
internally consistent, so validate_bundle passed them; the redesign's
attestation guard (mythic kills >= the attested 1) was the first gate to
refuse. These tests pin the fix: zeros that mean "the fetch failed" never
replace a committed block that carries real kills.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from build_site_data import carry_forward_raid  # noqa: E402


def _site(bosses_killed, mythic=0, heroic=0):
    return {"island_completion": {
        "generated_at": "2026-07-27T06:13:00+00:00",
        "raid": {"slug": "manaforge-omega", "bosses_killed": bosses_killed,
                 "killed_by_difficulty": {"normal": 0, "heroic": heroic,
                                          "mythic": mythic},
                 "islands": []}}}


def _prev(bosses_killed, mythic=0, heroic=0, generated_at="2026-07-27T00:03:00+00:00"):
    return {"generated_at": generated_at,
            "raid": {"slug": "manaforge-omega", "bosses_killed": bosses_killed,
                     "killed_by_difficulty": {"normal": 0, "heroic": heroic,
                                              "mythic": mythic},
                     "islands": [{"id": "chimaerus-the-undreamt-god",
                                  "status": "conquered"}]}}


def test_zeroed_fetch_carries_the_previous_block_forward():
    site = _site(0)
    prev = _prev(9, mythic=4, heroic=9)
    assert carry_forward_raid(site, prev) is True
    raid = site["island_completion"]["raid"]
    assert raid["bosses_killed"] == 9
    assert raid["killed_by_difficulty"]["mythic"] == 4
    assert raid["carried_forward_from"] == "2026-07-27T00:03:00+00:00"
    assert raid["islands"][0]["status"] == "conquered"


def test_fresh_kills_are_never_overwritten():
    site = _site(3, mythic=1, heroic=3)
    assert carry_forward_raid(site, _prev(9, mythic=4, heroic=9)) is False
    assert site["island_completion"]["raid"]["bosses_killed"] == 3
    assert "carried_forward_from" not in site["island_completion"]["raid"]


def test_no_previous_block_leaves_the_honest_zeros():
    site = _site(0)
    assert carry_forward_raid(site, None) is False
    assert site["island_completion"]["raid"]["bosses_killed"] == 0


def test_previous_zeros_are_not_worth_carrying():
    site = _site(0)
    assert carry_forward_raid(site, _prev(0)) is False
    assert "carried_forward_from" not in site["island_completion"]["raid"]

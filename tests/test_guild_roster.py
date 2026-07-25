"""Roster resolution across authorities — union, never intersect.

These lock in the fix for the defect that lost Phyrthepali: the roster's
only live source was Warcraft Logs, whose member list is a by-product of
log uploads rather than a guild roster, and a member missing from it
vanished from the site with no signal at all.
"""

from guild_board.guild_roster import (
    member_key,
    merge_sources,
    resolve,
    roster_keys,
    wcl_roster_entries,
)


def _rio():
    return {
        "phyrthepali-bleeding-hollow": {
            "name": "Phyrthepali", "realm_slug": "bleeding-hollow",
            "rank": 99, "class": "Paladin", "spec": "Holy", "role": "healing"},
        "amrevenge-stormrage": {
            "name": "Amrevenge", "realm_slug": "stormrage", "rank": 5,
            "class": "Hunter", "spec": "Beast Mastery", "role": "dps"},
        "beroben-queldorei": {
            "name": "Beroben", "realm_slug": "queldorei", "rank": 7,
            "class": "Paladin", "spec": "Protection", "role": "tank"},
        "beroben-emerald-dream": {
            "name": "Beroben", "realm_slug": "emerald-dream", "rank": 4,
            "class": "Mage", "spec": "Arcane", "role": "dps"},
    }


def _wcl():
    # WCL has Amrevenge and both Berobens but NOT Phyrthepali — the real
    # 2026-07-22 shape — plus a member Raider.io has not crawled.
    return wcl_roster_entries([
        "amrevenge-stormrage", "beroben-queldorei", "beroben-emerald-dream",
        "digglio-area-52",
    ])


def test_member_key_keeps_accents_so_the_two_violences_stay_distinct():
    a = member_key("Viôlence", "bleeding-hollow")
    b = member_key("Violënce", "bleeding-hollow")
    assert a != b, "accent folding collapses two real, distinct characters"
    assert a == "viôlence-bleeding-hollow"


def test_the_two_berobens_are_two_members():
    members, _ = merge_sources({"raiderio": _rio()})
    assert "beroben-queldorei" in members
    assert "beroben-emerald-dream" in members
    assert members["beroben-queldorei"]["class"] == "Paladin"
    assert members["beroben-emerald-dream"]["class"] == "Mage"


def test_a_member_only_one_source_knows_about_is_kept():
    """The whole point. Phyrthepali is in Raider.io and not in WCL."""
    members, report = merge_sources({"raiderio": _rio(), "wcl_cache": _wcl()})
    assert "phyrthepali-bleeding-hollow" in members
    assert members["phyrthepali-bleeding-hollow"]["sources"] == ["raiderio"]
    # ...and the same is true in the other direction.
    assert "digglio-area-52" in members
    assert members["digglio-area-52"]["sources"] == ["wcl_cache"]
    assert report["roster_total"] == 5


def test_disagreement_is_reported_by_name_not_just_counted():
    _, report = merge_sources({"raiderio": _rio(), "wcl_cache": _wcl()})
    disputed = {d["key"] for d in report["disputed_members"]}
    assert "phyrthepali-bleeding-hollow" in disputed
    assert "digglio-area-52" in disputed
    # the report must name who vouched, so the gap is actionable
    row = next(d for d in report["disputed_members"]
               if d["key"] == "phyrthepali-bleeding-hollow")
    assert row["confirmed_by"] == ["raiderio"]
    assert row["rank"] == 99
    assert report["only_in_source"]["raiderio"] == ["phyrthepali-bleeding-hollow"]
    assert report["missing_from_source"]["wcl_cache"] == ["phyrthepali-bleeding-hollow"]


def test_an_unreachable_source_never_empties_the_roster():
    members, report = merge_sources(
        {"raiderio": None, "wcl_cache": _wcl()})
    assert len(members) == 4
    assert report["unreachable_sources"] == ["raiderio"]
    # With only one reachable source nothing is "disputed" — you cannot
    # disagree with yourself — but the gap is still stated.
    assert report["disputed_members"] == []


def test_a_richer_source_fills_fields_a_thinner_one_left_blank():
    members, _ = merge_sources({"raiderio": _rio(), "wcl_cache": _wcl()})
    amre = members["amrevenge-stormrage"]
    assert amre["sources"] == ["raiderio", "wcl_cache"]
    assert amre["class"] == "Hunter"      # wcl_cache carries None here
    assert amre["disputed"] is False


def test_resolve_unions_supplement_and_survives_a_dead_network(tmp_path):
    out = tmp_path / "recon.json"

    def boom(cfg):
        raise ValueError("raider.io down")

    members, report = resolve(
        {}, wcl_roster=["amrevenge-stormrage"],
        supplement=[{"name": "Phyrthepali", "realm_slug": "bleeding-hollow",
                     "class": "Paladin", "spec": "Holy", "role": "healing"}],
        raiderio_fetch=boom, report_path=str(out))

    assert roster_keys(members) == ["amrevenge-stormrage",
                                    "phyrthepali-bleeding-hollow"]
    assert "raiderio" in report["unreachable_sources"]
    assert "blizzard" in report["unreachable_sources"]
    assert out.exists(), "the reconciliation must land on disk to be read"


def test_bare_name_collisions_are_detected_and_named():
    """The two Berobens share one season_scores slot; one score is lost."""
    from guild_board.guild_roster import detect_name_collisions

    members, _ = merge_sources({"raiderio": _rio()})
    collisions = detect_name_collisions(members)
    assert collisions == {
        "beroben": ["beroben-emerald-dream", "beroben-queldorei"]}
    # a name held by exactly one character is not a collision
    assert "amrevenge" not in collisions


def test_the_two_violences_are_not_a_bare_name_collision():
    """They differ in the raw name, so name-keying keeps them apart. It is
    accent *folding* that collapses them, which member_key does not do."""
    from guild_board.guild_roster import detect_name_collisions

    members, _ = merge_sources({"raiderio": {
        "viôlence-bleeding-hollow": {"name": "Viôlence",
                                     "realm_slug": "bleeding-hollow"},
        "violënce-bleeding-hollow": {"name": "Violënce",
                                     "realm_slug": "bleeding-hollow"},
    }})
    assert len(members) == 2
    assert detect_name_collisions(members) == {}


def test_report_counts_are_internally_consistent():
    _, report = merge_sources({"raiderio": _rio(), "wcl_cache": _wcl()})
    assert (report["agreed_by_all_reachable_sources"]
            + len(report["disputed_members"]) == report["roster_total"])
    assert report["sources"] == {"raiderio": 4, "wcl_cache": 4}

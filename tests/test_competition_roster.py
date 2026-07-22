"""The merged roster (roster.json) as roster authority — name-realm keying.

These pin the fix for the name-collapse bug: two crewmates named Beroben
(a Mage on Emerald Dream, a Protection Paladin on Quel'dorei) were being
silently merged by every bare-name data path. The extract keys members
`name-realm` and owns the slug policy (short, accent-folded, ordinal only
on true collision); crew.py consumes its rows verbatim.
"""

from guild_board import crew, wanted


ROWS = [
    {"name": "Amrevenge", "realm": "Stormrage", "realm_slug": "stormrage",
     "key": "amrevenge-stormrage", "slug": "amrevenge", "class": "Hunter",
     "spec": "Beast Mastery", "role": "dps", "score": 3908.1, "rank": 1},
    {"name": "Beroben", "realm": "Emerald Dream", "realm_slug": "emerald-dream",
     "key": "beroben-emerald-dream", "slug": "beroben-emerald-dream",
     "class": "Mage", "spec": "Arcane", "role": "dps",
     "score": 2307.3, "rank": 64},
    {"name": "Beroben", "realm": "Quel'dorei", "realm_slug": "queldorei",
     "key": "beroben-queldorei", "slug": "beroben-queldorei",
     "class": "Paladin", "spec": "Protection", "role": "tank",
     "score": 1907.8, "rank": 74},
    # The supplement's entry: real member the pull missed. Role comes in
    # as "healing" (extract vocabulary), which must map to "healer".
    {"name": "Phyrthepali", "realm": "Bleeding Hollow",
     "realm_slug": "bleeding-hollow", "key": "phyrthepali-bleeding-hollow",
     "slug": "phyrthepali", "class": "Paladin", "spec": "Holy",
     "role": "healing", "score": None, "rank": None},
    # Zero must normalize to "no score yet" — never a real 0 (§5.6).
    {"name": "Stinkypinkie", "realm": "Dalaran", "realm_slug": "dalaran",
     "key": "stinkypinkie-dalaran", "slug": "stinkypinkie",
     "class": "Warrior", "spec": "Arms", "role": "dps", "score": 0, "rank": None},
]


def _build(**kw):
    kw.setdefault("competition", ROWS)
    kw.setdefault("manifest", {})
    return crew.build_crew({}, {}, **kw)


def test_both_berobens_stand_on_deck_with_their_own_scores():
    built = _build(limit=50)
    berobens = {m["slug"]: m for m in built if m["name"] == "Beroben"}
    assert set(berobens) == {"beroben-emerald-dream", "beroben-queldorei"}
    assert berobens["beroben-emerald-dream"]["score"] == 2307.3
    assert berobens["beroben-queldorei"]["score"] == 1907.8
    assert berobens["beroben-queldorei"]["role"] == "tank"
    # Ambiguous names may not borrow bare-name board_state data.
    assert berobens["beroben-emerald-dream"]["legacy_slug"] is None


def test_roster_is_authority_not_bare_name_scores():
    # A bare-name score for someone absent from the roster adds nobody.
    built = _build(season_scores={"ghostplayer": 2000.0}, limit=50)
    assert not any(m["name"] == "Ghostplayer" for m in built)
    stinky = next(m for m in built if m["slug"] == "stinkypinkie")
    assert stinky["score"] is None            # 0 normalized, not a score
    assert stinky["key"] == "stinkypinkie-dalaran"


def test_supplemented_member_is_a_full_member_with_role_mapped():
    built = _build(limit=50)
    phyr = next(m for m in built if m["slug"] == "phyrthepali")
    assert not phyr["parked"]                 # real member, not parked
    assert phyr["role"] == "healer"           # "healing" -> healer
    assert phyr["realm_slug"] == "bleeding-hollow"
    assert phyr["legacy_slug"] == "phyrthepali"  # unique name: records match


def test_locally_evidenced_but_off_roster_members_are_parked():
    rows = [r for r in ROWS if r["slug"] != "phyrthepali"]
    built = crew.build_crew({}, {}, competition=rows, manifest={}, limit=50)
    parked = [m for m in built if m.get("parked")]
    # DERIVED_CREW's phyrthepali is now absent from the roster: page only.
    assert any(m["slug"] == "phyrthepali" for m in parked)
    assert built[-1]["parked"] is True        # parked sort last


def test_wanted_board_excludes_parked_and_counts_the_real_crew():
    built = _build(limit=50)
    b = wanted.board(built, {"season_scores": {}})
    assert b["ranked_count"] == 3             # both Berobens + Amrevenge
    assert b["total_count"] == 5              # + Phyrthepali + Stinkypinkie
    scores = {e["slug"]: e["score"] for e in b["entries"]}
    assert scores["beroben-queldorei"] == 1907.8


def test_without_roster_legacy_behavior_is_unchanged():
    built = crew.build_crew({}, {}, season_scores={"rakdisc": 3529.2},
                            manifest={})
    rak = next(m for m in built if m["slug"] == "rakdisc")
    assert rak["score"] == 3529.2
    assert rak["legacy_slug"] == "rakdisc"    # bare-name data still matches

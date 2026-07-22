"""Verified current + next season content — the source of truth for the
Voyage Map islands, island completion, and anything else that needs the
real M+ pool or raid roster.

Why this module exists: the island roster was being read from
`raiderio.DUNGEON_NAME_FIXES`, which is a dungeon-NAME-normalisation table
that still held the War Within Season 1 pool — two expansions stale. Its
job (fixing Raider.io's spellings) and "what dungeons are we running this
season" are different responsibilities that had rotted into one dict.

Everything below was pulled live and verified on 2026-07-21 against:
  - https://raider.io/api/v1/mythic-plus/static-data?expansion_id=11
  - https://raider.io/api/v1/raiding/static-data?expansion_id=11
No credentials are needed for either endpoint. `season_slug` matches what
a live character profile returns under mythic_plus_scores_by_season.

This is additive: it does not modify voyage.py (shared with the front-end
team). voyage.build_islands() can migrate onto CURRENT_SEASON when the
front-end is ready; until then both exist and this one is authoritative.
"""

# The live season slug a character profile reports (season-mn-1). Kept here
# so a consumer can assert the data it fetched matches the season it thinks
# it is rendering.
CURRENT_SEASON_SLUG = "season-mn-1"
NEXT_SEASON_SLUG = "season-mn-2"


CURRENT_SEASON = {
    "slug": "season-mn-1",
    "name": "Midnight Season 1",
    "expansion": "Midnight",
    "starts_utc": "2026-03-24T15:00:00Z",
    "ends_utc": "2026-12-16T15:00:00Z",
    # M+ pool. challenge_mode_id is Blizzard's dungeon id, stable across
    # data sources; slug matches Raider.io.
    "dungeons": [
        {"name": "Algeth'ar Academy", "slug": "algethar-academy", "challenge_mode_id": 402},
        {"name": "Magisters' Terrace", "slug": "magisters-terrace", "challenge_mode_id": 558},
        {"name": "Maisara Caverns", "slug": "maisara-caverns", "challenge_mode_id": 560},
        {"name": "Nexus-Point Xenas", "slug": "nexuspoint-xenas", "challenge_mode_id": 559},
        {"name": "Pit of Saron", "slug": "pit-of-saron", "challenge_mode_id": 556},
        {"name": "Seat of the Triumvirate", "slug": "seat-of-the-triumvirate", "challenge_mode_id": 239},
        {"name": "Skyreach", "slug": "skyreach", "challenge_mode_id": 161},
        {"name": "Windrunner Spire", "slug": "windrunner-spire", "challenge_mode_id": 557},
    ],
    # Current raid tier. The API name is a placeholder
    # ("MN Tier 1 (VS / DR / MQD)"); display_name is our human label.
    "raid": {
        "slug": "tier-mn-1",
        "raid_id": 16340,
        "api_name": "MN Tier 1 (VS / DR / MQD)",
        "display_name": "Voidspire Sanctum",
        "starts_utc": "2026-03-17T15:00:00Z",
        "bosses": [
            {"order": 1, "name": "Imperator Averzian", "slug": "imperator-averzian"},
            {"order": 2, "name": "Vorasius", "slug": "vorasius"},
            {"order": 3, "name": "Fallen-King Salhadaar", "slug": "fallenking-salhadaar"},
            {"order": 4, "name": "Vaelgor & Ezzorak", "slug": "vaelgor-ezzorak"},
            {"order": 5, "name": "Lightblinded Vanguard", "slug": "lightblinded-vanguard"},
            {"order": 6, "name": "Crown of the Cosmos", "slug": "crown-of-the-cosmos"},
            {"order": 7, "name": "Chimaerus the Undreamt God", "slug": "chimaerus-the-undreamt-god"},
            {"order": 8, "name": "Belo'ren, Child of Al'ar", "slug": "beloren-child-of-alar"},
            {"order": 9, "name": "Midnight Falls", "slug": "midnight-falls"},
        ],
    },
}


# Published but not yet live (opens 2026-12-16). Here so the front-end can
# build the Season 2 extension against a real roster, and so the map's
# hard S1 end date has a documented successor.
NEXT_SEASON = {
    "slug": "season-mn-2",
    "name": "Midnight Season 2",
    "expansion": "Midnight",
    "starts_utc": "2026-12-16T15:00:00Z",
    "dungeons": [
        {"name": "Altar of Fangs", "slug": "altar-of-fangs", "challenge_mode_id": 588},
        {"name": "Den of Nalorakk", "slug": "den-of-nalorakk", "challenge_mode_id": 586},
        {"name": "Kings' Rest", "slug": "kings-rest", "challenge_mode_id": 249},
        {"name": "Murder Row", "slug": "murder-row", "challenge_mode_id": 587},
        {"name": "Ruby Life Pools", "slug": "ruby-life-pools", "challenge_mode_id": 399},
        {"name": "Temple of Sethraliss", "slug": "temple-of-sethraliss", "challenge_mode_id": 250},
        {"name": "The Blinding Vale", "slug": "the-blinding-vale", "challenge_mode_id": 584},
        {"name": "Voidscar Arena", "slug": "voidscar-arena", "challenge_mode_id": 585},
    ],
    "raid": {
        "slug": "the-venomous-abyss",
        "raid_id": 16915,
        "display_name": "The Venomous Abyss",
        "starts_utc": "2026-12-16T15:00:00Z",
        "bosses": [
            {"order": 1, "name": "Nek'zali, the Soulcoiler", "slug": "nekzali-the-soulcoiler"},
            {"order": 2, "name": "Entombed Sentinels", "slug": "entombed-sentinels"},
            {"order": 3, "name": "Vashnik the Malignant", "slug": "vashnik-the-malignant"},
            {"order": 4, "name": "The Lost Explorers", "slug": "the-lost-explorers"},
            {"order": 5, "name": "Sszorak", "slug": "sszorak"},
            {"order": 6, "name": "The Twin Fangs", "slug": "the-twin-fangs"},
            {"order": 7, "name": "Zul'jan", "slug": "zuljan"},
            {"order": 8, "name": "Ula'tek", "slug": "ulatek"},
        ],
    },
}


def dungeon_names(season=None):
    """Set of display names for a season's M+ pool (default current)."""
    season = season or CURRENT_SEASON
    return {d["name"] for d in season["dungeons"]}


def boss_names(season=None):
    """Ordered list of the season raid's boss display names."""
    season = season or CURRENT_SEASON
    return [b["name"] for b in season["raid"]["bosses"]]

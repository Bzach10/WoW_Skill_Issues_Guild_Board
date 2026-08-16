"""Verified season content — the source of truth for the Voyage Map islands,
island completion, and anything else that needs the real M+ pool or raid
roster.

Why this module exists: the island roster was being read from
`raiderio.DUNGEON_NAME_FIXES`, which is a dungeon-NAME-normalisation table
that still held the War Within Season 1 pool — two expansions stale. Its
job (fixing Raider.io's spellings) and "what dungeons are we running this
season" are different responsibilities that had rotted into one dict.

WHY THIS IS DATE-DRIVEN. Season identity used to be a hand-edited constant:
`CURRENT_SEASON` was literally the S1 dict, and rolling over meant a human
noticing the date and shipping a commit. That is the shape of the
2026-07-28 mixed-vintage incident (docs/DATA_FLOW.md §2) — a truth that
existed upstream while the ship kept publishing the old one. So the module
now RESOLVES: `CURRENT_SEASON` is whichever authored season's `starts_utc`
is the latest one at or before now (UTC). Nobody has to remember; the flip
happens on the season's own date, in every workflow, at import.

All `starts_utc`/`ends_utc` are the **US** boundary, matching the guild's
`region: us` in config.yml. Raider.io publishes per-region boundaries; EU
and the rest are ~13h later and are deliberately not modelled — one guild,
one region, one clock.

Everything below was pulled live and verified — no credentials needed for
either endpoint — against:
  - https://raider.io/api/v1/mythic-plus/static-data?expansion_id=11
  - https://raider.io/api/v1/raiding/static-data?expansion_id=11
S1 content was verified 2026-07-21; S1's `ends_utc`, and every field of S2,
were re-verified 2026-08-16 (tests/test_season.py pins the shape).
`season_slug` matches what a live character profile returns under
mythic_plus_scores_by_season.

This is additive: it does not modify voyage.py (shared with the front-end
team). voyage.build_islands() can migrate onto CURRENT_SEASON when the
front-end is ready; until then both exist and this one is authoritative.
"""

import os
from datetime import datetime, timezone

# Set to a season slug to pin resolution regardless of the clock — for a CI
# dispatch that must rebuild a specific season's caches, or a local repro of
# a past bundle. Unknown slugs raise rather than silently falling back to
# the date, because a typo that quietly does the ordinary thing is exactly
# the failure this module exists to prevent.
SEASON_SLUG_ENV = "WIPEFEST_SEASON_SLUG"


SEASON_MN_1 = {
    "slug": "season-mn-1",
    "name": "Midnight Season 1",
    "expansion": "Midnight",
    "starts_utc": "2026-03-24T15:00:00Z",
    # Verified live 2026-08-16: raider.io ends season-mn-1 (us) at
    # 2026-08-18T15:00:00Z — the same instant season-mn-2 starts. The
    # 2026-12-16 previously carried here was never a published date.
    "ends_utc": "2026-08-18T15:00:00Z",
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
    # Season raid tier. The API name is a placeholder
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
    # Bonus raid running ALONGSIDE the tier — verified live 2026-07-24
    # against the same raiding static-data endpoint. The parse sweep
    # captures each of these as an extra WCL zone (see refresh_parses);
    # they never feed the Emperor Index, which is a current-tier stat.
    "extra_raids": [
        {"slug": "sporefall", "raid_id": 8062, "display_name": "Sporefall",
         "bosses": [{"order": 1, "name": "Rotmire", "slug": "rotmire"}]},
    ],
}


# Verified live 2026-08-16 against both static-data endpoints. Every field
# below was checked against the API response rather than carried forward:
# the pre-authored draft of this dict had a 2026-12-16 start (a date
# raider.io never published), boss 7 named "Zul'jan" (raider.io says "The
# Coiled Altar", encounter 197169), bosses 3 and 4 transposed, and no
# extra_raids at all.
SEASON_MN_2 = {
    "slug": "season-mn-2",
    "name": "Midnight Season 2",
    "expansion": "Midnight",
    # blizzard_season_id 18, is_main_season true.
    "starts_utc": "2026-08-18T15:00:00Z",
    # Raider.io's open-ended placeholder for a season with no announced
    # end. Not a real date — do not print it as one.
    "ends_utc": "2030-01-01T00:00:00Z",
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
    # Raider.io's `name` for this raid is already the human label, so there
    # is no api_name placeholder to carry (unlike tier-mn-1). The parse
    # sweep resolves the WCL zone by this display_name and then by each
    # boss name — these strings are load-bearing, not decoration.
    "raid": {
        "slug": "the-venomous-abyss",
        "raid_id": 16915,
        "display_name": "The Venomous Abyss",
        # The same instant as the M+ flip — this tier does NOT lag the
        # season, verified against the raid's own `starts` field.
        "starts_utc": "2026-08-18T15:00:00Z",
        # Order is raider.io's own encounter order.
        "bosses": [
            {"order": 1, "name": "Nek'zali the Soulcoiler", "slug": "nekzali-the-soulcoiler"},
            {"order": 2, "name": "Entombed Sentinels", "slug": "entombed-sentinels"},
            {"order": 3, "name": "The Lost Explorers", "slug": "the-lost-explorers"},
            {"order": 4, "name": "Vashnik the Malignant", "slug": "vashnik-the-malignant"},
            {"order": 5, "name": "Sszorak", "slug": "sszorak"},
            {"order": 6, "name": "The Twin Fangs", "slug": "the-twin-fangs"},
            {"order": 7, "name": "The Coiled Altar", "slug": "the-coiled-altar"},
            {"order": 8, "name": "Ula'tek", "slug": "ulatek"},
        ],
    },
    # S2's Sporefall-equivalent. Confirmed, not guessed: the raiding
    # static-data endpoint starts the-tidebound-grotto at exactly
    # 2026-08-18T15:00:00Z (us) — the same instant sporefall ENDS and the
    # new tier begins — with the same single-encounter shape sporefall had.
    "extra_raids": [
        {"slug": "the-tidebound-grotto", "raid_id": 16671,
         "display_name": "The Tidebound Grotto",
         "bosses": [{"order": 1, "name": "Nymrissa Wavecaller",
                     "slug": "nymrissa-wavecaller"}]},
    ],
}


# Every authored season, oldest first. Resolution walks this.
SEASONS = (SEASON_MN_1, SEASON_MN_2)


def _parse_utc(stamp):
    """An ISO stamp ending in Z as an aware UTC datetime."""
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def season_by_slug(slug):
    """The authored season with this slug, or None."""
    for entry in SEASONS:
        if entry["slug"] == slug:
            return entry
    return None


def season_for(ts=None):
    """The season in effect at `ts` (default: now, UTC).

    The latest authored season whose `starts_utc` is at or before `ts`.
    Before the first season starts, the earliest is returned rather than
    None — a board with no season at all has nothing honest to render, and
    the earliest is the only defensible answer.
    """
    if ts is None:
        ts = datetime.now(timezone.utc)
    elif isinstance(ts, str):
        ts = _parse_utc(ts)
    elif ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    started = [s for s in SEASONS if _parse_utc(s["starts_utc"]) <= ts]
    return started[-1] if started else SEASONS[0]


def next_season_after(season):
    """The season authored to follow `season`, or None when it is the last
    one on the books. None is the honest answer — it means nobody has
    published the successor yet, not that there is no future."""
    for i, entry in enumerate(SEASONS):
        if entry["slug"] == season["slug"]:
            return SEASONS[i + 1] if i + 1 < len(SEASONS) else None
    return None


def _resolve_current():
    """CURRENT_SEASON at import: the env pin if set, else the clock."""
    pinned = (os.environ.get(SEASON_SLUG_ENV) or "").strip()
    if pinned:
        season = season_by_slug(pinned)
        if season is None:
            known = ", ".join(s["slug"] for s in SEASONS)
            raise ValueError(
                f"{SEASON_SLUG_ENV}={pinned!r} is not an authored season "
                f"(known: {known}). Refusing to fall back to the date — a "
                f"pin that silently does something else is worse than a "
                f"crash.")
        return season
    return season_for()


# Resolved once, at import. Every consumer reads `season_mod.CURRENT_SEASON`
# and keeps working unchanged; the value is simply no longer hand-edited.
CURRENT_SEASON = _resolve_current()
NEXT_SEASON = next_season_after(CURRENT_SEASON)

# The live season slug a character profile reports. Kept here so a consumer
# can assert the data it fetched matches the season it thinks it is
# rendering. NEXT_SEASON_SLUG is None once CURRENT_SEASON is the last
# authored season.
CURRENT_SEASON_SLUG = CURRENT_SEASON["slug"]
NEXT_SEASON_SLUG = NEXT_SEASON["slug"] if NEXT_SEASON else None


def dungeon_names(season=None):
    """Set of display names for a season's M+ pool (default current)."""
    season = season or CURRENT_SEASON
    return {d["name"] for d in season["dungeons"]}


def boss_names(season=None):
    """Ordered list of the season raid's boss display names."""
    season = season or CURRENT_SEASON
    return [b["name"] for b in season["raid"]["bosses"]]

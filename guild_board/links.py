"""Per-player profile links that actually resolve.

The guild is cross-realm: `config.yml`'s `guild.realm_slug` is the realm
the GUILD is on, but most of the roster is not on it. At the time of
writing, 95 of 135 cached members (70%, across 37 realms) live somewhere
else — Rakdisc on proudmoore, Amrevenge on stormrage, Floofwall on
queldorei.

The board used to build every player's link from the guild realm, which
produced a URL for a character that does not exist:

    https://www.warcraftlogs.com/character/us/bleeding-hollow/rakdisc

Verified against Raider.io's API — the guild-realm form returns
400 "Could not find requested character" while the real realm returns the
character. That is the blank page Zach hit.

So: resolve each player's realm from the roster cache, which already
stores "<name>-<realm>" per member, and only fall back to the guild realm
when we genuinely have nothing better.
"""

import logging

logger = logging.getLogger(__name__)

WCL_CHARACTER = "https://www.warcraftlogs.com/character/{region}/{realm}/{name}"
RIO_CHARACTER = "https://raider.io/characters/{region}/{realm}/{name}"


def realm_index(roster_members):
    """{lowercased character name: realm slug} from the roster cache.

    A name that appears on more than one realm is ambiguous — we keep the
    first and say so, rather than silently picking a random one.
    """
    index = {}
    for entry in roster_members or []:
        if not isinstance(entry, str) or "-" not in entry:
            continue
        name, realm = entry.split("-", 1)
        name, realm = name.strip().lower(), realm.strip().lower()
        if not name or not realm:
            continue
        if name in index and index[name] != realm:
            logger.info("Character %r exists on both %s and %s; linking to %s.",
                        name, index[name], realm, index[name])
            continue
        index.setdefault(name, realm)
    return index


def realm_for(name, index, guild_realm=None):
    """The realm we believe this character is on."""
    return (index or {}).get((name or "").strip().lower()) or (guild_realm or "")


def character_url(name, index, region="us", guild_realm=None, site="wcl"):
    """A profile URL for one player, or None when we cannot build a real
    one. Returning None is deliberate: a link that goes nowhere is worse
    than no link, because it looks like the board is broken."""
    name = (name or "").strip()
    if not name:
        return None
    realm = realm_for(name, index, guild_realm)
    if not realm:
        return None
    template = RIO_CHARACTER if site == "raiderio" else WCL_CHARACTER
    return template.format(region=(region or "us").lower(), realm=realm,
                           name=name.lower())


def profile_urls(roster_members, region="us", guild_realm=None, site="wcl"):
    """{lowercased name: url} for everyone we can resolve a realm for."""
    index = realm_index(roster_members)
    out = {}
    for name in index:
        url = character_url(name, index, region, guild_realm, site)
        if url:
            out[name] = url
    return out


def unresolved(names, index):
    """Which of these names we have no realm for — surfaced so a missing
    roster entry is visible rather than quietly linking to the wrong
    realm."""
    return sorted({(n or "").strip().lower() for n in names or []
                   if (n or "").strip().lower() not in (index or {})} - {""})

"""THE CARD DATA LIMB -- the WHOLE Blizzard Profile API, per character, slimmed.

Why this exists, beside blizzard.py
-----------------------------------
blizzard.py answers ONE question well: "what does this character look like?"
(race/class/spec + the transmog render + the visible slots the art pipeline
maps onto layers). It deliberately throws away everything else the same HTTP
responses already carried -- level, faction, guild rank, item level, the whole
stats panel -- because the cast-art pipeline had no use for them.

The trading card does. A card face wants a GEAR line, a HISTORY line, a TITLE
line, a CRAFT line, and the honest weird numbers a game can turn into costs
and abilities. That is a different read of the same API, with a different
slimming policy, so it gets its own module and its own cache rather than
widening the one the live cast art depends on. Nothing here is imported by
blizzard.py, main.py, html_board.py or build_site_data.py: this limb can fail
whole and the board still ships.

THE RATE-LIMIT MATH (why the endpoint set is what it is)
--------------------------------------------------------
Blizzard's documented client budget is 36,000 requests/hour and 100
requests/second. The set below is 16 requests per character (17 for a
character with a keystone season). At the 156-entry roster that is

    156 x 16 = 2,496 requests  ==  6.9% of one hour's budget

and, with WORKERS parallel fetches at ~250ms each, ~90 seconds of wall clock.
The binding constraint is therefore NOT the API -- it is the CACHE FILE. The
raw JSON for those endpoints is ~2MB per character (a full /achievements is
half a megabyte on its own, /collections/pets can exceed one), which is
~300MB per run and uncommittable. So every endpoint is SLIMMED at fetch time
by a named slimmer below, to a target of ~2.5KB per character (~0.4MB for the
roster), and the raw response is never persisted.

WHAT IS DELIBERATELY NOT FETCHED (and why -- so the next reader does not
re-litigate it): /quests/completed (thousands of ids; the completed COUNT is
already in the statistics panel), /reputations (large, and renown/paragon says
little on a card), /appearance (character-media already gives the render),
/collections/transmogs (enormous), /collections/toys + /heirlooms (flavour
with no card slot), /soulbinds (dead Shadowlands data), /hunter-pets (one
class), /status (the 404 path already covers "not visible to us").

HONESTY
-------
Every endpoint can fail independently and a failure is RECORDED, never
guessed: each character carries `seams` naming the endpoints that did not
answer, and the cache carries a top-level `endpoints` inventory with the
per-endpoint hit/miss counts across the whole run. An absent number is absent;
nothing is zero-filled.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

from guild_board.blizzard import (
    BLIZZARD_API_HOSTS,
    DEFAULT_LOCALE,
    get_blizzard_token,
)
from guild_board.config import split_name_realm

logger = logging.getLogger(__name__)

CARD_CACHE_DEFAULT = "blizzard_card_cache.json"
CATALOG_DEFAULT = "blizzard_statistic_catalog.json"

# Parallel character fetches. 8 x ~4 req/s = ~32 req/s, comfortably under the
# documented 100/s ceiling with room for the runner's own jitter.
WORKERS = 8

# Cache schema version -- bump when the SHAPE of a character record changes in
# a way a consumer must react to. Additive fields never bump it.
CARD_CACHE_VERSION = 1

_local = threading.local()


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _session():
    """One requests.Session per worker thread (connection reuse without
    sharing a pool across threads)."""
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        _local.session = s
    return s


def _get(token, region, path, params, report=None, label=None):
    """GET one Profile API endpoint.

    Returns the decoded JSON, or None for every "we cannot see this" case
    (401/403/404) and for a transport failure -- one private character or one
    flaky endpoint never aborts a roster sweep. Each outcome is tallied into
    `report` under `label` so the run can state, afterwards, exactly which
    endpoints answered and which did not.
    """
    host = BLIZZARD_API_HOSTS.get((region or "us").lower(), BLIZZARD_API_HOSTS["us"])
    status = "error"
    try:
        resp = _session().get(
            f"{host}{path}",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if resp.status_code in (401, 403, 404):
            status = f"http_{resp.status_code}"
            return None
        if resp.status_code == 429:
            status = "http_429"
            logger.warning("Blizzard rate limit hit on %s", label or path)
            return None
        resp.raise_for_status()
        status = "ok"
        return resp.json()
    except (requests.RequestException, ValueError):
        logger.warning("Blizzard fetch failed: %s", label or path, exc_info=True)
        return None
    finally:
        if report is not None and label:
            report.setdefault(label, {}).setdefault(status, 0)
            report[label][status] += 1


def _name(obj):
    """`{"name": "Blood", "id": 250}` -> "Blood"; anything else -> None.

    The API returns this shape for every enum-ish field, and a few of them are
    plain strings in older payloads, so both are tolerated."""
    if isinstance(obj, dict):
        return obj.get("name")
    if isinstance(obj, str):
        return obj
    return None


def _iso(ms):
    """A Blizzard epoch-milliseconds timestamp -> an ISO-8601 UTC string, or
    None. Card surfaces print dates, never epoch integers."""
    if not isinstance(ms, (int, float)) or ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# THE CURATION LISTS -- what a card actually wants out of the huge panels.
#
# Matched on the en_US NAME, not on ids: the ids are undocumented and drift
# between expansions, while the names are what the card prints anyway. Every
# match is a case-insensitive substring test, so "Total deaths" catches
# "Total deaths" wherever Blizzard files it in the category tree.
#
# THE CATALOG IS THE PROOF: the run also writes the COMPLETE flattened
# statistic tree for one character (blizzard_statistic_catalog.json), so the
# next curation pass reads real available names instead of guessing.
# ---------------------------------------------------------------------------

# The honest weird numbers. Keyed by the card-facing name we want to print.
STAT_WANTED = {
    "deaths": "total deaths",
    "deaths_from_falling": "deaths from falling",
    "killing_blows": "total killing blows",
    "killing_blows_pvp": "total killing blows in a battleground",
    "quests_completed": "quests completed",
    "daily_quests_completed": "daily quests completed",
    "dungeons_entered": "total number of dungeons entered",
    "raids_entered": "total number of raids entered",
    "gold_looted": "gold looted",
    "gold_from_quests": "gold from quest rewards",
    "hearthstone_used": "number of times hearthstone used",
    "flight_paths_taken": "flight paths taken",
    "duels_won": "duels won",
    "duels_lost": "duels lost",
    "fish_caught": "fish caught",
    "food_eaten": "total food eaten",
    "drinks_consumed": "total drinks consumed",
    "hugs": "total hugs",
    "waves": "total waves",
    "epic_items_looted": "epic items looted",
    "total_damage_done": "largest hit dealt",
    "largest_heal": "largest heal cast",
    "highest_fall_survived": "highest fall survived",
}

# Achievements that mean something on a card: progression proof, M+ proof,
# PvP proof, and the loud one-offs. Substring, case-insensitive.
ACH_NOTABLE = (
    "cutting edge",
    "ahead of the curve",
    "realm first",
    "keystone master",
    "keystone hero",
    "keystone conqueror",
    "keystone legend",
    "mythic:",
    "glory of the",
    "gladiator",
    "hero of the",
    "the undaunted",
    "dungeon hero",
    "conqueror of azeroth",
)
ACH_NOTABLE_MAX = 24
TITLES_MAX = 20
GEAR_KEEP_SLOTS = (
    "HEAD", "NECK", "SHOULDER", "BACK", "CHEST", "WRIST", "HANDS", "WAIST",
    "LEGS", "FEET", "FINGER_1", "FINGER_2", "TRINKET_1", "TRINKET_2",
    "MAIN_HAND", "OFF_HAND",
)


# ---------------------------------------------------------------------------
# THE SLIMMERS -- one per endpoint. Each takes the raw JSON and returns the
# committed shape. A slimmer NEVER invents: a field the payload does not carry
# comes back absent, and the caller records the endpoint in `seams`.
# ---------------------------------------------------------------------------

def slim_summary(d):
    """/profile/wow/character/{realm}/{name} -- the card's identity block.

    This is the single richest response in the set and the one blizzard.py
    was already paying for and discarding: level, faction, guild + rank,
    achievement points, BOTH item levels, and the last-login stamp that tells
    a card whether its render is current."""
    guild = d.get("guild") or {}
    return {
        "name": d.get("name"),
        "id": d.get("id"),
        "level": d.get("level"),
        "race": _name(d.get("race")),
        "gender": _name(d.get("gender")),
        "class": _name(d.get("character_class")),
        "class_id": (d.get("character_class") or {}).get("id"),
        "spec": _name(d.get("active_spec")),
        "faction": _name(d.get("faction")),
        "title": _name(d.get("active_title")),
        "guild": guild.get("name"),
        "guild_realm": _name(guild.get("realm")),
        "achievement_points": d.get("achievement_points"),
        "item_level_equipped": d.get("equipped_item_level"),
        "item_level_average": d.get("average_item_level"),
        "last_login": _iso(d.get("last_login_timestamp")),
        "covenant": _name((d.get("covenant_progress") or {}).get("chosen_covenant")),
    }


def slim_specializations(d):
    """/specializations -- the active spec plus every spec the character has
    talents saved for (a card's "also plays" line, and the rules lane's hook
    for a dual-role card)."""
    active = _name(d.get("active_specialization"))
    known = []
    for entry in d.get("specializations") or []:
        nm = _name(entry.get("specialization"))
        if nm:
            known.append(nm)
    return {
        "active": active,
        "known": sorted(set(known)),
        "hero_talent": _name(d.get("active_hero_talent_tree")),
    }


def slim_media(d):
    """/character-media -- the renders. Already fetched by blizzard.py; kept
    here so a card record is self-contained."""
    assets = {a.get("key"): a.get("value")
              for a in d.get("assets") or [] if a.get("key")}
    return {
        "avatar": assets.get("avatar"),
        "inset": assets.get("inset"),
        "render": assets.get("main-raw") or assets.get("main"),
    }


def slim_equipment(d):
    """/equipment -- THE GEAR LINE.

    Per slot: what it is, how good it is, whether it is enchanted, how many
    sockets are filled. Blizzard renders the item level as a display string
    with the upgrade track ("Hero 6/6"), which is exactly the flavour a card
    wants, so both the integer and the display string are kept."""
    items = []
    ilvls = []
    enchanted = sockets = gemmed = 0
    for e in d.get("equipped_items") or []:
        slot = (e.get("slot") or {}).get("type")
        if slot not in GEAR_KEEP_SLOTS:
            continue
        lvl = (e.get("level") or {}).get("value")
        if isinstance(lvl, int):
            ilvls.append(lvl)
        ench = [x.get("display_string") for x in e.get("enchantments") or []
                if x.get("display_string")]
        if ench:
            enchanted += 1
        socks = e.get("sockets") or []
        sockets += len(socks)
        gemmed += sum(1 for s in socks if s.get("item"))
        items.append({
            "slot": slot,
            "name": e.get("name"),
            "item_id": (e.get("item") or {}).get("id"),
            "quality": _name(e.get("quality")),
            "item_level": lvl,
            "item_level_display": (e.get("level") or {}).get("display_string"),
            "subclass": _name(e.get("item_subclass")),
            "enchant": ench[0] if ench else None,
            "sockets": len(socks),
            "gems": [_name(s.get("item") or {}) for s in socks if s.get("item")],
            "transmog": ((e.get("transmog") or {}).get("item") or {}).get("name"),
            "is_set_piece": bool(e.get("set")),
        })
    items.sort(key=lambda i: GEAR_KEEP_SLOTS.index(i["slot"]))
    best = max(items, key=lambda i: (i["item_level"] or 0), default=None)
    return {
        "items": items,
        "slots_filled": len(items),
        "slots_enchanted": enchanted,
        "sockets_total": sockets,
        "sockets_gemmed": gemmed,
        # The highest-ilvl piece: a card's natural "signature item".
        "best_piece": ({"slot": best["slot"], "name": best["name"],
                        "item_level": best["item_level"],
                        "quality": best["quality"]} if best else None),
        "set_pieces": sum(1 for i in items if i["is_set_piece"]),
        "legendary_pieces": sum(1 for i in items if i["quality"] == "Legendary"),
    }


def slim_statistics(d):
    """/statistics -- the STATS PANEL: everything a game engine would call
    hit points, attack, and defense, straight off the character sheet.

    This is the endpoint that makes a card game possible on real data: health
    is a real number, the secondary spread is a real spread, and armour and
    the avoidances are a real defensive profile."""
    def _v(key):
        val = d.get(key)
        if isinstance(val, dict):
            return val.get("value")
        return val

    return {
        "health": d.get("health"),
        "power": d.get("power"),
        "power_type": _name(d.get("power_type")),
        "primary": {
            "strength": _v("strength"),
            "agility": _v("agility"),
            "intellect": _v("intellect"),
            "stamina": _v("stamina"),
        },
        "secondary": {
            "critical_strike": _v("melee_crit"),
            "haste": _v("spell_haste"),
            "mastery": _v("mastery"),
            "versatility": d.get("versatility"),
            "versatility_damage_done_bonus": d.get("versatility_damage_done_bonus"),
            "versatility_damage_taken_bonus": d.get("versatility_damage_taken_bonus"),
        },
        "defense": {
            "armor": _v("armor"),
            "dodge": _v("dodge"),
            "parry": _v("parry"),
            "block": _v("block"),
            "avoidance": _v("avoidance"),
        },
        "utility": {
            "leech": _v("lifesteal"),
            "speed": _v("speed"),
        },
        "attack_power": d.get("attack_power"),
        "spell_power": d.get("spell_power"),
        "mana_regen": d.get("mana_regen"),
        "main_hand_dps": d.get("main_hand_dps"),
        "off_hand_dps": d.get("off_hand_dps"),
    }


def _flatten_statistics(d):
    """The achievement-statistics tree -> a flat {name: value} map.

    The payload nests categories inside categories to arbitrary depth; a card
    only ever wants leaves. Returned whole for the catalog, curated for the
    per-character record."""
    flat = {}

    def walk(node):
        for s in node.get("statistics") or []:
            nm = s.get("name")
            if nm is not None and s.get("quantity") is not None:
                flat[nm] = s["quantity"]
        for sub in node.get("sub_categories") or []:
            walk(sub)

    for cat in d.get("categories") or []:
        walk(cat)
    walk(d)
    return flat


def slim_achievement_statistics(d):
    """/achievements/statistics -- THE HONEST WEIRD NUMBERS.

    Deaths, killing blows, quests, hugs, fish. A card game loves these
    precisely because nobody optimises them: they are a real record of how a
    person actually played. Curated by NAME against STAT_WANTED; a statistic
    the account has never recorded is simply absent, never zero."""
    flat = _flatten_statistics(d)
    lowered = {k.lower(): v for k, v in flat.items()}
    out = {}
    for card_key, want in STAT_WANTED.items():
        for name, value in lowered.items():
            if want == name or want in name:
                out[card_key] = int(value) if float(value).is_integer() else value
                break
    return {"values": out, "available": len(flat)}


def slim_achievements(d):
    """/achievements -- THE HISTORY LINE.

    Points and count are the headline; the notable list is the flavour and
    the rarity signal (a Cutting Edge is a different card from a Keystone
    Master). `most_recent` gives every card a live "last earned" line that
    changes week to week without any authoring."""
    entries = []
    for a in d.get("achievements") or []:
        nm = (a.get("achievement") or {}).get("name")
        ts = a.get("completed_timestamp")
        if nm:
            entries.append((nm, ts))

    notable = []
    for nm, ts in entries:
        low = nm.lower()
        if any(pat in low for pat in ACH_NOTABLE):
            notable.append({"name": nm, "earned": _iso(ts)})
    notable.sort(key=lambda a: (a["earned"] or "", a["name"]), reverse=True)

    dated = [(ts, nm) for nm, ts in entries if isinstance(ts, (int, float)) and ts > 0]
    dated.sort()
    return {
        "points": d.get("total_points"),
        "count": d.get("total_quantity"),
        "notable": notable[:ACH_NOTABLE_MAX],
        "notable_total": len(notable),
        "most_recent": ({"name": dated[-1][1], "earned": _iso(dated[-1][0])}
                        if dated else None),
        "first_earned": _iso(dated[0][0]) if dated else None,
    }


def slim_titles(d):
    """/titles -- THE TITLE LINE. Pure flavour gold: "the Kingslayer",
    "Battlelord", "Bane of the Fallen King". The active title is what the
    card prints under the name; the collection is an ability hook."""
    names = sorted({t.get("name") for t in d.get("titles") or [] if t.get("name")})
    return {
        "active": _name(d.get("active_title")),
        "count": len(names),
        "sample": names[:TITLES_MAX],
    }


def slim_keystone_index(d):
    """/mythic-keystone-profile -- current period runs + the season list.

    The season hrefs are what the season fetch below needs; only the ids are
    kept, since a href is a credentialed URL and not card data."""
    seasons = []
    for s in d.get("seasons") or []:
        if isinstance(s, dict) and s.get("id") is not None:
            seasons.append(s["id"])
    period = d.get("current_period") or {}
    runs = period.get("best_runs") or []
    return {
        "seasons": sorted(seasons),
        "current_period_id": (period.get("period") or {}).get("id"),
        "current_period_runs": len(runs),
        "current_mythic_rating": (d.get("current_mythic_rating") or {}).get("rating"),
    }


def slim_keystone_season(d):
    """/mythic-keystone-profile/season/{id} -- THE KEYSTONE LINE.

    Raider.io already gives us a season SCORE; this gives the runs behind it:
    which dungeon, what level, timed or not, and the rating each one earned.
    That is what turns "3000 io" into a card that names a real best key."""
    runs = []
    for r in d.get("best_runs") or []:
        dungeon = _name(r.get("dungeon"))
        runs.append({
            "dungeon": dungeon,
            "level": r.get("keystone_level"),
            "timed": r.get("is_completed_within_time"),
            "rating": (r.get("mythic_rating") or {}).get("rating"),
            "completed": _iso(r.get("completed_timestamp")),
            "duration_ms": r.get("duration"),
            "affixes": [_name(a) for a in r.get("keystone_affixes") or []],
        })
    runs.sort(key=lambda r: (-(r["level"] or 0), r["dungeon"] or ""))
    return {
        "season_id": (d.get("season") or {}).get("id"),
        "rating": (d.get("mythic_rating") or {}).get("rating"),
        "runs_total": len(runs),
        "best_runs": runs[:8],
        "highest_level": runs[0]["level"] if runs else None,
        "timed_count": sum(1 for r in runs if r.get("timed")),
    }


def slim_professions(d):
    """/professions -- THE CRAFT LINE, and the best ability hooks in the whole
    API. "Blacksmithing 100/100" is a card that can forge; "Fishing 25/100" is
    a joke a card can tell about itself."""
    def rows(key):
        out = []
        for p in d.get(key) or []:
            pname = _name(p.get("profession"))
            tiers = p.get("tiers") or []
            best = None
            for t in tiers:
                skill = t.get("skill_points")
                if best is None or (skill or 0) > (best.get("skill") or 0):
                    best = {"tier": _name(t.get("tier")),
                            "skill": skill,
                            "max": t.get("max_skill_points"),
                            "recipes": len(t.get("known_recipes") or [])}
            if pname:
                out.append({"name": pname, **(best or {})})
        out.sort(key=lambda r: r["name"])
        return out

    return {"primaries": rows("primaries"), "secondaries": rows("secondaries")}


def slim_mounts(d):
    """/collections/mounts -- the COUNT only. The list is hundreds of entries
    and no card prints it; the count is a real collector stat."""
    return {"count": len(d.get("mounts") or [])}


def slim_pets(d):
    """/collections/pets -- count, plus the highest-level pet as one flavour
    line. The raw list can exceed a megabyte, so nothing else is kept."""
    pets = d.get("pets") or []
    best = None
    for p in pets:
        lvl = p.get("level") or 0
        if best is None or lvl > (best.get("level") or 0):
            best = {"name": p.get("name") or _name(p.get("species")),
                    "level": lvl,
                    "quality": _name(p.get("quality"))}
    return {"count": len(pets), "best": best}


def slim_pvp_summary(d):
    """/pvp-summary -- honor level and lifetime honorable kills. Present for
    everyone; the bracket detail is only present for people who play rated,
    so it is fetched only where the summary says a bracket exists."""
    brackets = []
    for b in d.get("brackets") or []:
        href = b.get("href") or ""
        # ".../pvp-bracket/3v3?namespace=..." -> "3v3"
        slug = href.rsplit("/", 1)[-1].split("?")[0]
        if slug:
            brackets.append(slug)
    return {
        "honor_level": d.get("honor_level"),
        "honorable_kills": d.get("honorable_kills"),
        "brackets": sorted(set(brackets)),
    }


def slim_raid_encounters(d):
    """/encounters/raids -- boss kills, the whole career.

    Slimmed to the totals plus the MOST RECENT expansion's per-instance
    counts: a card wants "1,482 raid bosses killed" and "current tier: 8/8
    heroic", not a nine-expansion tree."""
    total = 0
    expansions = d.get("expansions") or []
    latest = None
    for exp in expansions:
        for inst in exp.get("instances") or []:
            for mode in inst.get("modes") or []:
                total += (mode.get("progress") or {}).get("completed_count") or 0
        latest = exp
    current = []
    for inst in (latest or {}).get("instances") or []:
        modes = []
        for mode in inst.get("modes") or []:
            prog = mode.get("progress") or {}
            modes.append({
                "difficulty": _name(mode.get("difficulty")),
                "completed": prog.get("completed_count"),
                "total": prog.get("total_count"),
            })
        modes.sort(key=lambda m: m["difficulty"] or "")
        current.append({"instance": _name(inst.get("instance")), "modes": modes})
    current.sort(key=lambda i: i["instance"] or "")
    return {
        "boss_kills_total": total,
        "expansions_raided": len(expansions),
        "latest_expansion": _name((latest or {}).get("expansion")),
        "latest_instances": current,
    }


def slim_dungeon_encounters(d):
    """/encounters/dungeons -- the lifetime dungeon count only. The per-
    instance tree is long and the M+ endpoints already carry what a card
    would print about dungeons."""
    total = 0
    for exp in d.get("expansions") or []:
        for inst in exp.get("instances") or []:
            for mode in inst.get("modes") or []:
                total += (mode.get("progress") or {}).get("completed_count") or 0
    return {"dungeon_kills_total": total}


# ---------------------------------------------------------------------------
# THE ENDPOINT REGISTRY -- the honest inventory, in code.
#
# (block, path suffix, slimmer, what it buys a card). The order is the fetch
# order and the report order, so a run's log reads top to bottom.
# ---------------------------------------------------------------------------

ENDPOINTS = (
    ("identity", "", slim_summary,
     "level / race / class / spec / faction / guild rank / BOTH item levels / "
     "achievement points / last login"),
    ("spec", "/specializations", slim_specializations,
     "active spec + every spec with saved talents + hero talent tree"),
    ("media", "/character-media", slim_media,
     "avatar + full transmog render (the card's portrait)"),
    ("gear", "/equipment", slim_equipment,
     "THE GEAR LINE: per-slot item, ilvl, upgrade track, enchants, sockets"),
    ("stats", "/statistics", slim_statistics,
     "the stats panel: health, primaries, crit/haste/mastery/vers, armor, "
     "avoidances -- the engine's HP/attack/defense"),
    ("history", "/achievements", slim_achievements,
     "THE HISTORY LINE: points, count, notable achievements, last earned"),
    ("record", "/achievements/statistics", slim_achievement_statistics,
     "the honest weird numbers: deaths, killing blows, quests, hugs, fish"),
    ("titles", "/titles", slim_titles,
     "THE TITLE LINE: active title + the collection"),
    ("keystone", "/mythic-keystone-profile", slim_keystone_index,
     "current-period key count + the season list (feeds the season fetch)"),
    ("craft", "/professions", slim_professions,
     "THE CRAFT LINE: professions, tiers, skill/max, recipe counts"),
    ("mounts", "/collections/mounts", slim_mounts, "collector stat: mount count"),
    ("pets", "/collections/pets", slim_pets, "collector stat: pet count + best pet"),
    ("pvp", "/pvp-summary", slim_pvp_summary,
     "honor level, lifetime honorable kills, which rated brackets exist"),
    ("raids", "/encounters/raids", slim_raid_encounters,
     "lifetime raid boss kills + the current expansion's per-instance progress"),
    ("dungeons", "/encounters/dungeons", slim_dungeon_encounters,
     "lifetime dungeon completion count"),
)


def endpoint_inventory():
    """The registry as data -- committed into the cache so the inventory is
    never a document that can drift from the code that fetches."""
    return [
        {"block": block,
         "path": "/profile/wow/character/{realm}/{name}" + suffix,
         "buys": buys}
        for block, suffix, _, buys in ENDPOINTS
    ] + [
        {"block": "keystone_season",
         "path": "/profile/wow/character/{realm}/{name}"
                 "/mythic-keystone-profile/season/{seasonId}",
         "buys": "THE KEYSTONE LINE: per-dungeon best runs, levels, timed "
                 "flags, per-run rating (fetched only for the latest season "
                 "the index reports)"},
    ]


# ---------------------------------------------------------------------------
# The per-character fetch
# ---------------------------------------------------------------------------

def fetch_card_record(token, region, realm_slug, character_name, report=None,
                      catalog_sink=None):
    """Every endpoint in the registry for one character, slimmed.

    Returns None only when the character's own summary endpoint does not
    answer -- that is the one response that means "this character is not
    visible to us at all". Every other endpoint failing leaves its block
    absent and its name in `seams`: a card renders an honest gap, never a
    zero.
    """
    name = character_name.lower()
    params = {"namespace": f"profile-{(region or 'us').lower()}",
              "locale": DEFAULT_LOCALE}
    base = f"/profile/wow/character/{realm_slug}/{name}"

    record = {}
    seams = []
    for block, suffix, slimmer, _buys in ENDPOINTS:
        raw = _get(token, region, base + suffix, params, report,
                   "character" + suffix)
        if not raw:
            if block == "identity":
                return None      # not visible to us at all
            seams.append(block)
            continue
        # The full statistic catalog, captured once per run from whichever
        # character answers first -- the discovery artifact that makes the
        # next curation pass read real names instead of guessing them.
        if block == "record" and catalog_sink is not None and not catalog_sink:
            catalog_sink.update(_flatten_statistics(raw))
        try:
            record[block] = slimmer(raw)
        except Exception:            # a slimmer must never take down a sweep
            logger.warning("slimmer failed for %s on %s-%s",
                           block, character_name, realm_slug, exc_info=True)
            seams.append(block)

    # The keystone SEASON detail, only where the index named a season. One
    # extra request for a character who has run keys this expansion, zero for
    # everyone else -- which is why the per-character cost is "16, sometimes 17".
    seasons = (record.get("keystone") or {}).get("seasons") or []
    if seasons:
        raw = _get(token, region,
                   f"{base}/mythic-keystone-profile/season/{seasons[-1]}",
                   params, report, "character/mythic-keystone-profile/season")
        if raw:
            record["keystone_season"] = slim_keystone_season(raw)
        else:
            seams.append("keystone_season")
    else:
        seams.append("keystone_season")

    record["seams"] = sorted(set(seams))
    record["realm_slug"] = realm_slug
    record["fetched_at"] = datetime.now(timezone.utc).isoformat()
    return record


def fetch_roster_cards(token, region, roster, workers=WORKERS):
    """The whole roster, in parallel. Returns (records, report, catalog).

    `records` is keyed by the same lowercased name-realm every other layer
    keys on. `report` is the per-endpoint outcome tally -- the measured
    inventory. `catalog` is one character's complete flattened statistic tree.
    """
    report: dict = {}
    catalog: dict = {}
    lock = threading.Lock()
    records: dict = {}

    def one(entry):
        if "-" not in entry:
            return
        name, realm = split_name_realm(entry)
        rec = fetch_card_record(token, region, realm, name, report, catalog)
        if rec:
            with lock:
                records[entry.lower()] = rec

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, list(roster)))

    missed = sorted(set(e.lower() for e in roster if "-" in e) - set(records))
    if missed:
        logger.warning(
            "Blizzard card record unavailable for %d of %d roster entries: %s",
            len(missed), len(missed) + len(records),
            ", ".join(missed[:10]) + (" ..." if len(missed) > 10 else ""))
    return records, report, catalog


# ---------------------------------------------------------------------------
# The cache
# ---------------------------------------------------------------------------

def get_card_cache_path(cfg):
    return ((cfg or {}).get("blizzard") or {}).get(
        "card_cache_file", CARD_CACHE_DEFAULT)


def get_catalog_path(cfg):
    return ((cfg or {}).get("blizzard") or {}).get(
        "statistic_catalog_file", CATALOG_DEFAULT)


def load_card_cache(cfg):
    try:
        with open(get_card_cache_path(cfg), encoding="utf-8") as f:
            data = json.load(f)
        return data.get("characters", {}), data.get("last_updated")
    except (FileNotFoundError, json.JSONDecodeError):
        return {}, None


def save_card_cache(cfg, characters, report, region):
    """Byte-stable on purpose: sort_keys everywhere, so an unchanged roster
    produces an unchanged file and the weekly commit is a real diff rather
    than key-order churn."""
    path = get_card_cache_path(cfg)
    payload = {
        "schema_version": CARD_CACHE_VERSION,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "region": region,
        "source": (f"Blizzard Profile API (profile-{(region or 'us').lower()} "
                   f"namespace, {DEFAULT_LOCALE} locale)"),
        "note": ("Per-character card data. Every block is SLIMMED at fetch "
                 "time (see guild_board/blizzard_cards.py); raw responses are "
                 "never persisted. A block absent from a character means that "
                 "endpoint did not answer for them -- see their `seams` list. "
                 "Nothing here is zero-filled and nothing is hand-written."),
        "endpoints": endpoint_inventory(),
        "endpoint_outcomes": report,
        "count": len(characters),
        "characters": characters,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, sort_keys=True)
    return path


def save_catalog(cfg, catalog):
    """The complete flattened achievement-statistics tree for one character:
    the discovery artifact behind STAT_WANTED. Committed so the curation list
    can be widened from real names, never from memory."""
    if not catalog:
        return None
    path = get_catalog_path(cfg)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "note": ("Every statistic name the Blizzard achievement-statistics "
                     "endpoint returned for ONE sampled character, with that "
                     "character's values. Curation input only -- the card "
                     "cache keeps STAT_WANTED's subset per character."),
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "count": len(catalog),
            "statistics": catalog,
        }, f, indent=1, sort_keys=True)
    return path


def refresh_card_cache(cfg, roster, max_age_days=7, workers=WORKERS):
    """Fetch + persist the card cache. Returns (characters, changed, report).

    Same two gates every credentialed limb in this repo uses: blizzard.enabled
    in config.yml AND both env secrets. Missing either is a clean no-op that
    keeps whatever cache is already on disk -- a failed refresh must never
    blank a good one.
    """
    cached, last_updated = load_card_cache(cfg)

    if not ((cfg or {}).get("blizzard") or {}).get("enabled", False):
        logger.info("blizzard.enabled is false in config.yml; skipping card refresh.")
        return cached, False, {}

    client_id = os.environ.get("BLIZZARD_CLIENT_ID", "").strip()
    client_secret = os.environ.get("BLIZZARD_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        logger.info("BLIZZARD_CLIENT_ID/BLIZZARD_CLIENT_SECRET not set; "
                    "skipping card refresh.")
        return cached, False, {}

    if last_updated and cached:
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(last_updated)
            if age.days < max_age_days:
                return cached, False, {}
        except ValueError:
            pass

    region = ((cfg or {}).get("guild") or {}).get("region", "us")
    try:
        token = get_blizzard_token(client_id, client_secret)
        fetched, report, catalog = fetch_roster_cards(token, region, roster, workers)
    except Exception:
        logger.warning("Blizzard card refresh failed; keeping existing cache.",
                       exc_info=True)
        return cached, False, {}

    if not fetched:
        logger.warning("Card refresh returned nothing; keeping existing cache.")
        return cached, False, report

    # MERGE, never replace: a character the API could not see this run keeps
    # their last good record rather than vanishing off the binder wall.
    merged = dict(cached)
    merged.update(fetched)
    save_card_cache(cfg, merged, report, region)
    save_catalog(cfg, catalog)
    return merged, True, report

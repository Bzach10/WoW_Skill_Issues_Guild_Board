"""Blizzard Community/Game Data API — OAuth + per-character profile lookups.

Entirely additive and off by default: nothing here is imported by the
existing board pipeline (main.py, html_board.py, board_image.py). It's
called only by scripts/refresh_blizzard_profiles.py, which itself no-ops
cleanly when creds or the config toggle are missing. See SETUP_BLIZZARD.md.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import requests

from guild_board.config import split_name_realm

logger = logging.getLogger(__name__)

BLIZZARD_TOKEN_URL = "https://oauth.battle.net/token"

# The Game Data API is region-hosted (unlike the shared OAuth endpoint above).
BLIZZARD_API_HOSTS = {
    "us": "https://us.api.blizzard.com",
    "eu": "https://eu.api.blizzard.com",
    "kr": "https://kr.api.blizzard.com",
    "tw": "https://tw.api.blizzard.com",
}

DEFAULT_LOCALE = "en_US"


def get_blizzard_token(client_id, client_secret):
    """OAuth client-credentials grant. Mirrors wcl.get_wcl_token exactly."""
    resp = requests.post(
        BLIZZARD_TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _api_host(region):
    return BLIZZARD_API_HOSTS.get((region or "us").lower(), BLIZZARD_API_HOSTS["us"])


def _get(token, region, path, params):
    """GET one Game Data API endpoint. Returns None for any expected
    "this character isn't visible to us" case instead of raising, so one
    private/missing/renamed character never aborts a whole roster refresh.
    """
    host = _api_host(region)
    resp = requests.get(
        f"{host}{path}",
        params=params,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if resp.status_code in (401, 403, 404):
        return None
    resp.raise_for_status()
    return resp.json()


# Slots that carry a visible appearance. Blizzard also returns rings,
# trinkets and neck, which have no model on the character, so they are
# dropped rather than handed to the art pipeline as noise.
VISIBLE_SLOTS = (
    "HEAD", "SHOULDER", "BACK", "CHEST", "SHIRT", "TABARD", "WRIST",
    "HANDS", "WAIST", "LEGS", "FEET", "MAIN_HAND", "OFF_HAND",
)

# item_subclass for armour pieces is the armour weight, which is what maps
# onto the art pipeline's kit taxonomy (cloth_robe_*, leather_*, mail_*,
# plate_*). Weapons report their weapon type here instead.
ARMOR_WEIGHTS = ("Cloth", "Leather", "Mail", "Plate")


def _equipped_item_summary(entry):
    """One /equipment `equipped_items[]` entry -> the fields art needs.

    The distinction that matters: `item` is what the character is actually
    wearing, `transmog` is what it LOOKS like. Art must follow the
    appearance, so transmog wins when present and the real item is the
    fallback.
    """
    slot = (entry.get("slot") or {}).get("type")
    item = entry.get("item") or {}
    subclass = (entry.get("item_subclass") or {}).get("name")

    transmog = entry.get("transmog") or {}
    transmog_item = transmog.get("item") or {}

    return {
        "slot": slot,
        "item_id": item.get("id"),
        "item_name": entry.get("name"),
        "quality": (entry.get("quality") or {}).get("name"),
        "item_class": (entry.get("item_class") or {}).get("name"),
        # "Cloth"/"Leather"/"Mail"/"Plate" for armour; weapon type otherwise.
        "item_subclass": subclass,
        "armor_weight": subclass if subclass in ARMOR_WEIGHTS else None,
        "inventory_type": (entry.get("inventory_type") or {}).get("type"),
        # Populated only when the slot is actually transmogged.
        "transmog_item_id": transmog_item.get("id"),
        "transmog_item_name": transmog_item.get("name"),
        # What the art pipeline should render: appearance if transmogged,
        # otherwise the equipped item itself.
        "appearance_item_id": transmog_item.get("id") or item.get("id"),
        "appearance_item_name": transmog_item.get("name") or entry.get("name"),
    }


def fetch_character_equipment(token, region, realm_slug, character_name):
    """Per-slot equipment for one character.

    Returns a list of slot dicts (see _equipped_item_summary), visible slots
    only, or [] for any missing/private/failed lookup — never raises, so one
    unreadable character cannot abort a roster refresh.
    """
    name = character_name.lower()
    namespace = f"profile-{(region or 'us').lower()}"
    params = {"namespace": namespace, "locale": DEFAULT_LOCALE}
    path = f"/profile/wow/character/{realm_slug}/{name}/equipment"

    try:
        data = _get(token, region, path, params)
    except requests.RequestException:
        logger.warning("Blizzard equipment fetch failed for %s-%s",
                       character_name, realm_slug, exc_info=True)
        return []
    if not data:
        return []

    items = []
    for entry in data.get("equipped_items") or []:
        summary = _equipped_item_summary(entry)
        if summary["slot"] in VISIBLE_SLOTS:
            items.append(summary)
    return items


def dominant_armor_weight(equipment):
    """The character's armour class ("Plate", "Mail", …) from their gear.

    Decided by the five slots that always match a character's armour
    proficiency — cloaks are always Cloth and would skew a naive count, so
    they are excluded. Returns None if those slots are missing.
    """
    core = {"CHEST", "LEGS", "FEET", "HANDS", "SHOULDER"}
    weights = [i["armor_weight"] for i in equipment or []
               if i.get("slot") in core and i.get("armor_weight")]
    if not weights:
        return None
    return max(set(weights), key=weights.count)


def fetch_character_profile(token, region, realm_slug, character_name):
    """Gender/race/class/active-spec + transmog render URLs for one character.

    Returns None — never raises — for any missing/private/network failure.
    Callers should treat None as "skip this character".
    """
    name = character_name.lower()
    namespace = f"profile-{(region or 'us').lower()}"
    params = {"namespace": namespace, "locale": DEFAULT_LOCALE}
    base_path = f"/profile/wow/character/{realm_slug}/{name}"

    try:
        summary = _get(token, region, base_path, params)
        if not summary:
            return None

        specs = _get(token, region, f"{base_path}/specializations", params) or {}
        active = specs.get("active_specialization")
        active_spec = active.get("name") if isinstance(active, dict) else None

        media = _get(token, region, f"{base_path}/character-media", params) or {}
        assets = {a.get("key"): a.get("value")
                  for a in media.get("assets", []) if a.get("key")}

        # Per-slot gear. The render URL above is only a picture; this is the
        # structured appearance data the art pipeline needs to map real gear
        # onto layers instead of falling back to a generic robe.
        equipment = fetch_character_equipment(
            token, region, realm_slug, character_name)

        return {
            "name": summary.get("name", character_name),
            "realm": realm_slug,
            "gender": (summary.get("gender") or {}).get("name"),
            "race": (summary.get("race") or {}).get("name"),
            "class": (summary.get("character_class") or {}).get("name"),
            "active_spec": active_spec,
            "avatar_render_url": assets.get("avatar"),
            # "main-raw" is the full current-transmog render; "main" is a
            # smaller composited fallback if main-raw isn't present.
            "transmog_render_url": assets.get("main-raw") or assets.get("main"),
            "equipment": equipment,
            "armor_weight": dominant_armor_weight(equipment),
        }
    except requests.RequestException:
        logger.warning("Blizzard profile fetch failed for %s-%s",
                        character_name, realm_slug, exc_info=True)
        return None


def fetch_roster_profiles(token, region, roster):
    """roster: iterable of 'Name-Realm' strings (same shape roster_cache.json
    already uses). Returns {"name-realm": profile_dict} — lowercased keys,
    entries that failed or came back empty are simply omitted.
    """
    profiles = {}
    missed = []
    for entry in roster:
        if "-" not in entry:
            continue
        name, realm = split_name_realm(entry)
        profile = fetch_character_profile(token, region, realm, name)
        if profile:
            profiles[entry.lower()] = profile
        else:
            missed.append(entry)
    if missed:
        # One missing character is routine (transferred, renamed, or an
        # opted-out profile). A large share of the roster missing is not —
        # it means a systemic fault (bad name/realm split, wrong namespace,
        # expired token). Logging the count surfaces that instead of
        # letting the cast quietly shrink.
        logger.warning(
            "Blizzard profile unavailable for %d of %d roster entries: %s",
            len(missed), len(missed) + len(profiles),
            ", ".join(sorted(missed)[:10]) + (" ..." if len(missed) > 10 else ""))
    return profiles


# ---------------------------------------------------------------------------
# Guild-level data — achievements (trophy hall + per-boss raid kills) and
# activity. Same client_credentials token as the profile fetch; these live
# under /data/wow/guild/ but still require the profile-{region} namespace
# (a documented source of 403s if you send dynamic-/static- instead).
# ---------------------------------------------------------------------------

def _guild_slug(guild_name):
    """'Skill Issues' -> 'skill-issues'. Reuses the same slug rule the rest
    of the pipeline uses for realm/server names."""
    from guild_board.config import slugify_server
    return slugify_server(guild_name)


def fetch_guild_achievements(token, region, realm_slug, guild_name):
    """Raw guild-achievements payload, or None.

    /data/wow/guild/{realm}/{guild-slug}/achievements — the trophy hall
    (layer 3) and the authoritative per-boss raid-kill source (layer 4):
    each boss-kill achievement carries a completed_timestamp. Fails soft to
    None so a missing guild or a creds/namespace problem cannot abort the
    refresh.
    """
    guild = _guild_slug(guild_name)
    if not guild:
        return None
    params = {"namespace": f"profile-{(region or 'us').lower()}", "locale": DEFAULT_LOCALE}
    path = f"/data/wow/guild/{realm_slug}/{guild}/achievements"
    try:
        return _get(token, region, path, params)
    except requests.RequestException:
        logger.warning("Blizzard guild-achievements fetch failed for %s-%s",
                       guild, realm_slug, exc_info=True)
        return None


def fetch_guild_activity(token, region, realm_slug, guild_name):
    """Raw guild-activity payload, or None.

    /data/wow/guild/{realm}/{guild-slug}/activity — recent guild events
    (member joins, high-level dungeon/raid encounters). NOTE: Blizzard
    returns these timestamps in local realm time, not UTC (a documented
    quirk), unlike achievement timestamps — do not correlate the two on
    time without accounting for that.
    """
    guild = _guild_slug(guild_name)
    if not guild:
        return None
    params = {"namespace": f"profile-{(region or 'us').lower()}", "locale": DEFAULT_LOCALE}
    path = f"/data/wow/guild/{realm_slug}/{guild}/activity"
    try:
        return _get(token, region, path, params)
    except requests.RequestException:
        logger.warning("Blizzard guild-activity fetch failed for %s-%s",
                       guild, realm_slug, exc_info=True)
        return None


def fetch_guild_data(token, region, realm_slug, guild_name):
    """Both guild-level payloads in one dict, for the guild cache. Either
    value may be None; the caller decides whether that is worth persisting.
    """
    return {
        "achievements": fetch_guild_achievements(token, region, realm_slug, guild_name),
        "activity": fetch_guild_activity(token, region, realm_slug, guild_name),
    }


# ---------------------------------------------------------------------------
# Profile cache — same load/save/freshness shape as config.py's roster cache.
# ---------------------------------------------------------------------------

def get_profile_cache_path(cfg):
    blizzard_cfg = (cfg or {}).get("blizzard", {})
    return blizzard_cfg.get("cache_file", "blizzard_profile_cache.json")


def load_profile_cache(cfg):
    path = get_profile_cache_path(cfg)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("characters", {}), data.get("last_updated")
    except (FileNotFoundError, json.JSONDecodeError):
        return {}, None


def save_profile_cache(cfg, characters):
    path = get_profile_cache_path(cfg)
    data = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "characters": characters,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    return path


def refresh_profile_cache(cfg, roster, max_age_days=7):
    """Fetch+merge fresh Blizzard profiles into the on-disk cache.

    Two independent gates keep this a true no-op until it's deliberately
    turned on: blizzard.enabled in config.yml, AND both env secrets. The
    existing WCL/Raider.io board pipeline never touches this function, so
    it can't regress today's board either way.

    Returns (characters_dict, changed_bool).
    """
    cached, last_updated = load_profile_cache(cfg)

    blizzard_cfg = (cfg or {}).get("blizzard", {})
    if not blizzard_cfg.get("enabled", False):
        logger.info("blizzard.enabled is false in config.yml; skipping profile refresh.")
        return cached, False

    client_id = os.environ.get("BLIZZARD_CLIENT_ID", "").strip()
    client_secret = os.environ.get("BLIZZARD_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        logger.info("BLIZZARD_CLIENT_ID/BLIZZARD_CLIENT_SECRET not set; skipping profile refresh.")
        return cached, False

    if last_updated:
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(last_updated)
            if age < timedelta(days=max_age_days) and cached:
                return cached, False
        except ValueError:
            pass

    region = ((cfg or {}).get("guild") or {}).get("region", "us")
    try:
        token = get_blizzard_token(client_id, client_secret)
        fetched = fetch_roster_profiles(token, region, roster)
    except Exception:
        logger.warning("Blizzard profile refresh failed; keeping existing cache.", exc_info=True)
        return cached, False

    if not fetched:
        return cached, False

    merged = dict(cached)
    merged.update(fetched)
    save_profile_cache(cfg, merged)
    return merged, True


# ---------------------------------------------------------------------------
# Guild cache — the guild-level payloads (achievements + activity), stored
# separately from the per-character profile cache so each refresh path is
# independent and neither blocks the other.
# ---------------------------------------------------------------------------

def get_guild_cache_path(cfg):
    blizzard_cfg = (cfg or {}).get("blizzard", {})
    return blizzard_cfg.get("guild_cache_file", "blizzard_guild_cache.json")


def load_guild_cache(cfg):
    """Returns (guild_data_dict, last_updated). guild_data_dict has
    'achievements' and 'activity' keys (either may be None). Fails open to
    ({}, None) so the site builder still runs without this file."""
    path = get_guild_cache_path(cfg)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {"achievements": data.get("achievements"),
                "activity": data.get("activity")}, data.get("last_updated")
    except (FileNotFoundError, json.JSONDecodeError):
        return {}, None


def save_guild_cache(cfg, guild_data):
    path = get_guild_cache_path(cfg)
    data = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "achievements": guild_data.get("achievements"),
        "activity": guild_data.get("activity"),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    return path


def refresh_guild_cache(cfg, max_age_days=7):
    """Fetch the guild achievements + activity into the on-disk guild cache.

    Same two gates as refresh_profile_cache (blizzard.enabled + both env
    secrets), so it is a true no-op until deliberately turned on. Keeps the
    existing cache on any failure rather than blanking the trophy hall.

    Returns (guild_data_dict, changed_bool).
    """
    cached, last_updated = load_guild_cache(cfg)

    blizzard_cfg = (cfg or {}).get("blizzard", {})
    if not blizzard_cfg.get("enabled", False):
        logger.info("blizzard.enabled is false in config.yml; skipping guild refresh.")
        return cached, False

    client_id = os.environ.get("BLIZZARD_CLIENT_ID", "").strip()
    client_secret = os.environ.get("BLIZZARD_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        logger.info("BLIZZARD_CLIENT_ID/BLIZZARD_CLIENT_SECRET not set; skipping guild refresh.")
        return cached, False

    if last_updated and cached.get("achievements"):
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(last_updated)
            if age < timedelta(days=max_age_days):
                return cached, False
        except ValueError:
            pass

    guild = (cfg or {}).get("guild") or {}
    region = guild.get("region", "us")
    realm_slug = guild.get("realm_slug", "")
    guild_name = guild.get("name", "")
    try:
        token = get_blizzard_token(client_id, client_secret)
        fetched = fetch_guild_data(token, region, realm_slug, guild_name)
    except Exception:
        logger.warning("Blizzard guild refresh failed; keeping existing cache.", exc_info=True)
        return cached, False

    # Only persist if we actually got something, so a transient empty
    # response can't wipe a good cache.
    if not fetched.get("achievements") and not fetched.get("activity"):
        logger.warning("Guild refresh returned no achievements or activity; keeping existing cache.")
        return cached, False

    save_guild_cache(cfg, fetched)
    return fetched, True

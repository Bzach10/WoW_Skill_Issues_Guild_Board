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

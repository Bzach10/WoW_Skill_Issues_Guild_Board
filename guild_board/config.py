import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import yaml

# Clean display names for classes from Raider.io/WCL data
CLASS_NAME_MAP = {
    "Warrior": "Warrior",
    "Paladin": "Paladin",
    "Hunter": "Hunter",
    "Rogue": "Rogue",
    "Priest": "Priest",
    "Death Knight": "DK",
    "Shaman": "Shaman",
    "Mage": "Mage",
    "Warlock": "Warlock",
    "Monk": "Monk",
    "Druid": "Druid",
    "Demon Hunter": "DH",
    "Evoker": "Evoker",
}

# Fallback class abbreviation map keyed by class_id
CLASS_ID_MAP = {
    1: "Warrior",
    2: "Paladin",
    3: "Hunter",
    4: "Rogue",
    5: "Priest",
    6: "DK",
    7: "Shaman",
    8: "Mage",
    9: "Warlock",
    10: "Monk",
    11: "Druid",
    12: "DH",
    13: "Evoker",
    32: "Evoker",
}

CLASS_COLORS = {
    "Warrior": "#C79C6E",
    "Paladin": "#F58CBA",
    "Hunter": "#ABD473",
    "Rogue": "#FFF569",
    "Priest": "#FFFFFF",
    "Death Knight": "#C41E3A",
    "Shaman": "#0070DE",
    "Mage": "#40C7EB",
    "Warlock": "#8787ED",
    "Monk": "#00FF96",
    "Druid": "#FF7D0A",
    "Demon Hunter": "#A330C9",
    "Evoker": "#33937F",
    # abbreviated aliases
    "DK": "#C41E3A",
    "DH": "#A330C9",
}


def load_config(path="config.yml"):
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    guild_name = ((cfg or {}).get("guild") or {}).get("name", "")
    if guild_name in ("", "Your Guild Name"):
        sys.exit(
            "Edit config.yml first: set guild.name, guild.realm_slug and "
            "guild.region to YOUR guild (exactly as shown on Warcraft Logs), "
            "then run again. See the README quick-start.")
    return cfg


def require_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"ERROR: missing required environment variable {name}")
    return value


def slugify_server(server):
    """Normalize a server name from WCL data into a realm slug."""
    if isinstance(server, dict):
        server = server.get("name") or server.get("slug") or ""
    if not isinstance(server, str):
        return None
    slug = server.strip().lower().replace("'", "").replace(" ", "-")
    return slug or None


def split_name_realm(entry, default_realm=None):
    """Split a roster entry ("name-realm-slug") into (name, realm_slug).

    THE realm slug usually contains hyphens itself ("bleeding-hollow",
    "area-52", "wyrmrest-accord"), so this splits on the FIRST hyphen —
    the character name is a single token, the realm is everything after.

    Splitting on the last hyphen instead (rsplit) silently mangles every
    multi-word realm: "dathar-area-52" becomes name="dathar-area",
    realm="52", which 400s/404s at both Blizzard and Raider.io and — because
    both callers treat a non-200 as "skip this character" — drops the
    member with no error. That was live for 65 of 135 roster members.

    Returns (name, realm) with both stripped; realm falls back to
    default_realm when the entry has no hyphen at all.
    """
    if not entry:
        return "", (default_realm or "")
    if "-" in entry:
        name, realm = entry.split("-", 1)
    else:
        name, realm = entry, (default_realm or "")
    return name.strip(), realm.strip()


def normalize_roster_entry(entry):
    """Canonical form for a roster entry: stripped, lowercased.

    Every data layer keys per-character records by the full name-realm
    entry ("amrevenge-stormrage") and merges across layers on
    byte-identical keys — competition.py, wcl.py's parse sweep and
    web_data.py all rely on it. Casing is folded HERE, where a roster
    enters the system (config.yml manual override, roster cache
    read/write, WCL auto-fetch), never per-layer: competition once
    lowercased its copy of a manual "Rakell-Proudmoore" entry while the
    parse sweep kept it verbatim, so that character's WCL parses
    silently failed to merge. Unicode is preserved; only case folds.
    """
    return (entry or "").strip().lower()


def index_roster_by_name(roster):
    """{bare lowercase name: sorted [character keys]} over the whole roster.

    A LIST, not a key, because bare display names COLLIDE. This roster
    carries `beroben-emerald-dream` AND `beroben-queldorei` — two different
    real people who share a name. Warcraft Logs hands us names without
    realms, so every layer fed from it (streaks, deaths, the improvement
    pools) is keyed on something that is not an identity; a ledger built on
    one of those keys credits whichever of the two sorted first, silently,
    forever. This index is what makes the collision visible instead.
    """
    index = {}
    for entry in roster or []:
        key = normalize_roster_entry(entry)
        if not key:
            continue
        name, _ = split_name_realm(key)
        if not name:
            continue
        bucket = index.setdefault(name, [])
        if key not in bucket:
            bucket.append(key)
    return {name: sorted(keys) for name, keys in index.items()}


def resolve_character_key(name, index):
    """Bare display name -> (character key or None, reason).

    reason is "" on a clean resolve, "ambiguous" when the name belongs to
    more than one roster character, "unknown" when it belongs to none.

    NEVER guesses past an ambiguity, and that is the whole point. Two
    characters called Beroben are two people; picking the higher-scored or
    first-sorted one credits the wrong one and nothing ever says so. An
    ambiguous name is returned as a named seam the surface can print — an
    honest em-dash beats a confident wrong number.
    """
    bare = normalize_roster_entry(name)
    if not bare:
        return None, "unknown"
    index = index or {}
    if "-" in bare:
        # Some sources already hand us a full name-realm key; accept it when
        # the roster agrees, otherwise fall through on the name token.
        head, _ = split_name_realm(bare)
        if bare in (index.get(head) or ()):
            return bare, ""
        bare = head
    matches = index.get(bare) or []
    if len(matches) == 1:
        return matches[0], ""
    if not matches:
        return None, "unknown"
    return None, "ambiguous"


def clean_spec_name(spec, class_name=""):
    """Return a clean 'Spec Class' display name from Raider.io/WCL spec data."""
    if isinstance(spec, dict):
        spec_name = spec.get("name") or spec.get("specName") or ""
    elif isinstance(spec, str):
        spec_name = spec
    else:
        spec_name = ""

    clean_class = ""
    if class_name:
        clean_class = CLASS_NAME_MAP.get(class_name.title(), class_name)

    if not clean_class and isinstance(spec, dict):
        class_id = spec.get("class_id")
        if class_id:
            clean_class = CLASS_ID_MAP.get(class_id, "")

    spec_name = spec_name.strip()
    clean_class = clean_class.strip()

    if spec_name and clean_class:
        return f"{spec_name} {clean_class}"
    if spec_name:
        return spec_name
    if clean_class:
        return clean_class
    return "Unknown"


def get_class_color(class_name_or_spec):
    """Return a hex class color for a class name or spec string.

    Matches case-insensitively so spec strings like "Unholy DK" or
    "beastmastery hunter" resolve; longest class names win so
    "Demon Hunter" isn't mistaken for "Hunter".
    """
    if not class_name_or_spec:
        return "#CCCCCC"
    lower = str(class_name_or_spec).lower()
    tokens = re.split(r"[^a-z]+", lower)
    for cls, color in sorted(CLASS_COLORS.items(), key=lambda kv: -len(kv[0])):
        cls_lower = cls.lower()
        if " " in cls_lower:
            if cls_lower in lower:
                return color
        elif cls_lower in tokens:
            return color
    return "#CCCCCC"


# ---------------------------------------------------------------------------
# Roster cache
# ---------------------------------------------------------------------------

def get_roster_cache_path(cfg):
    cache_cfg = cfg.get("roster_cache", {}) if cfg else {}
    return cache_cfg.get("file", "roster_cache.json")


def load_roster_cache(cfg):
    path = get_roster_cache_path(cfg)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        members = [normalize_roster_entry(m) for m in data.get("members", [])]
        return members, data.get("last_updated")
    except (FileNotFoundError, json.JSONDecodeError):
        return [], None


def save_roster_cache(cfg, members):
    path = get_roster_cache_path(cfg)
    data = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "members": sorted({normalize_roster_entry(m) for m in members}),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path


def resolve_roster(cfg, token=None, section_name="mplus"):
    """Return a roster list for the given M+ section, using cache if available.

    Priority: manual roster > cached roster > WCL auto-fetch.
    """
    sections = cfg.get("sections", {})
    mplus_cfg = sections.get(section_name) if sections else cfg.get(section_name, {})
    if not mplus_cfg and section_name == "mplus":
        mplus_cfg = cfg.get("mplus", {})

    roster = mplus_cfg.get("roster", []) if mplus_cfg else []
    # The documented config.yml format is mixed-case ("Rakell-Proudmoore");
    # fold to the canonical key form on the way in.
    roster = [normalize_roster_entry(r) for r in roster]
    auto_fetch = mplus_cfg.get("auto_fetch_roster", False) if mplus_cfg else False
    cache_cfg = cfg.get("roster_cache", {})
    cache_enabled = cache_cfg.get("enabled", True)
    max_age_days = float(cache_cfg.get("max_age_days", 7))

    if roster:
        return roster, False

    cached_roster = []
    cache_fresh = False
    if cache_enabled:
        cached_roster, last_updated = load_roster_cache(cfg)
        if cached_roster and last_updated:
            try:
                age = datetime.now(timezone.utc) - datetime.fromisoformat(last_updated)
                cache_fresh = age < timedelta(days=max_age_days)
            except ValueError:
                cache_fresh = False

    if cached_roster and cache_fresh:
        return cached_roster, False

    # Cache is missing or stale: re-fetch so new members actually show up.
    if auto_fetch and token:
        from guild_board.wcl import fetch_guild_member_roster

        try:
            guild_roster = fetch_guild_member_roster(token, cfg)
            if guild_roster:
                fetched = [normalize_roster_entry(f"{name}-{realm}")
                           for name, realm in guild_roster]
                if cache_enabled:
                    # Union with the old cache: WCL rosters drift, and a
                    # member who's temporarily missing shouldn't vanish.
                    merged = sorted(set(fetched) | set(cached_roster))
                    save_roster_cache(cfg, merged)
                    return merged, True
                return fetched, True
        except Exception:
            if cached_roster:
                return cached_roster, False  # stale beats nothing
            raise

    return cached_roster or roster, False

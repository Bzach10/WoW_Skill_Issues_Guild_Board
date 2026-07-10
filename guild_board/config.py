import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

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
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


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
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("members", []), data.get("last_updated")
    except (FileNotFoundError, json.JSONDecodeError):
        return [], None


def save_roster_cache(cfg, members):
    path = get_roster_cache_path(cfg)
    data = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "members": sorted(set(members)),
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
    auto_fetch = mplus_cfg.get("auto_fetch_roster", False) if mplus_cfg else False
    cache_enabled = cfg.get("roster_cache", {}).get("enabled", True)

    default_realm = cfg["guild"]["realm_slug"]

    if roster:
        return roster, False

    if cache_enabled:
        cached_roster, _ = load_roster_cache(cfg)
        if cached_roster:
            return cached_roster, False

    if auto_fetch and token:
        from guild_board.wcl import fetch_guild_member_roster

        try:
            guild_roster = fetch_guild_member_roster(token, cfg)
            if guild_roster:
                roster = [f"{name}-{realm}" for name, realm in guild_roster]
                if cache_enabled:
                    save_roster_cache(cfg, roster)
                return roster, True
        except Exception:
            raise

    return roster, False

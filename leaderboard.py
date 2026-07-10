#!/usr/bin/env python3
"""
WoW Guild Weekly Leaderboard -> Discord

Pulls the past week's raid logs from Warcraft Logs and posts a leaderboard
to Discord via webhook. Categories:
  - Guild standing: progress rank vs other guilds (realm / region / world)
  - Top DPS parses and top healing parses of the week
  - Realm Rank Leaders: guild's best players by WCL All Stars realm rank
  - Most deaths (Graveyard Camper award)
  - Roast of the week (from config)
  - Optional: highest M+ keys via Raider.io

Also handles:
  - Multiple people logging the same raid (duplicate pulls are fingerprinted
    and counted once, so deaths/pulls/kills are never double-counted)
  - Pugs in your raids (optional roster filtering via config)

Required environment variables (set as GitHub Actions secrets):
  WCL_CLIENT_ID, WCL_CLIENT_SECRET, DISCORD_WEBHOOK_URL

Everything else is configured in config.yml.
"""

import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import yaml
from PIL import Image, ImageDraw, ImageFont

WCL_TOKEN_URL = "https://www.warcraftlogs.com/oauth/token"
WCL_API_URL = "https://www.warcraftlogs.com/api/v2/client"
RAIDERIO_URL = "https://raider.io/api/v1/characters/profile"

DIFFICULTY_MAP = {"lfr": 1, "normal": 3, "heroic": 4, "mythic": 5}
MEDALS = ["\U0001F947", "\U0001F948", "\U0001F949", "**4.**", "**5.**"]

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

# Two fights in different reports are the same pull if they match on
# encounter, difficulty, and outcome, start within 60s of each other
# (allows for clock drift between loggers' PCs), and have durations
# within 15s of each other (separates rapid re-pulls of the same boss).
FIGHT_START_TOLERANCE_MS = 60_000
FIGHT_DURATION_TOLERANCE_MS = 15_000


# ---------------------------------------------------------------------------
# Config / auth
# ---------------------------------------------------------------------------

def load_config(path="config.yml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def require_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"ERROR: missing required environment variable {name}")
    return value


def get_wcl_token(client_id, client_secret):
    resp = requests.post(
        WCL_TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def gql(token, query, variables):
    resp = requests.post(
        WCL_API_URL,
        json={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("errors"):
        raise RuntimeError(f"WCL API error: {payload['errors']}")
    return payload.get("data", {})


def slugify_server(server):
    """Normalize a server name from WCL data into a realm slug."""
    if isinstance(server, dict):
        server = server.get("name") or server.get("slug") or ""
    if not isinstance(server, str):
        return None
    slug = server.strip().lower().replace("'", "").replace(" ", "-")
    return slug or None


def clean_spec_name(spec, class_name=""):
    """Return a clean 'Spec Class' display name from Raider.io/WCL spec data.

    `spec` can be a dict with a 'name' key or a string. `class_name` is the
    character class string (e.g. 'Demon Hunter').
    """
    if isinstance(spec, dict):
        spec_name = spec.get("name") or spec.get("specName") or ""
    elif isinstance(spec, str):
        spec_name = spec
    else:
        spec_name = ""

    # Normalize class name
    clean_class = ""
    if class_name:
        clean_class = CLASS_NAME_MAP.get(class_name.title(), class_name)

    if not clean_class and isinstance(spec, dict):
        class_id = spec.get("class_id")
        if class_id:
            clean_class = CLASS_ID_MAP.get(class_id, "")

    if not clean_class:
        clean_class = ""

    spec_name = spec_name.strip()
    clean_class = clean_class.strip()

    if spec_name and clean_class:
        return f"{spec_name} {clean_class}"
    if spec_name:
        return spec_name
    if clean_class:
        return clean_class
    return "Unknown"


def get_roster_cache_path(cfg):
    """Return the path to the roster cache file."""
    cache_cfg = cfg.get("roster_cache", {})
    return cache_cfg.get("file", "roster_cache.json")


def load_roster_cache(cfg):
    """Load the cached roster from disk. Returns a list of 'name-realm' entries."""
    path = get_roster_cache_path(cfg)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("members", []), data.get("last_updated")
    except (FileNotFoundError, json.JSONDecodeError):
        return [], None


def save_roster_cache(cfg, members):
    """Save the roster to disk for future runs."""
    path = get_roster_cache_path(cfg)
    data = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "members": sorted(set(members)),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"[ROSTER CACHE] Saved {len(data['members'])} members to {path}")


def resolve_roster(cfg, token, section_name="mplus"):
    """Return a roster list for the given M+ section, using cache if available.

    Priority: manual roster > cached roster > WCL auto-fetch.
    """
    sections = cfg.get("sections", {})
    mplus_cfg = sections.get(section_name) if sections else cfg.get(section_name, {})
    if not mplus_cfg and section_name == "mplus":
        # Legacy fallback
        mplus_cfg = cfg.get("mplus", {})

    roster = mplus_cfg.get("roster", []) if mplus_cfg else []
    auto_fetch = mplus_cfg.get("auto_fetch_roster", False) if mplus_cfg else False
    cache_enabled = cfg.get("roster_cache", {}).get("enabled", True)

    default_realm = cfg["guild"]["realm_slug"]

    if roster:
        print(f"[{section_name.upper()}] Using manual roster ({len(roster)} entries)")
        return roster, False

    if cache_enabled:
        cached_roster, last_updated = load_roster_cache(cfg)
        if cached_roster:
            print(f"[{section_name.upper()}] Using cached roster ({len(cached_roster)} entries, last updated {last_updated})")
            return cached_roster, False

    if auto_fetch and token:
        print(f"[{section_name.upper()}] Auto-fetching roster from WCL guild members...")
        try:
            guild_roster = fetch_guild_member_roster(token, cfg)
            if guild_roster:
                roster = [f"{name}-{realm}" for name, realm in guild_roster]
                print(f"[{section_name.upper()}] Fetched {len(roster)} guild members from WCL.")
                if cache_enabled:
                    save_roster_cache(cfg, roster)
                return roster, True
        except (RuntimeError, requests.RequestException) as exc:
            print(f"[{section_name.upper()}] Failed to auto-fetch roster: {exc}")

    return roster, False


# ---------------------------------------------------------------------------
# Warcraft Logs queries
# ---------------------------------------------------------------------------

REPORTS_QUERY = """
query ($name: String!, $slug: String!, $region: String!, $start: Float!, $end: Float!) {
  reportData {
    reports(
      guildName: $name
      guildServerSlug: $slug
      guildServerRegion: $region
      startTime: $start
      endTime: $end
      limit: 25
    ) {
      data {
        code
        title
        startTime
        endTime
        owner {
          name
        }
        zone {
          id
          name
        }
      }
    }
  }
}
"""

REPORT_DETAIL_QUERY = """
query ($code: String!, $difficulty: Int!) {
  reportData {
    report(code: $code) {
      fights(killType: Encounters) {
        id
        encounterID
        difficulty
        kill
        name
        startTime
        endTime
      }
      dps: rankings(playerMetric: dps, difficulty: $difficulty)
      hps: rankings(playerMetric: hps, difficulty: $difficulty)
    }
  }
}
"""

DEATHS_QUERY = """
query ($code: String!, $fightIDs: [Int]!) {
  reportData {
    report(code: $code) {
      table(dataType: Deaths, fightIDs: $fightIDs, startTime: 0, endTime: 999999999999)
    }
  }
}
"""

GUILD_STANDING_QUERY = """
query ($name: String!, $slug: String!, $region: String!, $zoneId: Int!) {
  guildData {
    guild(name: $name, serverSlug: $slug, serverRegion: $region) {
      zoneRanking(zoneId: $zoneId) {
        progress {
          worldRank { number }
          regionRank { number }
          serverRank { number }
        }
      }
    }
  }
}
"""

CHARACTER_ALLSTARS_QUERY = """
query ($name: String!, $slug: String!, $region: String!, $zoneId: Int!, $difficulty: Int!) {
  characterData {
    character(name: $name, serverSlug: $slug, serverRegion: $region) {
      zoneRankings(zoneID: $zoneId, metric: default, difficulty: $difficulty)
    }
  }
}
"""

GUILD_MEMBERS_QUERY = """
query ($name: String!, $slug: String!, $region: String!, $page: Int!) {
  guildData {
    guild(name: $name, serverSlug: $slug, serverRegion: $region) {
      members(limit: 100, page: $page) {
        data {
          name
          server {
            slug
            name
          }
        }
        has_more_pages
      }
    }
  }
}
"""


def fetch_guild_reports(token, cfg, start_ms, end_ms):
    guild = cfg["guild"]
    data = gql(token, REPORTS_QUERY, {
        "name": guild["name"],
        "slug": guild["realm_slug"],
        "region": guild["region"],
        "start": float(start_ms),
        "end": float(end_ms),
    })
    reports = (((data.get("reportData") or {}).get("reports") or {}).get("data")) or []
    return reports


def detect_zone(cfg, reports):
    """Pick the raid zone: config override if set, else the most recent report's zone."""
    override = int((cfg.get("rankings") or {}).get("zone_id", 0) or 0)
    if override > 0:
        return override, None
    zoned = [r for r in reports if (r.get("zone") or {}).get("id")]
    if not zoned:
        return None, None
    latest = max(zoned, key=lambda r: r.get("startTime") or 0)
    return latest["zone"]["id"], latest["zone"].get("name")


def extract_parses(rankings_blob, role_key, best_parses):
    """Walk a WCL rankings blob and keep each player's best parse.

    role_key: 'dps' to collect the dps role, 'healers' for the healer role.
    best_parses: dict name -> dict(parse, amount, boss, spec, cls)
    """
    if not rankings_blob:
        return
    for fight in (rankings_blob.get("data") or []):
        boss = ((fight.get("encounter") or {}).get("name")) or "Unknown boss"
        roles = fight.get("roles") or {}
        characters = ((roles.get(role_key) or {}).get("characters")) or []
        for ch in characters:
            name = ch.get("name")
            parse = ch.get("rankPercent")
            if not name or parse is None:
                continue
            prev = best_parses.get(name)
            if prev is None or parse > prev["parse"]:
                best_parses[name] = {
                    "parse": parse,
                    "amount": ch.get("amount") or 0,
                    "boss": boss,
                    "spec": ch.get("spec") or "",
                    "cls": ch.get("class") or "",
                }


def collect_participants(rankings_blob, participants):
    """Record everyone (tanks, healers, dps) seen in this week's kills,
    with their realm slug when WCL provides it."""
    if not rankings_blob:
        return
    for fight in (rankings_blob.get("data") or []):
        roles = fight.get("roles") or {}
        for role_key in ("tanks", "healers", "dps"):
            characters = ((roles.get(role_key) or {}).get("characters")) or []
            for ch in characters:
                name = ch.get("name")
                if not name:
                    continue
                slug = slugify_server(ch.get("server"))
                if name not in participants or (participants[name] is None and slug):
                    participants[name] = slug


def count_deaths(token, code, fight_ids, death_totals):
    if not fight_ids:
        return
    data = gql(token, DEATHS_QUERY, {"code": code, "fightIDs": fight_ids})
    table = (((data.get("reportData") or {}).get("report") or {}).get("table")) or {}
    entries = ((table.get("data") or {}).get("entries")) or []
    # Each entry in the Deaths table is one death event.
    for entry in entries:
        name = entry.get("name")
        if name:
            death_totals[name] += 1


# ---------------------------------------------------------------------------
# Difficulty fallback helper
# ---------------------------------------------------------------------------

def try_difficulties(func, cfg, token, reports, *args):
    """Try a function with each difficulty (mythic -> heroic -> normal) until one succeeds.

    Args:
        func: Function that takes (token, cfg, reports, difficulty, *args) as parameters
        cfg: Config dict
        token: WCL API token
        reports: List of reports from WCL
        *args: Additional arguments to pass to func

    Returns:
        Tuple of (result, difficulty_used) or (None, None) if all fail
    """
    difficulties = ["mythic", "heroic", "normal"]
    for diff in difficulties:
        try:
            print(f"[DIFFICULTY FALLBACK] Trying {diff}...")
            difficulty_num = DIFFICULTY_MAP.get(diff, 4)
            result = func(token, cfg, reports, difficulty_num, *args)
            if result:
                print(f"[DIFFICULTY FALLBACK] Found data for {diff}")
                return result, diff
            else:
                print(f"[DIFFICULTY FALLBACK] No data for {diff}")
        except Exception as exc:
            print(f"[DIFFICULTY FALLBACK] Error with {diff}: {exc}")
            continue
    print(f"[DIFFICULTY FALLBACK] No data found for any difficulty")
    return None, None


# ---------------------------------------------------------------------------
# Duplicate-log handling (multiple people logging the same raid)
# ---------------------------------------------------------------------------

class FightDeduper:
    """Recognizes the same boss pull appearing in multiple uploaded reports."""

    def __init__(self):
        self._seen = []

    def check_and_add(self, encounter_id, difficulty, kill, abs_start_ms, duration_ms):
        """Return True if this pull was already counted; otherwise record it."""
        for (enc, diff, was_kill, start, duration) in self._seen:
            if (enc == encounter_id
                    and diff == difficulty
                    and was_kill == kill
                    and abs(start - abs_start_ms) <= FIGHT_START_TOLERANCE_MS
                    and abs(duration - duration_ms) <= FIGHT_DURATION_TOLERANCE_MS):
                return True
        self._seen.append((encounter_id, difficulty, kill, abs_start_ms, duration_ms))
        return False


def report_sort_key(report, preferred_uploader):
    """Process the designated primary logger's reports first, then longest
    reports first, so the most complete log is the source of truth and
    fragments dedupe against it."""
    owner = ((report.get("owner") or {}).get("name") or "").strip().lower()
    is_preferred = bool(preferred_uploader) and owner == preferred_uploader
    duration = (report.get("endTime") or 0) - (report.get("startTime") or 0)
    return (0 if is_preferred else 1, -duration)


def collect_raid_stats(token, cfg, reports, difficulty=None):
    """Collect raid stats for a specific difficulty.
    
    Args:
        token: WCL API token
        cfg: Config dict
        reports: List of reports from WCL
        difficulty: Difficulty number (1-5), if None reads from config
    """
    if difficulty is None:
        difficulty = DIFFICULTY_MAP.get(str(cfg["raid"]["difficulty"]).lower(), 4)
    
    dedup_cfg = cfg.get("dedup") or {}
    dedup_enabled = bool(dedup_cfg.get("enabled", True))
    preferred_uploader = (dedup_cfg.get("preferred_uploader") or "").strip().lower()

    best_dps = {}
    best_hps = {}
    participants = {}
    death_totals = defaultdict(int)
    pulls = 0
    kills = 0
    duplicates_skipped = 0

    deduper = FightDeduper()
    ordered_reports = sorted(reports, key=lambda r: report_sort_key(r, preferred_uploader))

    for report in ordered_reports:
        code = report["code"]
        report_start = report.get("startTime") or 0
        data = gql(token, REPORT_DETAIL_QUERY, {"code": code, "difficulty": difficulty})
        rep = ((data.get("reportData") or {}).get("report")) or {}

        # Parses are naturally dedup-safe: the same kill in two logs yields
        # the same parse, and we only keep each player's best.
        extract_parses(rep.get("dps"), "dps", best_dps)
        extract_parses(rep.get("hps"), "healers", best_hps)
        collect_participants(rep.get("dps"), participants)

        fight_ids = []
        for fight in (rep.get("fights") or []):
            if fight.get("difficulty") != difficulty:
                continue
            if dedup_enabled:
                abs_start = report_start + (fight.get("startTime") or 0)
                duration = (fight.get("endTime") or 0) - (fight.get("startTime") or 0)
                if deduper.check_and_add(
                    fight.get("encounterID"),
                    difficulty,
                    bool(fight.get("kill")),
                    abs_start,
                    duration,
                ):
                    duplicates_skipped += 1
                    continue
            fight_ids.append(fight["id"])
            if fight.get("kill"):
                kills += 1

        pulls += len(fight_ids)
        count_deaths(token, code, fight_ids, death_totals)
        time.sleep(0.5)  # be polite to the API

    if duplicates_skipped:
        print(f"Deduplication: skipped {duplicates_skipped} duplicate pull(s) "
              f"from overlapping reports.")

    # Return None if no data found
    if not best_dps and not best_hps and pulls == 0:
        return None
    
    return {
        "best_dps": best_dps,
        "best_hps": best_hps,
        "participants": participants,
        "deaths": dict(death_totals),
        "pulls": pulls,
        "kills": kills,
        "difficulty": difficulty,
    }


# ---------------------------------------------------------------------------
# Roster filtering (pugs vs guild members)
# ---------------------------------------------------------------------------

def fetch_guild_member_roster(token, cfg):
    """Pull the guild roster from WCL as a list of (name, realm_slug) tuples."""
    guild = cfg["guild"]
    roster = []
    seen = set()
    page = 1
    while page <= 10:
        data = gql(token, GUILD_MEMBERS_QUERY, {
            "name": guild["name"],
            "slug": guild["realm_slug"],
            "region": guild["region"],
            "page": page,
        })
        members = (((data.get("guildData") or {}).get("guild") or {}).get("members")) or {}
        for member in (members.get("data") or []):
            name = member.get("name")
            if not name:
                continue
            server = member.get("server") or {}
            realm = server.get("slug") or guild["realm_slug"]
            key = f"{name.strip().lower()}-{realm.lower()}"
            if key not in seen:
                seen.add(key)
                roster.append((name.strip().lower(), realm))
        if not members.get("has_more_pages"):
            break
        page += 1
    return roster


def fetch_guild_member_names(token, cfg):
    """Pull the guild roster from Warcraft Logs (synced from the in-game roster).

    Returns a set of lowercase names for roster filtering compatibility.
    """
    return {name for name, _ in fetch_guild_member_roster(token, cfg)}


def apply_roster_filters(token, cfg, stats):
    """Optionally restrict the board to guild members (plus an allowlist),
    and always honor the exclude list. Fails open: if the roster can't be
    fetched, everyone stays on the board rather than posting a blank one."""
    filters = cfg.get("filters") or {}
    include = {n.strip().lower() for n in (filters.get("always_include") or [])}
    exclude = {n.strip().lower() for n in (filters.get("always_exclude") or [])}
    members_only = bool(filters.get("guild_members_only", False))

    allowed = None
    if members_only:
        try:
            allowed = fetch_guild_member_names(token, cfg) | include
            print(f"Roster filter active: {len(allowed)} allowed name(s).")
        except (RuntimeError, requests.RequestException) as exc:
            print(f"Guild roster lookup failed ({exc}); showing everyone this week.")
            allowed = None

    if allowed is None and not exclude:
        return stats

    def keep(name):
        low = name.strip().lower()
        if low in exclude:
            return False
        if allowed is not None and low not in allowed:
            return False
        return True

    for key in ("best_dps", "best_hps", "deaths", "participants"):
        stats[key] = {name: value for name, value in stats[key].items() if keep(name)}
    return stats


# ---------------------------------------------------------------------------
# Guild + character rankings (vs the rest of the region)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Guild + character rankings (vs the rest of the region)
# ---------------------------------------------------------------------------

def fetch_guild_standing(token, cfg, zone_id):
    """Guild progress rank vs other guilds: realm / region / world."""
    guild = cfg["guild"]
    data = gql(token, GUILD_STANDING_QUERY, {
        "name": guild["name"],
        "slug": guild["realm_slug"],
        "region": guild["region"],
        "zoneId": int(zone_id),
    })
    g = ((data.get("guildData") or {}).get("guild")) or {}
    progress = ((g.get("zoneRanking") or {}).get("progress")) or {}

    def rank_number(key):
        return (progress.get(key) or {}).get("number")

    return {
        "realm": rank_number("serverRank"),
        "region": rank_number("regionRank"),
        "world": rank_number("worldRank"),
    }


def fetch_realm_rank_leaders(token, cfg, participants, zone_id, difficulty):
    """For everyone who raided this week, pull their WCL All Stars standing
    for the current tier and rank them by realm rank (lower = better)."""
    rankings_cfg = cfg.get("rankings") or {}
    limit = int(rankings_cfg.get("max_characters", 30))
    region = cfg["guild"]["region"]
    default_slug = cfg["guild"]["realm_slug"]

    leaders = []
    for i, (name, slug) in enumerate(participants.items()):
        if i >= limit:
            break
        try:
            data = gql(token, CHARACTER_ALLSTARS_QUERY, {
                "name": name,
                "slug": slug or default_slug,
                "region": region,
                "zoneId": int(zone_id),
                "difficulty": int(difficulty),
            })
        except (RuntimeError, requests.RequestException) as exc:
            print(f"  Skipping {name}: {exc}")
            continue

        character = ((data.get("characterData") or {}).get("character")) or {}
        blob = character.get("zoneRankings") or {}
        all_stars = blob.get("allStars") or []
        if not all_stars:
            continue

        best = max(all_stars, key=lambda a: (a.get("points") or 0))
        realm_rank = best.get("serverRank")
        if not realm_rank:
            continue

        leaders.append({
            "name": name,
            "spec": best.get("spec") or "",
            "realm_rank": realm_rank,
            "region_rank": best.get("regionRank"),
            "best_avg": blob.get("bestPerformanceAverage"),
        })
        time.sleep(0.3)

    leaders.sort(key=lambda entry: entry["realm_rank"])
    return leaders


# ---------------------------------------------------------------------------
# Raider.io (optional M+ board)
# ---------------------------------------------------------------------------

def collect_mplus(cfg, token=None):
    """Return list of (key_level, dungeon, name, spec, timed) for the roster's best weekly runs.

    Supports both `mplus` and `mplus_last_week` section names. Uses cached roster when available.
    """
    print(f"[M+ LAST WEEK] Collecting weekly M+ data...")
    results = []
    region = cfg["guild"]["region"]

    # Try new section name first, then legacy `mplus`
    sections = cfg.get("sections", {})
    section_name = "mplus_last_week" if "mplus_last_week" in sections else "mplus"
    roster, _ = resolve_roster(cfg, token, section_name)

    print(f"[M+ LAST WEEK] Processing {len(roster)} characters...")
    for entry in roster:
        if "-" in entry:
            name, realm = entry.split("-", 1)
        else:
            name, realm = entry, cfg["guild"]["realm_slug"]
        try:
            resp = requests.get(RAIDERIO_URL, params={
                "region": region,
                "realm": realm.strip(),
                "name": name.strip(),
                "fields": "mythic_plus_weekly_highest_level_runs",
            }, timeout=30)
            if resp.status_code != 200:
                print(f"[M+ LAST WEEK] Failed to fetch {name}: HTTP {resp.status_code}")
                continue
            data = resp.json()
            runs = data.get("mythic_plus_weekly_highest_level_runs") or []
            if runs:
                best = max(runs, key=lambda r: r.get("mythic_level", 0))
                spec = clean_spec_name(best.get("spec"), data.get("class", ""))
                results.append((
                    best.get("mythic_level", 0),
                    best.get("dungeon", "?"),
                    name.strip(),
                    spec,
                    (best.get("num_keystone_upgrades", 0) or 0) > 0,
                ))
        except requests.RequestException as exc:
            print(f"[M+ LAST WEEK] Error fetching {name}: {exc}")
            continue
        time.sleep(0.3)
    results.sort(key=lambda r: r[0], reverse=True)
    print(f"[M+ LAST WEEK] Found {len(results)} players with weekly runs.")
    return results


def collect_mplus_season_scores(cfg, token=None):
    """Return list of (score, name, spec) for season-long M+ overall score from Raider.io.

    Tries `mythic_plus_scores` first (returns an `all` score), then falls back to the
    best `score` from `mythic_plus_best_runs`.
    """
    print(f"[M+ SEASON SCORES] Collecting season-long M+ scores...")
    results = []
    region = cfg["guild"]["region"]

    roster, _ = resolve_roster(cfg, token, "mplus_season_scores")

    print(f"[M+ SEASON SCORES] Processing {len(roster)} characters...")
    for entry in roster:
        if "-" in entry:
            name, realm = entry.split("-", 1)
        else:
            name, realm = entry, cfg["guild"]["realm_slug"]
        try:
            resp = requests.get(RAIDERIO_URL, params={
                "region": region,
                "realm": realm.strip(),
                "name": name.strip(),
                "fields": "mythic_plus_scores,mythic_plus_best_runs",
            }, timeout=30)
            if resp.status_code != 200:
                print(f"[M+ SEASON SCORES] Failed to fetch {name}: HTTP {resp.status_code}")
                continue
            data = resp.json()
            score = 0

            # Overall season score only (e.g., 3400 total rating)
            scores = data.get("mythic_plus_scores") or {}
            if isinstance(scores, dict):
                score = scores.get("all") or scores.get("score") or 0

            if score > 0:
                spec = clean_spec_name(data.get("active_spec_name"), data.get("class", ""))
                results.append((score, name.strip(), spec))
                print(f"[M+ SEASON SCORES] Added {name} with score {score}")
        except requests.RequestException as exc:
            print(f"[M+ SEASON SCORES] Error fetching {name}: {exc}")
            continue
        except Exception as exc:
            print(f"[M+ SEASON SCORES] Unexpected error for {name}: {exc}")
            continue
        time.sleep(0.3)
    results.sort(key=lambda r: r[0], reverse=True)
    print(f"[M+ SEASON SCORES] Found {len(results)} players with season scores.")
    return results


def collect_mplus_season_parses(cfg, token=None):
    """Return list of (parse/score, dungeon, name, spec, is_wcl) for best season M+ runs.

    Always starts with Raider.io `mythic_plus_best_runs` so the board has data.
    If WCL is enabled, tries to replace the top Raider.io entries with WCL parse
    percentiles for the same dungeon.
    """
    print("[M+ SEASON RUNS] Collecting season-long M+ runs...")
    sections = cfg.get("sections", {})
    mplus_cfg = sections.get("mplus_season_parses") or sections.get("mplus_season_runs", {})
    use_wcl = mplus_cfg.get("use_wcl_parses", True)

    roster, _ = resolve_roster(cfg, token, "mplus_season_parses" if "mplus_season_parses" in sections else "mplus_season_runs")

    # Always start with Raider.io data (reliable, gives us dungeon + score)
    results = collect_mplus_raiderio_season_runs(cfg, roster)

    if use_wcl and token and results:
        print("[M+ SEASON RUNS] Attempting WCL parse enrichment on top Raider.io entries...")
        try:
            wcl_results = collect_mplus_wcl_parses(cfg, token, results)
            if wcl_results:
                # Replace Raider.io entries by character name with WCL parse data
                by_name = {r[2].lower(): r for r in results}
                for wcl in wcl_results:
                    by_name[wcl[2].lower()] = wcl
                results = list(by_name.values())
                print(f"[M+ SEASON RUNS] Enriched {len(wcl_results)} entries with WCL parse data")
        except (RuntimeError, requests.RequestException) as exc:
            print(f"[M+ SEASON RUNS] WCL parse enrichment failed: {exc}")

    results.sort(key=lambda r: r[0], reverse=True)
    print(f"[M+ SEASON RUNS] Found {len(results)} players with season runs.")
    return results


def collect_mplus_raiderio_season_runs(cfg, roster):
    """Return list of (score, dungeon, name, spec) from Raider.io best runs."""
    print(f"[M+ SEASON RIO] Processing {len(roster)} characters...")
    results = []
    region = cfg["guild"]["region"]
    for entry in roster:
        if "-" in entry:
            name, realm = entry.split("-", 1)
        else:
            name, realm = entry, cfg["guild"]["realm_slug"]
        try:
            resp = requests.get(RAIDERIO_URL, params={
                "region": region,
                "realm": realm.strip(),
                "name": name.strip(),
                "fields": "mythic_plus_best_runs",
            }, timeout=30)
            if resp.status_code != 200:
                print(f"[M+ SEASON RIO] Failed to fetch {name}: HTTP {resp.status_code}")
                continue
            data = resp.json()
            runs = data.get("mythic_plus_best_runs") or []
            if not runs:
                runs = data.get("mythic_plus", {}).get("best_runs") or []
            if not runs:
                runs = data.get("mythic_plus_recent_best_runs") or []
            if runs:
                best_run = max(runs, key=lambda r: r.get("score", 0))
                score = best_run.get("score", 0)
                if score > 0:
                    spec = clean_spec_name(best_run.get("spec"), data.get("class", ""))
                    results.append((
                        score,
                        best_run.get("dungeon", "?"),
                        name.strip(),
                        spec,
                        False,
                    ))
                    print(f"[M+ SEASON RIO] Added {name} with score {score}")
        except requests.RequestException as exc:
            print(f"[M+ SEASON RIO] Error fetching {name}: {exc}")
            continue
        except Exception as exc:
            print(f"[M+ SEASON RIO] Unexpected error for {name}: {exc}")
            continue
        time.sleep(0.3)
    return results


# WCL M+ dungeon encounter IDs for current season (The War Within Season 2 / Liberation of Undermine)
# These are stable per expansion and may be discovered via worldData -> zones -> encounters if needed.
MPLUS_DUNGEON_IDS = [
    14963,  # The MOTHERLODE!!
    14971,  # The Rookery
    14973,  # Operation: Floodgate
    14975,  # The Theater of Pain
    14977,  # The Azure Vault
    14979,  # Darkflame Cleft
    14981,  # Cinderbrew Meadery
    14983,  # Priory of the Sacred Flame
]


def collect_mplus_wcl_parses(cfg, token, raiderio_results):
    """Attempt to fetch M+ parse percentiles from Warcraft Logs for top Raider.io entries.

    `raiderio_results` is a list of (score, dungeon, name, spec, is_wcl). We use
    the dungeon name to find the WCL encounter ID and replace the score with a
    parse percentile if one exists.

    Returns list of (percentile, dungeon, name, spec, is_wcl). Empty list if WCL
    does not return any data.
    """
    top_n = int(cfg.get("top_n", 5))
    candidates = raiderio_results[:top_n]
    print(f"[M+ WCL PARSES] Processing {len(candidates)} top Raider.io entries across {len(MPLUS_DUNGEON_IDS)} dungeons...")

    # Map dungeon name (case-insensitive) to encounter ID
    dungeon_to_id = {}
    for encounter_id in MPLUS_DUNGEON_IDS:
        name = _mplus_dungeon_name(cfg, token, encounter_id)
        dungeon_to_id[name.lower()] = encounter_id

    results = []
    call_count = 0
    call_limit = 100

    for score, rio_dungeon, name, spec, _ in candidates:
        if call_count >= call_limit:
            print(f"[M+ WCL PARSES] Hit call limit ({call_limit}); stopping.")
            break

        # Find WCL encounter ID for this dungeon
        encounter_id = dungeon_to_id.get((rio_dungeon or "").lower())
        if not encounter_id:
            continue

        # Parse realm from cached roster entry
        if "-" in name:
            char_name, realm = name.split("-", 1)
        else:
            char_name, realm = name, cfg["guild"]["realm_slug"]

        try:
            data = gql(token, MPLUS_PARSE_QUERY, {
                "name": char_name.strip(),
                "serverSlug": realm.strip(),
                "serverRegion": cfg["guild"]["region"],
                "encounterID": encounter_id,
            })
            call_count += 1
            rankings = (((data.get("characterData") or {}).get("character") or {}).get("encounterRankings") or {})
            ranks = rankings.get("ranks") or []
            if not ranks:
                continue
            # Best rank for this dungeon
            best = max(ranks, key=lambda r: r.get("percentile") or 0)
            percentile = best.get("percentile") or 0
            if percentile > 0:
                wcl_spec = clean_spec_name(best.get("spec"), best.get("class"))
                results.append((percentile, rio_dungeon, char_name.strip(), wcl_spec or spec, True))
                print(f"[M+ WCL PARSES] Added {char_name} {percentile:.0f}% on {rio_dungeon}")
        except Exception as exc:
            # WCL M+ parse lookup can fail for many reasons; log and continue
            print(f"[M+ WCL PARSES] Error for {char_name} on {rio_dungeon}: {exc}")
            continue

    print(f"[M+ WCL PARSES] Made {call_count} WCL calls, found {len(results)} results")
    return results


def _mplus_dungeon_name(cfg, token, encounter_id):
    """Best-effort dungeon name lookup from WCL encounter ID."""
    # Cache simple ID->name mapping to avoid extra calls
    if not hasattr(_mplus_dungeon_name, "cache"):
        _mplus_dungeon_name.cache = {}
    if encounter_id in _mplus_dungeon_name.cache:
        return _mplus_dungeon_name.cache[encounter_id]

    try:
        data = gql(token, MPLUS_DUNGEON_NAME_QUERY, {"encounterID": encounter_id})
        encounter = ((data.get("worldData") or {}).get("encounter") or {})
        name = encounter.get("name") or f"Dungeon {encounter_id}"
        _mplus_dungeon_name.cache[encounter_id] = name
        return name
    except Exception:
        return f"Dungeon {encounter_id}"


MPLUS_PARSE_QUERY = """
query ($name: String!, $serverSlug: String!, $serverRegion: String!, $encounterID: Int!) {
  characterData {
    character(name: $name, serverSlug: $serverSlug, serverRegion: $serverRegion) {
      encounterRankings(encounterID: $encounterID, metric: playerscore)
    }
  }
}
"""

MPLUS_DUNGEON_NAME_QUERY = """
query ($encounterID: Int!) {
  worldData {
    encounter(id: $encounterID) {
      name
    }
  }
}
"""


# ---------------------------------------------------------------------------
# Formatting + Discord
# ---------------------------------------------------------------------------

def fmt_amount(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return f"{n:.0f}"


def medal(i):
    return MEDALS[i] if i < len(MEDALS) else f"**{i + 1}.**"


def rank_lines_parses(best_parses, top_n, unit):
    ranked = sorted(best_parses.items(), key=lambda kv: kv[1]["parse"], reverse=True)[:top_n]
    lines = []
    for i, (name, info) in enumerate(ranked):
        lines.append(
            f"{medal(i)} **{name}** ({info['spec']}) — {info['parse']:.0f}% "
            f"on {info['boss']} ({fmt_amount(info['amount'])} {unit})"
        )
    return "\n".join(lines) if lines else "_No data this week_"


def rank_lines_deaths(deaths, top_n):
    ranked = sorted(deaths.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    lines = []
    for i, (name, count) in enumerate(ranked):
        lines.append(f"{medal(i)} **{name}** — {count} deaths")
    return "\n".join(lines) if lines else "_Nobody died. Suspicious._"


def rank_lines_leaders(leaders, top_n):
    lines = []
    for i, entry in enumerate(leaders[:top_n]):
        region_txt = ""
        if entry.get("region_rank"):
            region_txt = f" · Region #{entry['region_rank']:,}"
        avg_txt = ""
        if isinstance(entry.get("best_avg"), (int, float)):
            avg_txt = f" · {entry['best_avg']:.1f} best avg"
        lines.append(
            f"{medal(i)} **{entry['name']}** ({entry['spec']}) — "
            f"Realm **#{entry['realm_rank']:,}**{region_txt}{avg_txt}"
        )
    return "\n".join(lines) if lines else "_No ranked players found yet_"


def guild_standing_value(standing, zone_name):
    parts = []
    if standing.get("realm"):
        parts.append(f"Realm **#{standing['realm']:,}**")
    if standing.get("region"):
        parts.append(f"Region **#{standing['region']:,}**")
    if standing.get("world"):
        parts.append(f"World **#{standing['world']:,}**")
    if not parts:
        return None
    zone_txt = f" — {zone_name}" if zone_name else ""
    return " · ".join(parts) + f"\n_Progress ranking{zone_txt}_"


def rank_lines_mplus(results, top_n):
    lines = []
    for i, item in enumerate(results[:top_n]):
        # Support both old (level, dungeon, name, timed) and new (level, dungeon, name, spec, timed)
        if len(item) == 4:
            level, dungeon, name, timed = item
            spec = ""
        else:
            level, dungeon, name, spec, timed = item
        tag = "timed" if timed else "over time"
        spec_txt = f" ({spec})" if spec else ""
        lines.append(f"{medal(i)} **{name}**{spec_txt} — +{level} {dungeon} ({tag})")
    return "\n".join(lines) if lines else "_No keys recorded this week_"


# ---------------------------------------------------------------------------
# Section formatter functions for modular board system
# ---------------------------------------------------------------------------

def format_section_header(cfg, section_name, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    """Format a section header embed field for grouped board sections."""
    sections = cfg.get("sections", {})
    section_cfg = sections.get(section_name, {})

    if not section_cfg.get("enabled", True):
        return None

    title = section_cfg.get("title") or section_name.replace("_header", "").title()
    icon = section_cfg.get("icon", "")
    return {
        "name": f"────────── {icon} {title} {icon} ──────────",
        "value": "\u200b",
        "inline": False,
    }


def format_no_logs_notice(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    """Format the no logs notice field (only appears when no_logs is True)."""
    if not no_logs:
        return None
    
    sections = cfg.get("sections", {})
    notice_cfg = sections.get("no_logs_notice", {})
    
    if not notice_cfg.get("enabled", True):
        return None
    
    message = notice_cfg.get("message", "No raid logs found for the last {lookback_days} days.")
    lookback_days = cfg.get("lookback_days", 7)
    formatted_message = message.format(lookback_days=lookback_days)
    
    return {
        "name": "\u26A0\uFE0F No Logs This Week",
        "value": formatted_message,
        "inline": False,
    }


def format_guild_standing(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    """Format the guild standing field."""
    print(f"[SECTION] guild_standing: Checking if enabled...")
    sections = cfg.get("sections", {})
    standing_cfg = sections.get("guild_standing", {})
    
    if not standing_cfg.get("enabled", True):
        print(f"[SECTION] guild_standing: Disabled")
        return None
    
    # Fall back to legacy config if sections not present
    if not standing_cfg and cfg.get("rankings", {}).get("enabled", True):
        standing_cfg = cfg.get("rankings", {})
    
    if not standing_cfg.get("enabled", True):
        print(f"[SECTION] guild_standing: Disabled (legacy)")
        return None
    
    print(f"[SECTION] guild_standing: Enabled, formatting...")
    if standing:
        value = guild_standing_value(standing, zone_name)
        if value:
            return {"name": "\U0001F30D Guild Standing", "value": value, "inline": False}
    
    return None


def format_top_dps(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    """Format the top DPS parses field."""
    print(f"[SECTION] top_dps: Checking if enabled...")
    sections = cfg.get("sections", {})
    dps_cfg = sections.get("top_dps", {})
    
    if not dps_cfg.get("enabled", True):
        print(f"[SECTION] top_dps: Disabled")
        return None
    
    # Fall back to legacy config
    if not dps_cfg and cfg.get("raid", {}).get("enabled", True):
        dps_cfg = cfg.get("raid", {})
    
    if not dps_cfg.get("enabled", True):
        print(f"[SECTION] top_dps: Disabled (legacy)")
        return None
    
    print(f"[SECTION] top_dps: Enabled, formatting... stats is {stats}")
    if stats is not None:
        print(f"[SECTION] top_dps: stats has {len(stats.get('best_dps', {}))} DPS entries")
        top_n = int(cfg.get("top_n", 5))
        return {
            "name": "\u2694\uFE0F Top DPS Parses",
            "value": rank_lines_parses(stats["best_dps"], top_n, "DPS"),
            "inline": False,
        }
    else:
        print(f"[SECTION] top_dps: stats is None, skipping")
    
    return None


def format_top_healing(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    """Format the top healing parses field."""
    print(f"[SECTION] top_healing: Checking if enabled...")
    sections = cfg.get("sections", {})
    healing_cfg = sections.get("top_healing", {})
    
    if not healing_cfg.get("enabled", True):
        print(f"[SECTION] top_healing: Disabled")
        return None
    
    # Fall back to legacy config
    if not healing_cfg and cfg.get("raid", {}).get("enabled", True):
        healing_cfg = cfg.get("raid", {})
    
    if not healing_cfg.get("enabled", True):
        print(f"[SECTION] top_healing: Disabled (legacy)")
        return None
    
    print(f"[SECTION] top_healing: Enabled, formatting... stats is {stats}")
    if stats is not None:
        print(f"[SECTION] top_healing: stats has {len(stats.get('best_hps', {}))} HPS entries")
        top_n = int(cfg.get("top_n", 5))
        return {
            "name": "\U0001F489 Top Healing Parses",
            "value": rank_lines_parses(stats["best_hps"], top_n, "HPS"),
            "inline": False,
        }
    else:
        print(f"[SECTION] top_healing: stats is None, skipping")
    
    return None


def format_realm_rank_leaders(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    """Format the realm rank leaders field."""
    print(f"[SECTION] realm_rank_leaders: Checking if enabled...")
    sections = cfg.get("sections", {})
    leaders_cfg = sections.get("realm_rank_leaders", {})
    
    if not leaders_cfg.get("enabled", True):
        print(f"[SECTION] realm_rank_leaders: Disabled")
        return None
    
    # Fall back to legacy config
    if not leaders_cfg and cfg.get("rankings", {}).get("enabled", True):
        leaders_cfg = cfg.get("rankings", {})
    
    if not leaders_cfg.get("enabled", True):
        print(f"[SECTION] realm_rank_leaders: Disabled (legacy)")
        return None
    
    print(f"[SECTION] realm_rank_leaders: Enabled, formatting...")
    if leaders:
        top_n = int(cfg.get("top_n", 5))
        return {
            "name": "\u2B50 Realm Rank Leaders (Tier All Stars)",
            "value": rank_lines_leaders(leaders, top_n),
            "inline": False,
        }
    
    return None


def format_most_deaths(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    """Format the most deaths field."""
    print(f"[SECTION] most_deaths: Checking if enabled...")
    sections = cfg.get("sections", {})
    deaths_cfg = sections.get("most_deaths", {})
    
    if not deaths_cfg.get("enabled", True):
        print(f"[SECTION] most_deaths: Disabled")
        return None
    
    print(f"[SECTION] most_deaths: Enabled, formatting...")
    if stats is not None:
        top_n = int(cfg.get("top_n", 5))
        return {
            "name": "\U0001F480 Graveyard Camper Award (Most Deaths)",
            "value": rank_lines_deaths(stats["deaths"], top_n),
            "inline": False,
        }
    
    return None


def format_roast_of_the_week(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    """Format the roast of the week field."""
    print(f"[SECTION] roast_of_the_week: Checking if enabled...")
    sections = cfg.get("sections", {})
    roast_cfg = sections.get("roast_of_the_week", {})
    
    if not roast_cfg.get("enabled", True):
        print(f"[SECTION] roast_of_the_week: Disabled")
        return None
    
    # Fall back to legacy config
    if not roast_cfg:
        roast_cfg = cfg.get("roast_of_the_week", {})
    
    if not roast_cfg:
        print(f"[SECTION] roast_of_the_week: No config found")
        return None
    
    print(f"[SECTION] roast_of_the_week: Enabled, formatting...")
    if roast_cfg.get("roast"):
        winner = roast_cfg.get("winner", "Anonymous")
        target = roast_cfg.get("target", "")
        target_txt = f" (aimed at {target})" if target else ""
        return {
            "name": "\U0001F525 Roast of the Week",
            "value": f"\u201C{roast_cfg['roast']}\u201D\n— **{winner}**{target_txt}",
            "inline": False,
        }
    else:
        return {
            "name": "\U0001F525 Roast of the Week",
            "value": "_No roast submitted. Healers live to see another week._",
            "inline": False,
        }


def format_mplus(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    """Format the M+ last-week board field."""
    print(f"[SECTION] mplus_last_week: Checking if enabled...")
    sections = cfg.get("sections", {})
    mplus_cfg = sections.get("mplus_last_week") if sections else {}
    if not mplus_cfg:
        mplus_cfg = sections.get("mplus", {})
    if not mplus_cfg:
        mplus_cfg = cfg.get("mplus", {})

    if not mplus_cfg.get("enabled", True):
        print(f"[SECTION] mplus_last_week: Disabled")
        return None

    print(f"[SECTION] mplus_last_week: Enabled, formatting...")
    if mplus_results is not None:
        top_n = int(cfg.get("top_n", 5))
        return {
            "name": "\U0001F5DD\uFE0F Last Week M+ Runs",
            "value": rank_lines_mplus(mplus_results, top_n),
            "inline": False,
        }

    return None


def format_mplus_season_scores(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    """Format the M+ season scores field."""
    print(f"[SECTION] mplus_season_scores: Checking if enabled...")
    sections = cfg.get("sections", {})
    mplus_cfg = sections.get("mplus_season_scores", {})

    if not mplus_cfg.get("enabled", True):
        print(f"[SECTION] mplus_season_scores: Disabled")
        return None

    print(f"[SECTION] mplus_season_scores: Enabled, formatting...")
    if mplus_season_scores is not None:
        top_n = int(cfg.get("top_n", 5))
        lines = []
        for i, (score, name, spec) in enumerate(mplus_season_scores[:top_n]):
            spec_txt = f" ({spec})" if spec else ""
            lines.append(f"{medal(i)} **{name}**{spec_txt} — {score:.0f} score")
        value = "\n".join(lines) if lines else "_No season scores found_"
        return {
            "name": "\U0001F3C6 Season-Long M+ Scores",
            "value": value,
            "inline": False,
        }

    return None


def format_mplus_season_parses(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    """Format the M+ season runs/parses field."""
    print(f"[SECTION] mplus_season_runs: Checking if enabled...")
    sections = cfg.get("sections", {})
    mplus_cfg = sections.get("mplus_season_runs") if sections else {}
    if not mplus_cfg:
        mplus_cfg = sections.get("mplus_season_parses", {})

    if not mplus_cfg.get("enabled", True):
        print(f"[SECTION] mplus_season_runs: Disabled")
        return None

    print(f"[SECTION] mplus_season_runs: Enabled, formatting...")
    if mplus_season_parses is not None:
        top_n = int(cfg.get("top_n", 5))
        lines = []
        use_wcl = mplus_cfg.get("use_wcl_parses", True)
        for i, item in enumerate(mplus_season_parses[:top_n]):
            if len(item) == 5:
                value, dungeon, name, spec, is_wcl = item
            else:
                value, dungeon, name, spec = item
                is_wcl = use_wcl
            spec_txt = f" ({spec})" if spec else ""
            if is_wcl:
                lines.append(f"{medal(i)} **{name}**{spec_txt} — {value:.0f}% on {dungeon}")
            else:
                lines.append(f"{medal(i)} **{name}**{spec_txt} — {value:.0f} score on {dungeon}")
        value = "\n".join(lines) if lines else "_No season runs found_"
        return {
            "name": "\U0001F525 Top Season Mythic+ Runs",
            "value": value,
            "inline": False,
        }

    return None


# Section registry: maps section names to their formatter functions
SECTION_FORMATTERS = {
    "no_logs_notice": format_no_logs_notice,
    "guild_achievement_header": lambda cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs: format_section_header(cfg, "guild_achievement_header", stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs),
    "guild_standing": format_guild_standing,
    "mplus_header": lambda cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs: format_section_header(cfg, "mplus_header", stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs),
    "mplus": format_mplus,
    "mplus_last_week": format_mplus,
    "mplus_season_scores": format_mplus_season_scores,
    "mplus_season_parses": format_mplus_season_parses,
    "mplus_season_runs": format_mplus_season_parses,
    "raid_header": lambda cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs: format_section_header(cfg, "raid_header", stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs),
    "top_dps": format_top_dps,
    "top_healing": format_top_healing,
    "realm_rank_leaders": format_realm_rank_leaders,
    "most_deaths": format_most_deaths,
    "roast_of_the_week": format_roast_of_the_week,
}


def _load_font(size):
    """Try to load a nice font, fall back to Pillow default."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def generate_progress_image(cfg, stats, standing, zone_name, start_dt, end_dt, output_path="progress.png"):
    """Generate a static PNG progress image from the data we have and save it.

    Discord cannot embed the WCL HTML widget, so we attach a generated image instead.
    """
    width, height = 850, 320
    bg = (18, 18, 22)
    accent = (230, 180, 70)
    text = (220, 220, 220)
    muted = (150, 150, 150)

    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    title_font = _load_font(32)
    subtitle_font = _load_font(20)
    label_font = _load_font(16)
    value_font = _load_font(24)

    guild_name = cfg["guild"]["name"]
    difficulty = str(cfg.get("raid", {}).get("difficulty", "mythic")).title()
    zone = zone_name or "Current Raid"
    date_range = f"{start_dt.strftime('%b %d')} – {end_dt.strftime('%b %d, %Y')}"

    # Title
    draw.text((40, 30), guild_name, font=title_font, fill=accent)
    draw.text((40, 75), f"{difficulty} {zone}", font=subtitle_font, fill=text)
    draw.text((40, 105), date_range, font=label_font, fill=muted)

    # Stats boxes
    kills = stats.get("kills", 0) if stats else 0
    pulls = stats.get("pulls", 0) if stats else 0
    deaths = stats.get("deaths", {}) if stats else {}
    total_deaths = sum(deaths.values()) if deaths else 0

    stats_data = [
        ("Kills", str(kills)),
        ("Pulls", str(pulls)),
        ("Deaths", str(total_deaths)),
    ]

    if standing:
        if standing.get("world"):
            stats_data.append(("World", f"#{standing['world']:,}"))
        if standing.get("region"):
            stats_data.append(("Region", f"#{standing['region']:,}"))
        if standing.get("realm"):
            stats_data.append(("Realm", f"#{standing['realm']:,}"))

    x = 40
    y = 160
    for label, value in stats_data[:5]:
        draw.text((x, y), label, font=label_font, fill=muted)
        draw.text((x, y + 25), value, font=value_font, fill=text)
        x += 150

    # Pull bar
    bar_x, bar_y, bar_w, bar_h = 40, 250, 770, 30
    draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=6, outline=muted, width=2)
    if pulls > 0:
        fill_w = int(bar_w * (kills / max(pulls, 1)))
        if fill_w > 0:
            draw.rounded_rectangle([bar_x, bar_y, bar_x + fill_w, bar_y + bar_h], radius=6, fill=accent)
        pct = kills / max(pulls, 1) * 100
        label = f"{kills} / {pulls} kills ({pct:.1f}%)"
    else:
        label = "No pulls this week"
    bbox = draw.textbbox((0, 0), label, font=label_font)
    text_w = bbox[2] - bbox[0]
    draw.text((bar_x + (bar_w - text_w) // 2, bar_y + 4), label, font=label_font, fill=bg if pulls and kills else text)

    img.save(output_path, "PNG")
    print(f"[PROGRESS IMAGE] Generated static image at {output_path}")


def build_embed(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, start_dt, end_dt, no_logs=False, progress_image_url=None):
    guild_name = cfg["guild"]["name"]
    difficulty = str(cfg["raid"]["difficulty"]).title()
    top_n = int(cfg.get("top_n", 5))
    date_range = f"{start_dt.strftime('%b %d')} – {end_dt.strftime('%b %d, %Y')}"

    # Progress image configuration
    sections = cfg.get("sections", {})
    progress_cfg = sections.get("progress_image", {})
    
    progress_image = None
    if progress_cfg.get("enabled", True):
        if progress_image_url:
            progress_image = progress_image_url
            print(f"[PROGRESS IMAGE] Using provided image URL: {progress_image}")
        else:
            progress_image = progress_cfg.get("url", "https://www.warcraftlogs.com/embed/guild-progress-tile/46?difficulty=4&guild=821721")
            print(f"[PROGRESS IMAGE] URL: {progress_image}")

            # Test if image URL is accessible if remove_on_failure is set
            if progress_cfg.get("remove_on_failure", True) and progress_image:
                try:
                    print(f"[PROGRESS IMAGE] Verifying URL accessibility...")
                    # Use GET request instead of HEAD for better compatibility
                    resp = requests.get(progress_image, timeout=5, stream=True, allow_redirects=True)
                    print(f"[PROGRESS IMAGE] GET request status: {resp.status_code}")
                    if resp.status_code >= 400:
                        print(f"[PROGRESS IMAGE] URL returned error status {resp.status_code}, removing image.")
                        progress_image = None
                    else:
                        print(f"[PROGRESS IMAGE] URL accessible, including image.")
                    resp.close()
                except requests.RequestException as exc:
                    print(f"[PROGRESS IMAGE] Failed to verify URL: {exc}, removing image.")
                    progress_image = None
    else:
        print(f"[PROGRESS IMAGE] Section disabled.")

    # Build fields using section registry
    fields = []
    
    # Get sections and sort by order
    section_items = list(sections.items()) if sections else []
    
    # Add legacy config sections if new sections not present
    if not section_items:
        # Use legacy behavior
        if standing:
            value = guild_standing_value(standing, zone_name)
            if value:
                fields.append({"name": "\U0001F30D Guild Standing", "value": value, "inline": False})

        if stats is not None:
            fields.append({
                "name": "\u2694\uFE0F Top DPS Parses",
                "value": rank_lines_parses(stats["best_dps"], top_n, "DPS"),
                "inline": False,
            })
            fields.append({
                "name": "\U0001F489 Top Healing Parses",
                "value": rank_lines_parses(stats["best_hps"], top_n, "HPS"),
                "inline": False,
            })

        if leaders:
            fields.append({
                "name": "\u2B50 Realm Rank Leaders (Tier All Stars)",
                "value": rank_lines_leaders(leaders, top_n),
                "inline": False,
            })

        if stats is not None:
            fields.append({
                "name": "\U0001F480 Graveyard Camper Award (Most Deaths)",
                "value": rank_lines_deaths(stats["deaths"], top_n),
                "inline": False,
            })

        roast = cfg.get("roast_of_the_week") or {}
        if roast.get("roast"):
            winner = roast.get("winner", "Anonymous")
            target = roast.get("target", "")
            target_txt = f" (aimed at {target})" if target else ""
            fields.append({
                "name": "\U0001F525 Roast of the Week",
                "value": f"\u201C{roast['roast']}\u201D\n— **{winner}**{target_txt}",
                "inline": False,
            })
        else:
            fields.append({
                "name": "\U0001F525 Roast of the Week",
                "value": "_No roast submitted. Healers live to see another week._",
                "inline": False,
            })

        if mplus_results is not None:
            fields.append({
                "name": "\U0001F5DD\uFE0F Highest M+ Keys This Week",
                "value": rank_lines_mplus(mplus_results, top_n),
                "inline": False,
            })
    else:
        # Use new modular section system
        sorted_sections = sorted(section_items, key=lambda x: x[1].get("order", 999))
        
        for section_name, section_cfg in sorted_sections:
            formatter = SECTION_FORMATTERS.get(section_name)
            if formatter:
                try:
                    field = formatter(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs)
                    if field:
                        fields.append(field)
                except Exception as exc:
                    print(f"Error formatting section '{section_name}': {exc}")
                    continue

    footer_bits = []
    if stats is not None:
        footer_bits.append(f"{stats['kills']} kills / {stats['pulls']} pulls this week")
    footer_bits.append("Drop your healer roasts in the thread for next week \U0001F525")

    embed = {
        "title": f"\U0001F3C6 {guild_name} Weekly Board — {difficulty}",
        "description": f"Raid week: **{date_range}**",
        "color": 0xC69B6D,
        "fields": fields,
        "footer": {"text": " | ".join(footer_bits)},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    if progress_image:
        embed["image"] = {"url": progress_image}
    
    return embed


def post_to_discord(webhook_url, embed, content=None, image_path=None):
    payload = {"embeds": [embed]}
    if content:
        payload["content"] = content

    if image_path and os.path.exists(image_path):
        with open(image_path, "rb") as f:
            files = {"file": (os.path.basename(image_path), f, "image/png")}
            data = {"payload_json": json.dumps(payload)}
            resp = requests.post(webhook_url, data=data, files=files, timeout=30)
    else:
        resp = requests.post(webhook_url, json=payload, timeout=30)
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    cfg = load_config()
    webhook_url = require_env("DISCORD_WEBHOOK_URL")

    lookback_days = int(cfg.get("lookback_days", 7))
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=lookback_days)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    stats = None
    standing = None
    leaders = None
    zone_name = None
    no_logs = False
    token = None

    # Check if we need WCL token (for raid or M+ auto-fetch)
    sections = cfg.get("sections", {})
    mplus_cfg = sections.get("mplus") if sections else cfg.get("mplus", {})
    mplus_season_scores_cfg = sections.get("mplus_season_scores", {})
    mplus_season_parses_cfg = sections.get("mplus_season_parses") or sections.get("mplus_season_runs", {})
    raid_enabled = cfg.get("raid", {}).get("enabled", True)

    mplus_enabled = mplus_cfg.get("enabled", False)
    mplus_auto_fetch = mplus_cfg.get("auto_fetch_roster", False)
    season_scores_auto_fetch = mplus_season_scores_cfg.get("auto_fetch_roster", False)
    season_parses_auto_fetch = mplus_season_parses_cfg.get("auto_fetch_roster", False)

    needs_token = (
        raid_enabled
        or (mplus_enabled and mplus_auto_fetch)
        or (mplus_season_scores_cfg.get("enabled", False) and season_scores_auto_fetch)
        or (mplus_season_parses_cfg.get("enabled", False) and season_parses_auto_fetch)
    )
    
    if needs_token:
        client_id = require_env("WCL_CLIENT_ID")
        client_secret = require_env("WCL_CLIENT_SECRET")
        token = get_wcl_token(client_id, client_secret)

    if raid_enabled:
        reports = fetch_guild_reports(token, cfg, start_ms, end_ms)

        if not reports:
            print("No Warcraft Logs reports found in the lookback window.")
            no_logs = True
        else:
            print(f"Found {len(reports)} report(s) this week.")
            
            # Use difficulty fallback for raid stats
            sections = cfg.get("sections", {})
            raid_cfg = sections.get("top_dps") if sections else cfg.get("raid", {})
            use_fallback = raid_cfg.get("difficulty_fallback", True)
            
            if use_fallback:
                print("[RAID] Using difficulty fallback (mythic -> heroic -> normal)")
                stats, difficulty_used = try_difficulties(collect_raid_stats, cfg, token, reports)
                if stats:
                    print(f"[RAID] Using {difficulty_used} data")
                    print(f"[RAID] Stats: {len(stats.get('best_dps', {}))} DPS, {len(stats.get('best_hps', {}))} HPS, {stats.get('kills')} kills, {stats.get('pulls')} pulls")
                else:
                    print("[RAID] No data found for any difficulty")
            else:
                print("[RAID] Using configured difficulty only")
                stats = collect_raid_stats(token, cfg, reports)
                if stats:
                    print(f"[RAID] Stats: {len(stats.get('best_dps', {}))} DPS, {len(stats.get('best_hps', {}))} HPS, {stats.get('kills')} kills, {stats.get('pulls')} pulls")
                else:
                    print("[RAID] No data found")
            
            if stats:
                stats = apply_roster_filters(token, cfg, stats)
                print(f"[RAID] After roster filters: {len(stats.get('best_dps', {}))} DPS, {len(stats.get('best_hps', {}))} HPS")
            else:
                print("[RAID] Stats is None, skipping roster filters")

            # Rankings vs the rest of the region (never let this block the post)
            if (cfg.get("rankings") or {}).get("enabled", True):
                zone_id, zone_name = detect_zone(cfg, reports)
                if zone_id:
                    # Use difficulty fallback for guild standing
                    if use_fallback:
                        print("[GUILD STANDING] Using difficulty fallback")
                        # Guild standing doesn't use difficulty, just try once
                        try:
                            standing = fetch_guild_standing(token, cfg, zone_id)
                            if standing:
                                print("[GUILD STANDING] Found data")
                        except (RuntimeError, requests.RequestException) as exc:
                            print(f"Guild standing lookup failed: {exc}")
                    else:
                        try:
                            standing = fetch_guild_standing(token, cfg, zone_id)
                        except (RuntimeError, requests.RequestException) as exc:
                            print(f"Guild standing lookup failed: {exc}")
                    
                    # Use difficulty fallback for realm rank leaders
                    if stats and stats.get("participants"):
                        if use_fallback:
                            print("[REALM RANK LEADERS] Using difficulty fallback")
                            leaders, diff_used = try_difficulties(
                                lambda token, cfg, reports, difficulty: fetch_realm_rank_leaders(
                                    token, cfg, stats["participants"], zone_id, difficulty
                                ),
                                cfg, token, reports
                            )
                            if leaders:
                                print(f"[REALM RANK LEADERS] Using {diff_used} data")
                        else:
                            try:
                                leaders = fetch_realm_rank_leaders(
                                    token, cfg, stats["participants"], zone_id, stats["difficulty"]
                                )
                            except (RuntimeError, requests.RequestException) as exc:
                                print(f"Realm rank leaders lookup failed: {exc}")
                else:
                    print("Could not detect raid zone; skipping rankings section.")

    mplus_results = None
    mplus_season_scores = None
    mplus_season_parses = None
    
    if mplus_enabled:
        mplus_results = collect_mplus(cfg, token)
    
    # Collect M+ season data if enabled
    sections = cfg.get("sections", {})
    mplus_season_scores_cfg = sections.get("mplus_season_scores", {})
    mplus_season_parses_cfg = sections.get("mplus_season_parses", {})
    
    if mplus_season_scores_cfg.get("enabled", False):
        mplus_season_scores = collect_mplus_season_scores(cfg, token)
    
    if mplus_season_parses_cfg.get("enabled", False):
        mplus_season_parses = collect_mplus_season_parses(cfg, token)

    # Generate static progress image; Discord cannot embed the WCL HTML widget
    sections = cfg.get("sections", {})
    progress_cfg = sections.get("progress_image", {})
    progress_image_path = None
    progress_image_url = None
    if progress_cfg.get("enabled", True):
        progress_image_path = "progress.png"
        try:
            generate_progress_image(cfg, stats, standing, zone_name, start_dt, end_dt, progress_image_path)
            progress_image_url = "attachment://progress.png"
        except Exception as exc:
            print(f"[PROGRESS IMAGE] Failed to generate image: {exc}")
            progress_image_path = None

    embed = build_embed(cfg, stats, standing, leaders, zone_name,
                        mplus_results, mplus_season_scores, mplus_season_parses, start_dt, end_dt, no_logs,
                        progress_image_url=progress_image_url)
    post_to_discord(webhook_url, embed, image_path=progress_image_path)
    print("Board posted to Discord.")


if __name__ == "__main__":
    main()

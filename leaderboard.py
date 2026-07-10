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

import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import requests
import yaml

WCL_TOKEN_URL = "https://www.warcraftlogs.com/oauth/token"
WCL_API_URL = "https://www.warcraftlogs.com/api/v2/client"
RAIDERIO_URL = "https://raider.io/api/v1/characters/profile"

DIFFICULTY_MAP = {"lfr": 1, "normal": 3, "heroic": 4, "mythic": 5}
MEDALS = ["\U0001F947", "\U0001F948", "\U0001F949", "**4.**", "**5.**"]

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
        func: Function that takes (cfg, token, reports, difficulty, *args) as parameters
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
            result = func(cfg, token, reports, difficulty_num, *args)
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

def fetch_guild_member_names(token, cfg):
    """Pull the guild roster from Warcraft Logs (synced from the in-game roster)."""
    guild = cfg["guild"]
    names = set()
    page = 1
    while page <= 10:  # up to 1000 members; plenty
        data = gql(token, GUILD_MEMBERS_QUERY, {
            "name": guild["name"],
            "slug": guild["realm_slug"],
            "region": guild["region"],
            "page": page,
        })
        members = (((data.get("guildData") or {}).get("guild") or {}).get("members")) or {}
        for member in (members.get("data") or []):
            name = member.get("name")
            if name:
                names.add(name.strip().lower())
        if not members.get("has_more_pages"):
            break
        page += 1
    return names


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
    """Return list of (key_level, dungeon, name, timed) for the roster's best weekly runs.
    
    If token is provided and auto_fetch_roster is enabled, fetches roster from WCL guild API.
    Otherwise uses manual roster from config.
    """
    print(f"[M+ WEEKLY] Collecting weekly M+ data...")
    results = []
    region = cfg["guild"]["region"]
    default_realm = cfg["guild"]["realm_slug"]
    
    # Determine roster source
    sections = cfg.get("sections", {})
    mplus_cfg = sections.get("mplus") if sections else cfg.get("mplus", {})
    
    roster = mplus_cfg.get("roster", [])
    auto_fetch = mplus_cfg.get("auto_fetch_roster", False)
    
    # Auto-fetch roster from WCL if enabled and no manual roster provided
    if auto_fetch and not roster and token:
        try:
            print("[M+ WEEKLY] Auto-fetching roster from guild members...")
            guild_names = fetch_guild_member_names(token, cfg)
            if guild_names:
                # Format as Name-Realm for Raider.io
                roster = [f"{name}-{default_realm}" for name in guild_names]
                print(f"[M+ WEEKLY] Fetched {len(roster)} guild members for M+ roster.")
        except (RuntimeError, requests.RequestException) as exc:
            print(f"[M+ WEEKLY] Failed to auto-fetch roster: {exc}")
            roster = []
    
    print(f"[M+ WEEKLY] Processing {len(roster)} characters...")
    for entry in roster:
        if "-" in entry:
            name, realm = entry.split("-", 1)
        else:
            name, realm = entry, default_realm
        try:
            resp = requests.get(RAIDERIO_URL, params={
                "region": region,
                "realm": realm.strip(),
                "name": name.strip(),
                "fields": "mythic_plus_weekly_highest_level_runs",
            }, timeout=30)
            if resp.status_code != 200:
                print(f"[M+ WEEKLY] Failed to fetch {name}: HTTP {resp.status_code}")
                continue
            runs = resp.json().get("mythic_plus_weekly_highest_level_runs") or []
            if runs:
                best = max(runs, key=lambda r: r.get("mythic_level", 0))
                results.append((
                    best.get("mythic_level", 0),
                    best.get("dungeon", "?"),
                    name.strip(),
                    (best.get("num_keystone_upgrades", 0) or 0) > 0,
                ))
        except requests.RequestException as exc:
            print(f"[M+ WEEKLY] Error fetching {name}: {exc}")
            continue
        time.sleep(0.3)
    results.sort(key=lambda r: r[0], reverse=True)
    print(f"[M+ WEEKLY] Found {len(results)} players with weekly runs.")
    return results


def collect_mplus_season_scores(cfg, token=None):
    """Return list of (score, name, class, spec) for season-long M+ scores from Raider.io."""
    print(f"[M+ SEASON SCORES] Collecting season-long M+ scores...")
    results = []
    region = cfg["guild"]["region"]
    default_realm = cfg["guild"]["realm_slug"]
    
    # Determine roster source
    sections = cfg.get("sections", {})
    mplus_cfg = sections.get("mplus_season_scores", {})
    
    roster = mplus_cfg.get("roster", [])
    auto_fetch = mplus_cfg.get("auto_fetch_roster", False)
    
    # Auto-fetch roster from WCL if enabled and no manual roster provided
    if auto_fetch and not roster and token:
        try:
            print("[M+ SEASON SCORES] Auto-fetching roster from guild members...")
            guild_names = fetch_guild_member_names(token, cfg)
            if guild_names:
                roster = [f"{name}-{default_realm}" for name in guild_names]
                print(f"[M+ SEASON SCORES] Fetched {len(roster)} guild members.")
        except (RuntimeError, requests.RequestException) as exc:
            print(f"[M+ SEASON SCORES] Failed to auto-fetch roster: {exc}")
            roster = []
    
    print(f"[M+ SEASON SCORES] Processing {len(roster)} characters...")
    for entry in roster:
        if "-" in entry:
            name, realm = entry.split("-", 1)
        else:
            name, realm = entry, default_realm
        try:
            resp = requests.get(RAIDERIO_URL, params={
                "region": region,
                "realm": realm.strip(),
                "name": name.strip(),
                "fields": "mythic_plus_scores_by_season",
            }, timeout=30)
            if resp.status_code != 200:
                print(f"[M+ SEASON SCORES] Failed to fetch {name}: HTTP {resp.status_code}")
                continue
            data = resp.json()
            
            # Try to get season scores
            season_scores = data.get("mythic_plus_scores_by_season")
            if season_scores:
                # Get current season score
                current_season = season_scores.get("season", {})
                if current_season:
                    score = current_season.get("score", 0)
                    if score > 0:
                        results.append((score, name.strip(), data.get("class", ""), data.get("active_spec_name", "")))
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
    """Return list of (score, dungeon, name, class, spec) for best season runs from Raider.io."""
    print(f"[M+ SEASON PARSES] Collecting season-long M+ runs...")
    results = []
    region = cfg["guild"]["region"]
    default_realm = cfg["guild"]["realm_slug"]
    
    # Determine roster source
    sections = cfg.get("sections", {})
    mplus_cfg = sections.get("mplus_season_parses", {})
    
    roster = mplus_cfg.get("roster", [])
    auto_fetch = mplus_cfg.get("auto_fetch_roster", False)
    
    # Auto-fetch roster from WCL if enabled and no manual roster provided
    if auto_fetch and not roster and token:
        try:
            print("[M+ SEASON PARSES] Auto-fetching roster from guild members...")
            guild_names = fetch_guild_member_names(token, cfg)
            if guild_names:
                roster = [f"{name}-{default_realm}" for name in guild_names]
                print(f"[M+ SEASON PARSES] Fetched {len(roster)} guild members.")
        except (RuntimeError, requests.RequestException) as exc:
            print(f"[M+ SEASON PARSES] Failed to auto-fetch roster: {exc}")
            roster = []
    
    print(f"[M+ SEASON PARSES] Processing {len(roster)} characters...")
    for entry in roster:
        if "-" in entry:
            name, realm = entry.split("-", 1)
        else:
            name, realm = entry, default_realm
        try:
            resp = requests.get(RAIDERIO_URL, params={
                "region": region,
                "realm": realm.strip(),
                "name": name.strip(),
                "fields": "mythic_plus_best_runs",
            }, timeout=30)
            if resp.status_code != 200:
                print(f"[M+ SEASON PARSES] Failed to fetch {name}: HTTP {resp.status_code}")
                continue
            data = resp.json()
            
            # Try multiple possible field names for runs
            runs = data.get("mythic_plus_best_runs")
            if not runs:
                runs = data.get("mythic_plus", {}).get("best_runs")
            if not runs:
                runs = data.get("mythic_plus_recent_best_runs")
            
            if runs:
                # Get best run by score across all runs
                best_run = max(runs, key=lambda r: r.get("score", 0))
                score = best_run.get("score", 0)
                if score > 0:
                    results.append((
                        score,
                        best_run.get("dungeon", "?"),
                        name.strip(),
                        best_run.get("class", ""),
                        best_run.get("spec", ""),
                    ))
                    print(f"[M+ SEASON PARSES] Added {name} with score {score}")
        except requests.RequestException as exc:
            print(f"[M+ SEASON PARSES] Error fetching {name}: {exc}")
            continue
        except Exception as exc:
            print(f"[M+ SEASON PARSES] Unexpected error for {name}: {exc}")
            continue
        time.sleep(0.3)
    results.sort(key=lambda r: r[0], reverse=True)
    print(f"[M+ SEASON PARSES] Found {len(results)} players with season runs.")
    return results


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
    for i, (level, dungeon, name, timed) in enumerate(results[:top_n]):
        tag = "timed" if timed else "over time"
        lines.append(f"{medal(i)} **{name}** — +{level} {dungeon} ({tag})")
    return "\n".join(lines) if lines else "_No keys recorded this week_"


# ---------------------------------------------------------------------------
# Section formatter functions for modular board system
# ---------------------------------------------------------------------------

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
    """Format the M+ board field."""
    print(f"[SECTION] mplus: Checking if enabled...")
    sections = cfg.get("sections", {})
    mplus_cfg = sections.get("mplus", {})
    
    if not mplus_cfg.get("enabled", True):
        print(f"[SECTION] mplus: Disabled")
        return None
    
    # Fall back to legacy config
    if not mplus_cfg:
        mplus_cfg = cfg.get("mplus", {})
    
    if not mplus_cfg.get("enabled", False):
        print(f"[SECTION] mplus: Disabled (legacy)")
        return None
    
    print(f"[SECTION] mplus: Enabled, formatting...")
    if mplus_results is not None:
        top_n = int(cfg.get("top_n", 5))
        return {
            "name": "\U0001F5DD\uFE0F Highest M+ Keys This Week",
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
        for i, (score, name, cls, spec) in enumerate(mplus_season_scores[:top_n]):
            lines.append(f"{medal(i)} **{name}** ({cls} {spec}) — {score:.0f} score")
        value = "\n".join(lines) if lines else "_No season scores found_"
        return {
            "name": "\U0001F3C6 Season-Long M+ Scores",
            "value": value,
            "inline": False,
        }
    
    return None


def format_mplus_season_parses(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    """Format the M+ season parses field."""
    print(f"[SECTION] mplus_season_parses: Checking if enabled...")
    sections = cfg.get("sections", {})
    mplus_cfg = sections.get("mplus_season_parses", {})
    
    if not mplus_cfg.get("enabled", True):
        print(f"[SECTION] mplus_season_parses: Disabled")
        return None
    
    print(f"[SECTION] mplus_season_parses: Enabled, formatting...")
    if mplus_season_parses is not None:
        top_n = int(cfg.get("top_n", 5))
        lines = []
        for i, (parse, dungeon, name, cls, spec) in enumerate(mplus_season_parses[:top_n]):
            lines.append(f"{medal(i)} **{name}** ({cls} {spec}) — {parse:.0f}% on {dungeon}")
        value = "\n".join(lines) if lines else "_No season parses found_"
        return {
            "name": "\U0001F525 Season-Long Top M+ Parses",
            "value": value,
            "inline": False,
        }
    
    return None


# Section registry: maps section names to their formatter functions
SECTION_FORMATTERS = {
    "no_logs_notice": format_no_logs_notice,
    "guild_standing": format_guild_standing,
    "top_dps": format_top_dps,
    "top_healing": format_top_healing,
    "realm_rank_leaders": format_realm_rank_leaders,
    "most_deaths": format_most_deaths,
    "roast_of_the_week": format_roast_of_the_week,
    "mplus": format_mplus,
    "mplus_season_scores": format_mplus_season_scores,
    "mplus_season_parses": format_mplus_season_parses,
}


def build_embed(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, start_dt, end_dt, no_logs=False):
    guild_name = cfg["guild"]["name"]
    difficulty = str(cfg["raid"]["difficulty"]).title()
    top_n = int(cfg.get("top_n", 5))
    date_range = f"{start_dt.strftime('%b %d')} – {end_dt.strftime('%b %d, %Y')}"

    # Progress image configuration
    sections = cfg.get("sections", {})
    progress_cfg = sections.get("progress_image", {})
    
    progress_image = None
    if progress_cfg.get("enabled", True):
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


def post_to_discord(webhook_url, embed, content=None):
    payload = {"embeds": [embed]}
    if content:
        payload["content"] = content
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
    raid_enabled = cfg.get("raid", {}).get("enabled", True)
    mplus_enabled = mplus_cfg.get("enabled", False)
    mplus_auto_fetch = mplus_cfg.get("auto_fetch_roster", False)
    
    needs_token = raid_enabled or (mplus_enabled and mplus_auto_fetch)
    
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
                                lambda cfg, token, reports, difficulty: fetch_realm_rank_leaders(
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

    embed = build_embed(cfg, stats, standing, leaders, zone_name,
                        mplus_results, mplus_season_scores, mplus_season_parses, start_dt, end_dt, no_logs)
    post_to_discord(webhook_url, embed)
    print("Board posted to Discord.")


if __name__ == "__main__":
    main()

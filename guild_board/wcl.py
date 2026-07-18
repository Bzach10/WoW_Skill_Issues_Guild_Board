import logging
import time
from collections import defaultdict

import requests

from guild_board.config import clean_spec_name, slugify_server
from guild_board.dedup import FightDeduper, report_sort_key

logger = logging.getLogger(__name__)

WCL_TOKEN_URL = "https://www.warcraftlogs.com/oauth/token"
WCL_API_URL = "https://www.warcraftlogs.com/api/v2/client"

DIFFICULTY_MAP = {"lfr": 1, "normal": 3, "heroic": 4, "mythic": 5}

REPORTS_QUERY = """
query ($name: String!, $slug: String!, $region: String!, $start: Float!, $end: Float!, $limit: Int!) {
  reportData {
    reports(
      guildName: $name
      guildServerSlug: $slug
      guildServerRegion: $region
      startTime: $start
      endTime: $end
      limit: $limit
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


def fetch_guild_reports(token, cfg, start_ms, end_ms, limit=25):
    guild = cfg["guild"]
    data = gql(token, REPORTS_QUERY, {
        "name": guild["name"],
        "slug": guild["realm_slug"],
        "region": guild["region"],
        "start": float(start_ms),
        "end": float(end_ms),
        "limit": int(limit),
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
    """Walk a WCL rankings blob and keep each player's best parse."""
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
                    "report_code": None,
                    "fight_id": None,
                }


def collect_participants(rankings_blob, participants):
    """Record everyone seen in this week's kills, with their realm slug when WCL provides it."""
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
    for entry in entries:
        name = entry.get("name")
        if name:
            death_totals[name] += 1


def try_difficulties(func, cfg, token, reports, *args):
    """Try a function with each difficulty (mythic -> heroic -> normal) until one succeeds."""
    difficulties = ["mythic", "heroic", "normal"]
    for diff in difficulties:
        try:
            logger.info("Trying difficulty %s", diff)
            difficulty_num = DIFFICULTY_MAP.get(diff, 4)
            result = func(token, cfg, reports, difficulty_num, *args)
            if result:
                logger.info("Found data for %s", diff)
                return result, diff
            else:
                logger.info("No data for %s", diff)
        except Exception as exc:
            logger.warning("Error with difficulty %s: %s", diff, exc)
            continue
    logger.info("No data found for any difficulty")
    return None, None


def collect_raid_stats(token, cfg, reports, difficulty=None):
    """Collect raid stats for a specific difficulty."""
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
    report_codes = {}

    deduper = FightDeduper()
    ordered_reports = sorted(reports, key=lambda r: report_sort_key(r, preferred_uploader))

    for report in ordered_reports:
        code = report["code"]
        report_start = report.get("startTime") or 0
        data = gql(token, REPORT_DETAIL_QUERY, {"code": code, "difficulty": difficulty})
        rep = ((data.get("reportData") or {}).get("report")) or {}

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
        if code not in report_codes:
            report_codes[code] = report
        time.sleep(0.5)

    if duplicates_skipped:
        logger.info("Deduplication: skipped %s duplicate pull(s)", duplicates_skipped)

    # Enrich parse entries with report links where we can
    _enrich_parse_links(best_dps, report_codes)
    _enrich_parse_links(best_hps, report_codes)

    if not best_dps and not best_hps and pulls == 0:
        return None

    for info in best_dps.values():
        info["difficulty"] = difficulty
    for info in best_hps.values():
        info["difficulty"] = difficulty

    return {
        "best_dps": best_dps,
        "best_hps": best_hps,
        "participants": participants,
        "deaths": dict(death_totals),
        "pulls": pulls,
        "kills": kills,
        "difficulty": difficulty,
    }


def collect_parses_only(token, cfg, reports, difficulty):
    """Fetch just DPS/HPS parse rankings at a difficulty (no deaths/pulls)."""
    best_dps, best_hps = {}, {}
    for report in reports:
        data = gql(token, REPORT_DETAIL_QUERY, {"code": report["code"], "difficulty": difficulty})
        rep = ((data.get("reportData") or {}).get("report")) or {}
        extract_parses(rep.get("dps"), "dps", best_dps)
        extract_parses(rep.get("hps"), "healers", best_hps)
        time.sleep(0.3)
    for info in best_dps.values():
        info["difficulty"] = difficulty
    for info in best_hps.values():
        info["difficulty"] = difficulty
    return best_dps, best_hps


def fill_missing_parses(token, cfg, reports, stats, collector=None):
    """If DPS or HPS has no parses at the difficulty the week used, look one
    difficulty down (mythic -> heroic -> normal) for that metric only.

    Entries carry a per-row "difficulty" tag so the board can label them
    (e.g. "Heroic Rotmire" in an otherwise-mythic week)."""
    if not stats:
        return stats
    order = [5, 4, 3, 1]
    used = stats.get("difficulty")
    if used not in order:
        return stats
    lower = order[order.index(used) + 1:]
    collector = collector or collect_parses_only

    for metric, side in (("best_dps", 0), ("best_hps", 1)):
        if stats.get(metric):
            continue
        for diff in lower:
            try:
                found = collector(token, cfg, reports, diff)[side]
            except (RuntimeError, requests.RequestException) as exc:
                logger.warning("Parse fallback at difficulty %s failed: %s", diff, exc)
                continue
            if found:
                logger.info("No %s parses at difficulty %s; using difficulty %s instead.",
                            metric, used, diff)
                stats[metric] = found
                break
    return stats


def _enrich_parse_links(best_parses, report_codes):
    """Best-effort: attach the first known report code to each parse entry."""
    for name, info in best_parses.items():
        if report_codes:
            info["report_code"] = next(iter(report_codes))


# ---------------------------------------------------------------------------
# Most Improved — season-long parse history
# ---------------------------------------------------------------------------

IMPROVEMENT_MAX_DAYS = 180


def collect_improvement_history(token, cfg, zone_id, difficulty, end_ms, max_reports=30):
    """Collect each raider's best parse per report across the season.

    The "season" is every guild report in the current raid zone (up to
    IMPROVEMENT_MAX_DAYS back), so the award resets automatically when a
    new tier starts. Returns {"dps": {name: [sample]}, "hps": ...} where a
    sample is {ts, parse, amount, spec, cls}.
    """
    start_ms = end_ms - IMPROVEMENT_MAX_DAYS * 86_400_000
    try:
        reports = fetch_guild_reports(token, cfg, start_ms, end_ms, limit=100)
    except (RuntimeError, requests.RequestException) as exc:
        logger.warning("Season report sweep at limit=100 failed (%s); retrying with 25.", exc)
        reports = fetch_guild_reports(token, cfg, start_ms, end_ms)

    season = [r for r in reports if not zone_id or (r.get("zone") or {}).get("id") == zone_id]
    season.sort(key=lambda r: r.get("startTime") or 0)
    if len(season) > max_reports:
        # Improvement compares early vs late form, so the middle matters least.
        half = max_reports // 2
        season = season[:half] + season[-half:]

    logger.info("Most Improved: scanning %s season report(s)", len(season))
    history = {"dps": defaultdict(list), "hps": defaultdict(list)}
    for report in season:
        code = report["code"]
        ts = report.get("startTime") or 0
        try:
            data = gql(token, REPORT_DETAIL_QUERY, {"code": code, "difficulty": difficulty})
        except (RuntimeError, requests.RequestException) as exc:
            logger.warning("Skipping report %s in improvement scan: %s", code, exc)
            continue
        rep = ((data.get("reportData") or {}).get("report")) or {}
        _extract_history(rep.get("dps"), "dps", ts, history["dps"])
        _extract_history(rep.get("hps"), "healers", ts, history["hps"])
        time.sleep(0.4)
    return history


def _extract_history(rankings_blob, role_key, ts, out):
    """Record each player's best parse in this report into their timeline."""
    if not rankings_blob:
        return
    best_this_report = {}
    for fight in (rankings_blob.get("data") or []):
        characters = (((fight.get("roles") or {}).get(role_key) or {}).get("characters")) or []
        for ch in characters:
            name = ch.get("name")
            parse = ch.get("rankPercent")
            if not name or parse is None:
                continue
            prev = best_this_report.get(name)
            if prev is None or parse > prev["parse"]:
                best_this_report[name] = {
                    "parse": parse,
                    "amount": ch.get("amount") or 0,
                    "spec": ch.get("spec") or "",
                    "cls": ch.get("class") or "",
                }
    for name, entry in best_this_report.items():
        out[name].append({"ts": ts, **entry})


def compute_improvement(player_history, min_span_days=14):
    """Rank players by parse-percentile gain: best early-season parse vs
    best recent parse. Players need data spanning min_span_days, and only
    positive gains count — this is an award, not a shame list."""
    results = []
    for name, samples in player_history.items():
        if len(samples) < 2:
            continue
        samples = sorted(samples, key=lambda s: s["ts"])
        span = samples[-1]["ts"] - samples[0]["ts"]
        if span < min_span_days * 86_400_000:
            continue
        early_cut = samples[0]["ts"] + span * 0.25
        late_cut = samples[-1]["ts"] - span * 0.25
        early = [s for s in samples if s["ts"] <= early_cut] or [samples[0]]
        late = [s for s in samples if s["ts"] >= late_cut] or [samples[-1]]
        baseline = max(early, key=lambda s: s["parse"])
        current = max(late, key=lambda s: s["parse"])
        delta = current["parse"] - baseline["parse"]
        if delta <= 0:
            continue
        results.append({
            "name": name,
            "spec": current.get("spec") or "",
            "cls": current.get("cls") or "",
            "early_parse": baseline["parse"],
            "late_parse": current["parse"],
            "early_amount": baseline["amount"],
            "late_amount": current["amount"],
            "delta": delta,
        })
    results.sort(key=lambda r: r["delta"], reverse=True)
    return results


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
            logger.warning("Skipping %s: %s", name, exc)
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

        # Identify the boss this rank belongs to.
        boss = ""
        encounter = best.get("encounter") or {}
        if isinstance(encounter, dict):
            boss = encounter.get("name") or ""
        elif isinstance(encounter, str):
            boss = encounter
        if not boss:
            boss = best.get("name") or ""

        leaders.append({
            "name": name,
            "spec": best.get("spec") or "",
            "realm_rank": realm_rank,
            "region_rank": best.get("regionRank"),
            "best_avg": blob.get("bestPerformanceAverage"),
            "boss": boss,
        })
        time.sleep(0.3)

    leaders.sort(key=lambda entry: entry["realm_rank"])
    return leaders


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
    """Pull the guild roster from Warcraft Logs as a set of lowercase names."""
    return {name for name, _ in fetch_guild_member_roster(token, cfg)}


def wcl_character_url(name, realm, region):
    """Build a Warcraft Logs character URL."""
    return f"https://www.warcraftlogs.com/character/{region}/{realm}/{name}"


def wcl_report_url(code):
    """Build a Warcraft Logs report URL."""
    return f"https://www.warcraftlogs.com/reports/{code}"


def wcl_guild_url(name, realm, region):
    """Build a Warcraft Logs guild progress URL."""
    return f"https://www.warcraftlogs.com/guild/{region}/{realm}/{name}"

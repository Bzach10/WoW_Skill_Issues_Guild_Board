import logging
from datetime import datetime, timezone

import requests

from guild_board.config import clean_spec_name, split_name_realm
from guild_board.http import RateLimiter, get_session
from guild_board.wcl import gql

logger = logging.getLogger(__name__)

RAIDERIO_URL = "https://raider.io/api/v1/characters/profile"

# One limiter shared by every collector in this module, so three roster
# passes in the same run cannot stack up to 3x the intended request rate.
_rio_limiter = RateLimiter()


def _rio_request(url, params, timeout=30, headers=None):
    """GET any Raider.io endpoint through the pooled session, paced by the ONE
    shared limiter — so a collector on a second endpoint cannot stack up past
    the intended aggregate rate.

    `headers` is only forwarded when a caller actually sets one, so the profile
    path's call signature is byte-for-byte what it always was (several tests
    stand in a fake `get` that accepts exactly the old keywords)."""
    _rio_limiter.acquire()
    extra = {"headers": headers} if headers else {}
    return get_session().get(url, params=params, timeout=timeout, **extra)


def _rio_get(params, timeout=30):
    """GET the Raider.io profile endpoint through the pooled session, paced
    by the shared limiter. Replaces per-call requests.get + sleep(0.3)."""
    return _rio_request(RAIDERIO_URL, params, timeout=timeout)


DUNGEON_NAME_FIXES = {
    "Ara-Kara, City of Echoes": "Ara-Kara, City of Echoes",
    "City of Threads": "City of Threads",
    "The Dawnbreaker": "The Dawnbreaker",
    "The Stonevault": "The Stonevault",
    "Mists of Tirna Scithe": "Mists of Tirna Scithe",
    "The Necrotic Wake": "The Necrotic Wake",
    "Siege of Boralus": "Siege of Boralus",
    "Grim Batol": "Grim Batol",
    "Waycrest Manor": "Waycrest Manor",
    "Mechagon Workshop": "Operation: Mechagon - Workshop",
}


def collect_mplus(cfg, token=None):
    """Return list of (key_level, dungeon, name, spec, timed) for the roster's best weekly runs."""
    logger.info("Collecting weekly M+ data...")
    results = []
    region = cfg["guild"]["region"]

    sections = cfg.get("sections", {})
    section_name = "mplus_last_week" if "mplus_last_week" in sections else "mplus"
    from guild_board.config import resolve_roster

    roster, _ = resolve_roster(cfg, token, section_name)

    logger.info("Processing %s characters", len(roster))
    for entry in roster:
        name, realm = _split_name_realm(entry, cfg)
        try:
            resp = _rio_get(params={
                "region": region,
                "realm": realm.strip(),
                "name": name.strip(),
                "fields": "mythic_plus_weekly_highest_level_runs",
            }, timeout=30)
            if resp.status_code != 200:
                logger.warning("Failed to fetch %s: HTTP %s", name, resp.status_code)
                continue
            data = resp.json()
            runs = data.get("mythic_plus_weekly_highest_level_runs") or []
            # Only timed keys count — a depleted +20 doesn't beat a timed +16
            timed_runs = [r for r in runs if (r.get("num_keystone_upgrades", 0) or 0) > 0]
            if timed_runs:
                best = max(timed_runs, key=lambda r: r.get("mythic_level", 0))
                spec = clean_spec_name(best.get("spec"), data.get("class", ""))
                results.append((
                    best.get("mythic_level", 0),
                    _normalize_dungeon_name(best.get("dungeon", "?")),
                    name.strip(),
                    spec,
                    True,
                ))
        except requests.RequestException as exc:
            logger.warning("Error fetching %s: %s", name, exc)
            continue
    results.sort(key=lambda r: r[0], reverse=True)
    logger.info("Found %s players with weekly runs", len(results))
    return results


def collect_mplus_season_scores(cfg, token=None):
    """Return list of (score, name, spec) for season-long M+ overall score from Raider.io."""
    logger.info("Collecting season-long M+ scores...")
    results = []
    region = cfg["guild"]["region"]

    from guild_board.config import resolve_roster

    roster, _ = resolve_roster(cfg, token, "mplus_season_scores")

    logger.info("Processing %s characters", len(roster))
    for entry in roster:
        name, realm = _split_name_realm(entry, cfg)
        try:
            resp = _rio_get(params={
                "region": region,
                "realm": realm.strip(),
                "name": name.strip(),
                "fields": "mythic_plus_scores_by_season:current,mythic_plus_best_runs",
            }, timeout=30)
            if resp.status_code != 200:
                logger.warning("Failed to fetch %s: HTTP %s", name, resp.status_code)
                continue
            data = resp.json()
            score = 0

            # Raider.IO returns the current-season score under mythic_plus_scores_by_season
            scores_by_season = data.get("mythic_plus_scores_by_season") or []
            if isinstance(scores_by_season, list):
                current_entry = next(
                    (s for s in scores_by_season if s.get("season") == "current" or s.get("season", "").endswith("current")),
                    None,
                )
                if not current_entry and scores_by_season:
                    current_entry = max(scores_by_season, key=lambda s: (s.get("scores") or {}).get("all", 0) or 0)
                if current_entry:
                    scores = current_entry.get("scores") or {}
                    score = scores.get("all") or scores.get("score") or 0

            if score > 0:
                spec = clean_spec_name(data.get("active_spec_name"), data.get("class", ""))
                results.append((score, name.strip(), spec))
                logger.info("Added %s with score %s", name, score)
        except requests.RequestException as exc:
            logger.warning("Error fetching %s: %s", name, exc)
            continue
        except Exception as exc:
            logger.warning("Unexpected error for %s: %s", name, exc)
            continue
    results.sort(key=lambda r: r[0], reverse=True)
    logger.info("Found %s players with season scores", len(results))
    return results


def collect_mplus_season_parses(cfg, token=None):
    """Return (list of (parse/score, dungeon, name, spec, is_wcl), top_timed_key)."""
    logger.info("Collecting season-long M+ runs...")
    sections = cfg.get("sections", {})
    mplus_cfg = sections.get("mplus_season_parses") or sections.get("mplus_season_runs", {})
    use_wcl = mplus_cfg.get("use_wcl_parses", True)

    from guild_board.config import resolve_roster

    section_key = "mplus_season_parses" if "mplus_season_parses" in sections else "mplus_season_runs"
    roster, _ = resolve_roster(cfg, token, section_key)

    results, top_key = collect_mplus_raiderio_season_runs(cfg, roster)

    if use_wcl and token and results:
        logger.info("Attempting WCL parse enrichment on top Raider.io entries...")
        try:
            wcl_results = collect_mplus_wcl_parses(cfg, token, results)
            if wcl_results:
                by_name = {r[2].lower(): r for r in results}
                for wcl in wcl_results:
                    by_name[wcl[2].lower()] = wcl
                results = list(by_name.values())
                logger.info("Enriched %s entries with WCL parse data", len(wcl_results))
        except (RuntimeError, requests.RequestException) as exc:
            logger.warning("WCL parse enrichment failed: %s", exc)

    results.sort(key=lambda r: r[0], reverse=True)
    logger.info("Found %s players with season runs", len(results))
    return results, top_key


def _best_timed_run(runs):
    """Highest timed run in a Raider.io best-runs list, or None."""
    timed = [r for r in runs if (r.get("num_keystone_upgrades", 0) or 0) > 0]
    if not timed:
        return None
    return max(timed, key=lambda r: (r.get("mythic_level", 0), r.get("score", 0)))


def collect_mplus_raiderio_season_runs(cfg, roster):
    """Return (list of (score, dungeon, name, spec, is_wcl), top_timed_key).

    top_timed_key is the season's highest timed key across the roster —
    the Guild Records candidate."""
    logger.info("Processing %s characters for Raider.io season runs", len(roster))
    results = []
    top_key = None
    region = cfg["guild"]["region"]

    for entry in roster:
        name, realm = _split_name_realm(entry, cfg)
        try:
            resp = _rio_get(params={
                "region": region,
                "realm": realm.strip(),
                "name": name.strip(),
                "fields": "mythic_plus_best_runs",
            }, timeout=30)
            if resp.status_code != 200:
                logger.warning("Failed to fetch %s: HTTP %s", name, resp.status_code)
                continue
            data = resp.json()
            runs = data.get("mythic_plus_best_runs") or []
            if runs:
                best = max(runs, key=lambda r: r.get("score", 0))
                spec = clean_spec_name(best.get("spec"), data.get("class", ""))
                results.append((
                    best.get("score", 0),
                    _normalize_dungeon_name(best.get("dungeon", "?")),
                    name.strip(),
                    spec,
                    False,
                ))
                best_timed = _best_timed_run(runs)
                if best_timed:
                    level = best_timed.get("mythic_level", 0)
                    score = best_timed.get("score", 0)
                    if top_key is None or (level, score) > (top_key["level"], top_key.get("score", 0)):
                        top_key = {
                            "name": name.strip(),
                            "level": level,
                            "score": score,
                            "dungeon": _normalize_dungeon_name(best_timed.get("dungeon", "?")),
                            "spec": clean_spec_name(best_timed.get("spec"), data.get("class", "")),
                        }
        except requests.RequestException as exc:
            logger.warning("Error fetching %s: %s", name, exc)
            continue
    return results, top_key


WCL_MPLUS_QUERY = """
query ($name: String!, $slug: String!, $region: String!) {
  characterData {
    character(name: $name, serverSlug: $slug, serverRegion: $region) {
      mythicPlusSeasons {
        season {
          id
        }
        segments {
          dungeon {
            id
            name
          }
          scores
          best_runs: runs(limit: 1) {
            items {
              map {
                id
              }
              completionTime
              mythicLevel
              parse {
                percent
              }
            }
          }
        }
      }
    }
  }
}
"""


def collect_mplus_wcl_parses(cfg, token, raiderio_results):
    """WCL M+ parse enrichment — NOT IMPLEMENTED. Returns [] deliberately.

    This function's name and its previous body disagreed. Despite claiming
    to fetch parse percentiles from Warcraft Logs it never contacted WCL:
    it re-queried Raider.io (ignoring `token` entirely), took Raider.io's
    dungeon *score*, and returned it tagged is_wcl=True. formatters.py
    renders anything tagged that way with a percent sign, so the board
    published lines like:

        Rakdisc (Discipline Priest) - 456% on Skyreach

    A parse percentile is 0-100 by definition; those were unbounded
    Raider.io scores. It also looked every character up on the guild's own
    realm slug regardless of their actual realm, so cross-realm members
    either missed or matched a same-named stranger.

    Returning [] leaves the caller's Raider.io results untouched, and those
    already render correctly as "<n> score". That is strictly better than
    publishing a fabricated percentage, and it saves 15 redundant requests
    per run.

    To implement this for real: WCL_MPLUS_QUERY above is the (currently
    unused) GraphQL query for it. It needs a per-character serverSlug from
    split_name_realm(), and its parse.percent values then genuinely are
    percentiles and can carry is_wcl=True.
    """
    logger.info(
        "WCL M+ parse enrichment is not implemented; keeping Raider.io "
        "scores as-is. See collect_mplus_wcl_parses.__doc__.")
    return []


def _mplus_dungeon_name(cfg, token, encounter_id):
    """Best-effort dungeon name lookup from WCL encounter ID."""
    if not hasattr(_mplus_dungeon_name, "cache"):
        _mplus_dungeon_name.cache = {
            13982: "Grim Batol",
            13954: "Ara-Kara, City of Echoes",
            13968: "City of Threads",
            14185: "The Dawnbreaker",
            13720: "The Stonevault",
            13708: "Mists of Tirna Scithe",
            13789: "The Necrotic Wake",
            14063: "Siege of Boralus",
            13851: "Waycrest Manor",
            13796: "Operation: Mechagon - Workshop",
        }
    if encounter_id in _mplus_dungeon_name.cache:
        return _mplus_dungeon_name.cache[encounter_id]

    DUNGEON_LOOKUP_QUERY = """
    query ($id: Int!) {
      gameData {
        dungeon(id: $id) {
          name
        }
      }
    }
    """
    try:
        data = gql(token, DUNGEON_LOOKUP_QUERY, {"id": int(encounter_id)})
        name = (((data.get("gameData") or {}).get("dungeon") or {}).get("name")) or "Unknown"
        _mplus_dungeon_name.cache[encounter_id] = name
        return name
    except Exception:
        return "Unknown"


def _split_name_realm(entry, cfg):
    """Thin wrapper over config.split_name_realm that supplies this guild's
    realm as the fallback. Kept so the existing call sites in this module
    read unchanged; the splitting rule itself lives in one place now."""
    return split_name_realm(entry, default_realm=cfg["guild"]["realm_slug"])


def _normalize_dungeon_name(name):
    """Normalize a dungeon name to match official journal names."""
    if not name:
        return "?"
    name = name.strip()
    if name in DUNGEON_NAME_FIXES:
        return DUNGEON_NAME_FIXES[name]
    return name


def raiderio_profile_url(name, realm, region):
    """Build a Raider.io character profile URL."""
    return f"https://raider.io/characters/{region}/{realm}/{name}"


def raiderio_run_url(name, realm, region, dungeon):
    """Best-effort URL for a character's best run for a dungeon."""
    return f"https://raider.io/characters/{region}/{realm}/{name}#mythic-plus"


# ---------------------------------------------------------------------------
# PER-BOSS RAID KILLS — WHICH bosses are down, at which difficulty, and when.
#
# WHY THIS EXISTS. guilds/profile?fields=raid_progression reports progression as
# a COUNT per difficulty and nothing else: "5/9 M" says five bosses are down on
# Mythic, never WHICH five. Everything downstream that wanted names had to walk
# the pull order and credit the first five — a guess wearing a fact's clothes,
# and wrong the moment a guild kills out of order (this one did: Chimaerus at
# order 7 died before Lightblinded Vanguard at order 5). guilds/boss-kill
# answers the real question one boss and one difficulty at a time, dated:
#
#   GET /api/v1/guilds/boss-kill?region&realm&guild&raid&boss&difficulty
#       -> {"kill": {"defeatedAt": "...", ...}, "roster": [...]}   killed
#       -> {}                                                      not killed
#
# Public and unauthenticated like the rest of Raider.io, so it works locally and
# rides the same shared limiter: 9 bosses x 3 difficulties = 27 requests, ~9s.
#
# TWO KINDS OF "NO KILL", NEVER CONFLATED. HTTP 200 with an empty body is DATA
# ("this guild has not killed that boss at that difficulty"). A timeout, a 5xx,
# a rejected question or an unparseable body is IGNORANCE. Ignorance about even
# one pair makes the WHOLE payload non-authoritative (available=false): a
# partial sweep read as complete would publish "not killed" for a boss we merely
# failed to ask about — the exact confident-wrong-answer this endpoint exists to
# end. Consumers must treat available=false as "no named data", not as zeros.
# ---------------------------------------------------------------------------

RAIDERIO_BOSS_KILL_URL = "https://raider.io/api/v1/guilds/boss-kill"

# Raider.io wants a real User-Agent on the guild endpoints; requests' default
# names the library, not the caller. Identifying the project is what the API
# asks for and makes our traffic legible if we ever need support.
BOSS_KILL_USER_AGENT = ("skill-issues-guild-board "
                        "(+https://github.com/Bzach10/WoW_Skill_Issues_Guild_Board)")

# Ascending, the same order guild progression is reported in. Normal is swept
# too: it costs 9 requests and an early-season tier is normal-only.
KILL_DIFFICULTIES = ("normal", "heroic", "mythic")

# One retry before a pair is declared unknown. A transient 5xx should not cost
# the whole day's named data; a persistent one should not be papered over.
KILL_FETCH_ATTEMPTS = 2

RAID_KILLS_SCHEMA_VERSION = 1


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def fetch_boss_kill(guild, raid_slug, boss_slug, difficulty):
    """(defeated_at, known) for ONE boss at ONE difficulty.

        (None, True)   asked and answered: NOT killed at this difficulty
        (iso,  True)   asked and answered: killed, on this date
        (None, False)  we could not ask. NOT the same as "not killed" — the
                       caller must degrade the whole payload rather than
                       publish this silence as a negative.

    guild is {"name", "realm", "region"}. Never raises.
    """
    params = {"region": guild.get("region"), "realm": guild.get("realm"),
              "guild": guild.get("name"), "raid": raid_slug,
              "boss": boss_slug, "difficulty": difficulty}
    for attempt in range(1, KILL_FETCH_ATTEMPTS + 1):
        try:
            resp = _rio_request(RAIDERIO_BOSS_KILL_URL, params,
                                headers={"User-Agent": BOSS_KILL_USER_AGENT})
        except requests.RequestException as exc:
            logger.warning("boss-kill %s/%s: %s (attempt %s)",
                           boss_slug, difficulty, exc, attempt)
            continue
        if resp.status_code == 200:
            try:
                body = resp.json() or {}
            except ValueError:
                logger.warning("boss-kill %s/%s: unparseable body (attempt %s)",
                               boss_slug, difficulty, attempt)
                continue
            return ((body.get("kill") or {}).get("defeatedAt") or None), True
        if 400 <= resp.status_code < 500:
            # The API rejecting the question (bad slug, unknown guild) is not
            # transient; retrying only spends the rate limit. Still unknown.
            logger.warning("boss-kill %s/%s: HTTP %s — question rejected",
                           boss_slug, difficulty, resp.status_code)
            break
        logger.warning("boss-kill %s/%s: HTTP %s (attempt %s)",
                       boss_slug, difficulty, resp.status_code, attempt)
    return None, False


def collect_raid_boss_kills(cfg, season=None, difficulties=KILL_DIFFICULTIES):
    """The raid_kills.json payload: every boss of the season's raid, at every
    difficulty, with the date it died.

    Shape (schema_version 1):
        available   True only when EVERY boss x difficulty pair was answered.
        status      "ok" | "partial_fetch" | "unavailable"
        fetched_at  when this sweep ran (UTC ISO8601)
        bosses[]    {slug, name, order, kills: {difficulty: {defeated_at}}}
                    — a difficulty absent from `kills` means NOT killed, and
                    only means that when available is True.
        killed_by_difficulty  named-kill counts, for a consumer to reconcile
                    against raid_progression's aggregate. They must agree; a
                    consumer that finds them disagreeing should refuse rather
                    than pick a winner.

    Never raises on a network fault — every failure lands in `unresolved` and
    flips `available`. A malformed season definition is a code bug and is left
    to raise; the caller (build_site_data) wraps the whole call so a refresh
    still completes.
    """
    from guild_board import season as season_mod

    season = season or season_mod.CURRENT_SEASON
    g = (cfg or {}).get("guild") or {}
    guild = {"name": g.get("name"), "realm": g.get("realm_slug"),
             "region": g.get("region", "us")}
    raid = season["raid"]
    difficulties = tuple(difficulties)

    bosses = []
    unresolved = []
    for boss in raid["bosses"]:
        kills = {}
        for difficulty in difficulties:
            defeated_at, known = fetch_boss_kill(
                guild, raid["slug"], boss["slug"], difficulty)
            if not known:
                unresolved.append(f"{boss['slug']}/{difficulty}")
                continue
            if defeated_at:
                kills[difficulty] = {"defeated_at": defeated_at}
        bosses.append({"slug": boss["slug"], "name": boss["name"],
                       "order": boss["order"], "kills": kills})

    asked = len(bosses) * len(difficulties)
    if not unresolved:
        status = "ok"
    elif len(unresolved) >= asked:
        status = "unavailable"
    else:
        status = "partial_fetch"

    payload = {
        "schema_version": RAID_KILLS_SCHEMA_VERSION,
        "fetched_at": _now_iso(),
        "available": not unresolved,
        "status": status,
        "source": RAIDERIO_BOSS_KILL_URL,
        "guild": guild,
        "raid": {"slug": raid["slug"],
                 "display_name": raid.get("display_name"),
                 "total_bosses": len(raid["bosses"])},
        "difficulties": list(difficulties),
        "killed_by_difficulty": {d: sum(1 for b in bosses if d in b["kills"])
                                 for d in difficulties},
        "bosses": bosses,
    }
    if unresolved:
        payload["unresolved"] = unresolved
    return payload

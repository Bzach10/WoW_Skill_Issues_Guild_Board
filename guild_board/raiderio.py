import logging
import time

import requests

from guild_board.config import clean_spec_name, split_name_realm
from guild_board.wcl import gql

logger = logging.getLogger(__name__)

RAIDERIO_URL = "https://raider.io/api/v1/characters/profile"

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
            resp = requests.get(RAIDERIO_URL, params={
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
        time.sleep(0.3)
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
            resp = requests.get(RAIDERIO_URL, params={
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
        time.sleep(0.3)
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
            resp = requests.get(RAIDERIO_URL, params={
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
        time.sleep(0.3)
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
    """Attempt to fetch M+ parse percentiles from Warcraft Logs for top Raider.io entries."""
    logger.info("Attempting WCL parse enrichment for top Raider.io entries")
    results = []
    region = cfg["guild"]["region"]
    default_slug = cfg["guild"]["realm_slug"]

    for score, dungeon, name, spec, _ in raiderio_results[:15]:
        try:
            resp = requests.get(RAIDERIO_URL, params={
                "region": region,
                "realm": default_slug,
                "name": name,
                "fields": "mythic_plus_best_runs",
            }, timeout=30)
            if resp.status_code != 200:
                continue
            rio = resp.json()
            runs = rio.get("mythic_plus_best_runs") or []
            for run in runs:
                if _normalize_dungeon_name(run.get("dungeon", "")) == _normalize_dungeon_name(dungeon):
                    from_wcl = run.get("score", 0)
                    if from_wcl:
                        results.append((from_wcl, dungeon, name, spec, True))
                        break
        except requests.RequestException:
            continue
    return results


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

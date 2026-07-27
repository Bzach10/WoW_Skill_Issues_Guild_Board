"""The competition data layer — the heart of the site (the WANTED BOARD).

This is what the guild started as: a top-5 M+ board. It is expanded here
into the full, BROWSABLE dataset — every character's real numbers, not just
a summary — plus the guild-internal rankings and week-over-week movement
that make it a living competition.

Two halves, deliberately separated so the build is unit-testable offline:

  fetch_competition(cfg)      LIVE. One Raider.io call per roster member
                              (public API, no credentials), via the pooled +
                              rate-limited session. Returns raw per-character
                              M+ detail. Slow (~one roster sweep); this is the
                              daily-refresh input.
  build_competition(fetched,  PURE. Assembles the browsable envelope:
    board_state, season)      per-character detail, overall/by-role/by-class
                              rankings with the top 5 flagged, and movement
                              (climbers / new to the board / biggest gain).

Parses: full parse data (per-boss %, averages, WCL ranks) needs Warcraft
Logs credentials, which are not always present. Raider.io does not expose
parse percentiles. So the parse block is populated from board_state's real
records where we have them and marked partial otherwise — it never invents
a percentile.
"""

import logging

from guild_board import season as season_mod
from guild_board.config import clean_spec_name, load_roster_cache, split_name_realm

logger = logging.getLogger(__name__)

RAIDERIO_FIELDS = ("class,active_spec_name,active_spec_role,"
                   "mythic_plus_scores_by_season:current,"
                   "mythic_plus_best_runs,mythic_plus_ranks")

# Raider.io reports roles as TANK / HEALING / DPS — note "HEALING", not
# "HEALER". Canonicalise so the by-role rankings actually bucket healers.
ROLES = ("Tank", "Healer", "DPS")
_ROLE_MAP = {"tank": "Tank", "healing": "Healer", "healer": "Healer",
             "dps": "DPS", "melee": "DPS", "ranged": "DPS"}


def canonical_role(role):
    return _ROLE_MAP.get((role or "").strip().lower(), "")


# ---------------------------------------------------------------------------
# Live fetch
# ---------------------------------------------------------------------------

def _normalize_character(entry_key, data, region="us"):
    """One Raider.io profile response -> the normalized per-character record
    the builder consumes. Returns None if the character didn't resolve."""
    if not data:
        return None
    name = data.get("name") or entry_key.split("-")[0]
    realm = data.get("realm") or ""
    scores_season = (data.get("mythic_plus_scores_by_season") or [{}])[0]
    scores = scores_season.get("scores") or {}
    ranks = data.get("mythic_plus_ranks") or {}

    best_runs = []
    for run in data.get("mythic_plus_best_runs") or []:
        upgrades = run.get("num_keystone_upgrades", 0) or 0
        best_runs.append({
            "dungeon": run.get("dungeon"),
            "short": run.get("short_name"),
            "level": run.get("mythic_level", 0),
            "timed": upgrades > 0,
            "upgrades": upgrades,
            "score": round(run.get("score", 0) or 0, 1),
            "clear_ms": run.get("clear_time_ms"),
            "par_ms": run.get("par_time_ms"),
        })
    best_runs.sort(key=lambda r: r["score"], reverse=True)

    # The roster slug is the authoritative per-character realm (e.g.
    # "proudmoore"), which is what cross-realm links MUST use. Raider.io's
    # `realm` is the display name ("Proudmoore"); keep both. Prebuilding the
    # links here removes any chance the front-end reintroduces the
    # guild-realm link bug for a cross-realm member like Rakdisc.
    realm_slug = entry_key.split("-", 1)[1].lower() if "-" in entry_key else realm.lower()
    name_slug = name.lower()

    return {
        "name": name,
        "realm": realm,
        "realm_slug": realm_slug,
        # Verbatim, not re-lowercased: casing is folded once at roster
        # ingestion (config.normalize_roster_entry), and this key must stay
        # byte-identical to the ones the WCL parse sweep and web_data key by.
        "key": entry_key,
        "raiderio_url": f"https://raider.io/characters/{(region or 'us')}/{realm_slug}/{name_slug}",
        "warcraftlogs_url": f"https://www.warcraftlogs.com/character/{(region or 'us')}/{realm_slug}/{name_slug}",
        "class": data.get("class") or "",
        "spec": clean_spec_name(data.get("active_spec_name"), data.get("class", "")),
        "role": canonical_role(data.get("active_spec_role")),
        "score": round(scores.get("all", 0) or 0, 1),
        "scores_by_role": {
            "dps": round(scores.get("dps", 0) or 0, 1),
            "healer": round(scores.get("healer", 0) or 0, 1),
            "tank": round(scores.get("tank", 0) or 0, 1),
        },
        "best_runs": best_runs,
        "ranks": {
            "realm_overall": (ranks.get("overall") or {}).get("realm"),
            "realm_class": (ranks.get("class") or {}).get("realm"),
            "region_overall": (ranks.get("overall") or {}).get("region"),
        },
    }


def fetch_competition(cfg, roster=None):
    """Live per-character M+ competition detail for the whole roster.

    Uses the pooled, rate-limited Raider.io session (guild_board.http via the
    raiderio helper), so it respects the same limits as the rest of the
    pipeline. Fail-soft per character: one bad lookup is skipped, never
    aborts the sweep. Returns {"characters": [...], "count": n}.
    """
    from guild_board.raiderio import _rio_get

    region = ((cfg or {}).get("guild") or {}).get("region", "us")
    if roster is None:
        roster, _ = load_roster_cache(cfg)

    characters, missed = [], 0
    for entry in roster:
        name, realm = split_name_realm(entry)
        if not realm:
            continue
        try:
            resp = _rio_get(params={"region": region, "realm": realm,
                                    "name": name, "fields": RAIDERIO_FIELDS})
        except Exception:
            missed += 1
            continue
        if resp.status_code != 200:
            missed += 1
            continue
        record = _normalize_character(entry, resp.json(), region=region)
        if record:
            characters.append(record)
    if missed:
        logger.info("competition fetch: %d of %d roster entries didn't resolve",
                    missed, len(roster))
    return {"characters": characters, "count": len(characters)}


# ---------------------------------------------------------------------------
# Pure build
# ---------------------------------------------------------------------------

def _rank_within(rows):
    """Assign 1-based ranks to a score-sorted list (in place, returns it)."""
    for i, row in enumerate(rows, start=1):
        row["rank"] = i
    return rows


def build_competition(fetched=None, board_state=None, season=None,
                      top_n=5, wcl_parses=None):
    """Assemble the browsable competition envelope from fetched M+ detail.

    fetched: the dict from fetch_competition (or {"characters": [...]}).
    board_state: for week-over-week deltas (baseline.season_scores) and the
                 real parse records. board_state keys names lowercased with
                 no realm, so deltas match on that convention.
    wcl_parses: the envelope from web_data.build_parses (per-character
                current-tier WCL best-performance averages, keyed by the
                full name-realm key). When available it fills each
                character's `parse` field; board_state records remain the
                fallback for anyone the sweep missed.
    """
    season = season or season_mod.CURRENT_SEASON
    fetched = fetched or {}
    board_state = board_state or {}
    chars = list(fetched.get("characters") or [])

    baseline_scores = ((board_state.get("baseline") or {}).get("season_scores")) or {}
    current_scores = board_state.get("season_scores") or {}
    # Day-over-day: yesterday's cache scores, keyed by roster slug, carried
    # forward by refresh_competition. This is what makes the board feel alive
    # between the weekly board_state snapshots.
    prev_day_scores = (fetched.get("prev_day_scores")) or {}

    def _base_name(rec):
        # board_state convention: lowercase first name token.
        return (rec.get("name") or rec.get("key", "").split("-")[0]).lower()

    # Per-character detail + deltas (week-over-week from board_state baseline,
    # day-over-day from yesterday's cache).
    detail = []
    for rec in chars:
        bname = _base_name(rec)
        # Prefer the live score; fall back to board_state if the live fetch
        # had no season entry for them.
        score = rec.get("score") or current_scores.get(bname, 0)
        prior = baseline_scores.get(bname)
        delta_week = round(score - prior, 1) if prior is not None else None
        prior_day = prev_day_scores.get(rec.get("key"))
        delta_day = round(score - prior_day, 1) if prior_day is not None else None
        detail.append({
            **rec,
            "role": canonical_role(rec.get("role")),
            "score": score,
            "delta_week": delta_week,
            "delta_day": delta_day,
            "is_new": prior is None and score > 0,
            "parse": None,  # filled below from board records where available
        })

    # Guild-internal rankings — ONLY scored characters get a competition
    # rank/top5. Members with no score yet are a deliberate "unranked" bucket
    # (below), never rank 1-of-2 or a top-5 poster. All members stay
    # browsable in `characters`.
    scored = [r for r in detail if r["score"]]
    unscored = [r for r in detail if not r["score"]]
    ranked = _rank_within(sorted(scored, key=lambda r: r["score"], reverse=True))
    top5_keys = {r["key"] for r in ranked[:top_n]}
    for r in ranked:
        r["top5"] = r["key"] in top5_keys
    for r in unscored:
        r["rank"] = None
        r["top5"] = False
    # Browsable detail keeps everyone: ranked first, then the unscored.
    characters = ranked + unscored

    def _ladder_row(r):
        return {
            "rank": r["rank"], "name": r["name"], "key": r["key"],
            "score": r["score"], "class": r["class"], "spec": r["spec"],
            "role": r["role"], "top5": r["top5"], "delta_week": r["delta_week"],
            "delta_day": r.get("delta_day"), "is_new": r["is_new"],
        }

    overall = [_ladder_row(r) for r in ranked]

    # by_role / by_class rank FRESH ladder-row copies, never the shared
    # character dicts — otherwise re-ranking a subgroup would clobber each
    # character's canonical overall `rank` (e.g. the #1 healer would show as
    # rank 1 overall). This was a real bug caught on launch data.
    by_role = {}
    for role in ROLES:
        rows = [_ladder_row(r) for r in ranked if canonical_role(r.get("role")) == role]
        by_role[role] = _rank_within(sorted(rows, key=lambda r: r["score"], reverse=True))

    by_class = {}
    for cls in sorted({r["class"] for r in ranked if r["class"]}):
        rows = [_ladder_row(r) for r in ranked if r["class"] == cls]
        by_class[cls] = _rank_within(sorted(rows, key=lambda r: r["score"], reverse=True))

    # Movement — the living-competition signal (scored members only).
    with_delta = [r for r in ranked if r.get("delta_week") is not None]
    climbers = sorted([r for r in with_delta if r["delta_week"] > 0],
                      key=lambda r: r["delta_week"], reverse=True)
    # Day-over-day movers — what changed since yesterday, the "alive today" feed.
    day_movers = sorted([r for r in ranked if (r.get("delta_day") or 0) > 0],
                        key=lambda r: r["delta_day"], reverse=True)
    new_to_board = [r for r in ranked if r["is_new"]]
    biggest = climbers[0] if climbers else None
    biggest_today = day_movers[0] if day_movers else None

    # Guild key levels cleared (parity with the Discord board's M+ keys +
    # the highest-timed-key record) — derived live from everyone's best runs.
    key_records = _build_key_records(chars, season)

    # The 34-of-130 with no score are a DELIBERATE state, not missing data:
    # roster members who haven't posted a season score yet. Surfaced as their
    # own bucket so the UI renders "yet to set sail" rather than a blank row.
    unranked = [{"name": r["name"], "key": r["key"], "class": r["class"],
                 "spec": r["spec"], "role": r["role"]}
                for r in unscored]

    # Parses — real records only; never invented. WCL zoneRankings data
    # (when the credentialed sweep has run) fills per-character averages;
    # board_state's single record holders remain the fallback.
    parses = _build_parse_block(board_state, ranked, wcl_parses)
    parse_by_name = {p["name"].lower(): p for p in parses["leaders"]}
    # Matched on the FULL name-realm key, never bare name — two same-named
    # characters on different realms must each get their own parse.
    wcl_chars = (wcl_parses or {}).get("characters") or {}
    for r in characters:
        w = wcl_chars.get(r["key"])
        if w:
            r["parse"] = {
                # Headline = the difficulty with the best SCALED value; the
                # full per-difficulty split rides along so the site can show
                # mythic and heroic columns from this file alone.
                "best": w.get("best_perf_avg"),
                # The difficulty-discounted value rankings consume (config.yml
                # parses.difficulty_scale); equals `best` when the factor is 1.
                "scaled": w.get("scaled_perf_avg", w.get("best_perf_avg")),
                "by_role": w.get("by_role") or {},
                "difficulty": w.get("difficulty"),
                "by_difficulty": w.get("by_difficulty") or {},
                "source": "wcl_zone_rankings",
            }
            continue
        p = parse_by_name.get((r["name"] or "").lower())
        if p:
            r["parse"] = {"best": p["parse"], "boss": p["boss"], "source": "board_state"}

    return {
        "schema_version": 1,
        "available": len(detail) > 0,
        "season": {"slug": season["slug"], "name": season["name"]},
        # based_on must name the pull that produced THESE scores -- the daily
        # cache's own timestamp. Stamping the weekly board_state time on daily
        # data is how the 2026-07-23 split-brain bundle hid itself: fresh
        # scores wearing a week-old stamp, divergence invisible.
        # week_baseline_from names the weekly snapshot delta_week is measured
        # against, so both cadences stay visible and truthful.
        "based_on": fetched.get("last_updated") or board_state.get("last_updated"),
        "week_baseline_from": board_state.get("last_updated"),
        "character_count": len(detail),
        "ranked_count": len(ranked),
        "unranked_count": len(unranked),
        # Full browsable detail — one entry per character, every number.
        "characters": characters,
        "unranked": unranked,
        # Two-way roster truth (refresh_competition.apply_membership):
        # previous members now absent from the live guild roster, last-known
        # record retained, `departed_at` = first run that observed the
        # absence. Additive; empty until the live-membership pull has run.
        "departed": list(fetched.get("departed") or []),
        "departed_count": len(fetched.get("departed") or []),
        "membership": fetched.get("membership"),
        "key_records": key_records,
        "rankings": {
            "overall": overall,
            "by_role": by_role,
            "by_class": by_class,
            "top5": overall[:top_n],
        },
        "movement": {
            "climbers": [{"name": r["name"], "key": r["key"],
                          "delta_week": r["delta_week"]} for r in climbers],
            "climbers_today": [{"name": r["name"], "key": r["key"],
                                "delta_day": r["delta_day"]} for r in day_movers],
            "new_to_board": [{"name": r["name"], "key": r["key"],
                              "score": r["score"]} for r in new_to_board],
            "biggest_gain": ({"name": biggest["name"], "key": biggest["key"],
                              "delta_week": biggest["delta_week"]}
                             if biggest else None),
            "biggest_gain_today": ({"name": biggest_today["name"],
                                    "key": biggest_today["key"],
                                    "delta_day": biggest_today["delta_day"]}
                                   if biggest_today else None),
        },
        "parses": parses,
    }


def _build_key_records(chars, season):
    """Guild key levels cleared: the highest TIMED key per current-season
    dungeon across the whole roster, plus the single highest overall.

    Parity with the Discord board's weekly M+ keys / highest-timed-key
    record — derived live from every member's best runs, so it needs no
    separate fetch.
    """
    wanted = {d["name"] for d in season["dungeons"]}
    by_dungeon = {}
    overall = None
    for rec in chars:
        for run in rec.get("best_runs") or []:
            dungeon = run.get("dungeon")
            if dungeon not in wanted or not run.get("timed"):
                continue
            level = run.get("level", 0)
            cur = by_dungeon.get(dungeon)
            if cur is None or level > cur["level"]:
                by_dungeon[dungeon] = {"dungeon": dungeon, "level": level,
                                       "name": rec["name"], "key": rec["key"],
                                       "score": run.get("score")}
            if overall is None or level > overall["level"]:
                overall = {"dungeon": dungeon, "level": level,
                           "name": rec["name"], "key": rec["key"]}
    # Order by dungeon name for a stable, complete table (missing = not timed).
    dungeons = []
    for d in season["dungeons"]:
        entry = by_dungeon.get(d["name"])
        dungeons.append(entry or {"dungeon": d["name"], "level": None,
                                  "name": None, "key": None, "score": None})
    return {"highest_overall": overall, "by_dungeon": dungeons,
            "dungeons_timed": len(by_dungeon), "dungeon_total": len(wanted)}


def _build_parse_block(board_state, ranked, wcl_parses=None):
    """Real parse leaders from board_state records, upgraded to "full" when
    the credentialed WCL sweep has populated per-character averages.

    The leaders stay the true single-boss record holders (a 99 on one boss
    is a different fact from a 92 average); the WCL envelope's coverage is
    reported alongside so the front-end knows the per-character `parse`
    fields are populated."""
    records = board_state.get("records") or {}
    leaders = []
    for rec_id in ("best_dps_parse", "best_hps_parse"):
        rec = records.get(rec_id) or {}
        if rec.get("parse"):
            leaders.append({
                "name": rec.get("name"),
                "parse": rec.get("parse"),
                "boss": rec.get("boss"),
                "role": "DPS" if rec_id == "best_dps_parse" else "Healer",
                "spec": f"{rec.get('spec', '')} {rec.get('cls', '')}".strip(),
            })
    wcl_chars = (wcl_parses or {}).get("characters") or {}
    if wcl_chars:
        return {
            "available": "full",
            "source": "Warcraft Logs character zoneRankings (per-character "
                      "averages on characters[].parse; see the parses layer "
                      "for the full detail) + board_state record holders",
            "characters_with_parses": len(wcl_chars),
            "leaders": leaders,
        }
    return {
        "available": "partial" if leaders else "none",
        "source": "board_state records (Warcraft Logs enrichment not yet "
                  "enabled; Raider.io does not expose parses)",
        "leaders": leaders,
    }

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

def _normalize_character(entry_key, data):
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

    return {
        "name": name,
        "realm": realm,
        "key": entry_key.lower(),
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
        record = _normalize_character(entry, resp.json())
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
                      top_n=5):
    """Assemble the browsable competition envelope from fetched M+ detail.

    fetched: the dict from fetch_competition (or {"characters": [...]}).
    board_state: for week-over-week deltas (baseline.season_scores) and the
                 real parse records. board_state keys names lowercased with
                 no realm, so deltas match on that convention.
    """
    season = season or season_mod.CURRENT_SEASON
    fetched = fetched or {}
    board_state = board_state or {}
    chars = list(fetched.get("characters") or [])

    baseline_scores = ((board_state.get("baseline") or {}).get("season_scores")) or {}
    current_scores = board_state.get("season_scores") or {}

    def _base_name(rec):
        # board_state convention: lowercase first name token.
        return (rec.get("name") or rec.get("key", "").split("-")[0]).lower()

    # Per-character detail + deltas.
    detail = []
    for rec in chars:
        bname = _base_name(rec)
        # Prefer the live score; fall back to board_state if the live fetch
        # had no season entry for them.
        score = rec.get("score") or current_scores.get(bname, 0)
        prior = baseline_scores.get(bname)
        delta = round(score - prior, 1) if prior is not None else None
        detail.append({
            **rec,
            "role": canonical_role(rec.get("role")),
            "score": score,
            "delta_week": delta,
            "is_new": prior is None and score > 0,
            "parse": None,  # filled below from board records where available
        })

    # Guild-internal rankings.
    ranked = _rank_within(sorted(detail, key=lambda r: r["score"], reverse=True))
    top5_keys = {r["key"] for r in ranked[:top_n]}
    for r in ranked:
        r["top5"] = r["key"] in top5_keys

    def _ladder_row(r):
        return {
            "rank": r["rank"], "name": r["name"], "key": r["key"],
            "score": r["score"], "class": r["class"], "spec": r["spec"],
            "role": r["role"], "top5": r["top5"], "delta_week": r["delta_week"],
            "is_new": r["is_new"],
        }

    overall = [_ladder_row(r) for r in ranked]

    by_role = {}
    for role in ROLES:
        # canonical_role() defends against a cache written before roles were
        # normalized at fetch time (raw "HEALING" etc.).
        rows = [r for r in ranked if canonical_role(r.get("role")) == role]
        by_role[role] = [_ladder_row(r) for r in _rank_within(
            sorted(rows, key=lambda r: r["score"], reverse=True))]

    by_class = {}
    for cls in sorted({r["class"] for r in ranked if r["class"]}):
        rows = [r for r in ranked if r["class"] == cls]
        by_class[cls] = [_ladder_row(r) for r in _rank_within(
            sorted(rows, key=lambda r: r["score"], reverse=True))]

    # Movement — the living-competition signal.
    with_delta = [r for r in ranked if r.get("delta_week") is not None]
    climbers = sorted([r for r in with_delta if r["delta_week"] > 0],
                      key=lambda r: r["delta_week"], reverse=True)
    new_to_board = [r for r in ranked if r["is_new"]]
    biggest = climbers[0] if climbers else None

    # Parses — real records only; never invented.
    parses = _build_parse_block(board_state, ranked)
    parse_by_name = {p["name"].lower(): p for p in parses["leaders"]}
    for r in ranked:
        p = parse_by_name.get((r["name"] or "").lower())
        if p:
            r["parse"] = {"best": p["parse"], "boss": p["boss"], "source": "board_state"}

    return {
        "schema_version": 1,
        "available": len(detail) > 0,
        "season": {"slug": season["slug"], "name": season["name"]},
        "based_on": board_state.get("last_updated"),
        "character_count": len(detail),
        # Full browsable detail — one entry per character, every number.
        "characters": ranked,
        "rankings": {
            "overall": overall,
            "by_role": by_role,
            "by_class": by_class,
            "top5": overall[:top_n],
        },
        "movement": {
            "climbers": [{"name": r["name"], "key": r["key"],
                          "delta_week": r["delta_week"]} for r in climbers],
            "new_to_board": [{"name": r["name"], "key": r["key"],
                              "score": r["score"]} for r in new_to_board],
            "biggest_gain": ({"name": biggest["name"], "key": biggest["key"],
                              "delta_week": biggest["delta_week"]}
                             if biggest else None),
        },
        "parses": parses,
    }


def _build_parse_block(board_state, ranked):
    """Real parse leaders from board_state records. Marked partial because
    full per-boss/average parse data needs Warcraft Logs credentials, which
    Raider.io cannot supply."""
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
    return {
        "available": "partial" if leaders else "none",
        "source": "board_state records (Warcraft Logs enrichment pending "
                  "WCL_CLIENT_ID/SECRET; Raider.io does not expose parses)",
        "leaders": leaders,
    }

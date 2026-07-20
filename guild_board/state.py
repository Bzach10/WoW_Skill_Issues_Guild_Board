"""Board memory between weeks.

A small committed state file (like the roster cache) remembers what last
week's board showed, enabling week-over-week deltas (rank movement, score
gains, NEW badges) and a fallback when WCL's standing lookup flakes out.
Only real posts update it — previews and dry runs just read.
"""

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

STATE_FILE = "board_state.json"


def load_board_state(path=STATE_FILE):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_board_state(standing, season_scores, streaks=None, records=None, path=STATE_FILE):
    """Persist what this board showed, for next week's comparisons."""
    clean_standing = {
        k: v for k, v in (standing or {}).items()
        if k in ("realm", "region", "world") and v
    }
    state = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "standing": clean_standing,
        "season_scores": {
            name.strip().lower(): score
            for score, name, _ in (season_scores or [])
        },
        "streaks": streaks or {},
        "records": records or {},
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    logger.info("Board state saved for next week's deltas.")
    return path


def advance_streaks(previous_streaks, active_names):
    """Consecutive-week counter: active players tick up, absentees reset.

    Callers decide what "active" means — the board feeds RAID attendance
    (participants + parse pools) so streaks reward showing up to raid.
    Skip the call entirely on a no-logs week to carry streaks forward."""
    previous_streaks = previous_streaks or {}
    return {
        name.strip().lower(): int(previous_streaks.get(name.strip().lower(), 0)) + 1
        for name in active_names if name and name.strip()
    }


def raid_attendance_streaks(previous, stats):
    """Advance streaks from RAID attendance (participants + every parse
    pool). A week with no raid data carries streaks forward untouched —
    a cancelled raid night must not wipe everyone's Iron Attendance."""
    prev = (previous or {}).get("streaks") or {}
    if not stats:
        return dict(prev)
    raiders = set(stats.get("participants") or {})
    for pool in ("best_dps", "best_hps", "best_tanks"):
        raiders |= set(stats.get(pool) or {})
    return advance_streaks(prev, raiders)


def update_records(previous_records, stats=None, mplus_results=None,
                   season_parses=None, season_key=None):
    """Season records: highest timed key, best DPS parse, best HPS parse.

    Candidates come from this week's data AND full-season sweeps
    (season_parses = {"dps": entry, "hps": entry} from the WCL season
    scan; season_key from the Raider.io season scan), so the book truly
    reflects the whole season, not just weeks since the feature shipped.
    Returns the record book with a "new" flag on anything broken this
    week (a first-ever record counts as new — it IS news)."""
    records = {}
    for key, value in (previous_records or {}).items():
        value = dict(value)
        value["new"] = False
        records[key] = value

    def consider(key, candidate, metric):
        current = records.get(key)
        if current is None or (candidate.get(metric) or 0) > (current.get(metric) or 0):
            candidate = dict(candidate)
            candidate["new"] = True
            records[key] = candidate

    if mplus_results:
        best = max(mplus_results, key=lambda r: r[0])
        spec = best[3] if len(best) >= 5 else ""
        consider("highest_timed_key",
                 {"name": best[2], "level": best[0], "dungeon": best[1], "spec": spec},
                 "level")

    if season_key:
        consider("highest_timed_key", {
            "name": season_key.get("name", ""),
            "level": season_key.get("level", 0),
            "dungeon": season_key.get("dungeon", ""),
            "spec": season_key.get("spec", ""),
        }, "level")

    if stats:
        for key, pool in (("best_dps_parse", stats.get("best_dps")),
                          ("best_hps_parse", stats.get("best_hps"))):
            if pool:
                name, info = max(pool.items(), key=lambda kv: kv[1].get("parse") or 0)
                consider(key, {
                    "name": name,
                    "parse": info.get("parse") or 0,
                    "boss": info.get("boss") or "",
                    "spec": info.get("spec") or "",
                    "cls": info.get("cls") or "",
                    "difficulty": info.get("difficulty"),
                }, "parse")

    for role, key in (("dps", "best_dps_parse"), ("hps", "best_hps_parse")):
        candidate = (season_parses or {}).get(role)
        if candidate:
            consider(key, {
                "name": candidate.get("name", ""),
                "parse": candidate.get("parse") or 0,
                "boss": candidate.get("boss") or "",
                "spec": candidate.get("spec") or "",
                "cls": candidate.get("cls") or "",
                "difficulty": candidate.get("difficulty"),
            }, "parse")

    return records

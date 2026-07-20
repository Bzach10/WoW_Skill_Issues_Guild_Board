"""Board memory between weeks.

A small committed state file (like the roster cache) remembers what last
week's board showed, enabling week-over-week deltas (rank movement, score
gains, NEW badges) and a fallback when WCL's standing lookup flakes out.
Only real posts update it — previews and dry runs just read.
"""

import json
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

STATE_FILE = "board_state.json"


def raid_week_label(dt):
    """Date of the most recent NA weekly reset (Tuesday 15:00 UTC) at or
    before dt — the raid week every number on the board belongs to.

    NOT the ISO week: ISO weeks roll on Monday midnight, so a Monday
    repost would land in a "new week" while still covering the same raid
    week. Everything week-scoped (streak advancement, delta baselines)
    keys off this label so reposts are idempotent no matter the weekday."""
    dt = dt.astimezone(timezone.utc)
    days_since_tuesday = (dt.weekday() - 1) % 7   # Monday=0, Tuesday=1
    tuesday = (dt - timedelta(days=days_since_tuesday)).date()
    if days_since_tuesday == 0 and dt.hour < 15:
        tuesday -= timedelta(days=7)
    return tuesday.isoformat()


def baselines_view(state):
    """The state as delta displays must see it: standing/scores/records
    from the LAST COMPLETED week's final post, so mid-week reposts never
    zero the ▲ arrows or eat NEW badges. Falls back to the stored latest
    values for legacy state files without a baseline."""
    if not state:
        return {}
    base = state.get("baseline") or {}
    view = dict(state)
    view["standing"] = base.get("standing", state.get("standing") or {})
    view["season_scores"] = base.get("season_scores", state.get("season_scores") or {})
    view["records"] = base.get("records", state.get("records") or {})
    return view


def load_board_state(path=STATE_FILE):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_board_state(standing, season_scores, streaks=None, records=None, path=STATE_FILE,
                     streaks_week=None, previous=None, streaks_started=None):
    """Persist what this board showed, for next week's comparisons.

    Two-slot scheme: "baseline" holds the last COMPLETED week's finals
    (what deltas compare against) and rolls forward only when the raid
    week changes; the top-level values always hold the latest post. This
    makes every repost idempotent for arrows, badges and streaks alike.

    Runs the integrity checks first — bad values must never be committed,
    because this file seeds every future week's deltas and records."""
    from guild_board import integrity
    integrity.run_all(records=records, standing=standing)
    prev = previous if previous is not None else load_board_state(path)
    clean_standing = {
        k: v for k, v in (standing or {}).items()
        if k in ("realm", "region", "world") and v
    }
    if streaks_week and prev.get("streaks_week") == streaks_week:
        # Same raid week: the baseline must not move, or reposts would
        # compare this week against itself and zero every delta.
        baseline = (prev.get("baseline")
                    or {"standing": prev.get("standing") or {},
                        "season_scores": prev.get("season_scores") or {},
                        "records": prev.get("records") or {}})
    else:
        # New raid week: last week's finals become the comparison floor.
        baseline = {"standing": prev.get("standing") or {},
                    "season_scores": prev.get("season_scores") or {},
                    "records": prev.get("records") or {}}
    state = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "standing": clean_standing,
        "season_scores": {
            name.strip().lower(): score
            for score, name, _ in (season_scores or [])
        },
        "streaks": streaks or {},
        "streaks_week": streaks_week,
        "streaks_started": streaks_started or prev.get("streaks_started")
            or datetime.now(timezone.utc).date().isoformat(),
        "baseline": baseline,
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


def streaks_from_attendance(attendance, scanned_weeks, all_report_weeks):
    """Season-derived attendance streaks — recomputed from actual guild
    logs every run, so they start at the beginning of the season and can
    never drift, inflate, or need resets.

    attendance: {lower_name: set of raid-week labels attended}
    scanned_weeks: weeks whose report details were read
    all_report_weeks: every week the guild logged at all

    Walking back from the latest scanned week: attended -> +1; guild
    raided without them -> streak ends; guild logged but the sweep
    trimmed that week's details -> UNKNOWN, stop counting (honest lower
    bound); nobody logged at all -> neutral skip (a cancelled raid week
    breaks nobody's streak). Returns (streaks, earliest_scanned_week)."""
    from datetime import date
    if not attendance or not scanned_weeks:
        return {}, None
    scanned = set(scanned_weeks)
    unknown = set(all_report_weeks or ()) - scanned
    anchor = max(scanned)
    earliest = min(scanned | set(all_report_weeks or ()))
    streaks = {}
    for name, weeks in attendance.items():
        label, streak = anchor, 0
        while label >= earliest:
            if label in weeks:
                streak += 1
            elif label in unknown or label in scanned:
                break
            label = (date.fromisoformat(label) - timedelta(days=7)).isoformat()
        if streak:
            streaks[name] = streak
    return streaks, min(scanned)


def raid_attendance_streaks(previous, stats, week_label=None):
    """Advance streaks from RAID attendance (participants + every parse
    pool) — at most ONCE per raid week. Reposting the board mid-week
    must not inflate anyone's streak (it did: every manual rerun handed
    the whole roster +1 "week"). A week with no raid data carries
    streaks forward untouched — a cancelled raid night must not wipe
    everyone's Iron Attendance."""
    prev = (previous or {}).get("streaks") or {}
    if not stats:
        return dict(prev)
    if week_label and (previous or {}).get("streaks_week") == week_label:
        return dict(prev)   # this raid week is already counted
    raiders = set(stats.get("participants") or {})
    for pool in ("best_dps", "best_hps", "best_tanks"):
        raiders |= set(stats.get(pool) or {})
    return advance_streaks(prev, raiders)


def update_records(previous_records, stats=None, mplus_results=None,
                   season_parses=None, season_key=None, baseline_records=None):
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

    # Parse records DRIFT: WCL percentiles are relative to every log
    # uploaded, so an early-progression kill can briefly read ~100% and
    # settle far lower once the bracket fills in. When the season sweep
    # ran this week (it re-reads all season logs with TODAY'S percentiles),
    # parse records are rebuilt fresh from it — never compared against a
    # frozen snapshot that can immortalize a stale number. Without a sweep
    # (section disabled / lookup failed) the old cumulative behavior keeps
    # the record book alive.
    for role, key in (("dps", "best_dps_parse"), ("hps", "best_hps_parse")):
        pool = (stats or {}).get(f"best_{role}") or {}
        weekly = None
        if pool:
            name, info = max(pool.items(), key=lambda kv: kv[1].get("parse") or 0)
            weekly = {
                "name": name,
                "parse": info.get("parse") or 0,
                "boss": info.get("boss") or "",
                "spec": info.get("spec") or "",
                "cls": info.get("cls") or "",
                "difficulty": info.get("difficulty"),
            }
        sweep = (season_parses or {}).get(role)
        if sweep:
            sweep = {
                "name": sweep.get("name", ""),
                "parse": sweep.get("parse") or 0,
                "boss": sweep.get("boss") or "",
                "spec": sweep.get("spec") or "",
                "cls": sweep.get("cls") or "",
                "difficulty": sweep.get("difficulty"),
            }
            fresh = max((c for c in (sweep, weekly) if c),
                        key=lambda c: c.get("parse") or 0)
            # NEW is judged against LAST WEEK's record (baseline), not the
            # last posted run — so a mid-week repost keeps the badge lit
            # for the whole week the record was actually broken in.
            ref = ((baseline_records or {}).get(key)
                   if baseline_records is not None else records.get(key))
            fresh["new"] = bool(ref is None
                                or (fresh.get("parse") or 0) > (ref.get("parse") or 0))
            records[key] = fresh
        elif weekly:
            consider(key, weekly, "parse")

    return records

"""Rotating weekly awards — spotlights the mid-pack can actually win.

The top parsers own most of the board; these sections rotate through
prizes that reward showing up and improving, computed entirely from data
the pipeline already has (no extra API calls):

  IRONMAN         — fewest deaths among this week's raiders
  IRON ATTENDANCE — longest consecutive-week activity streaks
  BIGGEST CLIMB   — largest M+ season-score gain since last board

Each week `per_week` of them appear, rotating by ISO week number so the
spotlight moves even when the data doesn't. Everything fails open: a
missing dataset just means that award sits out this week.
"""

import logging

logger = logging.getLogger(__name__)

GREEN = (76, 220, 86)
MUTED = (179, 185, 197)


def _display(name):
    """Streak/state keys are lowercased; make them presentable again."""
    name = (name or "").strip()
    return name[:1].upper() + name[1:] if name else name


def _ironman(stats=None, **_):
    """Fewest deaths among everyone who raided this week."""
    if not stats:
        return None
    deaths = stats.get("deaths") or {}
    participants = set(stats.get("participants") or [])
    participants |= set(stats.get("best_dps") or {})
    participants |= set(stats.get("best_hps") or {})
    if not participants:
        return None
    pulls = stats.get("pulls") or 0
    ranked = sorted(participants, key=lambda n: (deaths.get(n, 0), n.lower()))
    rows = []
    for name in ranked:
        d = deaths.get(name, 0)
        rows.append({
            "name": name,
            "detail": f"survived {pulls} pulls" if pulls else "survived the week",
            "value": str(d),
            "value_suffix": "deaths",
            "value_color": GREEN if d == 0 else MUTED,
        })
    return rows


def _attendance(streaks=None, **_):
    """Longest consecutive-week activity streaks (2+ weeks to qualify)."""
    qualified = [(w, n) for n, w in (streaks or {}).items() if w >= 2]
    if not qualified:
        return None
    rows = []
    for weeks, name in sorted(qualified, key=lambda t: (-t[0], t[1])):
        rows.append({
            "name": _display(name),
            "detail": "weeks active in a row",
            "value": str(weeks),
            "value_suffix": "wks",
            "value_color": GREEN,
        })
    return rows


def _biggest_climb(season_scores=None, previous=None, **_):
    """Largest M+ season-score gain since the last posted board."""
    prev = (previous or {}).get("season_scores") or {}
    if not season_scores or not prev:
        return None
    climbs = []
    for score, name, spec in season_scores:
        old = prev.get((name or "").strip().lower())
        if old and score > old:
            climbs.append((score - old, name, spec, old, score))
    if not climbs:
        return None
    rows = []
    for gain, name, spec, old, score in sorted(climbs, key=lambda t: -t[0]):
        rows.append({
            "name": name,
            "spec": spec,
            "detail": f"{spec} · {old:.0f} → {score:.0f}",
            "detail_bits": [spec or "", f"{old:.0f} → {score:.0f}"],
            "value": f"+{gain:.0f}",
            "value_color": GREEN,
        })
    return rows


AWARD_POOL = [
    ("WEEKLY AWARD · IRONMAN", _ironman),
    ("WEEKLY AWARD · IRON ATTENDANCE", _attendance),
    ("WEEKLY AWARD · BIGGEST CLIMB", _biggest_climb),
]


def weekly_awards(week_index, stats=None, streaks=None, season_scores=None,
                  previous=None, per_week=2, top_n=3):
    """Sections (same shape the column builders emit) for this week's
    rotation — at most per_week awards, each with top_n rows."""
    sections = []
    data = dict(stats=stats, streaks=streaks, season_scores=season_scores,
                previous=previous)
    for k in range(len(AWARD_POOL)):
        title, builder = AWARD_POOL[(week_index + k) % len(AWARD_POOL)]
        try:
            rows = builder(**data)
        except Exception as exc:   # an award must never sink the board
            logger.warning("Award %s failed (%s); skipping.", title, exc)
            rows = None
        if rows:
            sections.append({"title": title, "rows": rows[:top_n]})
        if len(sections) >= per_week:
            break
    return sections

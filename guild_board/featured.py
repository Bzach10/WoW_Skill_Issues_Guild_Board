"""Cameo history (ARC-09) — who has been in the spotlight, who is owed one.

The site puts specific members on camera every week: the record holders
the recap and manga strip name, and the two names in the roast. That is
a real "featured" signal the front end produces on its own. Accumulated
week over week it becomes cameo debt — the never-featured members future
casting should lean toward.

The accumulation is the weekly job's to keep (one render only sees one
week), so this module both:

  * EMITS this week's spotlight (`emit_week`) for the backend to fold in, and
  * READS the accumulated `featured_history.json` when it exists, and
    degrades to "this week only" until it does.

The data shape both sides share:

    featured_history.json
    { "members": { "<slug>": { "features": <int>,
                               "last_featured": "YYYY-MM-DD" | null,
                               "where": ["manga","recap","roast", ...] } } }
"""

import json
import logging
from datetime import date
from pathlib import Path

from .showcase import slugify

logger = logging.getLogger(__name__)

HISTORY_FEED = Path("featured_history.json")
WEEK_OUT = Path("featured_this_week.json")


def this_week(board_state, cfg=None):
    """{slug: [where, ...]} — the members this week put on camera."""
    records = (board_state or {}).get("records") or {}
    out = {}

    def add(name, where):
        if not name:
            return
        s = slugify(name)
        if s:
            out.setdefault(s, set()).add(where)

    for key in ("highest_timed_key", "best_dps_parse", "best_hps_parse"):
        add((records.get(key) or {}).get("name"), "recap")
    roast = ((cfg or {}).get("sections") or {}).get("roast_of_the_week") or {}
    add(roast.get("winner"), "roast")
    add(roast.get("target"), "roast")
    return {s: sorted(w) for s, w in out.items()}


def load_history(path=HISTORY_FEED):
    """The accumulated feed's members map, or {} if it hasn't landed yet."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return (data or {}).get("members") or {}


def cameo_debt(crew, board_state, cfg=None, path=HISTORY_FEED):
    """Rank the cast by how often each member has been featured.

    With the accumulated feed present, this is real cameo debt. Without
    it, all we can evidence is this week, so `have_feed` is False and the
    view should show the spotlight rather than a wall of "never featured".
    """
    history = load_history(path)
    have_feed = bool(history)
    week = this_week(board_state, cfg)

    members = []
    for m in crew or []:
        s = m.get("slug")
        h = history.get(s) or {}
        features = int(h.get("features") or 0)
        if not have_feed and s in week:
            features = max(features, 1)     # this week is the only evidence
        members.append({
            "slug": s,
            "name": m.get("name"),
            "role": m.get("role"),
            "role_label": m.get("role_label"),
            "features": features,
            "last_featured": h.get("last_featured"),
            "in_spotlight": s in week,
        })

    never = [x for x in members if x["features"] == 0]
    featured = sorted((x for x in members if x["features"] > 0),
                      key=lambda x: (-x["features"], x["name"] or ""))
    spotlight = [x for x in members if x["in_spotlight"]]
    return {
        "have_feed": have_feed,
        "spotlight": spotlight,
        "featured": featured,
        "never": never,
        "never_count": len(never),
        "cast_size": len(members),
    }


def emit_week(board_state, cfg=None, out=WEEK_OUT):
    """Write this week's spotlight for the backend to accumulate. Local
    build artifact — never part of the published bundle."""
    week = this_week(board_state, cfg)
    payload = {
        "week_of": date.today().isoformat(),
        "featured": {s: {"where": w} for s, w in week.items()},
    }
    try:
        Path(out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("Emitted this week's spotlight (%d members) to %s",
                    len(week), out)
    except OSError as exc:
        logger.info("Could not write %s (%s).", out, exc)
    return payload

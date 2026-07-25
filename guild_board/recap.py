"""The Weekly Recap Ribbon — an in-world "story of the week".

Consumes the backend session's recap feed when it lands (recap.json with
a `sentences` or `story` field), and otherwise generates a recap from the
real data already on disk: board records, the roast, attendance streaks
and season-score climbs. Nothing is invented — every line names a real
player and a real number, or it is not written.
"""

import json
import logging

logger = logging.getLogger(__name__)

RECAP_FEED = "recap.json"


def _load_feed(path=RECAP_FEED):
    """The backend's recap, if it has been produced."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    sentences = data.get("sentences")
    if isinstance(sentences, list) and sentences:
        return [str(s) for s in sentences if s]
    story = data.get("story")
    if isinstance(story, str) and story.strip():
        # split a paragraph into sentences for the ribbon
        return [s.strip() + "." for s in story.replace("\n", " ").split(".") if s.strip()]
    return None


def _title(name):
    return (name or "").strip().title()


def generate(board_state, cfg=None, feed_path=RECAP_FEED):
    """Return the recap as a list of sentences (the ribbon renders each as
    a beat). Backend feed first; a data-derived recap otherwise."""
    fed = _load_feed(feed_path)
    if fed:
        return {"source": "backend", "sentences": fed}

    state = board_state if isinstance(board_state, dict) else {}
    records = state.get("records") if isinstance(state.get("records"), dict) else {}
    scores = state.get("season_scores") if isinstance(state.get("season_scores"), dict) else {}
    baseline = ((state.get("baseline") or {}).get("season_scores")
                if isinstance(state.get("baseline"), dict) else {}) or {}
    streaks = state.get("streaks") if isinstance(state.get("streaks"), dict) else {}

    lines = []

    # 1. the headline record — highest key or a fresh parse
    key = records.get("highest_timed_key") or {}
    if key.get("name") and key.get("level"):
        lines.append(
            f"{_title(key['name'])} drove the deepest key of the week — a timed "
            f"+{key['level']} through {key.get('dungeon', 'the depths')}.")

    dps = records.get("best_dps_parse") or {}
    if dps.get("name") and dps.get("parse"):
        spec = " ".join(x for x in (dps.get("spec"), dps.get("cls")) if x)
        lines.append(
            f"{_title(dps['name'])} topped the damage charts with a {dps['parse']} "
            f"parse on {dps.get('boss', 'the boss')}"
            f"{f' as {spec}' if spec else ''}.")

    hps = records.get("best_hps_parse") or {}
    if hps.get("name") and hps.get("parse"):
        lines.append(
            f"On heals, {_title(hps['name'])} answered with a {hps['parse']} on "
            f"{hps.get('boss', 'the pull')} — the crew lived to tell it.")

    # 2. biggest climber, from the baseline diff
    climbs = []
    for slug, score in scores.items():
        base = baseline.get(slug)
        if base is not None and score - base > 0:
            climbs.append((slug, round(score - base, 1)))
    if climbs:
        slug, gained = max(climbs, key=lambda kv: kv[1])
        lines.append(
            f"{_title(slug)} climbed hardest this week, up {gained} points of "
            f"Mythic+ score.")

    # 3. the longest attendance streak
    if streaks:
        slug, weeks = max(streaks.items(), key=lambda kv: kv[1])
        if weeks and weeks >= 2:
            lines.append(
                f"{_title(slug)} keeps showing up — {weeks} weeks on the board "
                f"and counting.")

    # 4. the roast, if there is one
    roast_cfg = (cfg or {}).get("sections", {}).get("roast_of_the_week") or {}
    if roast_cfg.get("roast"):
        who = roast_cfg.get("winner", "someone")
        target = roast_cfg.get("target")
        lines.append(
            f"And the roast of the week, from {who}"
            f"{f' aimed at {target}' if target else ''}: "
            f"“{roast_cfg['roast']}”.")

    if not lines:
        return {"source": "empty", "sentences": []}
    return {"source": "derived", "sentences": lines}

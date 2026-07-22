"""Persist the week's WCL parse ladders for the website.

The Discord board computes best-parse pools every run (wcl.collect_raid_stats,
already roster-filtered by main). The website's Standings hub reads the same
numbers from `web_stats.json` (guild_board/standings.py) and falls back to the
season's record holders when the file is absent — so this writer is fail-open
by design: a write failure costs the site freshness, never the board post.

This file is a snapshot, not memory. Unlike board_state.json there are no
week-over-week semantics, so writing it on preview/dry-run is safe.
"""

import json
import logging

logger = logging.getLogger(__name__)

ROWS_PER_LADDER = 10  # the site shows 5; extra rows are headroom, not promise


def _ladder(pool):
    """A best-parse pool ({name: {parse, boss, spec, ...}}) as ranked rows."""
    entries = sorted((pool or {}).items(),
                     key=lambda kv: -(kv[1].get("parse") or 0))
    return [{
        "name": name,
        "value": int(round(info.get("parse") or 0)),
        "detail": " · ".join(b for b in (info.get("boss"), info.get("spec")) if b),
    } for name, info in entries[:ROWS_PER_LADDER]]


def build_payload(stats):
    """The web_stats.json payload, or None when there is nothing to say."""
    if not stats:
        return None
    ladders = {
        "top_dps": _ladder(stats.get("best_dps")),
        "top_hps": _ladder(stats.get("best_hps")),
        "top_tanks": _ladder(stats.get("best_tanks")),
    }
    if not any(ladders.values()):
        return None
    ladders["difficulty"] = stats.get("difficulty")
    return ladders


def dump_web_stats(stats, path="web_stats.json"):
    """Write web_stats.json next to board_state.json. Fail open, always."""
    payload = build_payload(stats)
    if payload is None:
        logger.info("No parse data this run; web_stats.json not written.")
        return False
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except OSError as exc:
        logger.warning("Could not write %s: %s", path, exc)
        return False
    logger.info("web_stats.json written (%s dps / %s hps / %s tank rows)",
                len(payload["top_dps"]), len(payload["top_hps"]),
                len(payload["top_tanks"]))
    return True

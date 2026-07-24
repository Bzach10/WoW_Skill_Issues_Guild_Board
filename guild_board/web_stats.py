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


def absence_payload(stats):
    """Why there are no ladders this run — written instead of nothing.

    A *missing* web_stats.json is ambiguous: it looks identical whether the
    pipeline never ran, crashed, or ran fine against a source that returned
    no parses. The site then renders a bare em-dash under Top Tank with no
    explanation, and the page footer claims the ladders "populate
    automatically from the daily data refresh" — which is not true when the
    credentials that would populate them are unset.

    So record the absence as a fact. Missing data should fail visibly.

    Two audiences, two fields, and the split is deliberate:

      * ``reason`` is MEMBER-FACING. It renders on the ship page, which
        roughly 150 guild members read. It must never name an environment
        variable, a credential, a file path, or anything else that only
        means something to whoever runs the pipeline. Build-log text that
        escapes onto a members' page reads as unfinished, and naming
        credential variables in shipped HTML is a habit worth not having.
      * ``operator_detail`` is for the pipeline operator — logs, CI output
        and the runbook. It may name the variables, because the person
        reading it is the person who sets them. **It is never rendered:**
        ``tests/test_no_credentials_in_output.py`` fails the build if it
        reaches any HTML the site ships.
    """
    if not stats:
        reason = ("The board run produced no stats at all — Warcraft Logs "
                  "was not queried this run.")
        operator_detail = ("No stats object was produced; the Warcraft Logs "
                           "step did not run.")
    else:
        reason = ("Weekly parse ladders aren't running yet. Raider.io doesn't "
                  "publish parse data, so these fill in once Warcraft Logs is "
                  "connected.")
        operator_detail = ("Warcraft Logs returned no parse pools. The usual "
                           "cause is that the Warcraft Logs client id and "
                           "secret are unset on the pipeline (see "
                           "docs/RUNBOOK.md for the variable names); without "
                           "them the parse ladders cannot be built from any "
                           "other source, because Raider.io does not expose "
                           "parses.")
    return {
        "available": False,
        "reason": reason,
        "operator_detail": operator_detail,
        "top_dps": [], "top_hps": [], "top_tanks": [],
        "difficulty": (stats or {}).get("difficulty"),
    }


def dump_web_stats(stats, path="web_stats.json"):
    """Write web_stats.json next to board_state.json. Fail open, always.

    Returns True only when real ladders were written; an absence record
    still lands on disk but reports False, so callers and CI keep their
    existing "did we get parses this week?" semantics.
    """
    payload = build_payload(stats)
    if payload is None:
        absence = absence_payload(stats)
        # The LOG gets the operator detail (it may name variables); the
        # site gets absence["reason"], which may not.
        logger.warning("No parse data this run: %s Recording the absence in "
                       "%s so the site can say why rather than showing a "
                       "blank ladder.", absence["operator_detail"], path)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(absence, f, indent=2, ensure_ascii=False)
        except OSError as exc:
            logger.warning("Could not write %s: %s", path, exc)
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

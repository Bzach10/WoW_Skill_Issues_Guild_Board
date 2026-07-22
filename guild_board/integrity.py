"""Self-healing data-integrity checks for every board build.

The board has been bitten twice by numbers that were true at capture but
wrong at viewing time (ticking counters, WCL percentile drift). This
module is the guard rail: it runs inside every build, HEALS what it
safely can in place, and loudly logs what it can't — as GitHub Actions
warning annotations in CI, so problems surface in the run summary
without ever blocking a post.

Also runnable standalone against the committed state file (the weekly
caretaker agent uses this):

    python -m guild_board.integrity        # exit 1 on unhealable problems
"""

import json
import logging
import os
import re
import sys

logger = logging.getLogger(__name__)

_PCT = re.compile(r"^(\d+(?:\.\d+)?)%$")
_FALLBACK_NAME_COLOR = "rgb(235,236,240)"   # "class unknown" white


def _warn(messages, msg):
    messages.append(msg)
    logger.warning("INTEGRITY: %s", msg)
    if os.environ.get("GITHUB_ACTIONS"):
        # Annotation shows in the Actions run summary — visible without log-diving
        print(f"::warning title=Board integrity::{msg}")


def check_rows(context, messages):
    """Percent values must be 0-100 (heal: clamp); names that carry a
    spec/class but rendered in fallback white mean color resolution broke
    (the historical grey-name bug — warn, a human decides)."""
    grey = []
    for col in context.get("columns") or []:
        for sec in col.get("sections") or []:
            for row in sec.get("rows") or []:
                if "text" in row:
                    continue
                m = _PCT.match(str(row.get("value", "")))
                if m and float(m.group(1)) > 100:
                    _warn(messages,
                          f"{row.get('name')} showed {row['value']} in '{sec['title']}' — "
                          "clamped to 100% (source data suspect)")
                    row["value"] = "100%"
                if (row.get("color") == _FALLBACK_NAME_COLOR
                        and (row.get("spec") or row.get("cls"))):
                    grey.append(row.get("name"))
    if grey:
        _warn(messages,
              f"{len(grey)} row(s) rendered without class color despite known "
              f"spec/class (grey-name regression?): {', '.join(sorted(set(grey))[:6])}")


def check_hero(context, messages):
    """Wipes must equal pulls - kills; a mismatch means the hero band and
    the widgets came from different sources (heal: recompute)."""
    pulls = context.get("pulls") or 0
    kills = None
    for tile in context.get("hero_tiles") or []:
        if tile.get("label") == "KILLS":
            try:
                kills = int(str(tile.get("value")).replace(",", ""))
            except ValueError:
                pass
    if kills is not None:
        expected = max(pulls - kills, 0)
        if context.get("wipes") != expected:
            _warn(messages,
                  f"wipes={context.get('wipes')} but pulls-kills={expected} — healed")
            context["wipes"] = expected


def check_records(records, messages):
    """Record parses must be sane percentiles. An exact 100 is legal but
    historically a near-empty-bracket artifact — flag it so the weekly
    sweep's self-correction can be watched. Heal: clamp out-of-range."""
    for key, rec in (records or {}).items():
        if not isinstance(rec, dict) or "parse" not in rec:
            continue
        parse = rec.get("parse") or 0
        if parse > 100:
            _warn(messages, f"record {key} carried impossible parse {parse} — clamped to 100")
            rec["parse"] = 100
        elif parse < 0:
            _warn(messages, f"record {key} carried negative parse {parse} — dropped to 0")
            rec["parse"] = 0
        elif parse == 100:
            _warn(messages,
                  f"record {key} ({rec.get('name')}) sits at exactly 100% — possible "
                  "early-bracket artifact; the season sweep will re-verify next run")


def check_streaks(state, messages):
    """No streak may exceed the weeks physically possible since tracking
    began — the invariant that would have caught the everyone-at-15 bug
    (streaks were advancing per POST, not per raid week)."""
    streaks = (state or {}).get("streaks") or {}
    started = (state or {}).get("streaks_started")
    if not streaks or not started:
        return
    try:
        from datetime import date
        begun = date.fromisoformat(str(started))
        weeks_possible = max((date.today() - begun).days // 7 + 1, 1)
    except ValueError:
        return
    worst = max(streaks.values())
    if worst > weeks_possible:
        _warn(messages,
              f"max attendance streak is {worst}w but only {weeks_possible}w have "
              f"elapsed since tracking began ({started}) — per-post inflation bug?")


def check_theme_assets(theme, messages):
    """Every configured background image must exist on disk — a typo'd or
    uncommitted path (easy to do when the art director stages new assets)
    otherwise renders as a silent blank. Heal: poster falls back to the
    pure-CSS parchment (None); walls fall back to the shipped defaults."""
    from guild_board.theme import DEFAULT_THEME
    backgrounds = (theme or {}).get("backgrounds")
    if not backgrounds:
        return
    defaults = DEFAULT_THEME["backgrounds"]
    for key in ("header", "middle", "footer", "poster", "item", "crest"):
        path = backgrounds.get(key)
        if not path or os.path.exists(path):
            continue
        fallback = defaults.get(key)
        if fallback and os.path.exists(fallback):
            _warn(messages, f"backgrounds.{key} points at missing file '{path}' — "
                            f"healed to the shipped default")
            backgrounds[key] = fallback
        else:
            _warn(messages, f"backgrounds.{key} points at missing file '{path}' — "
                            f"cleared (renders without it)")
            backgrounds[key] = None


def check_standing(standing, messages):
    """Ranks must be positive integers; anything else is dropped rather
    than rendered (a '#0' or negative rank is worse than a blank)."""
    for key in ("realm", "region", "world"):
        value = (standing or {}).get(key)
        if value is None:
            continue
        try:
            ok = int(value) > 0
        except (TypeError, ValueError):
            ok = False
        if not ok:
            _warn(messages, f"standing.{key}={value!r} is not a positive rank — dropped")
            standing.pop(key, None)


def run_all(context=None, records=None, standing=None, theme=None):
    """Run every applicable check, healing in place. Returns the warning
    list — empty means a clean bill of health."""
    messages = []
    if theme:
        check_theme_assets(theme, messages)
    if context:
        check_rows(context, messages)
        check_hero(context, messages)
    if records is not None:
        check_records(records, messages)
    if standing is not None:
        check_standing(standing, messages)
    if messages:
        logger.warning("INTEGRITY: %s issue(s) found this build (healed where safe).",
                       len(messages))
    return messages


def main():
    """Standalone check of the committed board state (caretaker entry point)."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        with open("board_state.json", "r", encoding="utf-8") as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"board_state.json unreadable: {exc}")
        return 1
    messages = run_all(records=state.get("records"), standing=state.get("standing"))
    check_streaks(state, messages)
    hard = [m for m in messages
            if "clamped" in m or "dropped" in m or "unreadable" in m or "inflation" in m]
    print(f"integrity: {len(messages)} finding(s), {len(hard)} needing attention")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())

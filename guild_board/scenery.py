"""The month's scene: hero banner + page backdrop.

Two versions of the same artwork do two different jobs:

  * baked.png — the scene WITH characters. It is the hero banner across
    the top of the board, the visual centrepiece.
  * raw.png   — the same scene with no characters. It sits far behind the
    page content, darkened and blurred, as atmosphere only.

The busy character version must never end up behind text. That is the
whole point of the split, so `backdrop` only ever resolves to raw.

Rotation is data, not code: scenes/rotation.json maps month number to a
scene key, so reordering the year is an edit to that file.
"""

import calendar
import json
import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

SCENE_ROOTS = [Path("cast/_scenes"), Path("C:/wt/cg/cast/_scenes")]
ROTATION_FILE = Path("scenes/rotation.json")

HERO_FILE = "baked.png"        # with characters — banner only
BACKDROP_FILE = "raw.png"      # without characters — backdrop only


def _scene_dir(key):
    for root in SCENE_ROOTS:
        candidate = Path(root) / key
        if candidate.is_dir():
            return candidate
    return None


def available():
    """Every scene we have art for."""
    found = {}
    for root in SCENE_ROOTS:
        if not Path(root).is_dir():
            continue
        for entry in sorted(Path(root).iterdir()):
            if entry.is_dir() and (entry / BACKDROP_FILE).exists():
                found.setdefault(entry.name, entry)
    return found


def load_rotation(path=ROTATION_FILE, cfg=None):
    """{month number: scene key}. config.yml can override the whole map:

        scenery:
          rotation:
            7: "silvermoon_city"
    """
    override = ((cfg or {}).get("scenery") or {}).get("rotation")
    raw = override if isinstance(override, dict) else None
    if raw is None:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = (json.load(fh) or {}).get("months")
        except (OSError, ValueError) as exc:
            logger.info("No scene rotation (%s); the board renders without a scene.", exc)
            return {}
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, value in raw.items():
        try:
            month = int(key)
        except (TypeError, ValueError):
            continue
        if 1 <= month <= 12 and isinstance(value, str) and value.strip():
            out[month] = value.strip()
    return out


def scene_for_month(month=None, cfg=None, rotation=None):
    """The scene showing this month, or None if nothing is mapped."""
    month = month or datetime.now().month
    rotation = load_rotation(cfg=cfg) if rotation is None else rotation
    key = rotation.get(month)
    if not key:
        return None
    directory = _scene_dir(key)
    if directory is None:
        logger.info("Scene %r for month %d has no art on disk.", key, month)
        return None

    hero = directory / HERO_FILE
    backdrop = directory / BACKDROP_FILE
    if not backdrop.exists():
        logger.info("Scene %r has no %s; skipping the backdrop.", key, BACKDROP_FILE)
        return None

    return {
        "key": key,
        "month": month,
        "month_name": calendar.month_name[month],
        "title": key.replace("_", " ").title(),
        # the hero is optional: a scene with only a raw plate still gives
        # us atmosphere, it just has no banner
        "hero": str(hero).replace(os.sep, "/") if hero.exists() else None,
        "backdrop": str(backdrop).replace(os.sep, "/"),
    }


def year_plan(cfg=None):
    """The whole rotation, for showing what the year looks like."""
    rotation = load_rotation(cfg=cfg)
    have = available()
    return [{
        "month": m,
        "month_name": calendar.month_abbr[m],
        "key": rotation.get(m),
        "title": (rotation.get(m) or "").replace("_", " ").title(),
        "ready": rotation.get(m) in have,
    } for m in range(1, 13)]

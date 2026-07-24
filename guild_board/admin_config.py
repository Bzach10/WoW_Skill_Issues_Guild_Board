"""Read/write the guild-editable config knobs the local admin panel owns.

Round-trips config.yml preserving every key it does not touch, so the
admin panel can set the month's scene, the default theme, the backdrop
scrim, and which sections show / in what order, without disturbing the
guild/raid/section settings the rest of the board relies on.

This module is only ever used by the LOCAL admin server. It is not
imported by the render path that produces the published build.
"""

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

CONFIG_FILE = "config.yml"

# The sections of the trial page, in default order, that the panel can
# reorder or hide. Keys match data-section attributes in the template.
SECTIONS = ["recap", "cast", "how", "changed", "rotation", "cta"]
SECTION_LABELS = {
    "recap": "Weekly recap ribbon",
    "cast": "The cast (roster)",
    "how": "How it works",
    "changed": "What changed in this draft",
    "rotation": "Scene rotation strip",
    "cta": "Open the crew board",
}


def load(path=CONFIG_FILE):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("config.yml unreadable (%s); starting from empty.", exc)
        return {}


def current_settings(cfg=None):
    """The subset of config the panel edits, with sensible defaults."""
    cfg = load() if cfg is None else cfg
    scenery = cfg.get("scenery") or {}
    display = cfg.get("display") or {}
    panel = cfg.get("panel") or {}
    return {
        "theme": (cfg.get("crew") or {}).get("default_theme") or "codex",
        "rotation": {int(k): v for k, v in (scenery.get("rotation") or {}).items()
                     if str(k).isdigit()},
        "scrim": panel.get("scrim", 93),
        "sections": panel.get("sections") or list(SECTIONS),
        "hidden": panel.get("hidden") or [],
    }


def save(settings, path=CONFIG_FILE):
    """Merge the panel's settings into config.yml, preserving everything
    else. Returns the written settings."""
    cfg = load(path)

    theme = settings.get("theme")
    if theme in ("codex", "console", "chronicle"):
        cfg.setdefault("crew", {})["default_theme"] = theme

    rotation = settings.get("rotation")
    if isinstance(rotation, dict):
        clean = {}
        for k, v in rotation.items():
            try:
                month = int(k)
            except (TypeError, ValueError):
                continue
            if 1 <= month <= 12 and isinstance(v, str) and v.strip():
                clean[month] = v.strip()
        cfg.setdefault("scenery", {})["rotation"] = clean

    panel = cfg.setdefault("panel", {})
    scrim = settings.get("scrim")
    if isinstance(scrim, (int, float)) and 60 <= scrim <= 99:
        panel["scrim"] = int(scrim)

    sections = settings.get("sections")
    if isinstance(sections, list) and set(sections) <= set(SECTIONS):
        panel["sections"] = sections

    hidden = settings.get("hidden")
    if isinstance(hidden, list):
        panel["hidden"] = [h for h in hidden if h in SECTIONS]

    tmp = Path(path).with_suffix(".yml.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, sort_keys=False, allow_unicode=True)
    tmp.replace(path)
    logger.info("Wrote panel settings to %s", path)
    return current_settings(cfg)

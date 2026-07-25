"""Season content: which dungeons and raid make up the voyage.

Data-driven on purpose. Each season is a JSON file in seasons/, sourced
from Raider.io's static-data endpoint rather than typed by hand, and
seasons/active.json says which one the board is on. Swapping to Season 2
at the grand opening is a one-line edit to that file — no code change,
no redeploy of logic.

Nothing in here invents content. If a season file is missing or
malformed, the voyage renders empty and says so rather than falling back
to a stale or guessed island list.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SEASON_DIR = Path("seasons")


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError) as exc:
        logger.info("Season file %s unreadable (%s).", path, exc)
        return None


def available(season_dir=SEASON_DIR):
    """Every season we have content for, newest id last."""
    directory = Path(season_dir)
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.json") if p.stem != "active")


def active_id(season_dir=SEASON_DIR, cfg=None):
    """Which season the voyage shows.

    config.yml wins, so an officer can preview the next season without
    touching the data files:

        voyage:
          season: "season-mn-2"
    """
    configured = ((cfg or {}).get("voyage") or {}).get("season")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    pointer = _read(Path(season_dir) / "active.json") or {}
    chosen = pointer.get("active")
    if isinstance(chosen, str) and chosen:
        return chosen
    seasons = available(season_dir)
    return seasons[0] if seasons else None


def load(season_id=None, season_dir=SEASON_DIR, cfg=None):
    """The season's content, or None when we have nothing real to show."""
    season_id = season_id or active_id(season_dir, cfg)
    if not season_id:
        return None
    data = _read(Path(season_dir) / f"{season_id}.json")
    if not data:
        logger.warning("No content for season %r — the voyage will say so "
                       "rather than showing a stale island list.", season_id)
        return None
    return data


def islands(season, board_state=None, live=None):
    """The ordered island chain for a season.

    Dungeons first, then the raid's bosses. Each island carries whatever
    real guild data we have; anything we do not have is left as None so
    the page can say "no record yet" instead of implying a zero.
    """
    if not season:
        return []
    live = live or {}
    out = []
    for dungeon in season.get("dungeons") or []:
        name = dungeon.get("name")
        if not name:
            continue
        out.append({
            "id": _slug(name),
            "name": name,
            "short": dungeon.get("short_name") or "",
            "kind": "dungeon",
            "data": (live.get("dungeons") or {}).get(name),
        })
    raid = season.get("raid") or {}
    for boss in raid.get("bosses") or []:
        out.append({
            "id": _slug(boss),
            "name": boss,
            "short": "",
            "kind": "raid_boss",
            "raid": raid.get("name"),
            "data": (live.get("bosses") or {}).get(boss),
        })
    return out


def _slug(name):
    return "".join(c.lower() if c.isalnum() else "-" for c in (name or "")).strip("-")


def summary(season):
    if not season:
        return "no season content loaded"
    return (f"{season.get('label') or season.get('id')} · "
            f"{len(season.get('dungeons') or [])} dungeons · "
            f"{len((season.get('raid') or {}).get('bosses') or [])} raid bosses")

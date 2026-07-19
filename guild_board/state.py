"""Board memory between weeks.

A small committed state file (like the roster cache) remembers what last
week's board showed, enabling week-over-week deltas (rank movement, score
gains, NEW badges) and a fallback when WCL's standing lookup flakes out.
Only real posts update it — previews and dry runs just read.
"""

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

STATE_FILE = "board_state.json"


def load_board_state(path=STATE_FILE):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_board_state(standing, season_scores, path=STATE_FILE):
    """Persist what this board showed, for next week's comparisons."""
    clean_standing = {
        k: v for k, v in (standing or {}).items()
        if k in ("realm", "region", "world") and v
    }
    state = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "standing": clean_standing,
        "season_scores": {
            name.strip().lower(): score
            for score, name, _ in (season_scores or [])
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    logger.info("Board state saved for next week's deltas.")
    return path

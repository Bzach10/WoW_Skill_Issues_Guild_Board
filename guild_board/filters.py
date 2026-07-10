import logging

import requests

from guild_board.wcl import fetch_guild_member_names

logger = logging.getLogger(__name__)


def apply_roster_filters(token, cfg, stats):
    """Optionally restrict the board to guild members (plus an allowlist),
    and always honor the exclude list. Fails open: if the roster can't be
    fetched, everyone stays on the board rather than posting a blank one."""
    filters = cfg.get("filters") or {}
    include = {n.strip().lower() for n in (filters.get("always_include") or [])}
    exclude = {n.strip().lower() for n in (filters.get("always_exclude") or [])}
    members_only = bool(filters.get("guild_members_only", False))

    allowed = None
    if members_only:
        try:
            allowed = fetch_guild_member_names(token, cfg) | include
            logger.info("Roster filter active: %s allowed name(s)", len(allowed))
        except (RuntimeError, requests.RequestException) as exc:
            logger.warning("Guild roster lookup failed (%s); showing everyone this week.", exc)
            allowed = None

    if allowed is None and not exclude:
        return stats

    def keep(name):
        low = name.strip().lower()
        if low in exclude:
            return False
        if allowed is not None and low not in allowed:
            return False
        return True

    for key in ("best_dps", "best_hps", "deaths", "participants"):
        stats[key] = {name: value for name, value in stats[key].items() if keep(name)}
    return stats

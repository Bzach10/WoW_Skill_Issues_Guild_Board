import logging

import requests

from guild_board.config import load_roster_cache
from guild_board.wcl import fetch_guild_member_names

logger = logging.getLogger(__name__)


def make_name_filter(token, cfg):
    """Build a keep(name) predicate honoring guild_members_only plus the
    include/exclude lists.

    The allowed set is the UNION of the live WCL roster and the cached
    roster: WCL's guild roster drifts between runs (members drop off when
    WCL re-syncs), and the union keeps everyone we've ever confirmed as a
    member from being silently deleted off the board. Fails open: if no
    roster is available at all, everyone passes rather than blanking the
    board."""
    filters = cfg.get("filters") or {}
    include = {n.strip().lower() for n in (filters.get("always_include") or [])}
    exclude = {n.strip().lower() for n in (filters.get("always_exclude") or [])}
    members_only = bool(filters.get("guild_members_only", False))

    allowed = None
    if members_only:
        live = set()
        try:
            live = fetch_guild_member_names(token, cfg)
        except (RuntimeError, requests.RequestException) as exc:
            logger.warning("Live guild roster lookup failed (%s); falling back to cache.", exc)

        cached = set()
        try:
            members, _ = load_roster_cache(cfg)
            cached = {m.split("-", 1)[0].strip().lower() for m in members if m}
        except Exception as exc:
            logger.warning("Roster cache read failed: %s", exc)

        if live or cached:
            allowed = live | cached | include
            logger.info("Roster filter active: %s allowed name(s) (live %s / cached %s / include %s)",
                        len(allowed), len(live), len(cached), len(include))
        else:
            logger.warning("No roster available; showing everyone this week.")

    def keep(name):
        low = name.strip().lower()
        if low in exclude:
            return False
        if allowed is not None and low not in allowed:
            return False
        return True

    return keep


def apply_roster_filters(token, cfg, stats, keep=None):
    """Optionally restrict the board to guild members (plus an allowlist),
    and always honor the exclude list."""
    keep = keep or make_name_filter(token, cfg)
    removed = sorted({name for key in ("best_dps", "best_hps", "deaths", "participants")
                      for name in stats.get(key) or {} if not keep(name)})
    if removed:
        # Name the casualties so a wrongly-dropped member is visible in the log
        logger.info("Roster filter removed %s name(s): %s",
                    len(removed), ", ".join(removed[:30]))
    for key in ("best_dps", "best_hps", "deaths", "participants"):
        stats[key] = {name: value for name, value in stats[key].items() if keep(name)}
    return stats

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

        # Third source: the reconciled union across every roster authority
        # (Raider.io's guild roster, the WCL cache, the evidence-backed
        # supplement). Both sources above are WCL-derived, and WCL's member
        # list is a by-product of log uploads rather than a guild roster —
        # on 2026-07-22 it was missing 15 real members, Phyrthepali among
        # them. Widening `allowed` is strictly safer than narrowing it: a
        # name that shouldn't be here costs one wrong row, a name wrongly
        # excluded costs a real member their record.
        reconciled = set()
        try:
            from guild_board.guild_roster import resolve

            members_by_key, _report = resolve(cfg, wcl_roster=None)
            reconciled = {row["name"].strip().lower()
                          for row in members_by_key.values() if row.get("name")}
        except Exception as exc:  # noqa: BLE001 - never fatal to a board run
            logger.warning("Roster reconciliation unavailable (%s); "
                           "falling back to the WCL sources only.", exc)

        if live or cached or reconciled:
            allowed = live | cached | reconciled | include
            logger.info("Roster filter active: %s allowed name(s) "
                        "(live %s / cached %s / reconciled %s / include %s)",
                        len(allowed), len(live), len(cached),
                        len(reconciled), len(include))
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
    keys = ("best_dps", "best_hps", "best_tanks", "deaths", "participants")
    removed = sorted({name for key in keys
                      for name in stats.get(key) or {} if not keep(name)})
    if removed:
        # WARNING, not INFO, and the full list, not the first 30. Every name
        # here is either a pug (fine) or a real member the roster sources are
        # missing (not fine) — and the roster demonstrably misses real members,
        # so this list has to be read, not scrolled past. A drop that nobody
        # sees is how Phyrthepali's 96 parse vanished off the front page.
        #
        # Known limitation, stated rather than hidden: `stats` is keyed by
        # bare character name, so this filter cannot key on `name-realm` the
        # way roster identity does everywhere else. Two members sharing a name
        # across realms (there are two Berobens) pass or fail together here.
        # Fixing it means carrying realm through wcl.collect_raid_stats.
        logger.warning("Roster filter removed %s name(s) — check for real "
                       "members among them: %s", len(removed), ", ".join(removed))
    for key in keys:
        if key in stats:
            stats[key] = {name: value for name, value in stats[key].items() if keep(name)}
    return stats

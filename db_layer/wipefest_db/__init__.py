"""S.S. Wipe Fest data layer (Phase 1).

Surrogate-key model per docs/DATABASE_DESIGN.md. The Blizzard character id is
an observation, never a key. Names are stored exact (NFC); folding is search-only.
"""
from .db import (
    connect,
    finish_fetch_run,
    fold_name,
    get_or_create_guild,
    init_db,
    insert_mplus_score,
    insert_profile,
    log_attempt,
    mint_or_get_character,
    now_utc,
    open_membership_if_absent,
    start_fetch_run,
)

__all__ = [
    "connect", "init_db", "fold_name", "now_utc",
    "start_fetch_run", "finish_fetch_run", "log_attempt",
    "get_or_create_guild", "mint_or_get_character", "open_membership_if_absent",
    "insert_mplus_score", "insert_profile",
]

"""S.S. Wipe Fest data layer (Phase 1).

Surrogate-key model per docs/DATABASE_DESIGN.md. The Blizzard character id is
an observation, never a key. Names are stored exact (NFC); folding is search-only.
"""
from .db import (
    connect, init_db, fold_name, now_utc,
    start_fetch_run, finish_fetch_run, log_attempt,
    get_or_create_guild, mint_or_get_character, open_membership_if_absent,
    insert_mplus_score, insert_profile,
)

__all__ = [
    "connect", "init_db", "fold_name", "now_utc",
    "start_fetch_run", "finish_fetch_run", "log_attempt",
    "get_or_create_guild", "mint_or_get_character", "open_membership_if_absent",
    "insert_mplus_score", "insert_profile",
]

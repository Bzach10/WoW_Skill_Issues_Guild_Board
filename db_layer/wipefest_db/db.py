"""Core DB helpers for the S.S. Wipe Fest data layer.

Design invariants enforced here (docs/DATABASE_DESIGN.md):
  * Identity is keyed on (region, realm_slug, EXACT name). Folding is search-only.
  * Surrogate character_id is ours; Blizzard id is an observation.
  * Fact tables are APPEND-ONLY. No function here issues UPDATE or DELETE against
    an observation. A new value is a new row. Change-only insertion suppresses
    noise but never mutates history.
  * observed_to on membership/identity may only be set by a run whose outcome is
    'success' (enforced by the ingestion module, not here).
Stdlib only — no third-party dependency, so this runs under host `pytest`
without a `pip install`.
"""
from __future__ import annotations

import os
import sqlite3
import unicodedata
from datetime import datetime, timezone

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def now_utc() -> str:
    """ISO8601 UTC timestamp, second precision, 'Z' suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fold_name(name: str) -> str:
    """Accent-fold + casefold for SEARCH/DISPLAY only. NEVER a key.

    'Viôlence' and 'Violënce' both fold to 'violence' — which is exactly why
    folding must never be used to decide identity.
    """
    if name is None:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    stripped = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return stripped.casefold()


def nfc(name: str) -> str:
    """Canonical NFC form of the EXACT name we store and key on."""
    return unicodedata.normalize("NFC", name) if name else name


def connect(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as fh:
        conn.executescript(fh.read())
    conn.commit()


# --- provenance -------------------------------------------------------------
def start_fetch_run(conn, source, endpoint, started_at=None) -> int:
    started_at = started_at or now_utc()
    cur = conn.execute(
        "INSERT INTO fetch_run(source, endpoint, started_at, outcome) VALUES (?,?,?,?)",
        (source, endpoint, started_at, "failed"),  # pessimistic default; upgraded on success
    )
    return cur.lastrowid


def finish_fetch_run(conn, run_id, outcome, *, finished_at=None,
                     targets_attempted=None, targets_succeeded=None,
                     http_429_count=0, error_summary=None, raw_capture_path=None) -> None:
    assert outcome in ("success", "partial", "failed")
    conn.execute(
        """UPDATE fetch_run SET finished_at=?, outcome=?, targets_attempted=?,
               targets_succeeded=?, http_429_count=?, error_summary=?, raw_capture_path=?
           WHERE run_id=?""",
        (finished_at or now_utc(), outcome, targets_attempted, targets_succeeded,
         http_429_count, error_summary, raw_capture_path, run_id),
    )
    conn.commit()


def log_attempt(conn, run_id, *, character_id=None, target_key=None,
                http_status=None, outcome="ok", error=None) -> int:
    cur = conn.execute(
        """INSERT INTO fetch_attempt(run_id, character_id, target_key, http_status, outcome, error)
           VALUES (?,?,?,?,?,?)""",
        (run_id, character_id, target_key, http_status, outcome, error),
    )
    return cur.lastrowid


# --- identity ---------------------------------------------------------------
def get_or_create_guild(conn, region, realm_slug, name_slug, display_name) -> int:
    row = conn.execute(
        "SELECT guild_id FROM guild WHERE region=? AND realm_slug=? AND name_slug=?",
        (region, realm_slug, name_slug),
    ).fetchone()
    if row:
        return row["guild_id"]
    cur = conn.execute(
        "INSERT INTO guild(region, realm_slug, name_slug, display_name) VALUES (?,?,?,?)",
        (region, realm_slug, name_slug, display_name),
    )
    return cur.lastrowid


def find_character_by_identity(conn, region, realm_slug, name):
    """Return character_id for the CURRENT identity (region, realm, exact name), or None.

    Keyed on the EXACT name. Accent variants are different characters by design.
    """
    name = nfc(name)
    row = conn.execute(
        """SELECT character_id FROM character_identity
           WHERE region=? AND realm_slug=? AND name=? AND observed_to IS NULL""",
        (region, realm_slug, name),
    ).fetchone()
    return row["character_id"] if row else None


def mint_or_get_character(conn, region, realm_slug, name, *, source, run_id,
                          blizzard_id=None, observed_at=None):
    """Return (character_id, created).

    If a current identity for (region, realm, EXACT name) exists, reuse its
    surrogate. Otherwise mint a NEW surrogate and attach the identity. Never
    folds; never reuses across accent variants; never reuses across realms.
    """
    existing = find_character_by_identity(conn, region, realm_slug, name)
    if existing is not None:
        return existing, False

    observed_at = observed_at or now_utc()
    name = nfc(name)
    cur = conn.execute(
        "INSERT INTO character(first_observed_at, player_id) VALUES (?, NULL)",
        (observed_at,),
    )
    character_id = cur.lastrowid
    conn.execute(
        """INSERT INTO character_identity(
               character_id, region, realm_slug, name, name_folded, blizzard_id,
               observed_from, observed_to, source, run_id)
           VALUES (?,?,?,?,?,?,?,NULL,?,?)""",
        (character_id, region, realm_slug, name, fold_name(name), blizzard_id,
         observed_at, source, run_id),
    )
    return character_id, True


def open_membership_if_absent(conn, character_id, guild_id, *, run_id,
                              rank=None, observed_from=None) -> int | None:
    """Open a membership interval if the character has no OPEN interval in this guild.

    Returns the interval_id if one was opened, else None. Never deletes; a
    returning member gets a fresh interval elsewhere in the ingestion flow.
    """
    row = conn.execute(
        """SELECT interval_id FROM membership_interval
           WHERE character_id=? AND guild_id=? AND observed_to IS NULL""",
        (character_id, guild_id),
    ).fetchone()
    if row:
        # already an open member — just advance last_run_id (provenance, not mutation of facts)
        conn.execute("UPDATE membership_interval SET last_run_id=? WHERE interval_id=?",
                     (run_id, row["interval_id"]))
        return None
    observed_from = observed_from or now_utc()
    cur = conn.execute(
        """INSERT INTO membership_interval(
               character_id, guild_id, observed_from, observed_to, rank,
               first_run_id, last_run_id)
           VALUES (?,?,?,NULL,?,?,?)""",
        (character_id, guild_id, observed_from, rank, run_id, run_id),
    )
    return cur.lastrowid


# --- append-only facts ------------------------------------------------------
def _latest_score(conn, character_id, season, role, source):
    return conn.execute(
        """SELECT score FROM mplus_score_observation
           WHERE character_id=? AND season=? AND role=? AND source=?
           ORDER BY observed_at DESC, obs_id DESC LIMIT 1""",
        (character_id, season, role, source),
    ).fetchone()


def insert_mplus_score(conn, character_id, season, role, score, source,
                       observed_at, run_id, *, source_url=None,
                       change_only=True, ingested_at=None):
    """APPEND a score observation. Returns obs_id, or None if suppressed as unchanged.

    Never UPDATEs. Change-only insertion suppresses an identical repeat value
    (storage control, §3.3) but never mutates or removes the prior row.
    """
    if change_only:
        prev = _latest_score(conn, character_id, season, role, source)
        if prev is not None and prev["score"] == score:
            return None  # unchanged — do not add a noise row (and do not touch history)
    cur = conn.execute(
        """INSERT INTO mplus_score_observation(
               character_id, season, role, score, source, observed_at, ingested_at,
               run_id, source_url)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (character_id, season, role, score, source, observed_at,
         ingested_at or now_utc(), run_id, source_url),
    )
    return cur.lastrowid


def insert_profile(conn, character_id, *, source, observed_at, run_id,
                   character_class=None, race=None, spec=None, level=None,
                   faction=None, achievement_points=None, render_url=None,
                   transmog_fingerprint=None, source_url=None, ingested_at=None):
    """APPEND a profile observation (class/race/spec/level/...). Never UPDATEs."""
    cur = conn.execute(
        """INSERT INTO character_profile_observation(
               character_id, class, race, spec, level, faction, achievement_points,
               render_url, transmog_fingerprint, source, observed_at, ingested_at,
               run_id, source_url)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (character_id, character_class, race, spec, level, faction, achievement_points,
         render_url, transmog_fingerprint, source, observed_at,
         ingested_at or now_utc(), run_id, source_url),
    )
    return cur.lastrowid

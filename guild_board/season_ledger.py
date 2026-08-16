"""The season ledger — every raid week written down once, and kept.

WHY THIS EXISTS. The pipeline already computes, every single run, exactly
the facts a season history needs: each character's rank, score, week-over-
week delta, attendance streak and whether they raided. Then it throws the
*series* away. `board_state.json` keeps two slots (this week, last week's
baseline) and overwrites both; `web_data_public/` is rebuilt whole every
day. Git holds every old bake, but nothing has ever read one back as a
sequence, and `board_state.json` purges its own history to two weeks by
construction. The owner asked (2026-08-16) "how are we storing all of this
data for future use ... are we just getting rid of it currently?" — this
module is the honest answer: one compact line per character per raid week,
appended to `season_ledger/<season-slug>.jsonl`, forever, in git.

THE LAWS IT IS BUILT ON
  * Append-only. A line, once written, is never rewritten or reordered.
    Re-running a week appends nothing: `(season_slug, week_label,
    character_key)` is the identity, and a triple already on file is
    skipped. That is what makes it safe to call from every workflow.
  * The character key is `name-realm`, never a bare display name. The
    roster holds TWO characters called Beroben (`beroben-emerald-dream`,
    `beroben-queldorei`); a forever-ledger keyed on "beroben" would credit
    one person's whole season to the other, silently and permanently.
  * Real numbers or none. `streak` and `attended` are `null` whenever the
    evidence is missing or ambiguous — never `false`, never a guess.
    Absence of evidence is not evidence that somebody skipped the raid.
  * A freeze is written once. `data/seasons/<slug>/` gets the season's
    final standings, records and islands on the flip, and a guard refuses
    a second write forever after.

THE CADENCE, AND WHAT A ROW IS A SNAPSHOT OF. A row is appended for the
most recently COMPLETED raid week (`state.raid_week_label`'s Tuesday 15:00
UTC boundary), from the first bake taken after that week closed. So the
numbers are the week's closing numbers as the next bake saw them, plus the
few hours between the reset and that bake. The exact vintage of every line
is recoverable forever without carrying a timestamp in the row: git knows
which commit added the line, and this file is append-only, so `git blame`
answers "when was this written" per line for free.

SIZE. One row is ~130 bytes; the current roster ranks ~150 characters, so
a raid week costs ~19 KB and a full season ~400 KB of plain text. Under
1 MB/year at two seasons a year — smaller than a single day's
`web_data_public` bake, which this repo already commits daily.

WHO CALLS IT. `main.py` after `save_board_state` (the weekly post), and
the daily refresh workflow via `python -m guild_board.season_ledger
--append`. Both are idempotent, so whichever runs first that week writes
the row and the other does nothing. Both fail OPEN: a ledger problem must
never take down a board post or a data refresh.
"""

import argparse
import json
import logging
import os
import re
import subprocess
from datetime import date, datetime, timedelta, timezone

from guild_board import season as season_mod
from guild_board.state import raid_week_label

logger = logging.getLogger(__name__)

LEDGER_DIR = "season_ledger"
SEASONS_DIR = os.path.join("data", "seasons")
BUNDLE_DIR = "web_data_public"

COMPETITION_FILE = "competition.json"
WEEKLY_BOARD_FILE = "weekly_board.json"
RECORDS_FILE = "records_leaderboard.json"
ISLANDS_FILE = "island_completion.json"

# The three files a frozen season is made of. Written together, once.
FREEZE_FILES = ("final_standings.json", "records.json", "islands.json")

# Row field order. Fixed: a ledger read years from now should not have to
# guess what a column meant, and a stable order keeps the diff of an
# append-only file to exactly the lines that were appended.
ROW_FIELDS = ("season_slug", "week_label", "character_key",
              "rank", "score", "delta", "streak", "attended")

# name-realm, lowercase. Letters/digits, plus the apostrophe and hyphen
# real character names carry. This is a WRITE GATE, not cosmetics: the
# ledger is append-only, so a key with a newline, a path separator or a
# quote in it would be a permanent corruption of a file nothing may edit.
CHARACTER_KEY_RE = re.compile(r"^[^\W_]+(?:['’-][^\W_]+)+$", re.UNICODE)
MAX_KEY_LEN = 64


# ---------------------------------------------------------------------------
# paths and small helpers
# ---------------------------------------------------------------------------

def ledger_path(season_slug, root="."):
    """Where a season's ledger lives. One file per season, forever."""
    return os.path.join(root, LEDGER_DIR, f"{season_slug}.jsonl")


def freeze_dir(season_slug, root="."):
    return os.path.join(root, SEASONS_DIR, season_slug)


def valid_character_key(key):
    """True when `key` is a real name-realm key this file may carry."""
    if not isinstance(key, str):
        return False
    key = key.strip()
    if not key or len(key) > MAX_KEY_LEN or "-" not in key:
        return False
    if key != key.lower():
        return False
    return bool(CHARACTER_KEY_RE.match(key))


def _load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _number(value):
    """A JSON number, or None. Bools are not numbers here."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _as_utc(ts=None):
    """An instant as an aware UTC datetime — ISO string, naive or aware.

    Same tolerance `season.season_for` already offers, for the same
    reason: callers hand us stamps out of JSON as often as datetimes.
    """
    if ts is None:
        return datetime.now(timezone.utc)
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def week_to_record(now=None):
    """The most recently COMPLETED raid week's label.

    `raid_week_label` names the week currently in progress; a ledger row
    must describe a week that has finished, so this is that label minus
    seven days. Recording the in-progress week would freeze whichever
    mid-week moment happened to run first as if it were the week's result.
    """
    current = date.fromisoformat(raid_week_label(_as_utc(now)))
    return (current - timedelta(days=7)).isoformat()


def season_closing_week(season):
    """The last raid week that belongs to `season`.

    The instant before the season ends — S1 ends at the same Tuesday 15:00
    UTC reset that opens S2, so its final week is the one that closes on
    that boundary, not the one that starts on it.
    """
    ends = season.get("ends_utc")
    if not ends:
        return None
    end_dt = datetime.fromisoformat(ends.replace("Z", "+00:00"))
    return raid_week_label(end_dt - timedelta(seconds=1))


def week_belongs_to_season(week_label, season_slug):
    """True when the raid week labelled `week_label` is that season's.

    A week is attributed to the season that was live while it was being
    played — i.e. at its start. The season flip lands exactly on a reset
    boundary, so this is unambiguous by construction.
    """
    season = season_mod.season_by_slug(season_slug)
    if not season:
        return False
    start = datetime.fromisoformat(week_label).replace(
        hour=15, tzinfo=timezone.utc)
    return season_mod.season_for(start)["slug"] == season_slug


# ---------------------------------------------------------------------------
# building rows out of the delivered bundle
# ---------------------------------------------------------------------------

def _attendance_state(key, week_label, weekly_board):
    """Did this character raid that week? true / false / None.

    None is the honest seam and there are three ways to reach it: no
    roster reached the builder (so nothing is keyed at all), the week was
    logged but its details were never read, or the week is simply outside
    what the sweep covered. `false` is only returned when the sweep DID
    read that week and this character was not in it.
    """
    weekly_board = weekly_board or {}
    if not weekly_board.get("keyed_against_roster"):
        return None
    attendance = weekly_board.get("attendance")
    if attendance is None:
        return None
    weeks = attendance.get(key) or []
    if week_label in weeks:
        return True
    coverage = weekly_board.get("attendance_coverage") or {}
    if week_label in set(coverage.get("weeks_unknown") or ()):
        return None
    if week_label in set(coverage.get("weeks_scanned") or ()):
        return False
    return None


def _streak_state(key, week_label, weekly_board):
    """The attendance streak as of that week, or None.

    A streak integer is only meaningful for the week it was advanced in
    (`streaks_week`). Carrying last week's streak onto this week's row
    would be a number nobody measured.
    """
    weekly_board = weekly_board or {}
    if not weekly_board.get("keyed_against_roster"):
        return None
    if weekly_board.get("streaks_week") != week_label:
        return None
    streaks = weekly_board.get("streaks_by_key") or {}
    value = streaks.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return int(value)


def rows_for_week(competition, weekly_board=None, week_label=None,
                  season_slug=None, backfilled=False):
    """The week's ledger rows, built from the delivered bundle.

    Pure: takes loaded dicts, returns a list. The season comes from the
    bundle itself (`competition.season.slug`) unless pinned, because the
    bundle knows which season it was baked against and the clock does not
    know which season the bytes in front of it describe.

    Characters without a rank (the `unranked` list) get no row: a ledger
    of standings has nothing true to say about somebody who is not in the
    standing. Keys that fail the write gate are dropped and counted, never
    repaired.
    """
    competition = competition or {}
    season_slug = season_slug or ((competition.get("season") or {}).get("slug"))
    if not season_slug:
        raise ValueError("no season slug in the bundle and none pinned — "
                         "refusing to file rows under a guessed season")
    if not week_label:
        raise ValueError("week_label is required — a row without a week is "
                         "not a ledger entry")

    rows, seen, rejected = [], set(), []
    for char in competition.get("characters") or []:
        key = (char or {}).get("key")
        rank, score = _number(char.get("rank")), _number(char.get("score"))
        if rank is None or score is None:
            continue
        if not valid_character_key(key):
            rejected.append(key)
            continue
        if key in seen:
            # Two rows for one key in one week would make the ledger
            # ambiguous forever. The bundle should never do this; if it
            # does, the first one stands and the collision is reported.
            rejected.append(key)
            continue
        seen.add(key)
        row = {
            "season_slug": season_slug,
            "week_label": week_label,
            "character_key": key,
            "rank": int(rank),
            "score": score,
            "delta": _number(char.get("delta_week")),
            "streak": _streak_state(key, week_label, weekly_board),
            "attended": _attendance_state(key, week_label, weekly_board),
        }
        if backfilled:
            # Reconstructed from a git snapshot rather than written by the
            # run that lived through the week. Marked so no reader ever
            # mistakes a reconstruction for a contemporaneous record.
            row["backfilled"] = True
        rows.append(row)
    if rejected:
        logger.warning("season ledger: %d character(s) skipped — unusable or "
                       "duplicate key: %s", len(rejected), rejected[:5])
    rows.sort(key=lambda r: (r["rank"], r["character_key"]))
    return rows


# ---------------------------------------------------------------------------
# reading and appending
# ---------------------------------------------------------------------------

def read_rows(path):
    """Every row in a ledger file, in the order it was written.

    A malformed line is skipped and reported, never dropped from disk: the
    file is append-only, so repairing it here would be the one thing this
    module is not allowed to do.
    """
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for number, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("season ledger: %s line %d is not JSON — "
                                   "skipped (the file is not rewritten)",
                                   path, number)
    except (FileNotFoundError, OSError):
        return []
    return rows


def written_keys(path):
    """The `(season_slug, week_label, character_key)` triples already on
    file — the identity idempotency is enforced on."""
    return {
        (row.get("season_slug"), row.get("week_label"), row.get("character_key"))
        for row in read_rows(path)
    }


def _encode(row):
    ordered = {field: row[field] for field in ROW_FIELDS if field in row}
    for extra in row:
        if extra not in ordered:
            ordered[extra] = row[extra]
    return json.dumps(ordered, separators=(",", ":"), ensure_ascii=False)


def append_rows(rows, path):
    """Append the rows that are not already on file. Returns how many.

    This is the whole idempotency contract: re-running a week rewrites
    nothing and appends nothing new, so every workflow can call it on
    every run without anybody coordinating who writes first.
    """
    if not rows:
        return 0
    existing = written_keys(path)
    fresh = []
    for row in rows:
        ident = (row.get("season_slug"), row.get("week_label"),
                 row.get("character_key"))
        if ident in existing:
            continue
        existing.add(ident)
        fresh.append(row)
    if not fresh:
        return 0
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        for row in fresh:
            f.write(_encode(row) + "\n")
    return len(fresh)


def load_bundle(bundle_dir=BUNDLE_DIR, root="."):
    """The two delivered files a ledger row is built from."""
    base = os.path.join(root, bundle_dir)
    return (_load_json(os.path.join(base, COMPETITION_FILE), {}) or {},
            _load_json(os.path.join(base, WEEKLY_BOARD_FILE), {}) or {})


def append_for_run(root=".", bundle_dir=BUNDLE_DIR, now=None, week_label=None,
                   competition=None, weekly_board=None, backfilled=False):
    """Append the completed raid week's rows. The entry point every
    workflow calls.

    Returns a small summary dict (never raises for ordinary trouble): the
    ledger is a record of the run, not a precondition of it, so a missing
    bundle or an unwritable path is logged and reported, not thrown.
    """
    if competition is None or weekly_board is None:
        competition, weekly_board = load_bundle(bundle_dir, root)
    season_slug = (competition.get("season") or {}).get("slug")
    if not season_slug:
        logger.warning("season ledger: no %s/%s with a season — nothing "
                       "appended", bundle_dir, COMPETITION_FILE)
        return {"appended": 0, "reason": "no bundle"}

    label = week_label or week_to_record(now)
    if not week_belongs_to_season(label, season_slug):
        # The bundle has already been rebaked against the NEXT season while
        # the week being recorded still belongs to the old one — the two
        # hours around a season flip. Filing those numbers under either
        # season would be a lie; the closing week is written by the freeze,
        # from a bundle of the right vintage.
        logger.warning("season ledger: week %s does not belong to %s — "
                       "refusing to file it (season flip; the freeze writes "
                       "the closing week)", label, season_slug)
        return {"appended": 0, "reason": "week outside season",
                "week_label": label, "season_slug": season_slug}

    rows = rows_for_week(competition, weekly_board, week_label=label,
                         season_slug=season_slug, backfilled=backfilled)
    path = ledger_path(season_slug, root)
    try:
        appended = append_rows(rows, path)
    except OSError as exc:
        logger.warning("season ledger: could not append to %s: %s", path, exc)
        return {"appended": 0, "reason": "unwritable", "path": path}
    logger.info("season ledger: %s week %s — %d row(s) appended (%d built)",
                season_slug, label, appended, len(rows))
    return {"appended": appended, "built": len(rows), "path": path,
            "week_label": label, "season_slug": season_slug}


# ---------------------------------------------------------------------------
# the season-end freeze — written once, never rewritten
# ---------------------------------------------------------------------------

def is_frozen(season_slug, root="."):
    """True when any part of this season's freeze already exists."""
    base = freeze_dir(season_slug, root)
    return any(os.path.exists(os.path.join(base, name))
               for name in FREEZE_FILES)


def _vintage_problems(competition, records, islands, season_slug):
    """Do these three files actually describe `season_slug`?

    The guard that makes an automatic freeze safe. `competition.json` and
    `island_completion.json` name their season outright. `records_
    leaderboard.json` does not, so it is dated by `based_on` — the board
    state it was built from — and that instant must fall in the season
    being frozen. Freezing a rebaked Season 2 ladder into Season 1's grave
    is the one failure this whole design cannot recover from: the file is
    written once and read as final forever.
    """
    problems = []
    comp_slug = ((competition or {}).get("season") or {}).get("slug")
    if comp_slug != season_slug:
        problems.append(f"{COMPETITION_FILE} is {comp_slug!r}")
    isl_slug = (islands or {}).get("season_slug")
    if isl_slug != season_slug:
        problems.append(f"{ISLANDS_FILE} is {isl_slug!r}")
    based_on = (records or {}).get("based_on")
    if not based_on:
        problems.append(f"{RECORDS_FILE} carries no based_on to date it by")
    else:
        try:
            dated = season_mod.season_for(based_on)["slug"]
        except (ValueError, AttributeError):
            problems.append(f"{RECORDS_FILE} based_on {based_on!r} is unreadable")
        else:
            if dated != season_slug:
                problems.append(f"{RECORDS_FILE} is dated {dated!r}")
    return problems


def build_freeze(competition, records, islands, season_slug, frozen_at=None):
    """The three frozen payloads. Pure — no file is touched here.

    Every payload is the delivered layer verbatim under a `source` block,
    plus the season and the instant it was struck. Verbatim on purpose: a
    frozen season should read exactly like the live one did on its last
    day, not like a summary somebody wrote afterwards.
    """
    season = season_mod.season_by_slug(season_slug) or {"slug": season_slug}
    frozen_at = frozen_at or datetime.now(timezone.utc).isoformat()
    stamp = {
        "schema_version": 1,
        "season": {"slug": season_slug,
                   "name": season.get("name"),
                   "starts_utc": season.get("starts_utc"),
                   "ends_utc": season.get("ends_utc")},
        "frozen_at": frozen_at,
        "final": True,
    }
    standings = dict(stamp)
    standings["source"] = {
        "based_on": (competition or {}).get("based_on"),
        "generated_at": (competition or {}).get("generated_at"),
        "week_baseline_from": (competition or {}).get("week_baseline_from"),
        "file": f"{BUNDLE_DIR}/{COMPETITION_FILE}",
    }
    standings["closing_week"] = season_closing_week(season)
    standings["character_count"] = (competition or {}).get("character_count")
    standings["ranked_count"] = (competition or {}).get("ranked_count")
    standings["guild_standing"] = (records or {}).get("standing") or {}
    standings["characters"] = [
        {"rank": c.get("rank"), "key": c.get("key"), "name": c.get("name"),
         "realm": c.get("realm"), "class": c.get("class"), "spec": c.get("spec"),
         "role": c.get("role"), "score": c.get("score"),
         "ranks": c.get("ranks") or {}}
        for c in sorted((competition or {}).get("characters") or [],
                        key=lambda c: (c.get("rank") or 10 ** 9))
        if c.get("rank") is not None and c.get("key")
    ]

    frozen_records = dict(stamp)
    frozen_records["source"] = {"based_on": (records or {}).get("based_on"),
                                "generated_at": (records or {}).get("generated_at"),
                                "file": f"{BUNDLE_DIR}/{RECORDS_FILE}"}
    frozen_records["records"] = records or {}

    frozen_islands = dict(stamp)
    frozen_islands["source"] = {"generated_at": (islands or {}).get("generated_at"),
                                "file": f"{BUNDLE_DIR}/{ISLANDS_FILE}"}
    frozen_islands["islands"] = islands or {}

    return {"final_standings.json": standings,
            "records.json": frozen_records,
            "islands.json": frozen_islands}


def freeze_season(season_slug, root=".", bundle_dir=BUNDLE_DIR, source_rev=None,
                  competition=None, records=None, islands=None, frozen_at=None,
                  append_closing_week=True):
    """Write `data/seasons/<slug>/` once. Refuses to overwrite. Ever.

    Raises FileExistsError when the freeze already exists and ValueError
    when the sources are the wrong season. Both are refusals, not
    failures: the caller decides whether that is fatal (a producer running
    `--freeze` wants to hear it) or fine (the automatic flip check, where
    "already frozen" is the normal case every day after the flip).
    """
    if is_frozen(season_slug, root):
        raise FileExistsError(
            f"{freeze_dir(season_slug, root)} already holds a freeze. A "
            f"frozen season is written ONCE and never rewritten — if it is "
            f"genuinely wrong, delete it in a reviewed commit and rerun.")

    if competition is None or records is None or islands is None:
        loaded = _read_sources(root, bundle_dir, source_rev)
        competition = competition if competition is not None else loaded[0]
        records = records if records is not None else loaded[1]
        islands = islands if islands is not None else loaded[2]

    problems = _vintage_problems(competition, records, islands, season_slug)
    if problems:
        raise ValueError(
            f"refusing to freeze {season_slug} from sources of the wrong "
            f"vintage: {'; '.join(problems)}. Freeze from a pre-flip commit "
            f"instead: --freeze {season_slug} --source-rev <sha>.")

    payloads = build_freeze(competition, records, islands, season_slug, frozen_at)
    base = freeze_dir(season_slug, root)
    os.makedirs(base, exist_ok=True)
    written = []
    for name in FREEZE_FILES:
        path = os.path.join(base, name)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payloads[name], f, indent=2, ensure_ascii=False)
            f.write("\n")
        written.append(path)

    closing = None
    if append_closing_week:
        # The season's LAST raid week can only be recorded from a bundle of
        # the old season's vintage — by the time the next scheduled run
        # comes round, the bake has moved to the new season. The freeze is
        # holding exactly such a bundle, so it writes that week here or
        # nobody ever does.
        season = season_mod.season_by_slug(season_slug) or {}
        label = season_closing_week(season) if season.get("ends_utc") else None
        if label:
            rows = rows_for_week(competition, None, week_label=label,
                                 season_slug=season_slug)
            appended = append_rows(rows, ledger_path(season_slug, root))
            closing = {"week_label": label, "appended": appended}
    logger.info("season %s frozen: %s", season_slug, ", ".join(written))
    return {"season_slug": season_slug, "written": written, "closing_week": closing}


def previous_season_slug(root="."):
    """The season the last run wrote a ledger row for, or None.

    Read out of the ledger itself rather than a second state file: the
    ledger is already the append-only record of what has been written, and
    a separate "last season I saw" file would be a second thing to keep in
    sync with it.
    """
    base = os.path.join(root, LEDGER_DIR)
    latest, latest_week = None, None
    try:
        names = sorted(os.listdir(base))
    except (FileNotFoundError, OSError):
        return None
    for name in names:
        if not name.endswith(".jsonl"):
            continue
        slug = name[: -len(".jsonl")]
        weeks = [row.get("week_label") for row in read_rows(os.path.join(base, name))
                 if row.get("week_label")]
        if not weeks:
            continue
        newest = max(weeks)
        if latest_week is None or newest > latest_week:
            latest, latest_week = slug, newest
    return latest


def ended_seasons(root=".", now=None):
    """Seasons that have ended AND that this ledger actually recorded.

    A season nobody kept a ledger for is not this module's to freeze; a
    season with rows is one the pipeline lived through, so its finals are
    ours to write down.
    """
    moment = _as_utc(now)
    ended = []
    for season in season_mod.SEASONS:
        ends = season.get("ends_utc")
        if not ends or _as_utc(ends) > moment:
            continue
        slug = season["slug"]
        if os.path.exists(ledger_path(slug, root)):
            ended.append(slug)
    return ended


def maybe_freeze_on_flip(root=".", bundle_dir=BUNDLE_DIR, now=None,
                         allow_git=True):
    """Freeze an ended season the first time a run notices it ended.

    The trigger is "ended, recorded, and not yet frozen" rather than "this
    run's season differs from last run's". Those coincide on the flip
    itself, but only the first one SELF-HEALS: if the flip-day run cannot
    find sources of the right vintage, the very next row appended for the
    new season would make a "did the season change since last time?" test
    answer no forever, and the old season would never be frozen at all.

    On the first run after a flip the working bundle has usually already
    been rebaked against the new season, so the sources are re-read from
    the last commit whose bake still reported the old one. Fails OPEN and
    loudly: no freeze is ever written from doubtful bytes, and a data
    refresh is never taken down by one.
    """
    ended = ended_seasons(root, now)
    if not ended:
        return {"frozen": False, "reason": "no flip",
                "season_slug": previous_season_slug(root)}
    pending = [slug for slug in ended if not is_frozen(slug, root)]
    if not pending:
        return {"frozen": False, "reason": "already frozen",
                "season_slug": ended[-1]}
    if len(pending) > 1:
        logger.info("season ledger: %d ended seasons await a freeze (%s); "
                    "writing the oldest, the next run takes the next",
                    len(pending), ", ".join(pending))
    slug = pending[0]

    attempts = [None]
    if allow_git:
        rev = find_season_rev(slug, root)
        if rev:
            attempts.append(rev)
    last_error = None
    for rev in attempts:
        try:
            result = freeze_season(slug, root=root, bundle_dir=bundle_dir,
                                   source_rev=rev)
        except (FileExistsError, ValueError, OSError) as exc:
            last_error = exc
            continue
        result["frozen"] = True
        result["source_rev"] = rev
        return result
    logger.warning(
        "season ledger: %s ended and no source of the right vintage was "
        "found to freeze it from (%s). Nothing was written; this will be "
        "retried on every run. To resolve it by hand: python -m guild_board."
        "season_ledger --freeze %s --source-rev <pre-flip sha>",
        slug, last_error, slug)
    return {"frozen": False, "reason": "no clean source",
            "season_slug": slug, "error": str(last_error)}


# ---------------------------------------------------------------------------
# reading old bakes out of git — for the freeze's fallback and the backfill
# ---------------------------------------------------------------------------

def _git(args, root=".", binary=False):
    """Read-only git. Returns None instead of raising: every caller here
    has a working answer for "git could not tell me"."""
    try:
        out = subprocess.run(["git", "-C", root] + list(args),
                             capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    return out.stdout if binary else out.stdout.decode("utf-8", "replace")


def git_show_json(rev, path, root="."):
    """A JSON blob as it stood at `rev`, or None."""
    raw = _git(["show", f"{rev}:{path}"], root, binary=True)
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def competition_history(root=".", limit=200, rev="HEAD"):
    """[(sha, committed_at)] for every commit that touched the bundle's
    competition.json, newest first."""
    path = f"{BUNDLE_DIR}/{COMPETITION_FILE}"
    out = _git(["log", rev, f"--max-count={int(limit)}", "--format=%H %cI",
                "--", path], root)
    if not out:
        return []
    history = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2:
            history.append((parts[0], parts[1]))
    return history


def find_season_rev(season_slug, root=".", limit=200):
    """The newest commit whose bake still reported `season_slug` — i.e.
    the LAST bake of that season, which is what a freeze must be built
    from."""
    for sha, _when in competition_history(root, limit):
        blob = git_show_json(sha, f"{BUNDLE_DIR}/{COMPETITION_FILE}", root)
        if blob and ((blob.get("season") or {}).get("slug")) == season_slug:
            return sha
    return None


def _read_sources(root, bundle_dir, source_rev=None):
    """The three freeze inputs, from the working tree or from a git rev."""
    names = (COMPETITION_FILE, RECORDS_FILE, ISLANDS_FILE)
    if source_rev:
        return tuple(git_show_json(source_rev, f"{BUNDLE_DIR}/{name}", root) or {}
                     for name in names)
    base = os.path.join(root, bundle_dir)
    return tuple(_load_json(os.path.join(base, name), {}) or {} for name in names)


# ---------------------------------------------------------------------------
# the backfill — the weeks git already holds, marked as reconstructions
# ---------------------------------------------------------------------------

def _bake_instant(competition, committed_at):
    """When a bake's numbers were true: the bundle's own `based_on`, and
    the commit date only as a fallback."""
    stamp = (competition or {}).get("based_on") or committed_at
    try:
        return _as_utc(str(stamp))
    except ValueError:
        return None


def plan_backfill(root=".", limit=400, now=None, rev="HEAD"):
    """Which weeks git can honestly reconstruct, and from which commit.

    A week is reconstructed from the FIRST bake taken after it closed and
    within the following week — the same snapshot the live writer would
    have taken had it existed then. A week with no such bake gets no rows:
    the 2026-08-12→08-15 hole in the history stays a hole. Nothing is
    interpolated, ever.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = week_to_record(now)
    candidates = []
    for sha, committed_at in competition_history(root, limit, rev):
        blob = git_show_json(sha, f"{BUNDLE_DIR}/{COMPETITION_FILE}", root)
        if not blob:
            continue
        when = _bake_instant(blob, committed_at)
        if when is None:
            continue
        candidates.append((when, sha, blob))
    candidates.sort(key=lambda item: item[0])

    plan = {}
    for when, sha, blob in candidates:
        slug = (blob.get("season") or {}).get("slug")
        if not slug:
            continue
        # The week this bake is the first post-close view of.
        label = week_to_record(when)
        if label > cutoff:
            continue
        closed = datetime.fromisoformat(label).replace(
            hour=15, tzinfo=timezone.utc) + timedelta(days=7)
        if not (closed <= when < closed + timedelta(days=7)):
            continue        # more than a week stale: not this week's close
        if not week_belongs_to_season(label, slug):
            continue        # a rebaked bundle from the far side of a flip
        plan.setdefault((slug, label), {"season_slug": slug,
                                        "week_label": label,
                                        "sha": sha,
                                        "based_on": when.isoformat(),
                                        "bundle": blob})
    return [plan[k] for k in sorted(plan)]


def backfill(root=".", limit=400, now=None, dry_run=False, rev="HEAD"):
    """Write every week git can reconstruct, marked `backfilled: true`."""
    summary = {"weeks": [], "appended": 0, "skipped_weeks": 0}
    for entry in plan_backfill(root, limit, now, rev):
        rows = rows_for_week(entry["bundle"], None,
                             week_label=entry["week_label"],
                             season_slug=entry["season_slug"],
                             backfilled=True)
        appended = 0 if dry_run else append_rows(
            rows, ledger_path(entry["season_slug"], root))
        if not dry_run and not appended:
            summary["skipped_weeks"] += 1
        summary["appended"] += appended
        summary["weeks"].append({"season_slug": entry["season_slug"],
                                 "week_label": entry["week_label"],
                                 "sha": entry["sha"][:12],
                                 "based_on": entry["based_on"],
                                 "rows": len(rows),
                                 "appended": appended})
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="The season ledger: append this week's rows, freeze a "
                    "finished season, or backfill from git history.")
    parser.add_argument("--root", default=".", help="Repo root (default: .)")
    parser.add_argument("--bundle", default=BUNDLE_DIR,
                        help=f"Delivered bundle directory (default: {BUNDLE_DIR})")
    parser.add_argument("--append", action="store_true",
                        help="Append the completed raid week's rows (default "
                             "action when nothing else is asked for)")
    parser.add_argument("--week", help="Pin the raid-week label to append")
    parser.add_argument("--freeze", metavar="SLUG",
                        help="Write data/seasons/SLUG/ once. Refuses to "
                             "overwrite an existing freeze.")
    parser.add_argument("--source-rev",
                        help="Freeze from the bundle as it stood at this git "
                             "rev (use a pre-flip commit)")
    parser.add_argument("--backfill", action="store_true",
                        help="Reconstruct past weeks from git history, marked "
                             "backfilled: true")
    parser.add_argument("--no-flip-check", action="store_true",
                        help="Skip the automatic season-flip freeze")
    parser.add_argument("--dry-run", action="store_true",
                        help="Say what would be written; write nothing")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s")

    if args.freeze:
        try:
            result = freeze_season(args.freeze, root=args.root,
                                   bundle_dir=args.bundle,
                                   source_rev=args.source_rev)
        except (FileExistsError, ValueError) as exc:
            print(f"REFUSED: {exc}")
            return 2
        print(f"froze {result['season_slug']}: "
              f"{', '.join(os.path.relpath(p, args.root) for p in result['written'])}")
        if result.get("closing_week"):
            print(f"closing week {result['closing_week']['week_label']}: "
                  f"{result['closing_week']['appended']} row(s) appended")
        return 0

    if args.backfill:
        summary = backfill(args.root, now=None, dry_run=args.dry_run)
        for week in summary["weeks"]:
            print(f"{week['season_slug']} {week['week_label']}: "
                  f"{week['rows']} row(s) from {week['sha']} "
                  f"(based_on {week['based_on']}) -> +{week['appended']}")
        print(f"{summary['appended']} row(s) appended"
              f"{' (dry run)' if args.dry_run else ''}")
        return 0

    if not args.no_flip_check:
        flip = maybe_freeze_on_flip(args.root, args.bundle)
        if flip.get("frozen"):
            print(f"season {flip['season_slug']} frozen "
                  f"({flip.get('source_rev') or 'working tree'})")

    if args.dry_run:
        competition, weekly = load_bundle(args.bundle, args.root)
        label = args.week or week_to_record()
        slug = (competition.get("season") or {}).get("slug")
        rows = rows_for_week(competition, weekly, week_label=label,
                             season_slug=slug) if slug else []
        path = ledger_path(slug, args.root) if slug else "?"
        already = written_keys(path) if slug else set()
        new = [r for r in rows if (r["season_slug"], r["week_label"],
                                   r["character_key"]) not in already]
        print(f"{slug} week {label}: {len(rows)} row(s) built, "
              f"{len(new)} would be appended to {path}")
        return 0

    result = append_for_run(root=args.root, bundle_dir=args.bundle,
                            week_label=args.week)
    print(f"{result.get('season_slug')} week {result.get('week_label')}: "
          f"{result['appended']} row(s) appended"
          + (f" ({result['reason']})" if result.get("reason") else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

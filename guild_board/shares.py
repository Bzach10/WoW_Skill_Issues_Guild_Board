"""THE SHARES LEDGER — the rate card, computed weekly, per ACCOUNT.

THE RULE, and everything falls out of it
----------------------------------------
    PAY THE DEED, NEVER THE RANK.

A published rate card, identical for every hand, paid for a thing you did.
Your payout never depends on another member's number. Streaks multiply what
you *did*; they never pay you for nothing.

The ladder is explicitly NOT a faucet. `characters[].score`, `.rank`,
`.ranks.*`, `.top5`, `rankings.*` and `records_leaderboard.standing` set
your bounty. They may never set your wallet. `LADDER_FIELDS` names them and
`tests/test_shares.py::test_the_ladder_cannot_move_a_single_share` proves
it by MUTATION: every one of those fields is scrambled in the input bundle
and the emitted ledger has to come out byte-identical.

THE LAWS (each one is a test)
-----------------------------
1. **Real numbers only.** A deed that cannot be measured in the delivered
   bundle pays ZERO and records WHY. Nothing is estimated, back-filled or
   assumed. A loop with no data is a stated seam, never a zero pretending
   to be a measurement.
2. **The account is the unit.** Every cap in the rate card is per
   `account_id`, summed across every character signed under it. Alts change
   WHICH character earns; they never change HOW MUCH. An unsigned character
   earns nothing — absence from `articles.json` is the signal.
3. **Every share cites its deed.** A ledger row carries `deed_ref`: the run
   id, the boss, the week label, the record — the thing that paid it. A
   share with no citation cannot be written, because `row_id` is derived
   from the citation.
4. **Append-only, and a deed pays once.** `row_id` is a deterministic
   digest of (week, account, loop, deed_ref). Re-running a week cannot
   double-pay: the rows already in the ledger are recognised and skipped.
5. **Keys, never bare names.** Two roster characters are called Beroben.
   Every faucet resolves to a `name-realm` character key through the roster
   index; a name that will not resolve ships as a SEAM, unpaid, and is
   counted in the emitted words.
6. **Opaque.** The public projection carries the opaque `account_id`, the
   character keys and the numbers. No Discord id, ever —
   `articles.assert_opaque` runs on the bytes before they are written.

WHAT IS AND IS NOT COMPUTED TODAY
---------------------------------
Loops carry a TIER. T0 = measurable in the delivered bundle today. T1 = the
pipeline computes it and now delivers it (I4b-2). T2 = a new public pull
(I4b-8 owns it). T3 = blocked on a system that does not exist.

Only T0 and T1 loops pay. Every other loop is in the rate card with
`pays: False` and a `reason` string that ships to the site, because a loop
that quietly vanished is indistinguishable from a loop nobody thought of.
**PvP pays nothing until seats are authenticated** — the Worker's own source
says seat identity is a client-typed roster slug with no auth, so a share
paid from `/record` is a two-tab exploit, not a balance question.

WHAT THIS MODULE IS NOT
-----------------------
Pure. No network, no clock of its own, no file I/O. `scripts/refresh_shares.py`
is the shell that loads the bundle, calls `compute_week`, appends to the
ledger and writes the projection.
"""

import hashlib
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from guild_board.config import index_roster_by_name, resolve_character_key

SCHEMA_VERSION = 1

# Bump on ANY change to a rate, a cap, a source or a loop's paying status.
# Every ledger row records the version that paid it, so a rate change never
# silently rewrites history — the old rows keep saying what they were paid
# under.
RATE_CARD_VERSION = 1

CURRENCY = "shares"

THE_RULE = "PAY THE DEED, NEVER THE RANK."

# The ladder. Named here so the gate can scramble them and prove the ledger
# does not move. `parse`/`percentile` are on the list because the ticket's
# own gate names them: a percentile is a rank wearing a threshold's clothes.
LADDER_FIELDS = ("score", "rank", "ranks", "top5", "rankings", "parse",
                 "percentile", "standing", "bounty", "scores_by_role",
                 "delta_week", "delta_day")

# A headline record whose unit is a percentile is the ladder wearing a
# headline. THE PRESS pays for being NAMED, never for a percentile.
PRESS_EXCLUDED_UNITS = ("percentile",)
PRESS_EXCLUDED_BEATS = ("best_dps_parse", "best_hps_parse")

# streak multiplier: x(1 + min(streak, cap)/divisor) -> max x1.4
STREAK_CAP = 8
STREAK_DIVISOR = 20


class UnknownLoop(ValueError):
    """A deed was offered against a loop that is not on the rate card.

    Refused rather than paid at some default, because an unknown loop is
    either a typo (which would pay nothing and look like it paid) or a new
    faucet somebody added without publishing its rate. Both must stop.
    """


# ---------------------------------------------------------------------------
# THE RATE CARD — data, not code
# ---------------------------------------------------------------------------
#
# rate       what one deed pays TODAY. Zero for a loop that cannot be
#            measured yet; `deferred_rate` keeps the designed rate so the
#            number is not lost when the blocker clears.
# cap        the most this loop may pay ONE ACCOUNT in one week. None means
#            no weekly cap (the deed is naturally rare or finite).
# tier       T0/T1 measurable now; T2/T3 not.
# pays       False -> the loop is published, priced at zero, and says why.

RATE_CARD = {
    "version": RATE_CARD_VERSION,
    "currency": CURRENCY,
    "rule": THE_RULE,
    "unit": "account",
    "streak_multiplier": {
        "formula": "x (1 + min(streak, 8) / 20)",
        "streak_cap": STREAK_CAP,
        "divisor": STREAK_DIVISOR,
        "max": 1.4,
        "source": "weekly_board.streaks_by_key",
        "note": ("It never pays you for nothing. It makes what you DID worth "
                 "up to 40% more."),
    },
    "never_a_faucet": list(LADDER_FIELDS),
    "loops": (
        {
            "id": "key_log",
            "number": 1,
            "name": "THE KEY LOG",
            "deed": "timed a mythic+ key",
            "rate": 2,
            "per": "timed key",
            "cap": 8,
            "tier": "T1",
            "pays": True,
            "source": "competition.characters[].recent_runs[] "
                      "(timed, completed_at inside the week)",
            "reason": None,
            "note": ("Flat at every level: a +10 pays what a +21 pays. "
                     "49.5% of this guild's timed runs are +12 or below, and "
                     "a card that scales with level pays the top 10% and "
                     "calls it competition."),
        },
        {
            "id": "five_aboard",
            "number": 2,
            "name": "THE FIVE ABOARD",
            "deed": "brought guildmates",
            "rate": 0,
            "deferred_rate": 1,
            "per": "guildmate in the run, max 4 per run",
            "cap": 8,
            "tier": "T2",
            "pays": False,
            "source": "mythic-plus/run-details?id=<keystone_run_id> -> "
                      "roster[].guild.name",
            "reason": ("Needs a per-run public fan-out to Raider.io's "
                       "run-details endpoint, which is lane I4b-8's ticket "
                       "(deduped by keystone_run_id, volume ledgered under "
                       "300 requests/week). This lane does no network I/O, so "
                       "it pays zero rather than guessing at a roster it has "
                       "not read."),
        },
        {
            "id": "lower_deck",
            "number": 3,
            "name": "THE LOWER DECK",
            "deed": "went down to help someone",
            "rate": 0,
            "deferred_rate": 3,
            "per": "run below your own best, with a guildmate below you",
            "cap": 6,
            "tier": "T2",
            "pays": False,
            "source": "run-details roster[] + best_runs[].level",
            "reason": ("Same blocker as THE FIVE ABOARD: the run's five-person "
                       "roster is only readable through run-details, owned by "
                       "I4b-8."),
        },
        {
            "id": "first_through_the_door",
            "number": 4,
            "name": "FIRST THROUGH THE DOOR",
            "deed": "took a lane record",
            "rate": 5,
            "per": "dungeon lane taken",
            "cap": None,
            "tier": "T0",
            "pays": True,
            "source": "competition.key_records.by_dungeon[].key, compared "
                      "against the previous week's holders in the ledger",
            "reason": None,
            "note": ("Eight doors, one holder each. Naturally rare, so no "
                     "weekly cap. The FIRST computed week pays nothing here: "
                     "with no previous holder recorded, every one of the eight "
                     "lanes would read as newly taken. That is a stated seam, "
                     "not a zero."),
        },
        {
            "id": "raid_night",
            "number": 5,
            "name": "THE RAID NIGHT",
            "deed": "were in the pulls",
            "rate": 2,
            "per": "raid week attended",
            "cap": 4,
            "tier": "T1",
            "pays": True,
            "source": "weekly_board.attendance{character_key: [week labels]}",
            "reason": None,
            "note": ("The FLOOR, not the income — deliberately the smallest "
                     "per-hour rate on the card. SEAM: attendance resolves to "
                     "WEEKS, not nights, so one week pays once (2) and the "
                     "cap of 4 (two nights) is unreachable from this source. "
                     "Per-night attendance would need the report-level sweep, "
                     "not the week roll-up."),
        },
        {
            "id": "first_blood",
            "number": 6,
            "name": "FIRST BLOOD",
            "deed": "a boss died for the first time",
            "rate": 6,
            "per": "boss, to every hand in the kill week",
            "cap": None,
            "tier": "T1",
            "pays": True,
            "source": "island_completion.raid.islands[].first_kill_at inside "
                      "the week + weekly_board.attendance for that week",
            "reason": None,
            "note": ("The one payout the guild earns together, and it is "
                     "finite — it cannot be farmed, only progressed. No weekly "
                     "cap because the season itself is the cap."),
        },
        {
            "id": "the_pot",
            "number": 7,
            "name": "THE POT",
            "deed": "beat your own past self",
            "rate": 4,
            "per": "week",
            "cap": 4,
            "tier": "T0",
            "pays": True,
            "source": "weekly_board.improvement.{dps,hps}[].name (delta > 0)",
            "reason": None,
            "note": ("The only faucet whose opponent is YOU. It reads the "
                     "improvement pair the board already publishes — your late "
                     "parse against your own early one — never a percentile "
                     "against the field. This is what replaces a parse "
                     "threshold, which would be a rank in a threshold's "
                     "clothes."),
        },
        {
            "id": "a_warrant",
            "number": 8,
            "name": "A WARRANT",
            "deed": "cleared something the wall posted",
            "rate": 0,
            "deferred_rate": 6,
            "per": "warrant cleared",
            "cap": 6,
            "tier": "T3",
            "pays": False,
            "source": "the wanted wall's own posted-warrant ledger",
            "reason": ("MEASURED: the wall does not persist what it posted. "
                       "guild_board/wanted.py is a pure renderer over "
                       "board_state — there is no per-week record of which "
                       "warrants were up. Its three proposed sources are "
                       "already spoken for: open mythic bosses ARE "
                       "FIRST BLOOD's source and dungeon lane records ARE "
                       "FIRST THROUGH THE DOOR's, so paying this loop off "
                       "them pays the same deed twice; and "
                       "guild_achievements.trophies[] carries no per-character "
                       "holder at all (110 rows, id/name/completed_at/criteria "
                       "only), so it cannot pay a person. Zero until the wall "
                       "keeps a book."),
        },
        {
            "id": "the_press",
            "number": 9,
            "name": "THE PRESS",
            "deed": "got printed",
            "rate": 3,
            "per": "week",
            "cap": 3,
            "tier": "T0",
            "pays": True,
            "source": "recap_ribbon.beats[].subject + "
                      "records_leaderboard.headline_records[].holder + "
                      "weekly_board.roast.winner",
            "excludes": {
                "beat_kinds": list(PRESS_EXCLUDED_BEATS),
                "record_units": list(PRESS_EXCLUDED_UNITS),
                "why": ("A headline record whose unit is a PERCENTILE is the "
                        "ladder wearing a headline, and the Claim Law's gate "
                        "names `parse`. The press pays for being NAMED, once, "
                        "flat — never for where a percentile put you."),
            },
            "reason": None,
            "note": ("The roast pays for being FUNNY, which is the one contest "
                     "on this ship a bad player can win outright. Flat and "
                     "capped at one: first place and fifth place are paid the "
                     "same."),
        },
        {
            "id": "posted_bounty",
            "number": 10,
            "name": "A POSTED BOUNTY",
            "deed": "cleared a bounty another member put up",
            "rate": 0,
            "deferred_rate": None,
            "per": "whatever the poster staked",
            "cap": None,
            "tier": "T3",
            "pays": False,
            "source": "the bot's bounty ledger",
            "reason": ("The bounty ledger does not exist. Player-to-player "
                       "staking needs a write path this lane does not own and "
                       "must not invent."),
        },
        {
            "id": "the_table",
            "number": 11,
            "name": "THE TABLE",
            "deed": "won a PvP match",
            "rate": 0,
            "deferred_rate": 2,
            "per": "win",
            "cap": 5,
            "tier": "T3",
            "pays": False,
            "source": "the PvP Durable Object's /record",
            "reason": ("BLOCKED, and this is not a balance question. The "
                       "Worker's own source says seat identity is HONOUR "
                       "SYSTEM — a roster slug the client typed, no auth — so "
                       "a self-reported record is a claim, not a verified "
                       "ladder. Paying it today is a two-tab exploit: open a "
                       "room twice, type any slug into both seats, concede, "
                       "collect. PVP PAYS NOTHING UNTIL SEATS ARE "
                       "AUTHENTICATED (lane I4b-9)."),
        },
    ),
}

LOOPS_BY_ID = {loop["id"]: loop for loop in RATE_CARD["loops"]}
PAYING_LOOPS = tuple(loop["id"] for loop in RATE_CARD["loops"] if loop["pays"])

# The streak bonus is a ledger row like any other so the ledger still sums to
# the balance, but it is not a loop on the card: it multiplies, it does not
# pay a deed of its own.
STREAK_LOOP_ID = "streaks"


def loop(loop_id):
    """The rate-card entry for a loop id. Raises UnknownLoop otherwise."""
    try:
        return LOOPS_BY_ID[loop_id]
    except KeyError:
        raise UnknownLoop(
            f"'{loop_id}' is not a loop on rate card v{RATE_CARD_VERSION}. "
            f"Known loops: {', '.join(sorted(LOOPS_BY_ID))} (+ the "
            f"'{STREAK_LOOP_ID}' multiplier row). A deed offered against an "
            "unknown loop is refused, never paid at a default: an unpublished "
            "rate is not a rate."
        ) from None


def rate_for(loop_id):
    """What one deed of this loop pays today. Zero for a deferred loop."""
    return int(loop(loop_id).get("rate") or 0)


def cap_for(loop_id):
    """The per-account weekly cap, or None."""
    return loop(loop_id).get("cap")


# ---------------------------------------------------------------------------
# Time: the week window
# ---------------------------------------------------------------------------

def _as_date(value):
    """A date out of an ISO date or datetime string, or None.

    Raider.io's `completed_at` is carried VERBATIM through the contract
    ("2026-07-16T02:41:19.000Z"), so this has to survive the trailing Z and
    the milliseconds without re-stamping anything.
    """
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return None


def week_window(weekly_board):
    """(start, end, label) as dates, or (None, None, label).

    Without both boundaries "this week" is not a measurable idea and the
    whole computation refuses rather than paying against a guessed window.
    """
    week = weekly_board or {}
    return (_as_date(week.get("week_start")), _as_date(week.get("week_end")),
            week.get("week_label"))


def _in_window(value, start, end):
    when = _as_date(value)
    if when is None or start is None or end is None:
        return False
    return start <= when <= end


# ---------------------------------------------------------------------------
# Identity: the account is the unit
# ---------------------------------------------------------------------------

def accounts_from_articles(articles_projection):
    """{account_id: {"characters": [...], "main": key}} from articles.json.

    An unsigned character is simply absent. There is no "unsigned" sentinel
    to mis-read, and no pre-credited balance for a hand that has not signed.
    """
    projection = articles_projection or {}
    out = {}
    for account_id, account in (projection.get("accounts") or {}).items():
        keys = sorted(str(k) for k in (account.get("characters") or []) if k)
        if not keys:
            continue
        out[account_id] = {"characters": keys, "main": account.get("main")}
    return out


def character_owner(accounts):
    """{character key: account_id} — the reverse index the faucets pay through."""
    owner = {}
    for account_id, account in (accounts or {}).items():
        for key in account["characters"]:
            owner[key] = account_id
    return owner


# ---------------------------------------------------------------------------
# The deeds
# ---------------------------------------------------------------------------

def _deed(loop_id, character, deed_ref, detail=None):
    return {"loop": loop_id, "character": character, "deed_ref": deed_ref,
            "detail": detail}


def deeds_key_log(competition, owner, start, end):
    """Loop 1 — every timed key finished inside the week.

    Reads `recent_runs`, never `best_runs`: a dungeon best is a per-dungeon
    SEASON best and can be months old, so "did you time a key this week" is
    unanswerable from it. Reads level only to cite it; the RATE is flat.
    """
    deeds = []
    for character in (competition or {}).get("characters") or []:
        key = character.get("key")
        if key not in owner:
            continue
        for run in character.get("recent_runs") or []:
            if not run.get("timed"):
                continue
            if not _in_window(run.get("completed_at"), start, end):
                continue
            run_id = run.get("keystone_run_id")
            ref = f"run:{run_id}" if run_id is not None else (
                f"run:{key}:{run.get('short') or run.get('dungeon')}:"
                f"{run.get('completed_at')}")
            deeds.append(_deed("key_log", key, ref,
                               f"+{run.get('level')} {run.get('dungeon')}"))
    return deeds


def deeds_raid_night(weekly_board, owner, start, end):
    """Loop 5 — you were in the pulls.

    `attendance` is {character key: [week labels]}. A label inside the window
    is a raid week attended. SEAM: this is weeks, not nights.
    """
    deeds = []
    for key, labels in ((weekly_board or {}).get("attendance") or {}).items():
        if key not in owner:
            continue
        for label in sorted(set(labels or [])):
            if _in_window(label, start, end):
                deeds.append(_deed("raid_night", key, f"raid-week:{label}",
                                   f"in the pulls, week of {label}"))
    return deeds


def deeds_first_blood(island_completion, weekly_board, owner, start, end):
    """Loop 6 — a boss died for the first time, paid to every hand in the kill.

    "Every hand in the kill" is measured as every SIGNED character whose
    attendance covers the week the kill landed in. Without attendance nobody
    is paid — a first kill with no readable participant set is a seam, never
    a payout to the whole roster.
    """
    raid = ((island_completion or {}).get("raid") or {})
    attended = sorted(
        key for key, labels in ((weekly_board or {}).get("attendance") or {}).items()
        if key in owner and any(_in_window(lb, start, end) for lb in labels or [])
    )
    deeds = []
    for boss in raid.get("islands") or []:
        if not boss.get("kill_confirmed"):
            continue
        if not _in_window(boss.get("first_kill_at"), start, end):
            continue
        ref = f"first-blood:{boss.get('id')}"
        for key in attended:
            deeds.append(_deed("first_blood", key, ref, boss.get("name")))
    return deeds


def deeds_first_through_the_door(competition, owner, previous_holders):
    """Loop 4 — you took a lane record off whoever held it.

    `previous_holders` is {dungeon: character key} carried in the ledger from
    the last computed week. On the FIRST computed week it is empty and this
    pays nothing: with no prior holder every one of the eight lanes would
    read as newly taken, which would be eight fabricated records.
    """
    if not previous_holders:
        return []
    deeds = []
    for row in ((competition or {}).get("key_records") or {}).get("by_dungeon") or []:
        dungeon = row.get("dungeon")
        key = row.get("key")
        if not dungeon or key not in owner:
            continue
        was = previous_holders.get(dungeon)
        if was and was != key:
            deeds.append(_deed("first_through_the_door", key,
                               f"lane:{dungeon}:{key}",
                               f"took {dungeon} from {was}"))
    return deeds


def lane_holders(competition):
    """{dungeon: character key} — this week's record holders, for the ledger."""
    holders = {}
    for row in ((competition or {}).get("key_records") or {}).get("by_dungeon") or []:
        dungeon, key = row.get("dungeon"), row.get("key")
        if dungeon and key:
            holders[str(dungeon)] = str(key)
    return holders


def deeds_the_pot(weekly_board, owner, index, unresolved):
    """Loop 7 — you beat your own past self.

    `improvement` rows are keyed on a BARE NAME (Warcraft Logs has no realm),
    so each is resolved through the roster index and an ambiguous name is
    recorded as a seam rather than paid to whichever Beroben sorts first.
    """
    deeds = []
    seen = set()
    for role, rows in ((weekly_board or {}).get("improvement") or {}).items():
        for row in rows or []:
            try:
                delta = float(row.get("delta") or 0)
            except (TypeError, ValueError):
                delta = 0.0
            if delta <= 0:
                continue
            name = row.get("name")
            key, reason = resolve_character_key(name, index)
            if not key:
                unresolved.append({"loop": "the_pot", "name": str(name or ""),
                                   "reason": reason})
                continue
            if key not in owner or key in seen:
                continue
            seen.add(key)
            deeds.append(_deed("the_pot", key, f"improved:{key}:{role}",
                               f"beat their own {role} parse"))
    return deeds


def _press_names(recap_ribbon, records_leaderboard, weekly_board):
    """[(bare name, citation)] — everyone the week's press named.

    Percentile records are excluded on purpose: a headline whose unit is a
    percentile is the ladder wearing a headline.
    """
    named = []
    for beat in (recap_ribbon or {}).get("beats") or []:
        kind = beat.get("kind")
        if kind in PRESS_EXCLUDED_BEATS:
            continue
        if beat.get("subject"):
            named.append((beat["subject"], f"beat:{kind}"))
    for record in (records_leaderboard or {}).get("headline_records") or []:
        if record.get("unit") in PRESS_EXCLUDED_UNITS:
            continue
        if record.get("holder"):
            named.append((record["holder"], f"record:{record.get('id')}"))
    roast = (weekly_board or {}).get("roast") or {}
    if roast.get("winner"):
        named.append((roast["winner"], "roast:winner"))
    return named


def deeds_the_press(recap_ribbon, records_leaderboard, weekly_board, owner,
                    index, unresolved):
    """Loop 9 — you got printed. Flat, once, whoever you are."""
    deeds = []
    seen = set()
    for name, citation in _press_names(recap_ribbon, records_leaderboard,
                                       weekly_board):
        key, reason = resolve_character_key(name, index)
        if not key:
            unresolved.append({"loop": "the_press", "name": str(name or ""),
                               "reason": reason})
            continue
        if key not in owner or key in seen:
            continue
        seen.add(key)
        deeds.append(_deed("the_press", key, f"press:{key}:{citation}", citation))
    return deeds


# ---------------------------------------------------------------------------
# The fold: deeds -> ledger rows, per account, capped, then multiplied
# ---------------------------------------------------------------------------

def row_id(week_label, account_id, loop_id, deed_ref):
    """The row's identity, derived from its citation.

    Deterministic on purpose: it is what makes the ledger append-only in
    practice rather than by promise. Re-computing a week produces the same
    ids, so the same deed can never pay twice — and a row with no citation
    cannot be minted at all.
    """
    if not deed_ref:
        raise ValueError(
            "a share with no deed_ref cannot be written: every share cites "
            "the deed that paid it.")
    raw = "|".join(str(p) for p in (week_label, account_id, loop_id, deed_ref))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _round_half_up(value):
    """Deterministic rounding. Python's round() is banker's rounding, which
    would pay 0.5 differently depending on the integer beside it."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def account_streak(account, streaks_by_key):
    """An account's streak = the best of its hands'.

    The streak is "you kept showing up", and an account showed up if any of
    its characters did. Keyed on the character key, never the bare name.
    """
    best = 0
    for key in account["characters"]:
        try:
            best = max(best, int((streaks_by_key or {}).get(key) or 0))
        except (TypeError, ValueError):
            continue
    return best


def streak_multiplier(streak):
    return 1 + min(max(int(streak or 0), 0), STREAK_CAP) / STREAK_DIVISOR


def fold_deeds(deeds, accounts, owner, week_label, streaks_by_key=None):
    """Deeds -> (rows, per-account summary). Caps are per ACCOUNT.

    A deed past its loop's cap is NOT dropped: it is written with shares 0
    and `capped: true`, because a deed that vanished and a deed that paid
    nothing look identical in a total and an auditor has to be able to tell
    them apart.

    ONE CITATION, ONE PAYMENT. Deeds are deduplicated per account on
    (loop, deed_ref) before anything is paid. That is the anti-farm rule
    expressed in the citation rather than bolted on beside it: a raid week
    is cited `raid-week:<label>` and a first kill `first-blood:<boss>` with
    no character in either, so a hand who was logged on two of their own
    characters is paid for the one week and the one boss — while a timed
    key, cited by its own run id, is a genuinely separate deed every time.
    """
    by_account = {}
    seen = set()
    for deed in deeds:
        loop_id = deed["loop"]
        entry = loop(loop_id)                     # refuses an unknown loop
        if not entry["pays"]:
            continue
        account_id = owner.get(deed["character"])
        if not account_id:
            continue
        citation = (account_id, loop_id, str(deed["deed_ref"]))
        if citation in seen:
            continue
        seen.add(citation)
        by_account.setdefault(account_id, []).append(deed)

    rows, summary = [], {}
    for account_id in sorted(by_account):
        account_rows = []
        paid_by_loop = {}
        for deed in sorted(by_account[account_id],
                           key=lambda d: (d["loop"], str(d["deed_ref"]),
                                          d["character"])):
            loop_id = deed["loop"]
            rate = rate_for(loop_id)
            cap = cap_for(loop_id)
            paid = paid_by_loop.get(loop_id, 0)
            shares, capped = rate, False
            if cap is not None and paid + rate > cap:
                shares = max(cap - paid, 0)
                capped = True
            paid_by_loop[loop_id] = paid + shares
            account_rows.append({
                "row_id": row_id(week_label, account_id, loop_id,
                                 deed["deed_ref"]),
                "week": week_label,
                "account_id": account_id,
                "loop": loop_id,
                "character": deed["character"],
                "deed_ref": deed["deed_ref"],
                "detail": deed.get("detail"),
                "shares": shares,
                "capped": capped,
                "rate_card_version": RATE_CARD_VERSION,
            })

        base = sum(r["shares"] for r in account_rows)
        streak = account_streak(accounts[account_id], streaks_by_key)
        multiplier = streak_multiplier(streak)
        bonus = _round_half_up(base * multiplier) - base
        if bonus:
            account_rows.append({
                "row_id": row_id(week_label, account_id, STREAK_LOOP_ID,
                                 f"streak:{streak}"),
                "week": week_label,
                "account_id": account_id,
                "loop": STREAK_LOOP_ID,
                "character": None,
                "deed_ref": f"streak:{streak}",
                "detail": f"x{multiplier:g} on {base} earned",
                "shares": bonus,
                "capped": False,
                "rate_card_version": RATE_CARD_VERSION,
            })
        rows.extend(account_rows)
        summary[account_id] = {
            "base": base,
            "streak": streak,
            "multiplier": round(multiplier, 2),
            "streak_bonus": bonus,
            "total": base + bonus,
            "by_loop": {k: v for k, v in sorted(paid_by_loop.items()) if v},
            "capped_loops": sorted({r["loop"] for r in account_rows if r["capped"]}),
        }
    return rows, summary


# ---------------------------------------------------------------------------
# The week
# ---------------------------------------------------------------------------

def compute_week(bundle, articles_projection, roster=None, previous_holders=None):
    """One week's earn. Pure: dicts in, dicts out.

    `bundle` is the delivered layers by name: competition, weekly_board,
    island_completion, recap_ribbon, records_leaderboard.

    Returns {"available", "status", "week", "rows", "summary",
             "lane_holders", "unresolved", "seams", "accounts"}.

    Refuses (available: false, zero rows) when there is no week window or
    nobody has signed. Both are honest empties, not failures.
    """
    bundle = bundle or {}
    weekly_board = bundle.get("weekly_board") or {}
    start, end, label = week_window(weekly_board)

    accounts = accounts_from_articles(articles_projection)
    owner = character_owner(accounts)
    index = index_roster_by_name(roster)
    unresolved = []

    out = {
        "available": False,
        "status": "",
        "week": {"label": label,
                 "start": start.isoformat() if start else None,
                 "end": end.isoformat() if end else None},
        "rows": [],
        "summary": {},
        "accounts": accounts,
        "lane_holders": lane_holders(bundle.get("competition")),
        "unresolved": unresolved,
        "seams": [],
    }

    if start is None or end is None or not accounts:
        out["status"] = (
            "pending: weekly_board carries no week window, so \"this week\" is "
            "not a measurable idea. Nothing is paid against a guessed week."
            if start is None or end is None else
            "no-signatures: nobody has signed the articles, so no character is "
            "attached to an account and nothing is earned. An unsigned "
            "character earns nothing.")
        # The seams are printed even when nothing is paid — especially then.
        # An empty shelf that says WHY it is empty is the honest render.
        out["seams"] = week_seams(weekly_board, articles_projection, unresolved,
                                  previous_holders, index)
        return out

    deeds = []
    deeds += deeds_key_log(bundle.get("competition"), owner, start, end)
    deeds += deeds_raid_night(weekly_board, owner, start, end)
    deeds += deeds_first_blood(bundle.get("island_completion"), weekly_board,
                               owner, start, end)
    deeds += deeds_first_through_the_door(bundle.get("competition"), owner,
                                          previous_holders)
    deeds += deeds_the_pot(weekly_board, owner, index, unresolved)
    deeds += deeds_the_press(bundle.get("recap_ribbon"),
                             bundle.get("records_leaderboard"), weekly_board,
                             owner, index, unresolved)

    rows, summary = fold_deeds(deeds, accounts, owner, label,
                               weekly_board.get("streaks_by_key"))
    out["rows"] = rows
    out["summary"] = summary
    out["available"] = True
    out["status"] = "ok"
    out["seams"] = week_seams(weekly_board, articles_projection, unresolved,
                              previous_holders, index)
    return out


def week_seams(weekly_board, articles_projection, unresolved, previous_holders,
               index):
    """The sentences a surface must print. A seam stated is not a defect.

    These are words, not flags, because the ledger's honesty is only worth
    something if the reader can see where it stops.
    """
    projection = articles_projection or {}
    seams = []
    signed = projection.get("signed_accounts") or 0
    total = projection.get("roster_total")
    seams.append(f"{signed} of {total if total is not None else '?'} hands "
                 "have signed the articles. An unsigned character earns nothing.")

    streaks = (weekly_board or {}).get("streaks_by_key") or {}
    if index:
        seams.append(f"{len(streaks)} of {len(index)} hands carry a streak; "
                     "everyone else multiplies by x1.0.")
    if not (weekly_board or {}).get("keyed_against_roster"):
        seams.append("weekly_board was built with no roster, so attendance and "
                     "streaks are empty BECAUSE THEY COULD NOT BE BUILT — not "
                     "because nobody raided.")
    if not previous_holders:
        seams.append("No previous lane holders on record, so FIRST THROUGH THE "
                     "DOOR pays nothing this week: with nothing to compare "
                     "against, all eight lanes would read as newly taken.")
    for row in (weekly_board or {}).get("attendance_unresolved") or []:
        seams.append(f"attendance: '{row.get('name')}' is {row.get('reason')} "
                     "against the roster and is unpaid, never guessed.")
    for row in unresolved or []:
        seams.append(f"{row['loop']}: '{row['name']}' is {row['reason']} "
                     "against the roster and is unpaid, never guessed.")
    for entry in RATE_CARD["loops"]:
        if not entry["pays"]:
            seams.append(f"{entry['name']} pays 0: {entry['reason']}")
    return seams


# ---------------------------------------------------------------------------
# The ledger — append-only
# ---------------------------------------------------------------------------

def empty_ledger():
    """The ledger before the first week. An absent file IS this value."""
    return {
        "schema_version": SCHEMA_VERSION,
        "rate_card_version": RATE_CARD_VERSION,
        "generated_at": None,
        "currency": CURRENCY,
        "rule": THE_RULE,
        "weeks": [],
        "rows": [],
        # Sinks arrive later (a mailer, a round, a lantern, a posted bounty).
        # The field exists now so a balance is always earned minus spent and
        # never has to change shape to acquire a subtraction.
        "sinks": [],
        "lane_holders": {},
    }


def append_week(ledger, week, generated_at=None):
    """Append one computed week's rows. Returns (ledger, appended, skipped).

    APPEND-ONLY. Existing rows are never edited or removed; a row whose
    `row_id` is already present is skipped, so re-running a week is a no-op
    rather than a double payment. That is law 4, and it is enforced by
    construction rather than by a caller remembering.
    """
    ledger = dict(ledger or empty_ledger())
    ledger.setdefault("rows", [])
    ledger.setdefault("weeks", [])
    ledger.setdefault("sinks", [])
    ledger.setdefault("lane_holders", {})

    known = {row.get("row_id") for row in ledger["rows"]}
    appended = skipped = 0
    for row in week.get("rows") or []:
        if row["row_id"] in known:
            skipped += 1
            continue
        known.add(row["row_id"])
        ledger["rows"].append(row)
        appended += 1

    label = (week.get("week") or {}).get("label")
    if label and label not in ledger["weeks"]:
        ledger["weeks"].append(label)
    if week.get("lane_holders"):
        ledger["lane_holders"] = dict(week["lane_holders"])
    ledger["generated_at"] = generated_at or ledger.get("generated_at")
    ledger["schema_version"] = SCHEMA_VERSION
    ledger["rate_card_version"] = RATE_CARD_VERSION
    ledger["currency"] = CURRENCY
    ledger["rule"] = THE_RULE
    return ledger, appended, skipped


def balances(ledger):
    """{account_id: {"earned", "spent", "balance"}} — the ledger sum minus sinks.

    A balance is never stored: it is always the sum of citations minus the
    sum of spends, so it cannot drift away from the rows that justify it.
    """
    out = {}
    for row in (ledger or {}).get("rows") or []:
        acc = out.setdefault(row.get("account_id"),
                             {"earned": 0, "spent": 0, "balance": 0})
        acc["earned"] += int(row.get("shares") or 0)
    for sink in (ledger or {}).get("sinks") or []:
        acc = out.setdefault(sink.get("account_id"),
                             {"earned": 0, "spent": 0, "balance": 0})
        acc["spent"] += int(sink.get("shares") or 0)
    for acc in out.values():
        acc["balance"] = acc["earned"] - acc["spent"]
    out.pop(None, None)
    return out


def previous_lane_holders(ledger):
    """The lane holders recorded on the last computed week, or {}."""
    return dict((ledger or {}).get("lane_holders") or {})


# ---------------------------------------------------------------------------
# The public projection
# ---------------------------------------------------------------------------

def public_rate_card():
    """The rate card as the site prints it — every loop, including the zeros."""
    card = {k: v for k, v in RATE_CARD.items() if k != "loops"}
    card["loops"] = [dict(entry) for entry in RATE_CARD["loops"]]
    return card


def public_projection(ledger, week, articles_projection, names=None,
                      generated_at=None):
    """web_data_public/shares.json — what the site reads.

    Opaque account id, the character keys and display names signed under it,
    the balance, and THIS WEEK's earn broken out by loop with every deed that
    paid it. No Discord id, no handle, no real name: an account's face on the
    site is its main character's name, which the site already has.
    """
    ledger = ledger or empty_ledger()
    week = week or {}
    projection = articles_projection or {}
    names = names or {}

    balance_by_account = balances(ledger)
    summary = week.get("summary") or {}
    rows_by_account = {}
    for row in week.get("rows") or []:
        rows_by_account.setdefault(row["account_id"], []).append({
            "loop": row["loop"],
            "character": row["character"],
            "deed_ref": row["deed_ref"],
            "detail": row["detail"],
            "shares": row["shares"],
            "capped": row["capped"],
        })

    accounts = {}
    for account_id, account in sorted((week.get("accounts") or {}).items()):
        keys = account["characters"]
        totals = balance_by_account.get(account_id) or {
            "earned": 0, "spent": 0, "balance": 0}
        accounts[account_id] = {
            "account_id": account_id,
            "main": account.get("main"),
            "characters": keys,
            "names": [names.get(k) or _name_from_key(k) for k in keys],
            "earned": totals["earned"],
            "spent": totals["spent"],
            "balance": totals["balance"],
            "week": summary.get(account_id) or {
                "base": 0, "streak": 0, "multiplier": 1.0, "streak_bonus": 0,
                "total": 0, "by_loop": {}, "capped_loops": []},
            "deeds": rows_by_account.get(account_id) or [],
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "rate_card_version": RATE_CARD_VERSION,
        "generated_at": generated_at or ledger.get("generated_at"),
        "currency": CURRENCY,
        "rule": THE_RULE,
        "available": bool(week.get("available") and accounts),
        "status": week.get("status") or "no-signatures",
        "week": week.get("week") or {"label": None, "start": None, "end": None},
        "roster_total": projection.get("roster_total"),
        "signed_accounts": projection.get("signed_accounts") or 0,
        "signed_characters": projection.get("signed_characters") or 0,
        "weeks_computed": list(ledger.get("weeks") or []),
        "seams": list(week.get("seams") or []),
        "unresolved": list(week.get("unresolved") or []),
        "rate_card": public_rate_card(),
        "accounts": accounts,
    }


def _name_from_key(key):
    """Display name out of a `name-realm` key. The key is the identity; this
    is only what a surface prints."""
    return str(key or "").split("-", 1)[0].title()

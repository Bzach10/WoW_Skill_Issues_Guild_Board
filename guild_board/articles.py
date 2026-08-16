"""THE SHIP'S ARTICLES — the account <-> character mapping, signed by claim.

What this is
------------
Every share, every card and every board downstream is keyed on an ACCOUNT,
not on a character. This module is the only place that decides which
characters belong to which account, and it is deliberately the boring part:
pure functions over a store dict, no network, no clock of its own, no
Discord library. `scripts/refresh_articles.py` is the shell that feeds it.

THE LAWS (each one is a test in tests/test_articles.py)
------------------------------------------------------
1. **Characters are not people.** The mapping's unit is an `account_id`.
2. **The account id is OPAQUE.** It is `HMAC-SHA256(salt, discord_id)`
   truncated to 16 hex chars. The raw Discord id is never written to any
   file, never logged, and never returned in a projection. The salt is a
   secret and there is no default: without it `derive_account_id` raises,
   because an unsalted hash of a Discord id is reversible by anyone who can
   list the guild's members and hash each one. **Privacy fails CLOSED.**
3. **The roster verifies a claim.** A character not on the live roster is
   refused. A bare name that matches two roster characters (this guild has
   two Berobens and two Violences) is refused as ambiguous, never guessed.
4. **One character, one account.** First claim wins; a second account's
   claim on a signed character is refused and the refusal is logged.
   An officer `/revoke` is the only way to move it.
5. **Keys are character keys.** `name-realm`, via `guild_roster.member_key`.
   A bare name in this ledger would pay one of two real people at random.

WHO MAY DO WHAT
---------------
    /claim <character>     any member, in the claims channel; binds the
                           character to the caller's account
    /unclaim <character>   any member; releases a character they hold
    /revoke <character>    OFFICERS ONLY — honoured only when the message
                           came from an officer-locked channel, which is
                           the same authorization model config.yml already
                           uses for `announcement_channel_id`. There is no
                           roles table and no new secret.

MAIN vs ALTS
------------
The first character an account claims becomes its `main`. Unclaiming the
main promotes the oldest remaining claim. That rule is deterministic, needs
no extra command, and can be overridden later by an owner-chosen `/main`
without changing any shape here.

WHAT IS WRITTEN
---------------
`build_store()` produces the private ledger of record (accounts, the
character index, the audit log, a message watermark). `public_projection()`
produces the shipped view: character key -> {account_id, is_main}. The
projection is re-derivable from the store and carries nothing else — no
handle, no display name, no timestamp of a human action, and above all no
Discord id. `assert_opaque()` proves that on the actual bytes.
"""

import hmac
import re
from hashlib import sha256

# Only the audit trail is capped; accounts are never trimmed.
LOG_LIMIT = 500

# A member cannot spend an unbounded number of commands in one run
# (report section 5.6 item 9). Anything past this is refused and logged.
DEFAULT_MAX_COMMANDS_PER_ACCOUNT = 10

SCHEMA_VERSION = 1
ID_SCHEME = "hmac-sha256-16"

VERBS = ("claim", "unclaim", "revoke")

# `/claim Buchalter-Area-52`, `!claim buchalter`, `/CLAIM  Buchalter Area 52`.
# The leading sigil is optional so a member who types the word alone in a
# dedicated claims channel is still understood.
_COMMAND_RE = re.compile(
    r"^\s*[/!]?(claim|unclaim|revoke)\b[\s:]*(.*)$", re.IGNORECASE | re.DOTALL)

# A Discord snowflake: 17-20 digits. The opacity guard hunts for these.
_SNOWFLAKE_RE = re.compile(r"^\d{17,20}$")
_MENTION_RE = re.compile(r"<@!?\d+>")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")

# No word boundaries: the field to catch is `discord_id`, and `\bdiscord\b`
# does not match it because `_` is a word character. That near-miss is
# exactly the kind of guard that passes review and catches nothing.
_FORBIDDEN_FIELD_RE = re.compile(
    r"(?i)(discord|user_?id|author_?id|username|discriminator|email|battletag|"
    r"global_?name|snowflake)")

# The only shape an unresolved claim argument may take into the audit log.
# A refusal has to name what was attempted, but the attempt is text a member
# typed, so `/claim <@111...>` must not smuggle a Discord id into the store.
_SAFE_ARGUMENT_RE = re.compile(r"^[a-z0-9-]{1,64}$")


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

def derive_account_id(discord_id, salt):
    """The opaque account id: HMAC-SHA256(salt, discord_id)[:16].

    Raises ValueError when the salt is missing or trivially short. That is
    the point: Discord ids are enumerable for anyone who can see the guild's
    member list, so an unsalted or weakly salted digest is a rainbow table
    with extra steps. A caller with no salt must refuse to write, not fall
    back to something that merely looks opaque.
    """
    raw = str(discord_id or "").strip()
    if not raw:
        raise ValueError("cannot derive an account id from an empty discord id")
    key = (salt or "").strip()
    if len(key) < 16:
        raise ValueError(
            "ACCOUNTS_ID_SALT is missing or shorter than 16 characters. The "
            "account id must not be reversible from a guild member list; "
            "refusing to mint one.")
    return hmac.new(key.encode("utf-8"), raw.encode("utf-8"), sha256).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Parsing and resolution
# ---------------------------------------------------------------------------

def parse_command(text):
    """('claim'|'unclaim'|'revoke', argument) from a message, or None.

    Returns None for anything that is not a command, so ordinary chat in the
    channel is ignored rather than refused.
    """
    match = _COMMAND_RE.match(text or "")
    if not match:
        return None
    argument = match.group(2).strip()
    # Only the first line/token group is the character; trailing chatter
    # ("/claim Buchalter thanks!") would otherwise never resolve.
    argument = argument.splitlines()[0].strip() if argument else ""
    return match.group(1).lower(), argument


def normalize_argument(argument):
    """A typed character into the shape a roster key uses.

    Lowercased, apostrophes dropped and whitespace folded to hyphens, which
    is exactly what `_realm_slug` does to a realm: "Buchalter Area 52",
    "Buchalter-Area-52" and "buchalter-area-52" all land on the same string,
    and "Beroben Quel'Dorei" lands on "beroben-queldorei".
    """
    text = (argument or "").strip().strip("`\"'<>[]()")
    text = text.replace("'", "").replace("’", "")
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-").lower()


def bare_name_index(roster_keys):
    """{bare name: [character key, ...]} — the collision map.

    Two roster characters really are called Beroben. This index is how a
    bare-name claim gets refused as ambiguous instead of crediting one of
    two real people at random.
    """
    index = {}
    for key in roster_keys or ():
        index.setdefault(str(key).split("-", 1)[0], []).append(str(key))
    return {name: sorted(keys) for name, keys in index.items()}


def resolve_character(argument, roster_keys):
    """(character_key, reason). key is None when it did not resolve.

    reason is one of: 'ok', 'empty', 'not-on-roster', 'ambiguous'.
    """
    wanted = normalize_argument(argument)
    if not wanted:
        return None, "empty"
    roster = {str(k) for k in roster_keys or ()}
    if wanted in roster:
        return wanted, "ok"
    matches = bare_name_index(roster).get(wanted) or []
    if len(matches) == 1:
        return matches[0], "ok"
    if len(matches) > 1:
        return None, "ambiguous"
    return None, "not-on-roster"


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def empty_store():
    """The ledger before anybody has signed. Absent file == this value."""
    return {
        "schema_version": SCHEMA_VERSION,
        "id_scheme": ID_SCHEME,
        "generated_at": None,
        "accounts": {},
        "by_character": {},
        "last_message_id": None,
        "log": [],
    }


def _account(store, account_id):
    return store["accounts"].setdefault(account_id, {
        "account_id": account_id,
        "characters": [],
        "main": None,
        "claimed_at": None,
        "character_claimed_at": {},
    })


def _log(store, at, verb, account_id, character, result, reason):
    """One audit line. Carries the OPAQUE account id and nothing else about
    the human — a refusal has to be visible without being identifying.

    `account_id` is the account the line is ABOUT, which is the caller for
    every result except an accepted `revoke`: there it is the account that
    LOST the character, because that is the party an officer reading the log
    is asking after. `reason` ('revoked-by-officer') says which it is.
    """
    store["log"].append({
        "at": at,
        "verb": verb,
        "account_id": account_id,
        "character": character,
        "result": result,
        "reason": reason,
    })
    if len(store["log"]) > LOG_LIMIT:
        del store["log"][:-LOG_LIMIT]


def _drop_character(store, account_id, character):
    """Release one character and repair the account's main.

    Unclaiming the main promotes the OLDEST remaining claim, so an account
    is never left mainless while it still holds characters.
    """
    account = store["accounts"].get(account_id)
    if not account:
        return
    if character in account["characters"]:
        account["characters"].remove(character)
    account["character_claimed_at"].pop(character, None)
    store["by_character"].pop(character, None)
    if account["main"] == character:
        remaining = sorted(
            account["characters"],
            key=lambda k: (account["character_claimed_at"].get(k) or "", k))
        account["main"] = remaining[0] if remaining else None
    if not account["characters"]:
        # An account with no characters is not an account. Dropping the row
        # keeps "N of 129 hands have signed" an honest count.
        store["accounts"].pop(account_id, None)


def _sort_key(command):
    """Chronological. Discord snowflakes sort as integers, and first-claim-
    wins is only meaningful in the order the messages were actually sent."""
    try:
        return (0, int(command.get("message_id") or 0))
    except (TypeError, ValueError):
        return (1, str(command.get("message_id") or ""))


def apply_commands(store, commands, roster_keys, salt, now,
                   max_per_account=DEFAULT_MAX_COMMANDS_PER_ACCOUNT):
    """Fold Discord commands into the store. Returns (store, outcomes).

    `commands` are raw records from `discord_inputs.fetch_claim_commands`:
    {message_id, author_id, content, officer}. `author_id` is a raw Discord
    id and it is hashed on the way in — it is never stored, never logged and
    never returned.

    Messages at or below `store['last_message_id']` are skipped, so a re-run
    is idempotent and an officer's `/revoke` cannot be undone by replaying
    the original `/claim` on the next refresh. The watermark advances past
    every message considered, including refused ones.

    Outcomes are per-command dicts for the console: {verb, character,
    account_id, result, reason}. `result` is 'accepted', 'noop' or 'refused'.
    """
    store = dict(store or empty_store())
    store.setdefault("accounts", {})
    store.setdefault("by_character", {})
    store.setdefault("log", [])

    watermark = store.get("last_message_id")
    try:
        floor = int(watermark) if watermark else 0
    except (TypeError, ValueError):
        floor = 0

    roster = {str(k) for k in roster_keys or ()}
    outcomes = []
    seen_count = {}
    highest = floor

    for command in sorted(commands or [], key=_sort_key):
        try:
            message_id = int(command.get("message_id") or 0)
        except (TypeError, ValueError):
            message_id = 0
        if message_id and message_id <= floor:
            continue
        highest = max(highest, message_id)

        parsed = parse_command(command.get("content"))
        if not parsed:
            continue
        verb, argument = parsed

        try:
            account_id = derive_account_id(command.get("author_id"), salt)
        except ValueError:
            # No salt, or no author. Never mint a guessable id; the caller
            # is expected to have refused before getting here.
            raise

        seen_count[account_id] = seen_count.get(account_id, 0) + 1
        if seen_count[account_id] > max_per_account:
            outcomes.append(_outcome(verb, None, account_id, "refused", "rate-limited"))
            _log(store, now, verb, account_id, None, "refused", "rate-limited")
            continue

        character, reason = resolve_character(argument, roster)
        if character is None:
            attempted = _safe_argument(argument)
            outcomes.append(_outcome(verb, attempted, account_id, "refused", reason))
            _log(store, now, verb, account_id, attempted, "refused", reason)
            continue

        if verb == "claim":
            holder = store["by_character"].get(character)
            if holder == account_id:
                outcomes.append(_outcome(verb, character, account_id, "noop", "already-yours"))
                continue
            if holder:
                # FIRST CLAIM WINS. The refusal is logged so a contested
                # character is visible to an officer rather than silent.
                outcomes.append(_outcome(verb, character, account_id, "refused",
                                         "claimed-by-another-account"))
                _log(store, now, verb, account_id, character, "refused",
                     "claimed-by-another-account")
                continue
            account = _account(store, account_id)
            account["characters"] = sorted(set(account["characters"]) | {character})
            account["character_claimed_at"][character] = now
            account["claimed_at"] = account["claimed_at"] or now
            if not account["main"]:
                account["main"] = character
            store["by_character"][character] = account_id
            outcomes.append(_outcome(verb, character, account_id, "accepted", "signed"))
            _log(store, now, verb, account_id, character, "accepted", "signed")

        elif verb == "unclaim":
            holder = store["by_character"].get(character)
            if holder != account_id:
                outcomes.append(_outcome(verb, character, account_id, "refused",
                                         "not-yours" if holder else "not-claimed"))
                _log(store, now, verb, account_id, character, "refused",
                     "not-yours" if holder else "not-claimed")
                continue
            _drop_character(store, account_id, character)
            outcomes.append(_outcome(verb, character, account_id, "accepted", "released"))
            _log(store, now, verb, account_id, character, "accepted", "released")

        elif verb == "revoke":
            if not command.get("officer"):
                # The officer channel IS the authorization, exactly as
                # config.yml's announcement_channel_id already works.
                outcomes.append(_outcome(verb, character, account_id, "refused",
                                         "not-an-officer-channel"))
                _log(store, now, verb, account_id, character, "refused",
                     "not-an-officer-channel")
                continue
            holder = store["by_character"].get(character)
            if not holder:
                outcomes.append(_outcome(verb, character, account_id, "refused",
                                         "not-claimed"))
                _log(store, now, verb, account_id, character, "refused", "not-claimed")
                continue
            _drop_character(store, holder, character)
            outcomes.append(_outcome(verb, character, holder, "accepted", "revoked"))
            _log(store, now, verb, holder, character, "accepted", "revoked-by-officer")

    store["last_message_id"] = str(highest) if highest else watermark
    store["generated_at"] = now
    store["schema_version"] = SCHEMA_VERSION
    store["id_scheme"] = ID_SCHEME
    return store, outcomes


def _outcome(verb, character, account_id, result, reason):
    return {"verb": verb, "character": character, "account_id": account_id,
            "result": result, "reason": reason}


def _safe_argument(argument):
    """What a refused claim may name, or None.

    A refusal that does not say WHICH character was attempted is useless to
    the officer reading the log. But the argument is text a member typed, so
    `/claim <@111111111111111111>` would otherwise write a Discord id into a
    committed file. Only the shape a character key can actually take —
    lowercase letters, digits and hyphens — survives; anything else is
    dropped and the reason carries the story instead.
    """
    normalized = normalize_argument(argument)
    return normalized if _SAFE_ARGUMENT_RE.match(normalized or "") else None


# ---------------------------------------------------------------------------
# The public projection
# ---------------------------------------------------------------------------

def public_projection(store, roster_total=None, generated_at=None):
    """The shipped view: character key -> {account_id, is_main}.

    Deliberately thinner than the store. It carries no handle, no display
    name, no per-character timestamp and no audit log — an account's face on
    the site is its MAIN CHARACTER'S NAME, which the site already has from
    the roster. Nothing here originates with Discord except an HMAC digest.

    Absent signatures are an honest empty shape (`available: false`), never
    a missing file and never a pre-credited roster.
    """
    store = store or empty_store()
    accounts = store.get("accounts") or {}

    characters = {}
    account_view = {}
    for account_id, account in accounts.items():
        keys = sorted(account.get("characters") or [])
        if not keys:
            continue
        main = account.get("main")
        account_view[account_id] = {"main": main, "characters": keys}
        for key in keys:
            characters[key] = {"account_id": account_id, "is_main": key == main}

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or store.get("generated_at"),
        "id_scheme": ID_SCHEME,
        "available": bool(characters),
        "status": "ok" if characters else "no-signatures",
        "roster_total": roster_total,
        "signed_accounts": len(account_view),
        "signed_characters": len(characters),
        "characters": dict(sorted(characters.items())),
        "accounts": dict(sorted(account_view.items())),
    }


# ---------------------------------------------------------------------------
# The privacy gate
# ---------------------------------------------------------------------------

def find_identifiers(obj, path="$"):
    """Every place a raw identifier could be hiding. [] means clean.

    Walks keys AND values. Returns [(path, kind)] and — like
    tests/test_no_credentials_in_output.py — never echoes the offending
    value, because printing the id to prove the id leaked is its own leak.
    """
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            here = f"{path}.{key}"
            if _FORBIDDEN_FIELD_RE.search(str(key)):
                found.append((here, "identifying field name"))
            if _SNOWFLAKE_RE.match(str(key)):
                found.append((here, "discord snowflake used as a key"))
            found.extend(find_identifiers(value, here))
    elif isinstance(obj, (list, tuple)):
        for i, value in enumerate(obj):
            found.extend(find_identifiers(value, f"{path}[{i}]"))
    elif isinstance(obj, str):
        if _SNOWFLAKE_RE.match(obj.strip()):
            found.append((path, "discord snowflake"))
        if _MENTION_RE.search(obj):
            found.append((path, "discord mention markup"))
        if _EMAIL_RE.search(obj):
            found.append((path, "email address"))
    elif isinstance(obj, int) and not isinstance(obj, bool):
        if _SNOWFLAKE_RE.match(str(obj)):
            found.append((path, "discord snowflake (numeric)"))
    return found


def assert_opaque(projection):
    """Raise unless the projection is free of raw identifiers.

    Called by the producing script BEFORE the bytes are written and by the
    test suite afterwards. Both, on purpose: the report's section 5.6 asks
    for a producer assertion and an independent re-verification, and a gate
    that only exists in CI is a gate somebody will ship around.
    """
    violations = find_identifiers(projection)
    if violations:
        detail = "; ".join(f"{p} ({kind})" for p, kind in violations[:5])
        raise ValueError(
            f"{len(violations)} raw identifier(s) in the public articles "
            f"projection: {detail}. Discord ids never enter shipped bytes.")
    return True

"""THE SHIP'S ARTICLES — the account <-> character mapping.

No network: fetch_claim_commands is exercised against a stubbed
_collect_messages, and everything else is pure.

The four the ticket names are `test_claim_then_unclaim_round_trip`,
`test_second_account_claiming_a_signed_character_is_refused`,
`test_a_character_not_on_the_roster_is_refused` and
`test_projection_carries_no_raw_discord_ids` — the rest guard the laws that
make those four mean anything (opaque ids, ambiguity, officer authority,
idempotence).
"""

import json

import pytest

from guild_board import articles
from guild_board import discord_inputs as di

SALT = "a-salt-long-enough-to-be-a-secret"
NOW = "2026-08-16T18:00:00+00:00"

# The real collision this roster carries: two characters called Beroben, and
# two Violences differing only in which vowel takes the diacritic.
ROSTER = [
    "buchalter-area-52",
    "buchalta-area-52",
    "beroben-emerald-dream",
    "beroben-queldorei",
    "amrevenge-bleeding-hollow",
    "healmates-bleeding-hollow",
]

ALICE = "111111111111111111"   # a Discord snowflake, only ever an input
BOB = "222222222222222222"


def _cmd(mid, author, content, officer=False):
    return {"message_id": str(mid), "author_id": author, "content": content,
            "officer": officer}


def _apply(commands, store=None, roster=ROSTER, now=NOW, **kw):
    return articles.apply_commands(store or articles.empty_store(), commands,
                                   roster, SALT, now, **kw)


# --------------------------------------------------------------- identity

def test_account_id_is_opaque_stable_and_not_the_discord_id():
    first = articles.derive_account_id(ALICE, SALT)
    assert first == articles.derive_account_id(ALICE, SALT)      # stable
    assert first != articles.derive_account_id(BOB, SALT)        # distinct
    assert ALICE not in first
    assert len(first) == 16 and all(c in "0123456789abcdef" for c in first)


def test_a_different_salt_gives_a_different_id():
    """The salt is what makes the digest un-reversible, so it has to matter."""
    assert (articles.derive_account_id(ALICE, SALT)
            != articles.derive_account_id(ALICE, SALT + "x"))


def test_minting_an_id_without_a_salt_raises():
    for bad in (None, "", "tooshort"):
        with pytest.raises(ValueError):
            articles.derive_account_id(ALICE, bad)


# ---------------------------------------------------------------- parsing

@pytest.mark.parametrize("text,expected", [
    ("/claim Buchalter", ("claim", "Buchalter")),
    ("!claim Buchalter-Area-52", ("claim", "Buchalter-Area-52")),
    ("CLAIM Buchalter", ("claim", "Buchalter")),
    ("/unclaim buchalta-area-52", ("unclaim", "buchalta-area-52")),
    ("/revoke amrevenge-bleeding-hollow", ("revoke", "amrevenge-bleeding-hollow")),
    ("/claim Buchalter\nthanks", ("claim", "Buchalter")),
])
def test_parse_command(text, expected):
    assert articles.parse_command(text) == expected


def test_ordinary_chat_is_not_a_command():
    for text in ("who wants to run keys", "", None, "reclaiming my alt"):
        assert articles.parse_command(text) is None


def test_normalize_argument_folds_spaces_and_apostrophes():
    assert articles.normalize_argument("Buchalter Area 52") == "buchalter-area-52"
    assert articles.normalize_argument("Beroben Quel'Dorei") == "beroben-queldorei"
    assert articles.normalize_argument("  `Buchalter-Area-52` ") == "buchalter-area-52"


# ------------------------------------------------------------ claim/unclaim

def test_claim_then_unclaim_round_trip():
    store, outcomes = _apply([_cmd(1, ALICE, "/claim Buchalter-Area-52")])
    aid = articles.derive_account_id(ALICE, SALT)

    assert outcomes[0]["result"] == "accepted"
    assert store["accounts"][aid]["characters"] == ["buchalter-area-52"]
    assert store["accounts"][aid]["main"] == "buchalter-area-52"
    assert store["accounts"][aid]["claimed_at"] == NOW
    assert store["by_character"]["buchalter-area-52"] == aid

    store, outcomes = _apply([_cmd(2, ALICE, "/unclaim Buchalter-Area-52")], store)
    assert outcomes[0]["result"] == "accepted"
    assert "buchalter-area-52" not in store["by_character"]
    # An account holding nothing is not an account -- "N of 129 signed" stays honest.
    assert aid not in store["accounts"]


def test_mains_and_alts_first_claim_is_the_main():
    store, _ = _apply([
        _cmd(1, ALICE, "/claim Buchalter-Area-52"),
        _cmd(2, ALICE, "/claim buchalta-area-52"),
    ])
    aid = articles.derive_account_id(ALICE, SALT)
    account = store["accounts"][aid]
    assert account["characters"] == ["buchalta-area-52", "buchalter-area-52"]
    assert account["main"] == "buchalter-area-52"   # the one claimed first


def test_unclaiming_the_main_promotes_the_oldest_remaining_claim():
    store, _ = _apply([
        _cmd(1, ALICE, "/claim Buchalter-Area-52"),
        _cmd(2, ALICE, "/claim buchalta-area-52"),
        _cmd(3, ALICE, "/unclaim Buchalter-Area-52"),
    ])
    aid = articles.derive_account_id(ALICE, SALT)
    assert store["accounts"][aid]["main"] == "buchalta-area-52"


def test_claiming_your_own_character_twice_is_a_noop_not_a_refusal():
    store, outcomes = _apply([
        _cmd(1, ALICE, "/claim Buchalter-Area-52"),
        _cmd(2, ALICE, "/claim Buchalter-Area-52"),
    ])
    assert [o["result"] for o in outcomes] == ["accepted", "noop"]
    aid = articles.derive_account_id(ALICE, SALT)
    assert store["accounts"][aid]["characters"] == ["buchalter-area-52"]


def test_unclaiming_a_character_you_do_not_hold_is_refused():
    store, _ = _apply([_cmd(1, ALICE, "/claim Buchalter-Area-52")])
    store, outcomes = _apply([_cmd(2, BOB, "/unclaim Buchalter-Area-52")], store)
    assert outcomes[0]["result"] == "refused"
    assert outcomes[0]["reason"] == "not-yours"
    # ...and the real holder still holds it.
    assert store["by_character"]["buchalter-area-52"] == articles.derive_account_id(ALICE, SALT)


# ------------------------------------------------- one character, one account

def test_second_account_claiming_a_signed_character_is_refused():
    """FIRST CLAIM WINS, and the refusal is on the record."""
    store, outcomes = _apply([
        _cmd(1, ALICE, "/claim Buchalter-Area-52"),
        _cmd(2, BOB, "/claim Buchalter-Area-52"),
    ])
    alice = articles.derive_account_id(ALICE, SALT)
    bob = articles.derive_account_id(BOB, SALT)

    assert outcomes[1]["result"] == "refused"
    assert outcomes[1]["reason"] == "claimed-by-another-account"
    assert store["by_character"]["buchalter-area-52"] == alice
    assert bob not in store["accounts"]

    refusals = [row for row in store["log"] if row["result"] == "refused"]
    assert refusals and refusals[-1]["account_id"] == bob
    assert refusals[-1]["character"] == "buchalter-area-52"


def test_the_loser_of_a_contest_can_claim_it_after_an_officer_revoke():
    store, _ = _apply([
        _cmd(1, ALICE, "/claim Buchalter-Area-52"),
        _cmd(2, BOB, "/claim Buchalter-Area-52"),
    ])
    store, outcomes = _apply([
        _cmd(3, ALICE, "/revoke Buchalter-Area-52", officer=True),
        _cmd(4, BOB, "/claim Buchalter-Area-52"),
    ], store)
    assert [o["result"] for o in outcomes] == ["accepted", "accepted"]
    assert store["by_character"]["buchalter-area-52"] == articles.derive_account_id(BOB, SALT)
    assert any(row["reason"] == "revoked-by-officer" for row in store["log"])


# ------------------------------------------------------- the roster verifies

def test_a_character_not_on_the_roster_is_refused():
    store, outcomes = _apply([_cmd(1, ALICE, "/claim Nobodyhere-Area-52")])
    assert outcomes[0]["result"] == "refused"
    assert outcomes[0]["reason"] == "not-on-roster"
    assert store["accounts"] == {}
    assert store["by_character"] == {}
    assert store["log"][-1]["result"] == "refused"


def test_a_refusal_names_the_attempt_but_never_smuggles_an_id_into_it():
    """The officer reading the log needs to know WHAT was attempted; the
    attempt is member-typed text, so only key-shaped text is recorded."""
    store, _ = _apply([
        _cmd(1, ALICE, "/claim Nobodyhere-Area-52"),
        _cmd(2, BOB, "/claim <@111111111111111111>"),
    ])
    recorded = [row["character"] for row in store["log"]]
    assert "nobodyhere-area-52" in recorded          # useful
    assert None in recorded                          # and the mention dropped
    assert not any(r and "1111" in r for r in recorded)


def test_a_bare_name_two_roster_characters_share_is_refused_never_guessed():
    """Two real people are called Beroben. Picking one silently pays the
    wrong person forever; the ledger refuses and says why."""
    store, outcomes = _apply([_cmd(1, ALICE, "/claim Beroben")])
    assert outcomes[0]["result"] == "refused"
    assert outcomes[0]["reason"] == "ambiguous"
    assert store["by_character"] == {}


def test_an_unambiguous_bare_name_resolves_to_its_character_key():
    store, outcomes = _apply([_cmd(1, ALICE, "/claim Amrevenge")])
    assert outcomes[0]["result"] == "accepted"
    assert "amrevenge-bleeding-hollow" in store["by_character"]


def test_every_stored_key_is_a_character_key_never_a_bare_name():
    store, _ = _apply([
        _cmd(1, ALICE, "/claim Amrevenge"),
        _cmd(2, BOB, "/claim Healmates"),
    ])
    keys = list(store["by_character"])
    for account in store["accounts"].values():
        keys += account["characters"] + [account["main"]]
    assert keys and all("-" in k for k in keys)


# ------------------------------------------------------- officer authority

def test_revoke_outside_an_officer_channel_is_refused():
    store, _ = _apply([_cmd(1, ALICE, "/claim Buchalter-Area-52")])
    store, outcomes = _apply([_cmd(2, BOB, "/revoke Buchalter-Area-52")], store)
    assert outcomes[0]["result"] == "refused"
    assert outcomes[0]["reason"] == "not-an-officer-channel"
    assert store["by_character"]["buchalter-area-52"] == articles.derive_account_id(ALICE, SALT)


def test_revoking_an_unclaimed_character_is_refused_not_a_crash():
    store, outcomes = _apply([_cmd(1, BOB, "/revoke Amrevenge", officer=True)])
    assert outcomes[0]["result"] == "refused"
    assert outcomes[0]["reason"] == "not-claimed"


# ------------------------------------------------------------- idempotence

def test_the_watermark_stops_a_command_being_applied_twice():
    """A re-run must not resurrect a revoked claim by replaying its message."""
    commands = [_cmd(1, ALICE, "/claim Buchalter-Area-52")]
    store, _ = _apply(commands)
    store, _ = _apply([_cmd(2, ALICE, "/revoke Buchalter-Area-52", officer=True)], store)
    assert "buchalter-area-52" not in store["by_character"]

    # The next refresh reads the same window and sees message 1 again.
    store, outcomes = _apply(commands, store)
    assert outcomes == []
    assert "buchalter-area-52" not in store["by_character"]


def test_a_burst_from_one_account_is_rate_limited():
    commands = [_cmd(i, ALICE, "/claim Amrevenge") for i in range(1, 8)]
    _, outcomes = _apply(commands, max_per_account=3)
    assert [o["reason"] for o in outcomes[3:]] == ["rate-limited"] * 4


# -------------------------------------------------------- the public shape

def test_projection_is_character_key_to_account_id_and_is_main():
    store, _ = _apply([
        _cmd(1, ALICE, "/claim Buchalter-Area-52"),
        _cmd(2, ALICE, "/claim buchalta-area-52"),
        _cmd(3, BOB, "/claim Amrevenge"),
    ])
    projection = articles.public_projection(store, roster_total=len(ROSTER))
    alice = articles.derive_account_id(ALICE, SALT)

    assert projection["characters"]["buchalter-area-52"] == {
        "account_id": alice, "is_main": True}
    assert projection["characters"]["buchalta-area-52"] == {
        "account_id": alice, "is_main": False}
    assert projection["available"] is True
    assert projection["signed_accounts"] == 2
    assert projection["signed_characters"] == 3
    assert projection["roster_total"] == len(ROSTER)
    # Exactly one main per account -- the ledger keys account-wide caps on it.
    mains = [k for k, v in projection["characters"].items() if v["is_main"]]
    assert sorted(mains) == sorted(a["main"] for a in projection["accounts"].values())


def test_projection_before_anybody_signs_is_an_honest_empty_shape():
    projection = articles.public_projection(articles.empty_store(), roster_total=129)
    assert projection["available"] is False
    assert projection["status"] == "no-signatures"
    assert projection["signed_accounts"] == 0
    assert projection["characters"] == {}
    assert projection["roster_total"] == 129


def test_projection_carries_no_raw_discord_ids():
    """THE PRIVACY LAW, on the actual bytes."""
    store, _ = _apply([
        _cmd(1, ALICE, "/claim Buchalter-Area-52"),
        _cmd(2, BOB, "/claim Beroben"),                    # refused, logged
        _cmd(3, BOB, "/claim <@111111111111111111>"),      # refused, logged
    ])
    projection = articles.public_projection(store, roster_total=len(ROSTER))

    articles.assert_opaque(projection)
    articles.assert_opaque(store)

    blob = json.dumps({"store": store, "projection": projection})
    for raw in (ALICE, BOB):
        assert raw not in blob
    assert "discord" not in blob.lower()
    assert articles.find_identifiers(projection) == []


def test_the_opacity_gate_actually_catches_a_leak():
    """A guard nobody has watched fail is not a guard."""
    for leak in ({"characters": {"a-b": {"discord_id": "1"}}},
                 {"characters": {"a-b": {"account_id": ALICE}}},
                 {"note": "signed by <@222222222222222222>"},
                 {"contact": "someone@example.com"}):
        assert articles.find_identifiers(leak)
        with pytest.raises(ValueError):
            articles.assert_opaque(leak)


def test_the_projection_is_re_derivable_from_the_store():
    store, _ = _apply([_cmd(1, ALICE, "/claim Amrevenge")])
    once = articles.public_projection(store, roster_total=6, generated_at=NOW)
    twice = articles.public_projection(json.loads(json.dumps(store)),
                                       roster_total=6, generated_at=NOW)
    assert once == twice


# -------------------------------------------------------- the Discord read

def test_fetch_claim_commands_reads_only_allowlisted_channels(monkeypatch):
    seen = []

    def fake_collect(bot_token, channel_id, max_threads=8):
        seen.append(channel_id)
        return [{
            # Distinct per channel: messages are deduped by id.
            "id": str((1 << 22) + int(channel_id)),
            "content": "/claim Amrevenge",
            "author": {"id": ALICE, "username": "alice", "bot": False},
            "timestamp": NOW,
        }]

    monkeypatch.setattr(di, "_collect_messages", fake_collect)
    commands = di.fetch_claim_commands("token", ["100"], 0,
                                       officer_channel_ids=["200"])
    assert sorted(seen) == ["100", "200"]
    assert {c["officer"] for c in commands} == {False, True}
    assert all(set(c) == {"message_id", "author_id", "content", "timestamp", "officer"}
               for c in commands)
    # No display name is fetched at all -- a name never received cannot ship.
    assert all("username" not in c and "author" not in c for c in commands)


def test_fetch_claim_commands_drops_bots_blanks_and_old_messages(monkeypatch):
    recent = (5 << 22) + 1
    old = (1 << 22) + 1

    def fake_collect(bot_token, channel_id, max_threads=8):
        return [
            {"id": str(recent), "content": "/claim Amrevenge",
             "author": {"id": ALICE, "bot": False}, "timestamp": NOW},
            {"id": str(recent + 1), "content": "/claim Healmates",
             "author": {"id": BOB, "bot": True}, "timestamp": NOW},
            {"id": str(recent + 2), "content": "   ",
             "author": {"id": BOB, "bot": False}, "timestamp": NOW},
            {"id": str(old), "content": "/claim Healmates",
             "author": {"id": BOB, "bot": False}, "timestamp": NOW},
        ]

    monkeypatch.setattr(di, "_collect_messages", fake_collect)
    commands = di.fetch_claim_commands("token", ["100"],
                                       di.DISCORD_EPOCH_MS + 2)
    assert [c["message_id"] for c in commands] == [str(recent)]


def test_a_read_failure_never_empties_the_articles(monkeypatch):
    import requests

    def boom(bot_token, channel_id, max_threads=8):
        raise requests.ConnectionError("no")

    monkeypatch.setattr(di, "_collect_messages", boom)
    assert di.fetch_claim_commands("token", ["100"], 0) == []

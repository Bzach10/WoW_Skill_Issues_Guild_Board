"""THE SHIP'S ARTICLES — read /claim, /unclaim and /revoke, write the mapping.

This is the ONLY writer of data/accounts.json. Nothing else in this repo
may create, edit or repair it: the ledger's whole value is that one process
applied one ordered stream of member commands to it.

What it does
------------
1. Resolves the LIVE guild roster (guild_board.guild_roster.resolve — the
   union of every reachable authority). A claim is verified against it.
2. Reads the allowlisted claims channel(s) over the Discord REST API, using
   the SAME read-only DISCORD_BOT_TOKEN the weekly board already uses.
3. Folds the commands into data/accounts.json (guild_board.articles).
4. Writes the public projection the site may bake:
   web_data_public/articles.json — character key -> {account_id, is_main}.

What it refuses to do
---------------------
* **Write without a salt.** ACCOUNTS_ID_SALT mints the opaque account id.
  Without it the id would be a plain digest of a Discord id, reversible by
  anyone who can list the guild's members. No salt, no write, exit 0.
* **Write against an empty roster.** If every roster authority is
  unreachable, every claim would be refused as "not-on-roster" and the
  refusals would be recorded as fact. Nothing is written; exit 0.
* **Ship an identifier.** `articles.assert_opaque` runs on the projection
  BEFORE the bytes hit disk. A violation is a hard stop, not a warning.

It is inert until all three exist: discord_inputs.claim_channel_ids in
config.yml, the DISCORD_BOT_TOKEN secret, and the ACCOUNTS_ID_SALT secret.
Each absence prints its own reason and exits 0 — the repo's rule that a
credentialed path stays graceful when the credential is not there.

NOT WIRED TO A WORKFLOW ON PURPOSE. The owner deploys the bot on his word.
When he does, this is one step on an existing job (guild-pulse-refresh.yml
already carries DISCORD_BOT_TOKEN, runs every 6h and commits):

    - name: Read the Ship's Articles (claims)
      env:
        DISCORD_BOT_TOKEN: ${{ secrets.DISCORD_BOT_TOKEN }}
        ACCOUNTS_ID_SALT: ${{ secrets.ACCOUNTS_ID_SALT }}
      run: python scripts/refresh_articles.py

Usage:
    python scripts/refresh_articles.py [--dry-run] [--out DIR]
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guild_board import articles, guild_roster  # noqa: E402
from guild_board.config import load_config, load_roster_cache  # noqa: E402
from guild_board.discord_inputs import fetch_claim_commands  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
STORE_PATH = REPO_ROOT / "data" / "accounts.json"
DEFAULT_OUT = REPO_ROOT / "web_data_public"
PROJECTION_NAME = "articles.json"

# How far back the read looks. Generous because the watermark, not the
# window, is what stops a command being applied twice.
DEFAULT_LOOKBACK_DAYS = 30


def _say(msg):
    print(msg)


def load_store(path=STORE_PATH):
    """The ledger, or the honest empty one. A corrupt file is NOT silently
    replaced — that would erase every signature on a stray parse error."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return articles.empty_store()
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"REFUSED: {path} is present but unparseable ({exc}). Refusing to "
            "overwrite it — every signature in it would be lost. Fix or move "
            "the file by hand, then re-run.") from exc


def resolve_roster(cfg):
    """Live roster keys, unioned across every authority we can reach."""
    wcl_roster, _ = load_roster_cache(cfg)
    members, report = guild_roster.resolve(cfg, wcl_roster=wcl_roster)
    return guild_roster.roster_keys(members), report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="read and report; write nothing")
    parser.add_argument("--out", default=str(DEFAULT_OUT),
                        help="where the public projection is written")
    parser.add_argument("--lookback-days", type=int, default=None)
    args = parser.parse_args(argv)

    cfg = load_config()
    inputs_cfg = cfg.get("discord_inputs") or {}

    if not inputs_cfg.get("enabled", False):
        _say("discord_inputs is disabled in config.yml — the articles are closed.")
        return 0

    channels = inputs_cfg.get("claim_channel_ids") or []
    if isinstance(channels, (str, int)):
        channels = [channels]
    officer_channels = inputs_cfg.get("officer_channel_ids") or []
    if isinstance(officer_channels, (str, int)):
        officer_channels = [officer_channels]
    if not channels and not officer_channels:
        _say("No discord_inputs.claim_channel_ids configured — nothing read. "
             "Add the claims channel to open the articles.")
        return 0

    bot_token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not bot_token:
        _say("DISCORD_BOT_TOKEN is not set — skipping. It is the same "
             "read-only token the weekly board already uses.")
        return 0

    salt = os.environ.get("ACCOUNTS_ID_SALT", "").strip()
    if len(salt) < 16:
        _say("ACCOUNTS_ID_SALT is unset or under 16 characters — REFUSING to "
             "write. The account id is an HMAC of the Discord id; without a "
             "secret salt it is reversible from the guild's member list, and "
             "an id that can be reversed is a Discord id in shipped bytes.")
        return 0

    roster, report = resolve_roster(cfg)
    if not roster:
        _say("Roster resolved to ZERO characters (unreachable sources: "
             f"{', '.join(report.get('unreachable_sources') or []) or 'none'}). "
             "Every claim would be refused as not-on-roster and the refusal "
             "would be recorded as fact. Nothing written.")
        return 0
    _say(f"Roster: {len(roster)} character key(s) from "
         f"{', '.join(sorted(report.get('sources') or {})) or 'no source'}.")

    lookback = args.lookback_days or int(
        inputs_cfg.get("claim_lookback_days", DEFAULT_LOOKBACK_DAYS))
    since_ms = int((datetime.now(timezone.utc)
                    - timedelta(days=lookback)).timestamp() * 1000)

    commands = fetch_claim_commands(bot_token, channels, since_ms,
                                    officer_channel_ids=officer_channels)
    _say(f"Read {len(commands)} human message(s) since {lookback}d ago across "
         f"{len(set(list(channels) + list(officer_channels)))} channel(s).")

    store = load_store()
    now = datetime.now(timezone.utc).isoformat()
    store, outcomes = articles.apply_commands(
        store, commands, roster, salt, now,
        max_per_account=int(inputs_cfg.get("claim_max_per_run",
                            articles.DEFAULT_MAX_COMMANDS_PER_ACCOUNT)))

    projection = articles.public_projection(
        store, roster_total=len(roster), generated_at=now)

    # THE GATE. Runs on the object about to become bytes, before it does.
    articles.assert_opaque(projection)
    # The store is committed to a public repo, so it is held to the same bar.
    articles.assert_opaque(store)

    accepted = [o for o in outcomes if o["result"] == "accepted"]
    refused = [o for o in outcomes if o["result"] == "refused"]
    _say(f"Commands applied: {len(accepted)} accepted, {len(refused)} refused, "
         f"{len(outcomes) - len(accepted) - len(refused)} no-op.")
    for outcome in refused:
        _say(f"  REFUSED {outcome['verb']} {outcome['character'] or '(none)'} "
             f"-> {outcome['reason']}")
    _say(f"Signed: {projection['signed_accounts']} of {len(roster)} hands, "
         f"{projection['signed_characters']} character(s).")

    if args.dry_run:
        _say("--dry-run: nothing written.")
        return 0

    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _write(STORE_PATH, store)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write(out_dir / PROJECTION_NAME, projection)
    _say(f"Wrote {STORE_PATH} and {out_dir / PROJECTION_NAME}.")
    return 0


def _write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    sys.exit(main())

"""THE SHARES LEDGER — compute one week's earn and bake shares.json.

This is the ONLY writer of data/shares_ledger.json. Nothing else in this
repo may create, edit or repair it: the ledger's whole value is that it is
append-only and that every row in it cites the deed that paid it.

What it does
------------
1. Loads the DELIVERED bundle (web_data_public by default) — competition,
   weekly_board, island_completion, recap_ribbon, records_leaderboard. It
   reads only what the pipeline already published; it makes no network call
   and holds no credential.
2. Loads web_data_public/articles.json, the public account <-> character
   projection written by scripts/refresh_articles.py. An unsigned character
   is absent from it and earns nothing.
3. Loads roster_cache.json purely as an IDENTITY INDEX, so a bare Warcraft
   Logs name (the improvement pairs, the roast winner, the press) resolves
   to a `name-realm` character key or ships as a named seam. Two roster
   characters are called Beroben; a bare-name payout pays one of two real
   people at random, forever.
4. Computes the week against guild_board.shares.RATE_CARD and APPENDS the
   rows to data/shares_ledger.json. A row's id is a digest of its citation,
   so re-running a week is a no-op rather than a second payment.
5. Writes web_data_public/shares.json — the public projection.

What it refuses to do
---------------------
* **Pay a rank.** The rate card reads no score, rank, ranks, top5, rankings,
  parse or percentile. `tests/test_shares.py` proves it by mutation.
* **Pay against a guessed week.** No week window in weekly_board means no
  payment; the projection ships `available: false` and says so.
* **Ship an identifier.** `articles.assert_opaque` runs on the ledger AND
  the projection before either becomes bytes. A violation is a hard stop.
* **Rewrite history.** Existing rows are never edited or removed.

NOT WIRED TO A WORKFLOW ON PURPOSE — the same rule as refresh_articles.py:
the owner opens the economy on his word. When he does, this is one step at
the END of the daily refresh, after build_site_data.py has written the
bundle and before deliver_bundle.py hands it over:

    - name: Compute the shares ledger
      run: python scripts/refresh_shares.py

It needs no secret at all: everything it reads is already public bytes.

Usage:
    python scripts/refresh_shares.py [--bundle DIR] [--out DIR] [--dry-run]
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guild_board import articles, shares  # noqa: E402
from guild_board.config import load_config, load_roster_cache  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = REPO_ROOT / "data" / "shares_ledger.json"
PROJECTION_NAME = "shares.json"
ARTICLES_NAME = "articles.json"

BUNDLE_LAYERS = ("competition", "weekly_board", "island_completion",
                 "recap_ribbon", "records_leaderboard")


def _say(msg):
    print(msg.encode("ascii", "backslashreplace").decode("ascii"))


def default_bundle_dir():
    """The cloud-committed bundle when present, else the local build."""
    for name in ("web_data_public", "web_data"):
        candidate = REPO_ROOT / name
        if (candidate / "site_data.json").exists():
            return candidate
    return REPO_ROOT / "web_data"


def _load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"REFUSED: {path} is present but unparseable ({exc}).") from exc


def load_bundle(bundle_dir):
    """The delivered layers by name. A missing layer is None, never a zero."""
    return {name: _load_json(Path(bundle_dir) / f"{name}.json")
            for name in BUNDLE_LAYERS}


def load_ledger(path=LEDGER_PATH):
    """The ledger, or the honest empty one. A corrupt file is NOT silently
    replaced — that would erase every share ever earned on a parse error."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return shares.empty_ledger()
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"REFUSED: {path} is present but unparseable ({exc}). Refusing to "
            "overwrite it — every share in it would be lost. Fix or move the "
            "file by hand, then re-run.") from exc


def display_names(competition):
    """{character key: display name} straight off the competition layer.

    The key stays the identity; this is only what a surface prints.
    """
    names = {}
    for character in (competition or {}).get("characters") or []:
        if character.get("key") and character.get("name"):
            names[character["key"]] = character["name"]
    return names


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", default=None,
                        help="delivered bundle directory (default: "
                             "web_data_public if present, else web_data)")
    parser.add_argument("--out", default=None,
                        help="where shares.json is written (default: the "
                             "bundle directory)")
    parser.add_argument("--ledger", default=str(LEDGER_PATH))
    parser.add_argument("--dry-run", action="store_true",
                        help="compute and report; write nothing")
    args = parser.parse_args(argv)

    bundle_dir = Path(args.bundle) if args.bundle else default_bundle_dir()
    out_dir = Path(args.out) if args.out else bundle_dir
    ledger_path = Path(args.ledger)

    bundle = load_bundle(bundle_dir)
    missing = [name for name, layer in bundle.items() if layer is None]
    if missing:
        _say(f"Bundle layers absent from {bundle_dir}: {', '.join(missing)}. "
             "They are read as absent, never as empty.")
    if bundle.get("weekly_board") is None:
        _say("No weekly_board.json — the week's own numbers only exist once a "
             "credentialed weekly run has posted. Nothing is paid against a "
             "week nobody measured.")

    articles_projection = _load_json(bundle_dir / ARTICLES_NAME)
    if articles_projection is None:
        _say(f"No {ARTICLES_NAME} in {bundle_dir} — nobody has signed the "
             "articles yet. An unsigned character earns nothing, so the "
             "projection ships an honest empty shelf.")
        articles_projection = {}

    cfg = load_config()
    roster, _roster_at = load_roster_cache(cfg)
    _say(f"Roster index: {len(roster or [])} character key(s) — the only "
         "thing standing between a bare name and paying the wrong Beroben.")

    ledger = load_ledger(ledger_path)
    week = shares.compute_week(
        bundle, articles_projection, roster=roster,
        previous_holders=shares.previous_lane_holders(ledger))

    _say(f"Week {week['week']['label'] or '(none)'} "
         f"[{week['week']['start']} .. {week['week']['end']}]: {week['status']}")

    now = datetime.now(timezone.utc).isoformat()
    ledger, appended, skipped = shares.append_week(ledger, week, generated_at=now)
    _say(f"Ledger: +{appended} row(s), {skipped} already present (a deed pays "
         f"once), {len(ledger['rows'])} row(s) total across "
         f"{len(ledger['weeks'])} week(s).")

    projection = shares.public_projection(
        ledger, week, articles_projection,
        names=display_names(bundle.get("competition")), generated_at=now)

    # THE GATE. Runs on the objects about to become bytes, before they do.
    articles.assert_opaque(projection)
    articles.assert_opaque(ledger)

    for account_id, account in sorted(projection["accounts"].items()):
        wk = account["week"]
        _say(f"  {account_id} ({account['main'] or '-'}, "
             f"{len(account['characters'])} char): base {wk['base']} "
             f"x{wk['multiplier']} = {wk['total']} this week, "
             f"balance {account['balance']}")
    for seam in projection["seams"]:
        _say(f"  SEAM: {seam}")

    if args.dry_run:
        _say("--dry-run: nothing written.")
        return 0

    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    _write(ledger_path, ledger)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write(out_dir / PROJECTION_NAME, projection)
    _say(f"Wrote {ledger_path} and {out_dir / PROJECTION_NAME}.")
    return 0


def _write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    sys.exit(main())

"""One-time migration: import the CURRENT roster data into the surrogate schema
WITHOUT losing anyone.

Inputs (docs/DATABASE_DESIGN.md, brief decision 6/7):
  * data/competition.json      — 132 distinct characters (raider.io-derived).
  * data/roster_supplement.json — 15 recovered members the pull missed (L21).
                                  score is null for all 15: a supplement may ADD
                                  a character, never supply a stat (L10).

Provenance split:
  * fetch_run.source records HOW we got the rows ('legacy_json' for the
    competition snapshot, 'manual' for the supplement).
  * each FACT's source records its ORIGIN authority ('raiderio' for the scores,
    'manual' for supplement identity/profile), so read-time precedence resolves
    correctly.

Idempotent: a second run detects the prior successful legacy_json import and
does nothing, so the GitHub Action can call it unconditionally.
"""
from __future__ import annotations

import argparse
import json
import os

from . import db
from .config import seed_field_authority

REGION = "us"
GUILD_REALM = "bleeding-hollow"
GUILD_SLUG = "skill-issues"
GUILD_NAME = "Skill Issues"


def _already_migrated(conn) -> bool:
    row = conn.execute(
        "SELECT 1 FROM fetch_run WHERE source='legacy_json' AND outcome='success' LIMIT 1"
    ).fetchone()
    return row is not None


def migrate(conn, data_dir: str) -> dict:
    """Import competition.json + roster_supplement.json. Returns a reconciliation dict."""
    if _already_migrated(conn):
        n = conn.execute("SELECT COUNT(*) c FROM character").fetchone()["c"]
        return {"skipped": True, "reason": "already migrated", "surrogates": n}

    with open(os.path.join(data_dir, "competition.json"), encoding="utf-8") as fh:
        comp = json.load(fh)
    with open(os.path.join(data_dir, "roster_supplement.json"), encoding="utf-8") as fh:
        supp = json.load(fh)

    guild_id = db.get_or_create_guild(conn, REGION, GUILD_REALM, GUILD_SLUG, GUILD_NAME)
    season = comp["season"]["slug"]
    comp_observed = comp["based_on"]

    # ---- competition.json (raider.io-derived), 132 distinct characters -----
    run_comp = db.start_fetch_run(conn, "legacy_json", "data/competition.json")
    comp_chars = comp["characters"]
    comp_created = 0
    for c in comp_chars:
        name, realm_slug = c.get("name"), c.get("realm_slug")
        cid, created = db.mint_or_get_character(
            conn, REGION, realm_slug, name, source="raiderio",
            run_id=run_comp, observed_at=comp_observed,
        )
        comp_created += int(created)
        db.open_membership_if_absent(conn, cid, guild_id, run_id=run_comp,
                                     observed_from=comp_observed)
        db.insert_profile(conn, cid, source="raiderio", observed_at=comp_observed,
                          run_id=run_comp, character_class=c.get("class"),
                          spec=c.get("spec"), source_url=c.get("raiderio_url"))
        # scores: role 'all' + any nonzero per-role. NEVER guessed; only what the file holds.
        if (c.get("score") or 0) > 0:
            db.insert_mplus_score(conn, cid, season, "all", float(c["score"]),
                                  "raiderio", comp_observed, run_comp,
                                  source_url=c.get("raiderio_url"), change_only=False)
        for role, val in (c.get("scores_by_role") or {}).items():
            if (val or 0) > 0:
                db.insert_mplus_score(conn, cid, season, role, float(val),
                                      "raiderio", comp_observed, run_comp,
                                      source_url=c.get("raiderio_url"), change_only=False)
        db.log_attempt(conn, run_comp, character_id=cid, outcome="ok")
    db.finish_fetch_run(conn, run_comp, "success",
                        targets_attempted=len(comp_chars), targets_succeeded=len(comp_chars))

    # ---- roster_supplement.json, 15 recovered members (add existence only) -
    run_supp = db.start_fetch_run(conn, "manual", "data/roster_supplement.json")
    supp_chars = supp["characters"]
    supp_created = supp_reused = 0
    for c in supp_chars:
        name, realm_slug = c.get("name"), c.get("realm_slug")
        observed = ((c.get("evidence") or {}).get("observed")) or db.now_utc()
        cid, created = db.mint_or_get_character(
            conn, REGION, realm_slug, name, source="manual",
            run_id=run_supp, observed_at=observed,
        )
        supp_created += int(created)
        supp_reused += int(not created)
        db.open_membership_if_absent(conn, cid, guild_id, run_id=run_supp,
                                     observed_from=observed)
        db.insert_profile(conn, cid, source="manual", observed_at=observed,
                          run_id=run_supp, character_class=c.get("class"), spec=c.get("spec"))
        # NO score inserted: every supplement score is null by rule (L10).
        db.log_attempt(conn, run_supp, character_id=cid, outcome="ok")
    db.finish_fetch_run(conn, run_supp, "success",
                        targets_attempted=len(supp_chars), targets_succeeded=len(supp_chars))

    # ---- reconciliation ----------------------------------------------------
    total = conn.execute("SELECT COUNT(*) c FROM character").fetchone()["c"]
    open_members = conn.execute(
        "SELECT COUNT(*) c FROM membership_interval WHERE observed_to IS NULL"
    ).fetchone()["c"]
    scores = conn.execute("SELECT COUNT(*) c FROM mplus_score_observation").fetchone()["c"]
    return {
        "skipped": False,
        "competition_input_rows": len(comp_chars),
        "competition_surrogates_created": comp_created,
        "supplement_input_rows": len(supp_chars),
        "supplement_surrogates_created": supp_created,
        "supplement_rows_that_collided_with_competition": supp_reused,
        "total_surrogates": total,
        "open_membership_intervals": open_members,
        "mplus_score_observations": scores,
        "expected_total_surrogates": len(comp_chars) + supp_created,
    }


def main():
    ap = argparse.ArgumentParser(description="Import current roster into surrogate schema")
    ap.add_argument("--db", default="wipefest.sqlite3")
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()
    conn = db.connect(args.db)
    db.init_db(conn)
    seed_field_authority(conn)
    result = migrate(conn, args.data_dir)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

"""Blizzard guild-roster ingestion — the authoritative membership + identity source.

Endpoint: /data/wow/guild/{realm}/{guild}/roster  (guild: bleeding-hollow/skill-issues)

FAIL-OPEN (docs/DATABASE_DESIGN.md decision 7, §3.5, §3.2):
  * A failed fetch ADDS nothing and DELETES nothing. Every run is logged to
    fetch_run so gaps are visible, but a failure never mutates prior data.
  * observed_to (a departure) is only ever set by a run whose outcome is
    'success' AND whose roster pull is COMPLETE. A partial or failed run can
    never mark anyone as having left. This is the single most important write
    rule in the design.

HTTP uses stdlib urllib (no `requests` dependency) so it runs on the host
without a pip install. The network fetch is injected as `fetcher`, so this
module is fully unit-testable offline: tests pass a fake payload or a raising
fetcher — no live call, no credentials.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import db


# --------------------------------------------------------------------------
# Live HTTP client (used on the host / in the GitHub Action; not in tests)
# --------------------------------------------------------------------------
class BlizzardClient:
    """Minimal OAuth client-credentials + roster fetch over stdlib urllib."""

    def __init__(self, client_id: str, client_secret: str, region: str = "us",
                 timeout: int = 30):
        if not client_id or not client_secret:
            raise ValueError(
                "BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET are required for a live fetch"
            )
        self.client_id = client_id
        self.client_secret = client_secret
        self.region = region
        self.timeout = timeout
        self._token: Optional[str] = None

    @classmethod
    def from_env(cls, region: str = "us") -> "BlizzardClient":
        return cls(
            os.environ.get("BLIZZARD_CLIENT_ID", ""),
            os.environ.get("BLIZZARD_CLIENT_SECRET", ""),
            region=region,
        )

    def _get_token(self) -> str:
        if self._token:
            return self._token
        body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
        basic = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        req = urllib.request.Request(
            "https://oauth.battle.net/token", data=body,
            headers={"Authorization": f"Basic {basic}",
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            self._token = json.loads(resp.read().decode())["access_token"]
        return self._token

    def fetch_guild_roster(self, realm_slug: str, guild_slug: str) -> dict:
        token = self._get_token()
        path = f"/data/wow/guild/{realm_slug}/{guild_slug}/roster"
        qs = urllib.parse.urlencode(
            {"namespace": f"profile-{self.region}", "locale": "en_US"}
        )
        url = f"https://{self.region}.api.blizzard.com{path}?{qs}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode())


# --------------------------------------------------------------------------
# Payload parsing — pure function, no I/O
# --------------------------------------------------------------------------
_CLASS_BY_ID = {
    1: "Warrior", 2: "Paladin", 3: "Hunter", 4: "Rogue", 5: "Priest",
    6: "Death Knight", 7: "Shaman", 8: "Mage", 9: "Warlock", 10: "Monk",
    11: "Druid", 12: "Demon Hunter", 13: "Evoker",
}


def parse_roster(payload: dict, region: str = "us") -> list[dict]:
    """Normalise a Blizzard guild-roster payload into a list of member dicts."""
    members = []
    for m in payload.get("members", []):
        ch = m.get("character", {})
        realm = ch.get("realm", {})
        cls = ch.get("playable_class", {})
        members.append({
            "region": region,
            "realm_slug": realm.get("slug"),
            "name": ch.get("name"),
            "blizzard_id": ch.get("id"),
            "level": ch.get("level"),
            "class": _CLASS_BY_ID.get((cls or {}).get("id")),
            "faction": (ch.get("faction") or {}).get("type"),
            "rank": m.get("rank"),
        })
    return members


# --------------------------------------------------------------------------
# Ingestion — fail-open, append-only, success-only departures
# --------------------------------------------------------------------------
@dataclass
class IngestResult:
    run_id: int
    outcome: str                       # 'success' | 'partial' | 'failed'
    members_seen: int = 0
    surrogates_created: int = 0
    intervals_opened: int = 0
    intervals_closed: int = 0
    intervals_aged: int = 0            # confirmed-absent but still within the grace window
    unconfirmed_absent: int = 0       # open seed/competition-scope members Blizzard never confirmed (never closed by a Blizzard pull)
    identity_links_proposed: int = 0  # spelling/realm-drift matches raised for human review
    members_shielded: int = 0         # existing members protected from departure by a pending link candidate
    ambiguous_identities: int = 0     # observed names that fold-match >1 existing member (NOT merged)
    error: Optional[str] = None


def run_roster_ingest(conn, *, fetcher: Callable[[], dict],
                      region: str = "us",
                      guild_realm_slug: str = "bleeding-hollow",
                      guild_name_slug: str = "skill-issues",
                      guild_display_name: str = "Skill Issues",
                      complete_pull: bool = True,
                      grace_pulls: int = 2,
                      now: Optional[str] = None) -> IngestResult:
    """Ingest one guild-roster pull.

    `fetcher()` returns the raw Blizzard roster payload (or raises). On any
    exception, the run is recorded as 'failed' and NOTHING else is written:
    no identity, no interval, no profile, no departure. Prior data is untouched.

    Departures are hardened (2026-07-23, see docs/ENGINEERING_REVIEW.md). Before
    minting a new surrogate we reconcile the observed name against existing
    members (spelling/realm drift -> a human-reviewed identity_link_candidate,
    and the existing member is SHIELDED from departure). The sweep then closes
    only members Blizzard has actually confirmed, and only after `grace_pulls`
    consecutive complete pulls of absence. This is what stops a real, present
    member (e.g. both Viôlence and Violënce) being falsely marked departed.
    """
    now = now or db.now_utc()
    endpoint = f"/data/wow/guild/{guild_realm_slug}/{guild_name_slug}/roster"
    run_id = db.start_fetch_run(conn, "blizzard", endpoint, started_at=now)

    # ---- fetch (the only place a network error can occur) ----------------
    try:
        payload = fetcher()
    except Exception as exc:  # FAIL-OPEN: add nothing, delete nothing
        db.finish_fetch_run(conn, run_id, "failed", error_summary=f"{type(exc).__name__}: {exc}")
        return IngestResult(run_id=run_id, outcome="failed", error=str(exc))

    # ---- process (appends only; departures deferred to the very end) -----
    guild_id = db.get_or_create_guild(conn, region, guild_realm_slug,
                                      guild_name_slug, guild_display_name)
    members = parse_roster(payload, region=region)
    seen_char_ids: set[int] = set()
    shielded_ids: set[int] = set()
    deferred_links: list = []          # (new_cid, matched_cid, confidence, evidence)
    created = opened = links = ambiguous = 0
    try:
        for mem in members:
            if not mem["name"] or not mem["realm_slug"]:
                db.log_attempt(conn, run_id, target_key=str(mem.get("name")),
                               outcome="error", error="missing name/realm")
                continue

            # Reuse an exact-name surrogate if we have one; otherwise reconcile
            # BEFORE minting so drift doesn't duplicate + falsely depart a member.
            existing = db.find_character_by_identity(
                conn, mem["region"], mem["realm_slug"], mem["name"])
            if existing is not None:
                cid = existing
            else:
                # Who might this observed string already BE? (folding/blizzard_id)
                # Recorded now, resolved after the loop — a match that is ALSO
                # present under its own exact name this run is a distinct person,
                # not a link (that's how Viôlence + Violënce coexist cleanly).
                for cand_id, conf, evidence in db.find_link_candidates(
                        conn, mem["region"], mem["realm_slug"], mem["name"],
                        blizzard_id=mem["blizzard_id"]):
                    deferred_links.append((None, cand_id, conf, evidence))
                cid, was_created = db.mint_or_get_character(
                    conn, mem["region"], mem["realm_slug"], mem["name"],
                    source="blizzard", run_id=run_id, blizzard_id=mem["blizzard_id"],
                    observed_at=now,
                )
                created += int(was_created)
                # backfill the just-minted surrogate id onto its pending links
                deferred_links = [(cid if n is None else n, c, cf, ev)
                                  for (n, c, cf, ev) in deferred_links]

            seen_char_ids.add(cid)
            iid = db.open_membership_if_absent(conn, cid, guild_id, run_id=run_id,
                                              rank=mem["rank"], observed_from=now)
            opened += int(iid is not None)
            # This membership is now vouched for by an authoritative Blizzard pull.
            db.confirm_blizzard_membership(conn, cid, guild_id, run_id)
            db.insert_profile(conn, cid, source="blizzard", observed_at=now, run_id=run_id,
                              character_class=mem["class"], level=mem["level"],
                              faction=mem["faction"])
            db.log_attempt(conn, run_id, character_id=cid, http_status=200, outcome="ok")

        # ---- resolve identity links now the whole pull is known --------------
        by_new: dict = {}
        for new_cid, cand_id, conf, evidence in deferred_links:
            if cand_id in seen_char_ids:
                continue    # the match is present under its own exact name -> distinct person
            by_new.setdefault(new_cid, []).append((cand_id, conf, evidence))
        for new_cid, cands in by_new.items():
            for cand_id, conf, evidence in cands:
                db.propose_identity_link(conn, new_cid, cand_id, conf, evidence, now=now)
                shielded_ids.add(cand_id)          # never auto-depart a possible match
                links += 1
            if len(cands) > 1:
                ambiguous += 1
                # Anti-collapse guard: an accent-folding source made two real
                # people look like one. We minted ONE new surrogate and left
                # every candidate intact + shielded — never merged.
                print(f"::warning title=Ambiguous identity::new surrogate {new_cid} "
                      f"fold/blizzard-matches {len(cands)} existing members "
                      f"{[c[0] for c in cands]}; shielded all pending review — NOT merged.")
    except Exception as exc:
        conn.commit()
        db.finish_fetch_run(conn, run_id, "partial",
                            targets_attempted=len(members),
                            targets_succeeded=len(seen_char_ids),
                            error_summary=f"processing halted: {type(exc).__name__}: {exc}")
        return IngestResult(run_id=run_id, outcome="partial", members_seen=len(seen_char_ids),
                            surrogates_created=created, intervals_opened=opened,
                            identity_links_proposed=links, members_shielded=len(shielded_ids),
                            ambiguous_identities=ambiguous, error=str(exc))

    # ---- departures: ONLY on a complete, successful pull, and only for
    #      members Blizzard has confirmed, after the grace window ----------
    closed = aged = unconfirmed = 0
    if complete_pull and seen_char_ids:
        closed, aged, unconfirmed = db.reconcile_departures(
            conn, guild_id, run_id, seen_ids=seen_char_ids,
            shielded_ids=shielded_ids, now=now, grace_pulls=grace_pulls)
    conn.commit()
    db.finish_fetch_run(conn, run_id, "success",
                        targets_attempted=len(members),
                        targets_succeeded=len(seen_char_ids))
    return IngestResult(run_id=run_id, outcome="success", members_seen=len(seen_char_ids),
                        surrogates_created=created, intervals_opened=opened,
                        intervals_closed=closed, intervals_aged=aged,
                        unconfirmed_absent=unconfirmed, identity_links_proposed=links,
                        members_shielded=len(shielded_ids), ambiguous_identities=ambiguous)


def live_fetcher(region="us", guild_realm_slug="bleeding-hollow",
                 guild_name_slug="skill-issues") -> Callable[[], dict]:
    """Return a fetcher bound to a live BlizzardClient built from env credentials."""
    client = BlizzardClient.from_env(region=region)
    return lambda: client.fetch_guild_roster(guild_realm_slug, guild_name_slug)


if __name__ == "__main__":  # pragma: no cover
    # Live run (host / GitHub Action). Requires BLIZZARD_CLIENT_ID/SECRET.
    import argparse
    ap = argparse.ArgumentParser(description="Blizzard guild-roster ingest")
    ap.add_argument("--db", default="wipefest.sqlite3")
    ap.add_argument("--region", default="us")
    ap.add_argument("--realm", default="bleeding-hollow")
    ap.add_argument("--guild", default="skill-issues")
    args = ap.parse_args()
    conn = db.connect(args.db)
    db.init_db(conn)
    from .config import seed_field_authority
    seed_field_authority(conn)
    res = run_roster_ingest(
        conn, fetcher=live_fetcher(args.region, args.realm, args.guild),
        region=args.region, guild_realm_slug=args.realm,
        guild_name_slug=args.guild,
    )
    print(json.dumps(res.__dict__, indent=2))

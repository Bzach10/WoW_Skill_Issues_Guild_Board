"""Invariant tests for the S.S. Wipe Fest data layer.

Stdlib `unittest` ONLY — runs with `python -m unittest` and needs no PyPI
(pytest optional). Also discoverable by pytest on the host: `pytest tests/`.

Covers the four invariants the brief requires, plus zero-loss migration, plus
the 2026-07-23 departure hardening (the "28 departed" regression suite):
  1. Character-ID keying keeps the two Berobens separate.
  2. Viôlence / Violënce stay separate (no ASCII fold on the key).
  3. Append-only never overwrites.
  4. Fail-open keeps prior data on a simulated failed fetch.
  +  Migration imports the current roster with zero member loss.
  +  Departure hardening: no false departures from spelling/realm drift, no
     mass-departure of competition-scope seed on first pull, no accent-collapse
     merge, and a grace window before a confirmed member is closed.
"""
import os
import sys
import unittest

# make the package importable whether run from db_layer/ or tests/
_HERE = os.path.dirname(os.path.abspath(__file__))
_DB_LAYER = os.path.dirname(_HERE)
if _DB_LAYER not in sys.path:
    sys.path.insert(0, _DB_LAYER)

from wipefest_db import db  # noqa: E402
from wipefest_db.config import seed_field_authority  # noqa: E402
from wipefest_db.migrate_current import migrate  # noqa: E402
from wipefest_db import ingest_blizzard as ing  # noqa: E402

DATA_DIR = os.environ.get(
    "WIPEFEST_DATA_DIR", os.path.join(os.path.dirname(_DB_LAYER), "data")
)


def fresh_db():
    conn = db.connect(":memory:")
    db.init_db(conn)
    seed_field_authority(conn)
    return conn


def fake_roster(members):
    """Build a minimal Blizzard-shaped roster payload from (name, realm, id, rank) tuples."""
    return {
        "members": [
            {"rank": rank,
             "character": {"name": name, "id": bid,
                           "realm": {"slug": realm}, "level": 80,
                           "playable_class": {"id": 8},
                           "faction": {"type": "HORDE"}}}
            for (name, realm, bid, rank) in members
        ]
    }


class MigrationBackedTests(unittest.TestCase):
    """Tests that run against the real migrated snapshot."""

    @classmethod
    def setUpClass(cls):
        if not (os.path.exists(os.path.join(DATA_DIR, "competition.json"))
                and os.path.exists(os.path.join(DATA_DIR, "roster_supplement.json"))):
            raise unittest.SkipTest(f"data files not found in {DATA_DIR}")
        cls.conn = fresh_db()
        cls.recon = migrate(cls.conn, DATA_DIR)

    def test_migration_zero_loss(self):
        """147 distinct surrogates: 132 competition + 15 supplement, nobody dropped."""
        self.assertFalse(self.recon["skipped"])
        self.assertEqual(self.recon["total_surrogates"], 147)
        self.assertEqual(self.recon["competition_surrogates_created"], 132)
        self.assertEqual(self.recon["supplement_surrogates_created"], 15)
        self.assertEqual(self.recon["supplement_rows_that_collided_with_competition"], 0)
        # every open membership interval is a live member -> 147 current roster
        n = self.conn.execute("SELECT COUNT(*) FROM v_current_roster").fetchone()[0]
        self.assertEqual(n, 147)

    def test_two_berobens_stay_separate(self):
        """The name-collision bug (2307.3 destroyed) cannot recur: two surrogates."""
        rows = self.conn.execute(
            "SELECT character_id, realm_slug FROM character_identity "
            "WHERE name='Beroben' ORDER BY realm_slug"
        ).fetchall()
        self.assertEqual(len(rows), 2)
        ids = {r["character_id"] for r in rows}
        self.assertEqual(len(ids), 2, "two Berobens must map to two distinct surrogates")
        self.assertEqual({r["realm_slug"] for r in rows}, {"emerald-dream", "queldorei"})
        # both scores survive, each on its own surrogate
        scores = dict(self.conn.execute(
            "SELECT s.character_id, s.score FROM mplus_score_observation s "
            "JOIN character_identity ci ON ci.character_id=s.character_id "
            "WHERE ci.name='Beroben' AND s.role='all'"
        ).fetchall())
        self.assertEqual(sorted(scores.values()), [1907.8, 2307.3])

    def test_violence_pair_not_folded(self):
        """Viôlence and Violënce: identical folded form, different exact name -> 2 surrogates."""
        rows = self.conn.execute(
            "SELECT character_id, name, name_folded FROM character_identity "
            "WHERE realm_slug='bleeding-hollow' AND name_folded='violence'"
        ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({r["character_id"] for r in rows}), 2)
        # exact-name set must contain both accented forms; folding collapses them
        names = {r["name"] for r in rows}
        self.assertEqual(len(names), 2, "the two exact names must differ")
        self.assertEqual({r["name_folded"] for r in rows}, {"violence"})


class UnitInvariantTests(unittest.TestCase):
    """Focused unit tests that do not depend on the data files."""

    def test_accent_variants_never_fold_to_one_key(self):
        conn = fresh_db()
        run = db.start_fetch_run(conn, "manual", "test")
        a, ca = db.mint_or_get_character(conn, "us", "bleeding-hollow", "Viôlence",
                                         source="manual", run_id=run)
        b, cb = db.mint_or_get_character(conn, "us", "bleeding-hollow", "Viölence",
                                         source="manual", run_id=run)
        self.assertTrue(ca and cb)
        self.assertNotEqual(a, b, "accent-only difference must mint two surrogates")
        # same exact name in same realm reuses the surrogate (idempotent identity)
        a2, created = db.mint_or_get_character(conn, "us", "bleeding-hollow", "Viôlence",
                                               source="manual", run_id=run)
        self.assertFalse(created)
        self.assertEqual(a, a2)
        # same name, DIFFERENT realm is a different character
        c, cc = db.mint_or_get_character(conn, "us", "area-52", "Viôlence",
                                         source="manual", run_id=run)
        self.assertTrue(cc)
        self.assertNotEqual(a, c)

    def test_append_only_never_overwrites(self):
        conn = fresh_db()
        run = db.start_fetch_run(conn, "raiderio", "test")
        cid, _ = db.mint_or_get_character(conn, "us", "emerald-dream", "Beroben",
                                          source="raiderio", run_id=run)
        # first score
        db.insert_mplus_score(conn, cid, "season-mn-1", "all", 2307.3, "raiderio",
                              "2026-07-10T00:00:00Z", run)
        # a CHANGED score is a new row, not an overwrite
        db.insert_mplus_score(conn, cid, "season-mn-1", "all", 2500.0, "raiderio",
                              "2026-07-20T00:00:00Z", run)
        rows = conn.execute(
            "SELECT score, observed_at FROM mplus_score_observation "
            "WHERE character_id=? AND role='all' ORDER BY observed_at", (cid,)
        ).fetchall()
        self.assertEqual([r["score"] for r in rows], [2307.3, 2500.0],
                         "history retained; original NOT overwritten")
        # change-only insertion suppresses an identical repeat (no noise row, no mutation)
        res = db.insert_mplus_score(conn, cid, "season-mn-1", "all", 2500.0, "raiderio",
                                    "2026-07-21T00:00:00Z", run)
        self.assertIsNone(res)
        n = conn.execute("SELECT COUNT(*) FROM mplus_score_observation "
                         "WHERE character_id=?", (cid,)).fetchone()[0]
        self.assertEqual(n, 2, "unchanged repeat must not add a row")
        # the original 2307.3 is still on disk
        self.assertIsNotNone(conn.execute(
            "SELECT 1 FROM mplus_score_observation WHERE character_id=? AND score=2307.3",
            (cid,)).fetchone())

    def test_fail_open_keeps_prior_data(self):
        conn = fresh_db()
        # seed a good roster via a successful ingest
        ok = ing.run_roster_ingest(
            conn, fetcher=lambda: fake_roster([
                ("Alpha", "bleeding-hollow", 111, 0),
                ("Beta", "bleeding-hollow", 222, 5),
            ]),
        )
        self.assertEqual(ok.outcome, "success")
        before_chars = conn.execute("SELECT COUNT(*) FROM character").fetchone()[0]
        before_open = conn.execute(
            "SELECT COUNT(*) FROM membership_interval WHERE observed_to IS NULL"
        ).fetchone()[0]
        before_ids = conn.execute("SELECT COUNT(*) FROM character_identity").fetchone()[0]
        self.assertEqual((before_chars, before_open, before_ids), (2, 2, 2))

        # now a FAILED fetch: must add nothing, delete nothing, close nobody
        def boom():
            raise ConnectionError("simulated Blizzard outage")

        fail = ing.run_roster_ingest(conn, fetcher=boom)
        self.assertEqual(fail.outcome, "failed")

        after_chars = conn.execute("SELECT COUNT(*) FROM character").fetchone()[0]
        after_open = conn.execute(
            "SELECT COUNT(*) FROM membership_interval WHERE observed_to IS NULL"
        ).fetchone()[0]
        after_ids = conn.execute("SELECT COUNT(*) FROM character_identity").fetchone()[0]
        self.assertEqual((after_chars, after_open, after_ids),
                         (before_chars, before_open, before_ids),
                         "a failed fetch must not change prior data")
        # nobody was marked as departed
        closed = conn.execute(
            "SELECT COUNT(*) FROM membership_interval WHERE observed_to IS NOT NULL"
        ).fetchone()[0]
        self.assertEqual(closed, 0)
        # the failure IS logged, so the gap is visible
        failed_runs = conn.execute(
            "SELECT COUNT(*) FROM fetch_run WHERE outcome='failed'"
        ).fetchone()[0]
        self.assertGreaterEqual(failed_runs, 1)

    def test_departure_only_on_successful_complete_pull(self):
        """A confirmed member absent from complete pulls is closed AFTER the grace
        window (default 2 consecutive); a failed pull never closes anyone; a
        single absence only ages, it does not close (guards fail-open + grace)."""
        conn = fresh_db()
        ing.run_roster_ingest(conn, fetcher=lambda: fake_roster([
            ("Alpha", "bleeding-hollow", 111, 0),
            ("Beta", "bleeding-hollow", 222, 5),
        ]))  # both now Blizzard-confirmed
        # failed pull: Beta must NOT be closed and must NOT even age
        ing.run_roster_ingest(conn, fetcher=lambda: (_ for _ in ()).throw(IOError("x")))
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM membership_interval WHERE observed_to IS NOT NULL"
        ).fetchone()[0], 0)
        # 1st complete pull without Beta: Beta AGES (streak 1), not yet closed
        r1 = ing.run_roster_ingest(conn, fetcher=lambda: fake_roster([
            ("Alpha", "bleeding-hollow", 111, 0),
        ]))
        self.assertEqual(r1.intervals_closed, 0)
        self.assertEqual(r1.intervals_aged, 1)
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM membership_interval WHERE observed_to IS NOT NULL"
        ).fetchone()[0], 0, "a single missed pull must not evict a confirmed member")
        # 2nd consecutive complete pull without Beta: NOW Beta is closed, Alpha stays
        r2 = ing.run_roster_ingest(conn, fetcher=lambda: fake_roster([
            ("Alpha", "bleeding-hollow", 111, 0),
        ]))
        self.assertEqual(r2.intervals_closed, 1)
        closed = conn.execute(
            "SELECT ci.name FROM membership_interval mi "
            "JOIN character_identity ci ON ci.character_id=mi.character_id "
            "WHERE mi.observed_to IS NOT NULL"
        ).fetchall()
        self.assertEqual([r["name"] for r in closed], ["Beta"])
        # Beta's identity row still exists (never deleted)
        self.assertIsNotNone(conn.execute(
            "SELECT 1 FROM character_identity WHERE name='Beta'").fetchone())
        # Alpha, seen every pull, is never aged/closed
        self.assertIsNone(conn.execute(
            "SELECT mi.observed_to FROM membership_interval mi "
            "JOIN character_identity ci ON ci.character_id=mi.character_id "
            "WHERE ci.name='Alpha'").fetchone()["observed_to"])


class DepartureHardeningTests(unittest.TestCase):
    """Regression tests for the '28 departed incl. both Viôlences' bug
    (docs/ENGINEERING_REVIEW.md). These are the paths the old ingest broke:
    cross-source spelling drift, competition-scope seed, and accent-collapse."""

    def _closed_names(self, conn):
        return [r["name"] for r in conn.execute(
            "SELECT ci.name FROM membership_interval mi "
            "JOIN character_identity ci ON ci.character_id=mi.character_id "
            "WHERE mi.observed_to IS NOT NULL")]

    def test_spelling_drift_does_not_falsely_depart(self):
        """A confirmed member returning under a drifted spelling (accent dropped
        by the source) must NOT be departed or duplicated-then-orphaned: the
        original is shielded and a pending link candidate is raised."""
        conn = fresh_db()
        # pull 1: the real accented member, Blizzard-confirmed
        ing.run_roster_ingest(conn, fetcher=lambda: fake_roster([
            ("Viôlence", "bleeding-hollow", 501, 5)]))
        # pull 2: same person, source dropped the accent + gave a new id
        res = ing.run_roster_ingest(conn, fetcher=lambda: fake_roster([
            ("Violence", "bleeding-hollow", 502, 5)]))
        # the accented original is NOT departed
        self.assertEqual(self._closed_names(conn), [])
        self.assertEqual(res.intervals_closed, 0)
        # it was shielded and a candidate was raised for a human to resolve
        self.assertGreaterEqual(res.members_shielded, 1)
        self.assertEqual(res.identity_links_proposed, 1)
        cand = conn.execute(
            "SELECT confidence, evidence_json, status FROM identity_link_candidate"
        ).fetchone()
        self.assertEqual(cand["status"], "pending")
        self.assertEqual(cand["confidence"], "low")          # fold match is ambiguous
        self.assertIn("accent_fold", cand["evidence_json"])
        # both exact names now exist as distinct surrogates (never merged)
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM character_identity "
            "WHERE name_folded='violence'").fetchone()[0], 2)

    def test_blizzard_id_drift_raises_high_confidence_link(self):
        """Same blizzard_id, new (realm,name) = a rename/transfer signal: shield
        + a stronger candidate, still never auto-applied."""
        conn = fresh_db()
        ing.run_roster_ingest(conn, fetcher=lambda: fake_roster([
            ("Oldname", "bleeding-hollow", 900, 5)]))
        res = ing.run_roster_ingest(conn, fetcher=lambda: fake_roster([
            ("Newname", "bleeding-hollow", 900, 5)]))   # same id, same realm
        self.assertEqual(res.intervals_closed, 0)
        self.assertEqual(self._closed_names(conn), [])
        cand = conn.execute(
            "SELECT confidence, evidence_json FROM identity_link_candidate").fetchone()
        self.assertEqual(cand["confidence"], "high")         # same-realm id match
        self.assertIn("blizzard_id", cand["evidence_json"])

    def test_competition_scope_seed_not_mass_departed_on_first_pull(self):
        """The migration seeds a WIDER (raider.io competition) scope than the
        guild roster. First Blizzard contact must confirm those it lists and
        leave the rest OPEN — never evict everyone Blizzard doesn't return."""
        conn = fresh_db()
        seed = db.start_fetch_run(conn, "legacy_json", "seed")
        gid = db.get_or_create_guild(conn, "us", "bleeding-hollow", "skill-issues", "Skill Issues")
        for name, realm in [("Inguild", "bleeding-hollow"),
                            ("Crossrealm", "stormrage"),      # competition-scope, not a guild member
                            ("Alsoseed", "area-52")]:
            cid, _ = db.mint_or_get_character(conn, "us", realm, name,
                                              source="raiderio", run_id=seed)
            db.open_membership_if_absent(conn, cid, gid, run_id=seed)
        db.finish_fetch_run(conn, seed, "success")
        # Blizzard returns only the one true guild member
        res = ing.run_roster_ingest(conn, fetcher=lambda: fake_roster([
            ("Inguild", "bleeding-hollow", 1, 0)]))
        self.assertEqual(res.intervals_closed, 0, "no seed member may be closed on first pull")
        self.assertEqual(res.unconfirmed_absent, 2, "the two unseen seed members stay open, unconfirmed")
        self.assertEqual(self._closed_names(conn), [])
        # all three still current; exactly one is Blizzard-confirmed
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM v_current_roster").fetchone()[0], 3)
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM v_blizzard_confirmed_roster").fetchone()[0], 1)

    def test_accent_collapse_never_merges_two_people(self):
        """The exact sim from the review: a folding source returns one 'Violence'
        for two real people. We mint ONE new surrogate, shield BOTH twins, raise
        TWO candidates, flag ambiguity — and merge NOBODY, depart NOBODY."""
        conn = fresh_db()
        # both twins confirmed first
        ing.run_roster_ingest(conn, fetcher=lambda: fake_roster([
            ("Viôlence", "bleeding-hollow", 601, 5),
            ("Violënce", "bleeding-hollow", 602, 5)]))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM character").fetchone()[0], 2)
        # source folds both to "Violence" in a later pull
        res = ing.run_roster_ingest(conn, fetcher=lambda: fake_roster([
            ("Violence", "bleeding-hollow", 603, 5)]))
        self.assertEqual(res.surrogates_created, 1, "mint exactly one new surrogate, not a merge")
        self.assertEqual(res.ambiguous_identities, 1)
        self.assertEqual(res.members_shielded, 2, "both twins shielded")
        self.assertEqual(res.intervals_closed, 0, "neither twin departed")
        self.assertEqual(self._closed_names(conn), [])
        # 3 distinct people on record now; 2 pending links for a human to resolve
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM character").fetchone()[0], 3)
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM identity_link_candidate WHERE status='pending'"
        ).fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

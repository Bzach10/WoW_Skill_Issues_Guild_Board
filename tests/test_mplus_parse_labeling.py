"""Regression tests for the M+ season-parse value/label contract.

The bug: collect_mplus_wcl_parses claimed to return Warcraft Logs parse
percentiles but actually re-queried Raider.io and returned unbounded
Raider.io *scores* tagged is_wcl=True. formatters.py renders anything so
tagged with a percent sign, so the board published "456% on Skyreach" —
impossible, since a parse percentile is 0-100.

The invariant these lock down: a tuple may only carry is_wcl=True if its
value is a real percentile.
"""

import pytest

from guild_board import raiderio

CFG = {"guild": {"region": "us", "realm_slug": "bleeding-hollow"}}

# (score, dungeon, name, spec, is_wcl) — the shape the collectors return.
RAIDERIO_RESULTS = [
    (456.2, "Grim Batol", "Rakdisc", "Discipline Priest", False),
    (455.9, "The Stonevault", "Floofwall", "Brewmaster Monk", False),
]


def test_wcl_enrichment_returns_nothing_rather_than_mislabeled_scores():
    """It must not invent WCL data. Returning [] leaves the caller's
    correctly-labelled Raider.io scores in place."""
    assert raiderio.collect_mplus_wcl_parses(CFG, "tok", RAIDERIO_RESULTS) == []


def test_wcl_enrichment_makes_no_network_call(monkeypatch):
    """The old body issued 15 Raider.io requests per run while claiming to
    talk to WCL. It should now issue none."""
    def boom(*a, **kw):
        raise AssertionError("collect_mplus_wcl_parses must not make requests")

    monkeypatch.setattr(raiderio.requests, "get", boom)
    assert raiderio.collect_mplus_wcl_parses(CFG, "tok", RAIDERIO_RESULTS) == []


@pytest.mark.parametrize("results", [
    RAIDERIO_RESULTS,
    [],
    [(1.0, "Grim Batol", "X", "Y", False)],
])
def test_enrichment_never_upgrades_a_score_to_a_percentile(results):
    """Whatever enrichment returns, no entry may claim is_wcl=True with a
    value outside 0-100. This is the invariant the old code violated, and
    it stays meaningful if the WCL query is implemented for real later."""
    for value, _dungeon, _name, _spec, is_wcl in raiderio.collect_mplus_wcl_parses(
            CFG, "tok", results):
        if is_wcl:
            assert 0 <= value <= 100, (
                f"{value} is tagged as a WCL parse percentile but is outside 0-100")


def test_season_parses_keep_raiderio_labeling_when_enrichment_is_empty(monkeypatch):
    """End-to-end: with enrichment returning nothing, collect_mplus_season_parses
    passes Raider.io scores through with is_wcl=False, so the board renders
    "<n> score" and not "<n>%"."""
    monkeypatch.setattr(raiderio, "collect_mplus_raiderio_season_runs",
                        lambda cfg, roster: (list(RAIDERIO_RESULTS), None))
    monkeypatch.setattr(raiderio, "resolve_roster", lambda *a, **kw: ([], False),
                        raising=False)
    monkeypatch.setattr("guild_board.config.resolve_roster",
                        lambda *a, **kw: (["rakdisc-proudmoore"], False))

    cfg = {**CFG, "sections": {"mplus_season_parses": {"use_wcl_parses": True}}}
    results, _top = raiderio.collect_mplus_season_parses(cfg, "tok")

    assert results, "expected the Raider.io results to survive"
    for value, _d, _n, _s, is_wcl in results:
        assert is_wcl is False
        assert value > 100  # a real Raider.io score, correctly not a percentile

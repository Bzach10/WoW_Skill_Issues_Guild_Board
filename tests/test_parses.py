"""Per-character WCL parse averages: fetch normalization, the pure
build_parses layer, the competition merge, and the delivery set.

Everything runs offline: wcl.gql is monkeypatched, never called live.

The one invariant this file guards hardest: parse data is keyed by the
FULL name-realm key (exact Unicode), never the bare name. board_state's
bare-name season_scores keying is a documented data-destroying bug for
same-named characters on different realms — this layer must not repeat it.
"""

import os
import subprocess
import sys

from guild_board import config as gb_config
from guild_board import wcl
from guild_board.competition import build_competition, fetch_competition
from guild_board.web_data import build_parses, build_site_data

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CFG = {"guild": {"name": "Skill Issues", "realm_slug": "bleeding-hollow",
                 "region": "us"}}


def _blob(avg, median=None, kills=None):
    out = {"bestPerformanceAverage": avg}
    if median is not None:
        out["medianPerformanceAverage"] = median
    if kills is not None:
        out["totalKills"] = kills
    return out


# ---------------------------------------------------------------------------
# normalize_character_parses — pure
# ---------------------------------------------------------------------------

def test_normalize_full_blob_rounds_and_buckets_roles():
    char = {
        "name": "Rakdisc", "classID": 7,
        "overall_dps": _blob(41.25, median=30.0),
        "overall_hps": _blob(88.123, median=74.456),
        "dps": _blob(41.25, kills=2),
        "healer": _blob(88.123, kills=6),
        "tank": _blob(None),
    }
    entry = wcl.normalize_character_parses(char)
    assert entry["name"] == "Rakdisc"
    assert entry["class"] == "Priest"  # WCL id 7 is Priest, not Blizzard's Shaman
    assert entry["best_perf_avg"] == 88.1
    assert entry["median_perf_avg"] == 74.5
    assert set(entry["by_role"]) == {"DPS", "Healer"}  # tank blob empty -> absent
    assert entry["by_role"]["Healer"] == {"best_perf_avg": 88.1, "kills": 6}
    assert entry["by_role"]["DPS"] == {"best_perf_avg": 41.2, "kills": 2}
    # BEST-ACROSS-METRICS: counted on hps here, with both figures kept and
    # the median taken from the SAME blob the counted figure came from.
    assert entry["metric"] == "hps"
    assert entry["by_metric"] == {"dps": 41.2, "hps": 88.1}


def test_normalize_counts_the_better_overall_metric():
    # THE HEALER BUG (2026-07-26): the overall blob asked for `metric:
    # default`, which WCL resolved per its own spec detection and handed
    # most healers their DAMAGE percentile (Hellful mythic 84.0 damage
    # beside 19.9 real healing). Both metrics are asked for now and the
    # higher one counts — which also pays dual-spec raiders for their
    # better spec instead of guessing at a roster role.
    healer = wcl.normalize_character_parses(
        {"name": "Shadoxii", "classID": 5,
         "overall_dps": _blob(16.7, median=12.1),
         "overall_hps": _blob(53.0, median=43.1)})
    assert (healer["best_perf_avg"], healer["metric"]) == (53.0, "hps")
    assert healer["median_perf_avg"] == 43.1

    dual = wcl.normalize_character_parses(
        {"name": "Hellful", "classID": 9,
         "overall_dps": _blob(84.0, median=74.9),
         "overall_hps": _blob(19.9, median=15.0)})
    assert (dual["best_perf_avg"], dual["metric"]) == (84.0, "dps")
    assert dual["median_perf_avg"] == 74.9

    # One metric answering alone is enough; a tie counts as dps.
    solo = wcl.normalize_character_parses(
        {"name": "Aime", "classID": 2, "overall_hps": _blob(61.0)})
    assert (solo["best_perf_avg"], solo["metric"]) == (61.0, "hps")
    tied = wcl.normalize_character_parses(
        {"name": "Aime", "classID": 2,
         "overall_dps": _blob(61.0), "overall_hps": _blob(61.0)})
    assert tied["metric"] == "dps"


def test_query_asks_both_overall_metrics_and_never_default():
    q = wcl.CHARACTER_PARSES_QUERY
    assert "metric: default" not in q
    assert "overall_dps: zoneRankings" in q and "overall_hps: zoneRankings" in q
    # Unbracketed: the overall blobs carry no role filter...
    for line in q.splitlines():
        if line.strip().startswith("overall_"):
            assert "role:" not in line
    # ...while the by-role sub-queries keep their own metrics unchanged.
    assert "metric: dps, role: DPS" in q
    assert "metric: hps, role: Healer" in q
    assert "metric: dps, role: Tank" in q


def test_normalize_no_rankings_is_none():
    assert wcl.normalize_character_parses(None) is None
    assert wcl.normalize_character_parses({}) is None
    assert wcl.normalize_character_parses(
        {"name": "Aiime", "classID": 4, "overall_dps": _blob(None),
         "overall_hps": _blob(None), "dps": _blob(None),
         "healer": _blob(None), "tank": _blob(None)}) is None


def test_normalize_role_blob_alone_still_counts():
    entry = wcl.normalize_character_parses(
        {"name": "Floofwall", "classID": 5, "overall_dps": _blob(None),
         "tank": _blob(71.9, kills=5)})
    assert entry["best_perf_avg"] == 71.9
    assert entry["by_role"] == {"Tank": {"best_perf_avg": 71.9, "kills": 5}}


# ---------------------------------------------------------------------------
# fetch_character_parses — mocked gql
# ---------------------------------------------------------------------------

def _fake_gql(answers, calls):
    """answers: {(name, difficulty): character-or-None}. Records every call."""
    def fake(token, query, variables):
        calls.append(dict(variables))
        char = answers.get((variables["name"], variables["difficulty"]))
        return {"characterData": {"character": char}}
    return fake


def test_fetch_keys_by_full_name_realm_never_bare_name(monkeypatch):
    # The bug guard: same bare name on two realms must stay two entries.
    roster = ["violënce-bleeding-hollow", "violënce-area-52"]
    per_realm = {
        "bleeding-hollow": {"name": "Violënce", "classID": 11,
                            "overall_dps": _blob(90.0), "dps": _blob(90.0, kills=8)},
        "area-52": {"name": "Violënce", "classID": 2,
                    "overall_dps": _blob(30.0), "dps": _blob(30.0, kills=1)},
    }
    calls = []

    def fake(token, query, variables):
        calls.append(dict(variables))
        return {"characterData": {"character": per_realm.get(variables["slug"])}}

    monkeypatch.setattr(wcl, "gql", fake)
    monkeypatch.setattr(wcl.time, "sleep", lambda s: None)

    out = wcl.fetch_character_parses("tok", CFG, roster, zone_id=46)
    assert set(out) == set(roster)
    bh = out["violënce-bleeding-hollow"]["by_difficulty"]
    a52 = out["violënce-area-52"]["by_difficulty"]
    assert bh["mythic"]["best_perf_avg"] == 90.0
    assert a52["mythic"]["best_perf_avg"] == 30.0
    # The exact-Unicode name and the full realm slug reached the API.
    assert {c["name"] for c in calls} == {"violënce"}
    assert {c["slug"] for c in calls} == {"bleeding-hollow", "area-52"}


def test_fetch_splits_multiword_realms_on_first_hyphen(monkeypatch):
    calls = []
    monkeypatch.setattr(wcl, "gql", _fake_gql({}, calls))
    monkeypatch.setattr(wcl.time, "sleep", lambda s: None)
    wcl.fetch_character_parses("tok", CFG, ["rhansìk-area-52"], zone_id=46)
    assert calls[0]["name"] == "rhansìk"
    assert calls[0]["slug"] == "area-52"


def test_fetch_collects_every_enabled_difficulty(monkeypatch):
    # The website shows mythic and heroic side by side, so BOTH are
    # fetched — a mythic answer must never stop the heroic query.
    char_mythic = {"name": "Aiime", "classID": 4, "overall_dps": _blob(80.0),
                   "dps": _blob(80.0, kills=5)}
    char_heroic = {"name": "Aiime", "classID": 4, "overall_dps": _blob(95.5),
                   "dps": _blob(95.5, kills=9)}
    answers = {("aiime", 5): char_mythic, ("aiime", 4): char_heroic}
    calls = []
    monkeypatch.setattr(wcl, "gql", _fake_gql(answers, calls))
    monkeypatch.setattr(wcl.time, "sleep", lambda s: None)

    out = wcl.fetch_character_parses("tok", CFG, ["aiime-bleeding-hollow"],
                                     zone_id=46, difficulties=(5, 4))
    entry = out["aiime-bleeding-hollow"]
    assert entry["key"] == "aiime-bleeding-hollow"
    assert entry["name"] == "Aiime"
    assert entry["sourced_at"]
    assert entry["by_difficulty"]["mythic"]["best_perf_avg"] == 80.0
    assert entry["by_difficulty"]["heroic"]["best_perf_avg"] == 95.5
    assert [c["difficulty"] for c in calls] == [5, 4]  # both queried


def test_fetch_keeps_heroic_only_raiders(monkeypatch):
    # Empty at mythic (character exists, no rankings) -> heroic still lands.
    char_empty = {"name": "Aiime", "classID": 4, "overall_dps": _blob(None)}
    char_heroic = {"name": "Aiime", "classID": 4, "overall_dps": _blob(65.5),
                   "dps": _blob(65.5, kills=3)}
    answers = {("aiime", 5): char_empty, ("aiime", 4): char_heroic}
    calls = []
    monkeypatch.setattr(wcl, "gql", _fake_gql(answers, calls))
    monkeypatch.setattr(wcl.time, "sleep", lambda s: None)

    out = wcl.fetch_character_parses("tok", CFG, ["aiime-bleeding-hollow"],
                                     zone_id=46, difficulties=(5, 4))
    entry = out["aiime-bleeding-hollow"]
    assert set(entry["by_difficulty"]) == {"heroic"}
    assert entry["by_difficulty"]["heroic"]["best_perf_avg"] == 65.5


def test_fetch_unknown_character_skips_lower_difficulties(monkeypatch):
    # character: null means WCL has never seen them — lower difficulties
    # cannot help, so exactly one query is spent.
    calls = []
    monkeypatch.setattr(wcl, "gql", _fake_gql({}, calls))
    monkeypatch.setattr(wcl.time, "sleep", lambda s: None)
    out = wcl.fetch_character_parses("tok", CFG, ["ghost-bleeding-hollow"], zone_id=46)
    assert out == {}
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# build_parses — pure layer
# ---------------------------------------------------------------------------

def test_build_parses_degrades_without_cache():
    layer = build_parses(None)
    assert layer["available"] is False
    assert layer["status"] == "pending_credentials"
    assert layer["characters"] == {}
    assert layer["character_count"] == 0
    # Shipped copy must never name credential environment variables.
    assert "WCL_CLIENT" not in str(layer)


def _fetched_one(key="amrevenge-stormrage", name="Amrevenge", avg=92.4, diff=5):
    return {
        "last_updated": "2026-07-24T13:30:00+00:00",
        "tier": {"zone_id": 46, "name": "Voidspire Sanctum"},
        "characters": {key: {"name": name, "best_perf_avg": avg, "by_role": {},
                             "difficulty": diff,
                             "sourced_at": "2026-07-24T13:30:00+00:00"}},
    }


def test_build_parses_applies_difficulty_scale_at_build_time():
    scale = {"mythic": 1.0, "heroic": 0.8, "normal": 0.6}
    heroic = build_parses(_fetched_one(avg=71.9, diff=4), difficulty_scale=scale)
    entry = heroic["characters"]["amrevenge-stormrage"]
    assert entry["best_perf_avg"] == 71.9          # raw is never overwritten
    assert entry["scaled_perf_avg"] == 57.5        # 71.9 * 0.8, rounded
    assert entry["difficulty_scale"] == 0.8
    assert heroic["difficulty_scale"]["heroic"] == 0.8  # envelope provenance

    mythic = build_parses(_fetched_one(avg=92.4, diff=5), difficulty_scale=scale)
    assert mythic["characters"]["amrevenge-stormrage"]["scaled_perf_avg"] == 92.4


def test_build_parses_unconfigured_scale_is_identity():
    layer = build_parses(_fetched_one(avg=88.0, diff=4))
    entry = layer["characters"]["amrevenge-stormrage"]
    assert entry["scaled_perf_avg"] == 88.0
    assert entry["difficulty_scale"] == 1.0


def test_build_parses_scale_is_forgiving_and_capped():
    # Officer-edited YAML: junk values must not break the build, and a
    # factor > 1 can never mint a percentile above 100. A factor clamped
    # to 0 (negative or explicit) EXCLUDES that difficulty's characters.
    scale = {"mythic": 1.5, "heroic": "not-a-number", "normal": -2}
    layer = build_parses({
        "last_updated": "x", "tier": {},
        "characters": {
            "a-bleeding-hollow": {"name": "A", "best_perf_avg": 90.0,
                                  "by_role": {}, "difficulty": 5, "sourced_at": "x"},
            "b-bleeding-hollow": {"name": "B", "best_perf_avg": 70.0,
                                  "by_role": {}, "difficulty": 4, "sourced_at": "x"},
            "c-bleeding-hollow": {"name": "C", "best_perf_avg": 50.0,
                                  "by_role": {}, "difficulty": 3, "sourced_at": "x"},
        }}, difficulty_scale=scale)
    chars = layer["characters"]
    assert chars["a-bleeding-hollow"]["scaled_perf_avg"] == 100.0  # capped
    assert chars["b-bleeding-hollow"]["scaled_perf_avg"] == 70.0   # junk -> 1.0
    assert "c-bleeding-hollow" not in chars                        # 0 -> excluded
    assert layer["character_count"] == 2


def test_build_parses_zero_factor_excludes_not_zeroes():
    # normal: 0.0 means "not available" — the character disappears from the
    # layer (the site shows its existing "no logs yet" state), never a
    # 0.0% row. The raw cache is untouched, so re-enabling is loss-free.
    scale = {"mythic": 1.0, "heroic": 0.8, "normal": 0.0}
    layer = build_parses({
        "last_updated": "x", "tier": {},
        "characters": {
            "hero-bleeding-hollow": {"name": "Hero", "best_perf_avg": 80.0,
                                     "by_role": {}, "difficulty": 4, "sourced_at": "x"},
            "norm-bleeding-hollow": {"name": "Norm", "best_perf_avg": 95.0,
                                     "by_role": {}, "difficulty": 3, "sourced_at": "x"},
        }}, difficulty_scale=scale)
    assert set(layer["characters"]) == {"hero-bleeding-hollow"}
    assert layer["character_count"] == 1
    assert layer["difficulty_scale"]["normal"] == 0.0  # provenance still records it


def test_build_parses_headline_is_best_scaled_across_difficulties():
    # A heroic 95 at x0.8 (76) loses to a mythic 80 — the headline triple
    # (best/scaled/difficulty) must all come from the WINNING sub-entry,
    # and both difficulties stay browsable in by_difficulty.
    scale = {"mythic": 1.0, "heroic": 0.8, "normal": 0.0}
    layer = build_parses({
        "last_updated": "x", "tier": {"zone_id": 46},
        "characters": {"aiime-bleeding-hollow": {
            "name": "Aiime", "class": "Mage", "key": "aiime-bleeding-hollow",
            "sourced_at": "x",
            "by_difficulty": {
                "mythic": {"best_perf_avg": 80.0,
                           "by_role": {"DPS": {"best_perf_avg": 80.0}}},
                "heroic": {"best_perf_avg": 95.0,
                           "by_role": {"DPS": {"best_perf_avg": 95.0}}},
            }}}}, difficulty_scale=scale)
    e = layer["characters"]["aiime-bleeding-hollow"]
    assert e["best_perf_avg"] == 80.0
    assert e["scaled_perf_avg"] == 80.0
    assert e["difficulty"] == 5
    assert e["by_difficulty"]["heroic"]["scaled_perf_avg"] == 76.0
    assert e["by_difficulty"]["mythic"]["scaled_perf_avg"] == 80.0


def test_build_parses_drops_zero_factor_difficulty_but_keeps_the_rest():
    # normal: 0.0 removes the normal sub-entry; a character with ONLY
    # normal data disappears entirely (the "not available" state).
    scale = {"mythic": 1.0, "heroic": 0.8, "normal": 0.0}
    layer = build_parses({
        "last_updated": "x", "tier": {},
        "characters": {
            "both-bleeding-hollow": {
                "name": "Both", "sourced_at": "x",
                "by_difficulty": {"heroic": {"best_perf_avg": 70.0},
                                  "normal": {"best_perf_avg": 99.0}}},
            "normonly-bleeding-hollow": {
                "name": "Normonly", "sourced_at": "x",
                "by_difficulty": {"normal": {"best_perf_avg": 95.0}}},
        }}, difficulty_scale=scale)
    chars = layer["characters"]
    assert set(chars) == {"both-bleeding-hollow"}
    assert set(chars["both-bleeding-hollow"]["by_difficulty"]) == {"heroic"}


def test_sweep_difficulties_follows_the_scale_knob():
    from guild_board.web_data import sweep_difficulties
    assert sweep_difficulties(None) == (5, 4, 3)                  # unconfigured
    assert sweep_difficulties({"normal": 0.0}) == (5, 4)          # excluded
    assert sweep_difficulties(
        {"mythic": 0, "heroic": 0, "normal": 0}) == ()            # nothing left
    assert sweep_difficulties({"heroic": 0.8, "normal": 0.6}) == (5, 4, 3)


def test_build_parses_stamps_tier_onto_every_character():
    fetched = {
        "last_updated": "2026-07-24T13:30:00+00:00",
        "tier": {"zone_id": 46, "name": "Voidspire Sanctum"},
        "characters": {
            "amrevenge-stormrage": {"name": "Amrevenge", "best_perf_avg": 92.4,
                                    "by_role": {}, "difficulty": 5,
                                    "sourced_at": "2026-07-24T13:30:00+00:00"},
        },
    }
    layer = build_parses(fetched)
    assert layer["available"] is True
    assert layer["sourced_at"] == "2026-07-24T13:30:00+00:00"
    entry = layer["characters"]["amrevenge-stormrage"]
    assert entry["key"] == "amrevenge-stormrage"
    assert entry["tier"] == {"zone_id": 46, "name": "Voidspire Sanctum"}
    assert layer["character_count"] == 1


# ---------------------------------------------------------------------------
# competition merge — by full key, with board_state fallback
# ---------------------------------------------------------------------------

def _comp_char(name, key, score=1000.0, role="DPS"):
    return {"name": name, "realm": key.split("-", 1)[1], "key": key,
            "class": "Hunter", "spec": "Marksmanship", "role": role,
            "score": score, "scores_by_role": {}, "best_runs": [], "ranks": {}}


def test_competition_merges_wcl_parse_by_key_not_name():
    fetched = {"characters": [
        _comp_char("Violënce", "violënce-bleeding-hollow", 3000.0),
        _comp_char("Violënce", "violënce-area-52", 2000.0),
        _comp_char("Amrevenge", "amrevenge-stormrage", 3900.0),
    ]}
    board_state = {"records": {"best_dps_parse": {
        "name": "Amrevenge", "parse": 96, "boss": "Fallen-King Salhadaar"}}}
    wcl_parses = build_parses({
        "last_updated": "2026-07-24T13:30:00+00:00",
        "tier": {"zone_id": 46, "name": "Voidspire Sanctum"},
        "characters": {
            "violënce-bleeding-hollow": {"name": "Violënce", "best_perf_avg": 90.0,
                                         "by_role": {"DPS": {"best_perf_avg": 90.0}},
                                         "difficulty": 5, "sourced_at": "x"},
            "violënce-area-52": {"name": "Violënce", "best_perf_avg": 30.0,
                                 "by_role": {"DPS": {"best_perf_avg": 30.0}},
                                 "difficulty": 3, "sourced_at": "x"},
        },
    }, difficulty_scale={"mythic": 1.0, "heroic": 0.8, "normal": 0.6})
    comp = build_competition(fetched, board_state, wcl_parses=wcl_parses)
    by_key = {c["key"]: c for c in comp["characters"]}
    # Same bare name, two realms, two different parses — never collapsed.
    assert by_key["violënce-bleeding-hollow"]["parse"]["best"] == 90.0
    assert by_key["violënce-area-52"]["parse"]["best"] == 30.0
    # The competition merge carries the discounted value for rankings and
    # the per-difficulty split for the site's mythic/heroic columns.
    assert by_key["violënce-bleeding-hollow"]["parse"]["scaled"] == 90.0
    assert by_key["violënce-area-52"]["parse"]["scaled"] == 18.0  # 30 * 0.6
    assert "mythic" in by_key["violënce-bleeding-hollow"]["parse"]["by_difficulty"]
    assert by_key["violënce-area-52"]["parse"]["source"] == "wcl_zone_rankings"
    # No WCL entry -> board_state record fallback still applies.
    assert by_key["amrevenge-stormrage"]["parse"]["source"] == "board_state"
    assert comp["parses"]["available"] == "full"
    assert comp["parses"]["characters_with_parses"] == 2


def test_competition_parse_block_stays_partial_without_wcl():
    fetched = {"characters": [_comp_char("Amrevenge", "amrevenge-stormrage")]}
    board_state = {"records": {"best_dps_parse": {
        "name": "Amrevenge", "parse": 96, "boss": "Fallen-King Salhadaar"}}}
    comp = build_competition(fetched, board_state)
    assert comp["parses"]["available"] == "partial"


def test_mixed_case_manual_roster_entry_still_merges_parses(monkeypatch):
    """Regression: config.yml's documented manual roster format is mixed-case
    ("Rakell-Proudmoore"). Casing is folded once at roster ingestion
    (config.normalize_roster_entry), so the competition record and the WCL
    parse sweep key the character identically and the merge holds. Before
    the fold, competition lowercased its copy of the key while the sweep
    kept the entry verbatim — the parse silently failed to merge for
    exactly this kind of entry.
    """
    cfg = {
        "guild": {"name": "Skill Issues", "realm_slug": "bleeding-hollow",
                  "region": "us"},
        "sections": {"mplus": {"roster": ["Rakell-Proudmoore"]}},
    }
    # Ingestion: the manual override comes out canonical...
    roster, _ = gb_config.resolve_roster(cfg)
    assert roster == ["rakell-proudmoore"]

    # ...and the SAME list feeds both fetch paths, as the pipeline does.
    class Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"name": "Rakell", "realm": "Proudmoore",
                    "class": "Paladin", "active_spec_name": "Holy",
                    "active_spec_role": "HEALING",
                    "mythic_plus_scores_by_season": [
                        {"scores": {"all": 2800.0, "healer": 2800.0}}]}

    monkeypatch.setattr("guild_board.raiderio._rio_get",
                        lambda params=None, timeout=None: Resp())
    fetched = fetch_competition(cfg, roster=roster)
    assert [c["key"] for c in fetched["characters"]] == ["rakell-proudmoore"]

    answers = {("rakell", 5): {"name": "Rakell", "classID": 6,
                               "overall_hps": _blob(77.0),
                               "healer": _blob(77.0, kills=4)}}
    calls = []
    monkeypatch.setattr(wcl, "gql", _fake_gql(answers, calls))
    monkeypatch.setattr(wcl.time, "sleep", lambda s: None)
    parses = wcl.fetch_character_parses("tok", CFG, roster, zone_id=46)
    assert set(parses) == {"rakell-proudmoore"}

    wcl_parses = build_parses({"last_updated": "x", "tier": {"zone_id": 46},
                               "characters": parses})
    comp = build_competition(fetched, {}, wcl_parses=wcl_parses)
    by_key = {c["key"]: c for c in comp["characters"]}
    assert by_key["rakell-proudmoore"]["parse"]["source"] == "wcl_zone_rankings"
    assert by_key["rakell-proudmoore"]["parse"]["best"] == 77.0


# ---------------------------------------------------------------------------
# zone pinning + extra zones (bonus raids like Sporefall/Rotmire)
# ---------------------------------------------------------------------------

def test_resolve_zone_id_matches_exact_then_containment():
    zones = [{"id": 44, "name": "Old Tier"},
             {"id": 46, "name": "VS / DR / MQD"},
             {"id": 47, "name": "Sporefall"}]
    # Exact (case-insensitive).
    assert wcl.resolve_zone_id(zones, "sporefall") == 47
    # WCL's short tier name is contained in Raider.io's api_name.
    assert wcl.resolve_zone_id(zones, "MN Tier 1 (VS / DR / MQD)") == 46
    # No match -> None, never a guess.
    assert wcl.resolve_zone_id(zones, "The Venomous Abyss") is None
    assert wcl.resolve_zone_id(zones, "") is None
    assert wcl.resolve_zone_id([], "Sporefall") is None


def test_build_parses_extra_zones_scaled_but_never_merged():
    scale = {"mythic": 1.0, "heroic": 0.8, "normal": 0.0}
    layer = build_parses({
        "last_updated": "x",
        "tier": {"zone_id": 46, "name": "Voidspire Sanctum"},
        "characters": {"amrevenge-stormrage": {
            "name": "Amrevenge", "sourced_at": "x",
            "by_difficulty": {"mythic": {"best_perf_avg": 92.4}}}},
        "extra_zones": {"sporefall": {
            "zone_id": 47, "name": "Sporefall",
            "characters": {
                "amrevenge-stormrage": {
                    "name": "Amrevenge", "sourced_at": "x",
                    "by_difficulty": {"heroic": {"best_perf_avg": 82.3}}},
                "rotonly-bleeding-hollow": {
                    "name": "Rotonly", "sourced_at": "x",
                    "by_difficulty": {"heroic": {"best_perf_avg": 64.0}}},
            }}},
    }, difficulty_scale=scale)
    # The bonus raid never bleeds into the tier map (Emperor axis purity)...
    assert set(layer["characters"]) == {"amrevenge-stormrage"}
    sf = layer["extra_zones"]["sporefall"]
    assert sf["name"] == "Sporefall"
    assert sf["character_count"] == 2
    # ...but gets the identical scaling + headline treatment, tagged with
    # its own tier, and keeps Rotmire-only raiders visible.
    amr = sf["characters"]["amrevenge-stormrage"]
    assert amr["scaled_perf_avg"] == 65.8  # 82.3 * 0.8
    assert amr["tier"] == {"zone_id": 47, "name": "Sporefall"}
    assert "rotonly-bleeding-hollow" in sf["characters"]


def test_build_parses_extra_zones_absent_is_empty_dict():
    assert build_parses(None)["extra_zones"] == {}
    assert build_parses(_fetched_one())["extra_zones"] == {}


def test_resolve_raid_zone_falls_back_to_boss_names():
    # WCL may name a world-raid zone after its lone encounter ("Rotmire")
    # rather than the raid ("Sporefall") — resolution must catch both, and
    # report WHICH name matched so the run log can say so.
    raid = {"slug": "sporefall", "display_name": "Sporefall",
            "bosses": [{"order": 1, "name": "Rotmire", "slug": "rotmire"}]}
    by_raid_name = [{"id": 47, "name": "Sporefall"}]
    by_boss_name = [{"id": 47, "name": "Rotmire"}]
    assert wcl.resolve_raid_zone(by_raid_name, raid) == (47, "Sporefall")
    assert wcl.resolve_raid_zone(by_boss_name, raid) == (47, "Rotmire")
    assert wcl.resolve_raid_zone([{"id": 46, "name": "VS / DR / MQD"}],
                                 raid) == (None, None)


def test_build_parses_passes_zones_swept_provenance_through():
    fetched = _fetched_one()
    fetched["zones_swept"] = [
        {"slug": "tier-mn-1", "zone_id": 46, "name": "Voidspire Sanctum"},
        {"slug": "sporefall", "zone_id": 47, "name": "Sporefall"}]
    layer = build_parses(fetched)
    assert [z["slug"] for z in layer["zones_swept"]] == ["tier-mn-1", "sporefall"]
    assert build_parses(None)["zones_swept"] == []


def test_season_lists_sporefall_as_extra_raid():
    from guild_board import season as season_mod
    extras = {r["slug"]: r for r in season_mod.CURRENT_SEASON["extra_raids"]}
    assert extras["sporefall"]["bosses"][0]["name"] == "Rotmire"


# ---------------------------------------------------------------------------
# activity gate — who the sweep spends queries on
# ---------------------------------------------------------------------------

def test_fetch_active_raiders_reads_report_rankings(monkeypatch):
    reports = [{"code": "AAA"}, {"code": "BBB"}]

    def fake_detail(token, code, difficulty):
        if code == "AAA" and difficulty == 5:
            return {"dps": {"data": [{"roles": {
                "dps": {"characters": [
                    {"name": "Violënce", "server": "Bleeding Hollow"}]},
                "tanks": {"characters": [{"name": "Floofwall",
                                          "server": "Quel'dorei"}]},
            }}]}}
        if code == "BBB" and difficulty == 4:
            return {"hps": {"data": [{"roles": {
                "healers": {"characters": [{"name": "Rakdisc", "server": None}]},
            }}]}}
        return {}

    monkeypatch.setattr(wcl, "fetch_report_detail", fake_detail)
    active = wcl.fetch_active_raiders("tok", CFG, reports, difficulties=(5, 4))
    assert active["violënce"] == "bleeding-hollow"
    assert active["floofwall"] == "queldorei"   # apostrophe slugified away
    assert "rakdisc" in active                   # slugless still counts


def test_select_active_roster_gates_on_logs_and_cache():
    roster = ["violënce-bleeding-hollow",   # active, realm matches
              "violënce-area-52",           # same name, wrong realm -> out
              "rakdisc-proudmoore",         # active with no slug -> name-only in
              "oldtimer-bleeding-hollow",   # inactive but cached -> stays
              "ghost-bleeding-hollow"]      # inactive, uncached -> out
    active = {"violënce": "bleeding-hollow", "rakdisc": None}
    picked = wcl.select_active_roster(
        roster, active, cached_keys={"oldtimer-bleeding-hollow"},
        default_realm="bleeding-hollow")
    assert picked == ["violënce-bleeding-hollow", "rakdisc-proudmoore",
                      "oldtimer-bleeding-hollow"]


# ---------------------------------------------------------------------------
# site envelope + delivery set
# ---------------------------------------------------------------------------

def test_site_data_carries_parses_layer_and_parity_upgrade():
    parses_fetched = {
        "last_updated": "2026-07-24T13:30:00+00:00",
        "tier": {"zone_id": 46, "name": "Voidspire Sanctum"},
        "characters": {"amrevenge-stormrage": {
            "name": "Amrevenge", "best_perf_avg": 92.4, "by_role": {},
            "difficulty": 5, "sourced_at": "2026-07-24T13:30:00+00:00"}},
    }
    site = build_site_data(
        competition_fetched={"characters": [
            _comp_char("Amrevenge", "amrevenge-stormrage", 3900.0)]},
        parses_fetched=parses_fetched)
    assert site["parses"]["available"] is True
    states = {f["field"]: f["state"] for f in site["parity"]["fields"]}
    assert states["top_dps_parses"] == "live"
    assert states["top_healing_parses"] == "live"
    assert states["top_tank_parses"] == "live"


def test_site_data_parses_layer_degrades_cleanly():
    site = build_site_data()
    assert site["parses"]["available"] is False
    states = {f["field"]: f["state"] for f in site["parity"]["fields"]}
    assert states["top_dps_parses"] == "pending"


def test_delivery_set_includes_parses():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from deliver_bundle import DELIVERED
    assert "parses.json" in DELIVERED


# ---------------------------------------------------------------------------
# refresh script — inert without credentials
# ---------------------------------------------------------------------------

def test_refresh_parses_is_inert_without_credentials(tmp_path):
    env = dict(os.environ)
    env.pop("WCL_CLIENT_ID", None)
    env.pop("WCL_CLIENT_SECRET", None)
    env["PYTHONIOENCODING"] = "utf-8"
    existed_before = os.path.exists(os.path.join(ROOT, "parses_cache.json"))
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "refresh_parses.py")],
        capture_output=True, text=True, env=env, cwd=ROOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "skipping the parse refresh" in proc.stdout
    # Nothing written when it declines to run.
    assert os.path.exists(os.path.join(ROOT, "parses_cache.json")) == existed_before

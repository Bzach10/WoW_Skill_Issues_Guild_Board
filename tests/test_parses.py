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

from guild_board import wcl
from guild_board.competition import build_competition
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
        "overall": _blob(88.123, median=74.456),
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


def test_normalize_no_rankings_is_none():
    assert wcl.normalize_character_parses(None) is None
    assert wcl.normalize_character_parses({}) is None
    assert wcl.normalize_character_parses(
        {"name": "Aiime", "classID": 4, "overall": _blob(None),
         "dps": _blob(None), "healer": _blob(None), "tank": _blob(None)}) is None


def test_normalize_role_blob_alone_still_counts():
    entry = wcl.normalize_character_parses(
        {"name": "Floofwall", "classID": 5, "overall": _blob(None),
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
                            "overall": _blob(90.0), "dps": _blob(90.0, kills=8)},
        "area-52": {"name": "Violënce", "classID": 2,
                    "overall": _blob(30.0), "dps": _blob(30.0, kills=1)},
    }
    calls = []

    def fake(token, query, variables):
        calls.append(dict(variables))
        return {"characterData": {"character": per_realm.get(variables["slug"])}}

    monkeypatch.setattr(wcl, "gql", fake)
    monkeypatch.setattr(wcl.time, "sleep", lambda s: None)

    out = wcl.fetch_character_parses("tok", CFG, roster, zone_id=46)
    assert set(out) == set(roster)
    assert out["violënce-bleeding-hollow"]["best_perf_avg"] == 90.0
    assert out["violënce-area-52"]["best_perf_avg"] == 30.0
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


def test_fetch_walks_difficulties_and_labels_the_hit(monkeypatch):
    # Nothing at mythic (empty blobs), heroic answers -> difficulty 4 kept.
    char_empty = {"name": "Aiime", "classID": 4, "overall": _blob(None)}
    char_heroic = {"name": "Aiime", "classID": 4, "overall": _blob(65.5),
                   "dps": _blob(65.5, kills=3)}
    answers = {("aiime", 5): char_empty, ("aiime", 4): char_heroic}
    calls = []
    monkeypatch.setattr(wcl, "gql", _fake_gql(answers, calls))
    monkeypatch.setattr(wcl.time, "sleep", lambda s: None)

    out = wcl.fetch_character_parses("tok", CFG, ["aiime-bleeding-hollow"], zone_id=46)
    entry = out["aiime-bleeding-hollow"]
    assert entry["difficulty"] == 4
    assert entry["best_perf_avg"] == 65.5
    assert entry["key"] == "aiime-bleeding-hollow"
    assert entry["sourced_at"]
    assert [c["difficulty"] for c in calls] == [5, 4]  # stopped at the hit


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
    # The competition merge carries the discounted value for rankings.
    assert by_key["violënce-bleeding-hollow"]["parse"]["scaled"] == 90.0
    assert by_key["violënce-area-52"]["parse"]["scaled"] == 18.0  # 30 * 0.6
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

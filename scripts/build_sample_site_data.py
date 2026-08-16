"""Generate a committed SAMPLE site-data bundle for the front-end.

The live builder (build_site_data.py) writes to gitignored web_data/, and
today's real data leaves several UI states empty — no Blizzard creds means
the trophy hall is blank, and without a live dungeon sweep the islands read
"locked". The website UI session needs to see every state *populated* to
build the components, so this runs the SAME producers over realistic
fixture inputs and writes the result to the committed samples/ directory.

The shapes are therefore guaranteed identical to production — only the
input values are illustrative. Each file carries "_sample": true so nobody
mistakes it for live data.

Usage: python scripts/build_sample_site_data.py
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guild_board import season as season_mod  # noqa: E402
from guild_board import web_data  # noqa: E402

OUT = os.path.join(str(Path(__file__).resolve().parents[1]), "samples")

# --- Realistic fixture inputs (illustrative values, real shapes) ----------

BOARD_STATE = {
    "last_updated": "2026-07-20T12:14:49+00:00",
    "streaks_week": "2026-07-14",
    "standing": {"realm": 49, "region": 2219, "world": 6840},
    "season_scores": {"amrevenge": 3921.4, "shadoxii": 3692.2,
                      "tommybravoo": 3686.3, "rakdisc": 3560.1,
                      "floofwall": 3484.3, "newrecruit": 1802.0},
    # Bare names, because Warcraft Logs reports names without realms.
    # "beroben" is here on purpose: the live roster carries TWO characters by
    # that name, so this row is the collision, in the fixture, where a test
    # can see what the delivery does with it.
    "streaks": {"amrevenge": 2, "tommybravoo": 3, "rakdisc": 1,
                "healmates": 3, "beroben": 2},
    # Season attendance: the raid weeks each member was actually in. The Most
    # Improved sweep has always computed this and the pipeline discarded it
    # after collapsing it into the streak integers above.
    "attendance": {
        "weeks": {
            "amrevenge": ["2026-07-07", "2026-07-14"],
            "tommybravoo": ["2026-06-30", "2026-07-07", "2026-07-14"],
            "rakdisc": ["2026-07-14"],
            "healmates": ["2026-06-30", "2026-07-07", "2026-07-14"],
            "beroben": ["2026-07-07", "2026-07-14"],
            "ghostofseasonspast": ["2026-06-30"],
        },
        "scanned": ["2026-06-30", "2026-07-07", "2026-07-14"],
        # 2026-06-23 was logged but its report details were never read --
        # an UNKNOWN week, not an absence.
        "all": ["2026-06-23", "2026-06-30", "2026-07-07", "2026-07-14"],
    },
    "records": {
        "highest_timed_key": {"name": "amrevenge", "level": 21,
                              "dungeon": "Skyreach",
                              "spec": "Beast Mastery Hunter", "new": True},
        "best_dps_parse": {"name": "Amrevenge", "parse": 99,
                           "boss": "Chimaerus the Undreamt God",
                           "spec": "BeastMastery", "cls": "Hunter", "new": True},
        "best_hps_parse": {"name": "Phyrthepali", "parse": 96,
                           "boss": "Imperator Averzian", "spec": "Holy",
                           "cls": "Paladin", "new": False},
    },
    # The week the board posted — the Warcraft Logs facts that used to die
    # with the run (guild_board.state.build_week_block writes this shape).
    "week": {
        "label": "2026-07-14", "start": "2026-07-13", "end": "2026-07-20",
        "zone": "Voidspire Sanctum", "difficulty": "Mythic",
        "kills": 6, "pulls": 54, "wipes": 48,
        "deaths_total": 123,
        "deaths": {"maillo": 32, "buchalter": 30, "tommybravoo": 18,
                   "chokalock": 17, "rakdisc": 11},
        "repair_estimate": 8253,
        "keys": [
            {"level": 20, "dungeon": "Pit of Saron", "name": "Amrevenge",
             "spec": "Beast Mastery Hunter"},
            {"level": 19, "dungeon": "Skyreach", "name": "Tommybravoo",
             "spec": "Unholy DK"},
        ],
        "parses": {
            "dps": [{"name": "Maillo", "spec": "BeastMastery", "cls": "Hunter",
                     "boss": "Chimaerus the Undreamt God", "parse": 92,
                     "amount": 144000, "difficulty": 5, "key_level": None}],
            "hps": [{"name": "Phyrthepali", "spec": "Holy", "cls": "Paladin",
                     "boss": "Imperator Averzian", "parse": 96,
                     "amount": 167000, "difficulty": 5, "key_level": None}],
            "tanks": [{"name": "Brewzleeh", "spec": "Brewmaster", "cls": "Monk",
                       "boss": "Chimaerus the Undreamt God", "parse": 91,
                       "amount": 88000, "difficulty": 5, "key_level": None}],
        },
        "mplus_parses": {
            "dps": [{"name": "Brewzleeh", "spec": "Windwalker", "cls": "Monk",
                     "boss": "Pit of Saron", "parse": 96, "amount": 146000,
                     "difficulty": 10, "key_level": 18}],
        },
        "improvement": {
            "dps": [{"name": "Tommybravoo", "spec": "Unholy", "cls": "DeathKnight",
                     "early_parse": 19, "late_parse": 67, "delta": 48,
                     "early_amount": 90000, "late_amount": 127000,
                     "difficulty": 5}],
        },
        "roast": {"roast": "Healmates Sucks", "winner": "Rakdaddy",
                  "target": "Healmates"},
    },
    "baseline": {
        "standing": {"realm": 52, "region": 2451, "world": 6855},
        "season_scores": {"amrevenge": 3908.1, "shadoxii": 3692.2,
                          "tommybravoo": 3667.7, "rakdisc": 3529.2,
                          "floofwall": 3484.3},
        "records": {
            "highest_timed_key": {"name": "amrevenge", "level": 20,
                                  "dungeon": "Pit of Saron"},
            "best_dps_parse": {"name": "Amrevenge", "parse": 97,
                               "boss": "Fallen-King Salhadaar"},
            "best_hps_parse": {"name": "Phyrthepali", "parse": 96,
                               "boss": "Imperator Averzian"},
        },
    },
}

MANIFEST = {"characters": {
    "rakdisc-proudmoore": {"name": "Rakdisc", "class": "Priest",
                           "spec": "Discipline",
                           "render_url": "https://render.worldofwarcraft.com/us/character/proudmoore/239/243420911-main-raw.png",
                           "transmog_fingerprint": "NEW_FP_AAA"},
    "floofwall-queldorei": {"name": "Floofwall", "class": "Monk",
                            "spec": "Brewmaster",
                            "transmog_fingerprint": "SAME_FP_BBB"},
    "healyeah-queldorei": {"name": "Healyeah", "class": "Evoker",
                           "spec": "Augmentation",
                           "transmog_fingerprint": "SAME_FP_CCC"},
}}

# Last week's snapshot: Rakdisc's fingerprint differs -> one changed look.
TRANSMOG_SNAPSHOT = {
    "rakdisc-proudmoore": "OLD_FP_ZZZ",
    "floofwall-queldorei": "SAME_FP_BBB",
    "healyeah-queldorei": "SAME_FP_CCC",
}

# The season these fixtures describe. Pinned, NOT resolved from the clock:
# every fixture below is hand-authored against the S1 pool (S1 dungeon
# names, tier-mn-1, "3/9 M"), so building them against whatever season is
# current would emit an incoherent sample — S2's pool with S1's dungeon
# bests resolves to 0 conquered, and the sample's whole job is to show
# populated states. Moving the sample to S2 means rewriting these fixture
# inputs to S2 names and repointing this constant, deliberately, together.
SAMPLE_SEASON = season_mod.SEASON_MN_1

# A full sample-season dungeon sweep, so the islands show real states:
# most conquered, one merely attempted, one still locked.
DUNGEON_BESTS = {
    "Algeth'ar Academy": {"level": 21, "timed": True, "by": "Amrevenge"},
    "Magisters' Terrace": {"level": 20, "timed": True, "by": "Shadoxii"},
    "Maisara Caverns": {"level": 19, "timed": True, "by": "Tommybravoo"},
    "Nexus-Point Xenas": {"level": 18, "timed": True, "by": "Rakdisc"},
    "Pit of Saron": {"level": 21, "timed": True, "by": "Amrevenge"},
    "Seat of the Triumvirate": {"level": 17, "timed": True, "by": "Floofwall"},
    "Skyreach": {"level": 16, "timed": False, "by": "Healyeah"},  # attempted
    # Windrunner Spire absent -> locked
}

RAID_PROGRESSION = {"tier-mn-1": {"summary": "3/9 M",
                                  "mythic_bosses_killed": 3,
                                  "heroic_bosses_killed": 5,
                                  "normal_bosses_killed": 0}}

# A populated guild-achievements payload (Blizzard /achievements shape),
# so the trophy hall has real content to render.
GUILD_ACHIEVEMENTS = {
    "total_quantity": 1655,
    "achievements": [
        {"achievement": {"id": 15001, "name": "Ahead of the Curve: Imperator Averzian"},
         "completed_timestamp": 1_772_500_000_000,
         "criteria": {"is_completed": True, "child_criteria": [{}, {}]}},
        {"achievement": {"id": 15002, "name": "Cutting Edge: Fallen-King Salhadaar"},
         "completed_timestamp": 1_774_200_000_000,
         "criteria": {"is_completed": True, "child_criteria": []}},
        {"achievement": {"id": 15010, "name": "Midnight Keystone Master: Season One"},
         "completed_timestamp": 1_775_000_000_000,
         "criteria": {"is_completed": True, "child_criteria": [{}] * 8}},
    ],
}


# A realistic guild-pulse feed (already privacy-filtered by the fetch layer:
# display names only, no user ids; opt-outs and blocklist applied upstream).
PULSE_ITEMS = [
    {"author": "Tommybravoo", "snippet": "we timed the +21 with 4 seconds left, "
     "@Amrevenge literally soloed the last boss", "channel": "general", "kind": "chat",
     "timestamp": "2026-07-20T02:14:00+00:00",
     "reactions": [{"emoji": "🔥", "count": 12}, {"emoji": "😭", "count": 3}],
     "media": [], "has_media": False},
    {"author": "Rakdisc", "snippet": "healer pov of that pull", "channel": "clip-dump",
     "kind": "memes", "timestamp": "2026-07-19T23:40:00+00:00",
     "reactions": [{"emoji": "💀", "count": 8}],
     "media": [{"url": "https://cdn.discordapp.com/attachments/…/clip.mp4",
                "content_type": "video/mp4", "width": 1280, "height": 720,
                "is_image": False, "filename": "clip.mp4"}], "has_media": True},
    {"author": "Floofwall", "snippet": "lost 40k gold in the guild casino tonight, "
     "no notes", "channel": "bully-corner", "kind": "gambling",
     "timestamp": "2026-07-19T20:05:00+00:00",
     "reactions": [{"emoji": "🎰", "count": 6}, {"emoji": "😂", "count": 9}],
     "media": [], "has_media": False},
    {"author": "Healyeah", "snippet": "made this for the raid team", "channel": "memes",
     "kind": "memes", "timestamp": "2026-07-18T15:22:00+00:00",
     "reactions": [{"emoji": "🤣", "count": 21}, {"emoji": ":kekw:", "count": 14}],
     "media": [{"url": "https://cdn.discordapp.com/attachments/…/meme.png",
                "content_type": "image/png", "width": 800, "height": 600,
                "is_image": True, "filename": "meme.png"}], "has_media": True},
]


# A small but complete competition fetch (real Raider.io shape) so the
# WANTED BOARD renders with rankings, roles, movement and browsable detail.
def _cchar(name, key, cls, spec, role, score, runs=None, recent=None):
    return {"name": name, "realm": key.split("-", 1)[1], "key": key,
            "class": cls, "spec": spec, "role": role, "score": score,
            "scores_by_role": {"dps": score if role == "DPS" else 0,
                               "healer": score if role == "Healer" else 0,
                               "tank": score if role == "Tank" else 0},
            "best_runs": runs or [], "recent_runs": recent or [],
            "ranks": {"realm_overall": 800, "realm_class": 20}}


COMPETITION_FETCHED = {"prev_day_scores": {
    "amrevenge-stormrage": 3902.0,        # +6.1 today
    "tommybravoo-bleeding-hollow": 3700.0,  # +53.4 today
}, "characters": [
    # completed_at + keystone_run_id are in EVERY Raider.io run object; the
    # normalizer used to drop both. completed_at is Raider.io's own ISO
    # string, verbatim; keystone_run_id is what mythic-plus/run-details?id=
    # takes, and it is the only handle on who else was in the run.
    _cchar("Amrevenge", "amrevenge-stormrage", "Hunter", "Beast Mastery Hunter", "DPS", 3908.1,
           runs=[{"dungeon": "Pit of Saron", "short": "POS", "level": 20, "timed": True,
                  "upgrades": 1, "score": 492.2, "clear_ms": 1456281, "par_ms": 1800999,
                  "completed_at": "2026-07-16T02:41:19.000Z",
                  "keystone_run_id": 42508722}],
           recent=[{"dungeon": "Skyreach", "short": "SKY", "level": 21, "timed": False,
                    "upgrades": 0, "score": 0.0, "clear_ms": 1994003, "par_ms": 1800999,
                    "completed_at": "2026-07-19T23:08:44.000Z",
                    "keystone_run_id": 42611904},
                   {"dungeon": "Pit of Saron", "short": "POS", "level": 20, "timed": True,
                    "upgrades": 1, "score": 492.2, "clear_ms": 1456281, "par_ms": 1800999,
                    "completed_at": "2026-07-16T02:41:19.000Z",
                    "keystone_run_id": 42508722}]),
    _cchar("Tommybravoo", "tommybravoo-bleeding-hollow", "DK", "Unholy DK", "DPS", 3753.4,
           recent=[{"dungeon": "Skyreach", "short": "SKY", "level": 19, "timed": True,
                    "upgrades": 1, "score": 471.8, "clear_ms": 1502117, "par_ms": 1740000,
                    "completed_at": "2026-07-18T01:12:05.000Z",
                    "keystone_run_id": 42588140}]),
    _cchar("Shadoxii", "shadoxii-illidan", "Monk", "Mistweaver Monk", "Healer", 3692.2),
    _cchar("Brewzleeh", "brewzleeh-tichondrius", "Monk", "Brewmaster Monk", "Tank", 3685.8),
    _cchar("Rakdisc", "rakdisc-proudmoore", "Priest", "Discipline Priest", "Healer", 3529.2),
    _cchar("Floofwall", "floofwall-queldorei", "Monk", "Brewmaster Monk", "Tank", 3484.3),
    _cchar("Newrecruit", "newrecruit-area-52", "Mage", "Frost Mage", "DPS", 1802.0),
]}


# The roster, as an IDENTITY INDEX for the weekly board's bare Warcraft Logs
# names. Two Berobens on purpose — that is the live roster's real collision
# (beroben-emerald-dream / beroben-queldorei), and the sample bundle has to
# carry it or nothing downstream ever meets it before production does.
SAMPLE_ROSTER = [
    "amrevenge-stormrage", "tommybravoo-bleeding-hollow", "shadoxii-illidan",
    "brewzleeh-tichondrius", "rakdisc-proudmoore", "floofwall-queldorei",
    "newrecruit-area-52", "healmates-bleeding-hollow", "maillo-bleeding-hollow",
    "buchalter-area-52", "chokalock-bleeding-hollow",
    "phyrthepali-bleeding-hollow",
    "beroben-emerald-dream", "beroben-queldorei",
]


# The credentialed WCL parse sweep (real parses_cache.json shape) so the
# Four Emperors ranking, standings parse columns and newspaper raid sections
# all render populated. Keyed by the FULL name-realm key, exactly like the
# live cache — never bare names. Every enabled difficulty is fetched per
# character (mythic AND heroic), nested under by_difficulty; Amrevenge shows
# the headline rule (heroic 96.8 x 0.8 = 77.4 loses to mythic 92.4).
PARSES_FETCHED = {
    "last_updated": "2026-07-20T13:30:00+00:00",
    "last_full_sweep": "2026-07-20T13:30:00+00:00",
    "sweep_mode": "active",
    "tier": {"zone_id": 46, "name": "Voidspire Sanctum"},
    "zones_swept": [
        {"slug": "tier-mn-1", "zone_id": 46, "name": "Voidspire Sanctum"},
        {"slug": "sporefall", "zone_id": 47, "name": "Sporefall"},
    ],
    "characters": {
        "amrevenge-stormrage": {
            "name": "Amrevenge", "key": "amrevenge-stormrage",
            "class": "Hunter", "sourced_at": "2026-07-20T13:30:00+00:00",
            "by_difficulty": {
                "mythic": {"best_perf_avg": 92.4, "median_perf_avg": 81.0,
                           "by_role": {"DPS": {"best_perf_avg": 92.4, "kills": 7}}},
                "heroic": {"best_perf_avg": 96.8, "median_perf_avg": 90.2,
                           "by_role": {"DPS": {"best_perf_avg": 96.8, "kills": 11}}},
            }},
        "rakdisc-proudmoore": {
            "name": "Rakdisc", "key": "rakdisc-proudmoore",
            "class": "Priest", "sourced_at": "2026-07-20T13:30:00+00:00",
            "by_difficulty": {
                "mythic": {"best_perf_avg": 88.1, "median_perf_avg": 74.5,
                           "by_role": {"Healer": {"best_perf_avg": 88.1, "kills": 6},
                                       "DPS": {"best_perf_avg": 41.2, "kills": 2}}},
                "heroic": {"best_perf_avg": 93.0, "median_perf_avg": 85.1,
                           "by_role": {"Healer": {"best_perf_avg": 93.0, "kills": 9}}},
            }},
        "floofwall-queldorei": {
            "name": "Floofwall", "key": "floofwall-queldorei",
            "class": "Monk", "sourced_at": "2026-07-20T13:30:00+00:00",
            "by_difficulty": {
                "heroic": {"best_perf_avg": 71.9,
                           "by_role": {"Tank": {"best_perf_avg": 71.9, "kills": 5}}},
            }},
    },
    # Bonus raid swept alongside the tier (season.py extra_raids): the
    # one-boss Sporefall raid (Rotmire). Healyeah is Sporefall-only, so
    # the sample shows a character who exists ONLY in an extra zone.
    "extra_zones": {
        "sporefall": {
            "zone_id": 47, "name": "Sporefall",
            "characters": {
                "amrevenge-stormrage": {
                    "name": "Amrevenge", "key": "amrevenge-stormrage",
                    "class": "Hunter", "sourced_at": "2026-07-20T13:30:00+00:00",
                    "by_difficulty": {
                        "heroic": {"best_perf_avg": 82.3,
                                   "by_role": {"DPS": {"best_perf_avg": 82.3,
                                                       "kills": 2}}}}},
                "healyeah-queldorei": {
                    "name": "Healyeah", "key": "healyeah-queldorei",
                    "class": "Evoker", "sourced_at": "2026-07-20T13:30:00+00:00",
                    "by_difficulty": {
                        "heroic": {"best_perf_avg": 64.0,
                                   "by_role": {"Healer": {"best_perf_avg": 64.0,
                                                          "kills": 1}}}}},
            }},
    },
}


# Mirrors config.yml's parses.difficulty_scale so the sample shows the
# scaled values the way a tuned production bundle would (Floofwall's
# heroic 71.9 scales to 57.5, showing the discount visibly; normal is
# excluded outright, matching the live config).
PARSES_DIFFICULTY_SCALE = {"mythic": 1.0, "heroic": 0.8, "normal": 0.0}


def _stamp_fixture(obj, stamp):
    """Rewrite every generated_at in the envelope to the fixture's own clock."""
    if isinstance(obj, dict):
        if "generated_at" in obj:
            obj["generated_at"] = stamp
        for value in obj.values():
            _stamp_fixture(value, stamp)
    elif isinstance(obj, list):
        for value in obj:
            _stamp_fixture(value, stamp)


def main():
    os.makedirs(OUT, exist_ok=True)
    site = web_data.build_site_data(
        board_state=BOARD_STATE, manifest=MANIFEST,
        dungeon_bests=DUNGEON_BESTS, raid_progression=RAID_PROGRESSION,
        guild_achievements=GUILD_ACHIEVEMENTS, transmog_snapshot=TRANSMOG_SNAPSHOT,
        pulse_items=PULSE_ITEMS, competition_fetched=COMPETITION_FETCHED,
        parses_fetched=PARSES_FETCHED,
        difficulty_scale=PARSES_DIFFICULTY_SCALE,
        guild={"name": "Skill Issues", "realm": "bleeding-hollow", "region": "us"},
        season=SAMPLE_SEASON, roster=SAMPLE_ROSTER)
    # FIXTURE STAMPS, not wall-clock ones. The producers stamp generated_at
    # = now, but every other date in this bundle is a fixture from the sample
    # week -- so a sample regenerated any later day reads to the bundle
    # validator (and to the consumer's 30-minute vintage guard) as a bundle
    # whose layers came from different fortnights, and gets REFUSED. The
    # sample is a fixture: its clock is the fixture's clock.
    _stamp_fixture(site, BOARD_STATE["last_updated"])
    site["_sample"] = True
    site["_note"] = ("Illustrative values, production shapes. Generated by "
                     "scripts/build_sample_site_data.py through the real "
                     "guild_board.web_data producers. Every generated_at is "
                     "the fixture week's stamp, not the run's.")

    _write(os.path.join(OUT, "site_data.sample.json"), site)
    layers = ("recap_ribbon", "records_leaderboard", "weekly_board",
              "guild_achievements", "island_completion", "transmog_changes",
              "guild_pulse", "competition", "parses")
    for layer in layers:
        payload = dict(site[layer])
        payload["_sample"] = True
        _write(os.path.join(OUT, f"{layer}.sample.json"), payload)

    print(f"Wrote {OUT}/site_data.sample.json (+ {len(layers)} per-layer samples)")
    print(f"  recap beats     : {site['recap_ribbon']['beat_count']}")
    print(f"  ladder rows     : {site['records_leaderboard']['ladder_size']}")
    print(f"  achievements    : {site['guild_achievements']['trophy_count']} trophies")
    print(f"  dungeon islands : {site['island_completion']['dungeons']['conquered']}/{site['island_completion']['dungeons']['total']} conquered")
    print(f"  raid bosses     : {site['island_completion']['raid']['bosses_killed']}/{site['island_completion']['raid']['total_bosses']}")
    print(f"  transmog changes: {site['transmog_changes']['changed_count']}")
    print(f"  guild pulse     : {site['guild_pulse']['item_count']} items {site['guild_pulse']['by_kind']}")
    print(f"  competition     : {site['competition']['character_count']} ranked, "
          f"top: {site['competition']['rankings']['top5'][0]['name'] if site['competition']['rankings']['top5'] else '-'}")
    print(f"  parses          : {site['parses']['character_count']} characters with WCL averages")
    return 0


def _write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    sys.exit(main())

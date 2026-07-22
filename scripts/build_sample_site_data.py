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
    "streaks": {"amrevenge": 2, "tommybravoo": 3, "rakdisc": 1, "healmates": 3},
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
    "baseline": {
        "standing": {"world": 6855},
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

# A full current-season dungeon sweep, so the islands show real states:
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


def main():
    os.makedirs(OUT, exist_ok=True)
    site = web_data.build_site_data(
        board_state=BOARD_STATE, manifest=MANIFEST,
        dungeon_bests=DUNGEON_BESTS, raid_progression=RAID_PROGRESSION,
        guild_achievements=GUILD_ACHIEVEMENTS, transmog_snapshot=TRANSMOG_SNAPSHOT,
        guild={"name": "Skill Issues", "realm": "bleeding-hollow", "region": "us"},
        season=season_mod.CURRENT_SEASON)
    site["_sample"] = True
    site["_note"] = ("Illustrative values, production shapes. Generated by "
                     "scripts/build_sample_site_data.py through the real "
                     "guild_board.web_data producers.")

    _write(os.path.join(OUT, "site_data.sample.json"), site)
    for layer in ("recap_ribbon", "records_leaderboard", "guild_achievements",
                  "island_completion", "transmog_changes"):
        payload = dict(site[layer])
        payload["_sample"] = True
        _write(os.path.join(OUT, f"{layer}.sample.json"), payload)

    print(f"Wrote {OUT}/site_data.sample.json (+ 5 per-layer samples)")
    print(f"  recap beats     : {site['recap_ribbon']['beat_count']}")
    print(f"  ladder rows     : {site['records_leaderboard']['ladder_size']}")
    print(f"  achievements    : {site['guild_achievements']['trophy_count']} trophies")
    print(f"  dungeon islands : {site['island_completion']['dungeons']['conquered']}/{site['island_completion']['dungeons']['total']} conquered")
    print(f"  raid bosses     : {site['island_completion']['raid']['bosses_killed']}/{site['island_completion']['raid']['total_bosses']}")
    print(f"  transmog changes: {site['transmog_changes']['changed_count']}")
    return 0


def _write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    sys.exit(main())

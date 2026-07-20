"""Instant local board preview with canned data — no API keys, no waiting.

Edit theme.yml (or a template module), run this, refresh your browser.
The fake week exercises every section: parses, keys, season scores,
records with a NEW flag (so the headline fires), streak awards, the
graveyard, the roast — all of it.

    python scripts/preview_board.py            # writes board_render.html (+ mobile)
    python scripts/preview_board.py --png      # also screenshots via Playwright
    python scripts/preview_board.py --open     # opens the HTML in your browser

Run from the repo root so assets/ paths resolve.
"""

import argparse
import sys
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guild_board import html_board  # noqa: E402

FAKE_CFG = {
    "guild": {"name": "Skill Issues", "realm_slug": "bleeding-hollow", "region": "us"},
    "raid": {"enabled": True, "difficulty": "mythic"},
    "top_n": 5,
    "lookback_days": 7,
    "display": {"layout": "image_board", "renderer": "html", "icons": True,
                "watermark": True, "item_art": "assets/item_art.png"},
    "sections": {
        "raid_header": {"title": "Raid"},
        "mplus_header": {"title": "Mythic Plus"},
        "top_dps": {"enabled": True},
        "top_healing": {"enabled": True},
        "realm_rank_leaders": {"enabled": True},
        "mplus": {"enabled": True},
        "mplus_weekly_parses": {"enabled": True},
        "mplus_season_scores": {"enabled": True},
        "mplus_season_parses": {"enabled": True},
        "closest_race": {"enabled": True},
        "guild_records": {"enabled": True},
        "roast_of_the_week": {
            "enabled": True, "winner": "Bzach1000", "target": "Healmates",
            "roast": "Healmates got out parsed by a 274 ilvl Resto Shaman … Git Gud",
        },
    },
}

FAKE_STATS = {
    "best_dps": {
        "Maillo": {"parse": 92, "amount": 144_000, "boss": "Chimaerus", "spec": "BeastMastery", "cls": "Hunter"},
        "Rakdisc": {"parse": 88, "amount": 146_000, "boss": "Chimaerus", "spec": "Shadow", "cls": "Priest"},
        "Enyo": {"parse": 85, "amount": 125_000, "boss": "Vorasius", "spec": "Devourer", "cls": "Demon Hunter"},
        "Tommybravox": {"parse": 79, "amount": 138_000, "boss": "Chimaerus", "spec": "Havoc", "cls": "Demon Hunter"},
        "Tommybravoo": {"parse": 67, "amount": 127_000, "boss": "Imperator Averzian", "spec": "Unholy", "cls": "Death Knight"},
    },
    "best_hps": {
        "Phyrthepali": {"parse": 96, "amount": 167_000, "boss": "Imperator Averzian", "spec": "Holy", "cls": "Paladin"},
        "Healmates": {"parse": 75, "amount": 130_000, "boss": "Imperator Averzian", "spec": "Holy", "cls": "Priest"},
        "Rakdisc": {"parse": 61, "amount": 173_000, "boss": "Fallen-King Salhadaar", "spec": "Discipline", "cls": "Priest"},
    },
    "best_tanks": {
        "Brewzleeh": {"parse": 91, "amount": 88_000, "boss": "Chimaerus", "spec": "Brewmaster", "cls": "Monk"},
        "Chokalock": {"parse": 74, "amount": 79_000, "boss": "Vorasius", "spec": "Protection", "cls": "Warrior"},
        "Boondocka": {"parse": 52, "amount": 71_000, "boss": "Chimaerus", "spec": "Blood", "cls": "Death Knight"},
    },
    "deaths": {"Maillo": 32, "Buchalter": 30, "Tommybravoo": 18, "Chokalock": 17,
               "Phyrthepali": 4, "Healmates": 9, "Rakdisc": 11, "Enyo": 2},
    "participants": ["Maillo", "Rakdisc", "Enyo", "Tommybravox", "Tommybravoo",
                     "Phyrthepali", "Healmates", "Buchalter", "Chokalock", "Boondocka"],
    "pulls": 54,
    "kills": 6,
    "difficulty": 5,
}

FAKE_STANDING = {"realm": 49, "region": 2219, "world": 6854}
FAKE_LEADERS = [
    {"name": "Healyeah", "spec": "Augmentation", "cls": "Evoker", "realm_rank": 1, "region_rank": 1462, "best_avg": 23.7, "boss": "Chimaerus"},
    {"name": "Boondocka", "spec": "BeastMastery", "cls": "Hunter", "realm_rank": 1, "region_rank": 1708, "best_avg": 34.3, "boss": "Vorasius"},
    {"name": "Healmates", "spec": "Holy", "cls": "Priest", "realm_rank": 3, "region_rank": 725, "best_avg": 58.3, "boss": "Chimaerus"},
    {"name": "Glinkz", "spec": "Fire", "cls": "Mage", "realm_rank": 5, "region_rank": 287, "best_avg": 40.9, "boss": "Vorasius"},
    {"name": "Tommybravox", "spec": "Havoc", "cls": "Demon Hunter", "realm_rank": 12, "region_rank": 393, "best_avg": 72.8, "boss": "Chimaerus"},
]
FAKE_MPLUS = [
    (20, "Pit of Saron", "Amrevenge", "Beast Mastery Hunter", True),
    (19, "Skyreach", "Tommybravoo", "Unholy DK", True),
    (18, "Magisters' Terrace", "Brewzleeh", "Brewmaster Monk", True),
    (18, "Skyreach", "Rakdisc", "Discipline Priest", True),
    (17, "Maisara Caverns", "Enyo", "Devourer DH", True),
]
FAKE_SEASON_SCORES = [
    (3908, "Amrevenge", "Beast Mastery Hunter"),
    (3692, "Shadoxii", "Mistweaver Monk"),
    (3686, "Brewzleeh", "Brewmaster Monk"),
    (3668, "Tommybravoo", "Unholy DK"),
    (3529, "Rakdisc", "Discipline Priest"),
]
FAKE_SEASON_PARSES = [
    (492, "Pit of Saron", "Amrevenge", "Beast Mastery Hunter", False),
    (473, "Pit of Saron", "Shadoxii", "Mistweaver Monk", False),
    (473, "Magisters' Terrace", "Brewzleeh", "Brewmaster Monk", False),
    (472, "Skyreach", "Tommybravoo", "Unholy DK", False),
    (456, "Skyreach", "Rakdisc", "Discipline Priest", False),
]
FAKE_IMPROVEMENT = {
    "dps": [
        {"name": "Tommybravoo", "spec": "Unholy", "cls": "Death Knight", "early_parse": 19, "late_parse": 67, "early_amount": 90_000, "late_amount": 127_000, "delta": 48},
        {"name": "Buchalter", "spec": "Frost", "cls": "Mage", "early_parse": 8, "late_parse": 55, "early_amount": 89_000, "late_amount": 109_000, "delta": 47},
        {"name": "Healyeah", "spec": "Augmentation", "cls": "Evoker", "early_parse": 7, "late_parse": 37, "early_amount": 72_000, "late_amount": 108_000, "delta": 30},
    ],
    "hps": [
        {"name": "Healmates", "spec": "Holy", "cls": "Priest", "early_parse": 19, "late_parse": 75, "early_amount": 97_000, "late_amount": 130_000, "delta": 56},
    ],
}
FAKE_MPLUS_WEEKLY = {
    "dps": {
        "Brewzleeh": {"parse": 96, "amount": 146_000, "boss": "Pit of Saron", "spec": "Windwalker", "cls": "Monk", "key_level": 18},
        "Tommybravoo": {"parse": 89, "amount": 143_000, "boss": "Skyreach", "spec": "Unholy", "cls": "Death Knight", "key_level": 19},
        "Boondocka": {"parse": 89, "amount": 111_000, "boss": "Algeth'ar Academy", "spec": "BeastMastery", "cls": "Hunter", "key_level": 16},
    },
    "hps": {
        "Rakdisc": {"parse": 96, "amount": 100_000, "boss": "Magisters' Terrace", "spec": "Discipline", "cls": "Priest", "key_level": 19},
        "Healmates": {"parse": 95, "amount": 46_000, "boss": "Algeth'ar Academy", "spec": "Holy", "cls": "Priest", "key_level": 16},
    },
    "tanks": {
        "Brewzleeh": {"parse": 93, "amount": 84_000, "boss": "Pit of Saron", "spec": "Brewmaster", "cls": "Monk", "key_level": 18},
        "Chokalock": {"parse": 68, "amount": 74_000, "boss": "Skyreach", "spec": "Protection", "cls": "Warrior", "key_level": 15},
    },
}
FAKE_PREVIOUS = {
    "standing": {"realm": 52, "region": 2451, "world": 7425},
    "season_scores": {"amrevenge": 3838, "shadoxii": 3641, "brewzleeh": 3660,
                      "tommybravoo": 3652, "rakdisc": 3480},
    "streaks": {"amrevenge": 7, "rakdisc": 6, "healmates": 5, "brewzleeh": 3, "maillo": 1},
}
FAKE_STREAKS = {"amrevenge": 8, "rakdisc": 7, "healmates": 6, "brewzleeh": 4, "maillo": 2}
FAKE_RECORDS = {
    "highest_timed_key": {"name": "Amrevenge", "level": 20, "dungeon": "Pit of Saron",
                          "spec": "Beast Mastery Hunter", "new": True},
    "best_dps_parse": {"name": "Tommybravoo", "parse": 100, "boss": "Chimaerus",
                       "spec": "Unholy", "cls": "Death Knight", "new": False},
    "best_hps_parse": {"name": "Phyrthepali", "parse": 96, "boss": "Imperator Averzian",
                       "spec": "Holy", "cls": "Paladin", "new": False},
}


def main():
    parser = argparse.ArgumentParser(description="Preview the board with fake data")
    parser.add_argument("--png", action="store_true",
                        help="Also capture board_preview.png / board_mobile.png (needs Playwright)")
    parser.add_argument("--open", action="store_true", help="Open the HTML preview in your browser")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    ctx = html_board.build_context(
        FAKE_CFG, FAKE_STATS, FAKE_STANDING, FAKE_LEADERS, "Voidspire Sanctum",
        FAKE_MPLUS, FAKE_SEASON_SCORES, FAKE_SEASON_PARSES,
        now - timedelta(days=7), now,
        improvement=FAKE_IMPROVEMENT, mplus_weekly=FAKE_MPLUS_WEEKLY,
        previous=FAKE_PREVIOUS, streaks=FAKE_STREAKS, records=FAKE_RECORDS)

    Path("board_render.html").write_text(html_board.render_html(ctx), encoding="utf-8")
    Path("board_mobile_render.html").write_text(
        html_board.render_html(ctx, template="mobile.html.j2"), encoding="utf-8")
    print("Wrote board_render.html (desktop) and board_mobile_render.html (mobile).")
    print("Open them in any browser — refresh after each theme.yml edit.")

    if args.png:
        out = html_board.generate_board_html(
            FAKE_CFG, FAKE_STATS, FAKE_STANDING, FAKE_LEADERS, "Voidspire Sanctum",
            FAKE_MPLUS, FAKE_SEASON_SCORES, FAKE_SEASON_PARSES,
            now - timedelta(days=7), now, output_path="board_preview.png",
            mobile_path="board_mobile.png",
            improvement=FAKE_IMPROVEMENT, mplus_weekly=FAKE_MPLUS_WEEKLY,
            previous=FAKE_PREVIOUS, streaks=FAKE_STREAKS, records=FAKE_RECORDS)
        print(f"Screenshot: {out or 'FAILED (is Playwright installed? pip install playwright && playwright install chromium)'}")

    if args.open:
        webbrowser.open(Path("board_render.html").resolve().as_uri())


if __name__ == "__main__":
    main()

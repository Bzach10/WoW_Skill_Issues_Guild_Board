"""The S.S. Wipe Fest — assembling the ship's rooms (HANGOUT_DESIGN Phase 0).

Turns the real board data + the guild's gag config (theme.yml) into the
content for each room below deck: the Crow's Nest lookout, "Who's Popping
Off," the Galley's MOTD, the Brig's Healer of Shame, and the Hold's
graveyard + Hall of Flame. The Casino debt, the roast and the Captain's
Log recap are already assembled upstream; this fills the rest.

Everything is a pure function of data already on disk, so a daily refresh
carries straight through.
"""

from datetime import datetime, timedelta

SHIP_NAME = "S.S. Wipe Fest"

# Raid nights, from the guild's own MOTD ("Raid times: Tue/Thu, 8 PM").
# Monday=0 … Sunday=6.
RAID_NIGHTS = (1, 3)      # Tue, Thu
RAID_HOUR = 20            # 8 PM local


def next_raid(now=None):
    """The next raid night as {day_name, when, days_away, hour}."""
    now = now or datetime.now()
    for ahead in range(0, 8):
        day = now + timedelta(days=ahead)
        if day.weekday() in RAID_NIGHTS:
            if ahead == 0 and now.hour >= RAID_HOUR:
                continue          # tonight's raid already started
            return {
                "day_name": day.strftime("%A"),
                "days_away": ahead,
                "hour": RAID_HOUR,
                "label": ("tonight" if ahead == 0 else
                          "tomorrow" if ahead == 1 else
                          day.strftime("%A")),
            }
    return None


def crows_nest(islands, board_state, theme, now=None):
    """What's ahead: next island, next boss, the raid countdown."""
    islands = islands or []
    # next uncleared dungeon island, and next unkilled raid boss
    next_island = next((i for i in islands
                        if i.get("kind") != "raid_boss"
                        and i.get("state") != "cleared"), None)
    next_boss = next((i for i in islands
                      if i.get("kind") == "raid_boss"
                      and i.get("state") != "cleared"), None)
    standing = (board_state or {}).get("standing") or {}
    return {
        "next_island": next_island,
        "next_boss": next_boss,
        "raid": next_raid(now),
        "standing": standing,
        "recruiting": True,
    }


def popping_off(wanted, board_state):
    """Auto shoutouts — rotating so it's never the same three names."""
    records = (board_state or {}).get("records") or {}
    out = []

    key = records.get("highest_timed_key") or {}
    if key.get("level") and key.get("dungeon"):
        out.append({"icon": "🗝️", "who": (key.get("name") or "").title(),
                    "line": f"drove the deepest key of the week — a +{key['level']} "
                            f"through {key['dungeon']}."})
    climb = (wanted or {}).get("biggest_climb")
    if climb and climb.get("delta"):
        out.append({"icon": "📈", "who": climb["name"],
                    "line": f"climbed hardest — up {climb['delta']:.1f} points of "
                            f"Mythic+ score."})
    dps = records.get("best_dps_parse") or {}
    if dps.get("parse") and dps.get("boss"):
        out.append({"icon": "🔥", "who": (dps.get("name") or "").title(),
                    "line": f"topped the charts with a {dps['parse']} on {dps['boss']}."})
    streak = (wanted or {}).get("longest_streak")
    if streak and streak.get("streak"):
        out.append({"icon": "⚓", "who": streak["name"],
                    "line": f"keeps showing up — {streak['streak']} weeks on deck and counting."})
    hps = records.get("best_hps_parse") or {}
    if hps.get("parse") and hps.get("boss"):
        out.append({"icon": "✨", "who": (hps.get("name") or "").title(),
                    "line": f"kept the crew breathing — a {hps['parse']} on {hps['boss']}."})
    return out


def galley(theme, week_index=0):
    """Item of the Month + the week's MOTD quip."""
    footer = (theme or {}).get("footer") or {}
    quips = (theme or {}).get("motd_quips") or []
    motd = quips[week_index % len(quips)] if quips else None
    return {
        "item_title": footer.get("item_title") or "Guild Item of the Month",
        "motd": motd,
        "quips": quips,
    }


def brig(theme):
    """The Bully Corner — Healer of Shame, opt-out honored."""
    grave = ((theme or {}).get("footer") or {}).get("graveyard") or {}
    shamed = grave.get("reserved")          # HEALMATES, canonically
    note = grave.get("reserved_note")
    if not shamed:
        return None
    return {
        "shamed": shamed.title() if shamed.isupper() else shamed,
        "note": note,
        "optout_note": "Anyone can leave the Brig for good — just say the word. "
                       "No questions, honored everywhere.",
    }


# Guild-canon epitaphs. Wipe humour, not real death counts — the Hold is a
# gag memorial. Officers can rewrite these in theme.yml later.
_EPITAPHS = [
    {"name": "The +21 Key", "epitaph": "Depleted on the last boss. 4 seconds over."},
    {"name": "“I Got It”", "epitaph": "He did not, in fact, got it."},
    {"name": "The Pull Timer", "epitaph": "Ignored. As always."},
    {"name": "One More Pull", "epitaph": "It was never one more pull."},
    {"name": "The Repair Bill", "epitaph": "Self-inflicted. Not reimbursable."},
    {"name": "Rakdisc's Patience", "epitaph": "Died blaming the tank."},
]


def hold(theme, roast=None):
    """The graveyard + reserved plot + Hall of Flame (roast archive)."""
    grave = ((theme or {}).get("footer") or {}).get("graveyard") or {}
    reserved = grave.get("reserved")
    hall = []
    if roast and roast.get("roast"):
        hall.append({
            "roast": roast["roast"],
            "winner": roast.get("winner") or "Anonymous",
            "target": roast.get("target") or "",
            "current": True,
        })
    return {
        "title": grave.get("title") or "Graveyard Campers Memorial",
        "caption": grave.get("caption") or "Die in the fire, enter the leaderboard.",
        "reserved": reserved.title() if (reserved and reserved.isupper()) else reserved,
        "reserved_note": grave.get("reserved_note"),
        "tombstones": _EPITAPHS,
        "hall_of_flame": hall,
        "most_roasted": reserved.title() if (reserved and reserved.isupper()) else reserved,
    }


# Officer-seeded guild canon — the inside-jokes shrine in the Bar.
INSIDE_JOKES = [
    {"title": "Why “Skill Issues”", "body": "Every wipe, every depleted key, every "
     "death to the same fire — the diagnosis was always the same. So we made it the "
     "name. Own the bit."},
    {"title": "Brewzleeh's Debt", "body": "It started with one !roll. It has never "
     "stopped. The counter only goes up, the collateral is his monk, and he has never "
     "once been ahead."},
    {"title": "The Great Healmates Wipe", "body": "Six straight weeks standing in the "
     "fire. A guild record nobody wanted and everybody remembers. The Brig has his "
     "name on the door."},
]

"""The trial showcase: three characters in full character-in-scene art.

This is the "second draft" presentation — distinct from the animated
paper-doll deck. The deck composites transparent cut-outs over a
changeable scene; a showcase scene is a single finished illustration of
the character *in* their setting, in the art direction Zach approved.

Scene art is resolved per character with an ordered list of candidates,
so the art team can drop a newer file in and it is picked up without a
code change. Every character degrades on its own: no scene art means the
card still renders with real data and says the art is pending.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# The trial cast, in the order they appear. Candidates are tried in
# order, newest/approved first — drop a better file in and it wins.
TRIAL_SCENES = {
    "rakdisc": {
        "setting": "The stone temple",
        "candidates": [
            # Stable handoff paths from the art pipeline (cast/_trial/)
            # are copies under fixed names, so the site never depends on
            # a seed number. Originals stay untouched behind them.
            # Nano Banana Pro Edit restyle — most consistent set across
            # all three, and the only one where every character is
            # unambiguously the right species.
            "cast/rakdisc/rakdisc_anime_final.png",
            "cast/_trial/rakdisc.png",
            "cast/rakdisc/scene1_raidhall_w025.png",
        ],
    },
    "floofwall": {
        "setting": "The tavern",
        "candidates": [
            # Nano Banana Pro Edit restyle — most consistent set across
            # all three, and the only one where every character is
            # unambiguously the right species.
            "cast/floofwall/floofwall_anime_final.png",
            "cast/_trial/floofwall.png",
            "cast/floofwall/floofwall_tavern_w025.png",
        ],
    },
    "healyeah": {
        "setting": "The Dragon Isles",
        "candidates": [
            # Nano Banana Pro Edit restyle — most consistent set across
            # all three, and the only one where every character is
            # unambiguously the right species.
            "cast/healyeah/healyeah_anime_final.png",
            "cast/_trial/healyeah.png",
            "cast/healyeah/healyeah_dragonflight_v2_w030.png",
        ],
    },
}

# The art pipeline also ships alternates. Swapping one in is a config
# change, not a code change:
#
#   showcase:
#     scenes:
#       healyeah: "cast/_trial/healyeah_alt.png"
ALTERNATES = {
    "healyeah": "cast/_trial/healyeah_alt.png",
}

TRIAL_ORDER = ["floofwall", "rakdisc", "healyeah"]   # tank · healer · dps


def resolve_scene(slug, cfg=None):
    """The scene illustration for one character.

    An officer can override the pick in config.yml without touching code:

        showcase:
          scenes:
            rakdisc: "cast/rakdisc/scene3_vista_w045.png"
    """
    override = (((cfg or {}).get("showcase") or {}).get("scenes") or {}).get(slug)
    entry = TRIAL_SCENES.get(slug) or {}
    candidates = []
    if isinstance(override, str) and override.strip():
        candidates.append(override.strip())
    candidates += entry.get("candidates") or []

    for candidate in candidates:
        if Path(candidate).exists():
            return {
                "src": candidate.replace(os.sep, "/"),
                "setting": entry.get("setting", ""),
                "pending": False,
            }
    if candidates:
        logger.info("No scene art on disk yet for %s (tried %s).",
                    slug, ", ".join(candidates))
    return {"src": None, "setting": entry.get("setting", ""), "pending": True}


def build_cards(crew, profiles_by_slug, cfg=None):
    """One showcase card per trial character, in tank/healer/dps order.

    Only characters we actually have on the deck are included — the page
    never invents a member.
    """
    by_slug = {m["slug"]: m for m in crew or []}
    cards = []
    for slug in TRIAL_ORDER:
        member = by_slug.get(slug)
        if not member:
            logger.info("Trial character %r is not on the deck; skipping.", slug)
            continue
        profile = profiles_by_slug.get(slug) or {}
        cards.append({
            "slug": slug,
            "member": member,
            "profile": profile,
            "scene": resolve_scene(slug, cfg),
        })
    return cards


def trial_status(cards):
    """A plain-English line about what is real and what is still coming."""
    ready = [c for c in cards if not c["scene"]["pending"]]
    pending = [c["member"]["name"] for c in cards if c["scene"]["pending"]]
    parts = [f"{len(ready)} of {len(cards)} scenes delivered"]
    if pending:
        parts.append("awaiting art: " + ", ".join(pending))
    return " · ".join(parts)

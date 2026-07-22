"""The weekly two-panel manga strip (ANIM-08).

A tiny comic built from the week's real events, laid over the scene
dioramas we already have. The first panel narrates the week's headline
deed; the second delivers the roast of the week as an actual speech
bubble — a genuine quote, so it earns the bubble. With no roast on the
board, the second panel falls back to the week's clutch heal, narrated.

No dialogue is invented. Derived lines are narration boxes; only a real
quote becomes a speech bubble.
"""


def _label(name):
    return (name or "").strip().replace("-", " ").title() or "Someone"


def _headline_panel(records):
    """The biggest single deed of the week, as a narration caption."""
    key = records.get("highest_timed_key") or {}
    dps = records.get("best_dps_parse") or {}
    if key.get("level") and key.get("dungeon"):
        return {
            "kind": "narration",
            "who": _label(key.get("name")),
            "text": f"drove a +{key['level']} through {key['dungeon']} — "
                    f"the deepest key of the week.",
        }
    if dps.get("parse") and dps.get("boss"):
        return {
            "kind": "narration",
            "who": _label(dps.get("name")),
            "text": f"topped the charts with a {dps['parse']} on {dps['boss']}.",
        }
    return None


def _punchline_panel(records, cfg):
    """The roast as a speech bubble, or the clutch heal as narration."""
    roast_cfg = ((cfg or {}).get("sections") or {}).get("roast_of_the_week") or {}
    if roast_cfg.get("roast"):
        return {
            "kind": "speech",
            "who": _label(roast_cfg.get("winner")),
            "target": _label(roast_cfg.get("target")) if roast_cfg.get("target") else None,
            "text": roast_cfg["roast"].strip(),
        }
    hps = records.get("best_hps_parse") or {}
    if hps.get("parse") and hps.get("boss"):
        return {
            "kind": "narration",
            "who": _label(hps.get("name")),
            "text": f"answered with a {hps['parse']} on {hps['boss']} — "
                    f"the crew lived to tell it.",
        }
    return None


def strip(board_state, cfg=None, stills=None):
    """Return the week's two-panel strip, or None if there is nothing to tell.

    `stills` is a list of scene-still image paths to lay the panels over;
    it is cycled, so one still is enough and two reads best. The panels
    are decorative backdrops — the strip never claims the events happened
    in that scene.
    """
    records = (board_state or {}).get("records") or {}
    panels = [p for p in (_headline_panel(records),
                          _punchline_panel(records, cfg)) if p]
    if not panels:
        return None

    stills = [s for s in (stills or []) if s]
    for i, panel in enumerate(panels):
        panel["still"] = stills[i % len(stills)] if stills else None
    return {"panels": panels}

"""Player profile pages: one real permalink per crew member.

This is also the durable fix for the blank-link bug. Before, a player's
name linked straight out to Warcraft Logs on a guessed realm; now every
member has a page we own and can always render, with the external links
(correct realm, via guild_board.links) as outbound options rather than
the only destination.

Everything on a profile is REAL data already on disk:
  * identity   — cast_manifest.json (race/class/spec/gender/role) or the
                 evidence-gated fallback in guild_board.crew
  * standing   — board_state.json season_scores (score + rank + delta
                 against the stored baseline)
  * records    — board_state.json records, when this player holds one
  * streak     — board_state.json streaks
  * art        — the assembled paper doll, same rig as the deck

A player with none of the optional pieces still gets a page.
"""

import logging

from guild_board import links as links_mod

logger = logging.getLogger(__name__)

PROFILE_DIR = "p"


def profile_path(slug):
    """Where a member's page lives, relative to the site root."""
    return f"{PROFILE_DIR}/{slug}.html"


def profile_href(slug, from_profile=False):
    """Link to a profile from the board root, or from another profile."""
    return f"../{profile_path(slug)}" if from_profile else profile_path(slug)


def _rank_of(slug, season_scores):
    ordered = sorted((season_scores or {}).items(), key=lambda kv: -kv[1])
    for i, (name, _score) in enumerate(ordered, start=1):
        if name == slug:
            return i, len(ordered)
    return None, len(ordered)


def _records_for(slug, records):
    """Every board record this player currently holds, described plainly."""
    held = []
    for key, label in (("highest_timed_key", "Highest timed key"),
                       ("best_dps_parse", "Best DPS parse"),
                       ("best_hps_parse", "Best HPS parse")):
        record = (records or {}).get(key)
        record = record if isinstance(record, dict) else {}
        if (record.get("name") or "").strip().lower() != slug:
            continue
        if key == "highest_timed_key":
            detail = f"+{record.get('level')} {record.get('dungeon', '')}".strip()
            value = f"+{record.get('level')}"
        else:
            detail = f"{record.get('boss', '')}".strip()
            value = str(record.get("parse"))
        held.append({
            "label": label, "value": value, "detail": detail,
            "spec": " ".join(x for x in (record.get("spec"), record.get("cls")) if x),
            "fresh": bool(record.get("new")),
        })
    return held


def build_profile(member, board_state, cfg, roster_members, theme=None):
    """The full context for one member's page."""
    def _mapping(value):
        """board_state.json is written by another workstream; a section
        that is the wrong shape must not take a profile page down."""
        return value if isinstance(value, dict) else {}

    state = _mapping(board_state)
    season_scores = _mapping(state.get("season_scores"))
    baseline = _mapping(_mapping(state.get("baseline")).get("season_scores"))
    streaks = _mapping(state.get("streaks"))
    records = _mapping(state.get("records"))
    guild = _mapping(_mapping(cfg).get("guild"))
    region = (guild.get("region") or "us").lower()

    slug = member["slug"]
    score = season_scores.get(slug)
    rank, field = _rank_of(slug, season_scores)

    delta = None
    if score is not None and baseline.get(slug) is not None:
        raw = round(score - baseline[slug], 1)
        if raw:
            delta = f"{'+' if raw > 0 else ''}{raw}"

    index = links_mod.realm_index(roster_members)
    realm = links_mod.realm_for(slug, index)

    return {
        "member": member,
        "slug": slug,
        "name": member["name"],
        "realm": realm,
        "realm_label": (realm or "").replace("-", " ").title(),
        "score": score,
        "rank": rank,
        "field": field,
        "delta": delta,
        "streak": streaks.get(slug),
        "records": _records_for(slug, records),
        "wcl_url": links_mod.character_url(slug, index, region=region, site="wcl"),
        "rio_url": links_mod.character_url(slug, index, region=region, site="raiderio"),
        # An unresolved realm is stated on the page rather than hidden —
        # it is exactly the gap that produced the original blank links.
        "realm_unknown": not realm,
    }


def build_all(crew, board_state, cfg, roster_members, theme=None):
    return [build_profile(m, board_state, cfg, roster_members, theme) for m in crew]

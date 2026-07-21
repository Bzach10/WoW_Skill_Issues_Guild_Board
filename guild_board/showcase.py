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
# ---------------------------------------------------------------------
#  ONE resolver, used by every surface that shows a character: the trial
#  cards, the full-profile view, and the crew deck. Before this, the
#  cards used the new art while the profile and deck still rendered the
#  old paper-doll layers — which is exactly the mismatch Zach caught.
# ---------------------------------------------------------------------

# Any art path matching one of these is LEGACY and must never render.
# This is a hard floor: even if a manifest or a config override points at
# one, it is refused. Purging old art is a guarantee, not a convention.
OLD_ART_MARKERS = (
    "/one_piece/",       # paper-doll layer sets
    "cast/_trial/",      # the earlier IP-Adapter handoff
    "scene1_raidhall",   # pre-restyle scene picks
    "scene2_dungeon", "scene3_vista",
    "_tavern_", "_dragonflight_", "_plainbg_",
    "char_flat_", "char_form_", "il_light_", "il2_light_",
    "il_shadow_", "il2_shadow_", "hybrid_", "nightborne_",
    "/board.png", "composite.png",
)

# Where the restyle pipeline writes each character's final image.
NEW_ART_TEMPLATE = "cast/{slug}/{slug}_anime_final.png"

# Per-character scene labels. A character with no entry simply gets no
# label — the roster is wiring in over time and we never invent one.
SETTINGS = {
    "rakdisc": "The stone temple",
    "floofwall": "The tavern",
    "healyeah": "The Dragon Isles",
}

TRIAL_ORDER = ["floofwall", "rakdisc", "healyeah"]   # tank · healer · dps


def is_legacy_art(path):
    """True for any pre-restyle art path."""
    if not path or not isinstance(path, str):
        return False
    probe = path.replace("\\", "/").lower()
    return any(marker.lower() in probe for marker in OLD_ART_MARKERS)


def _usable(path):
    """A path that exists on disk AND is not legacy art."""
    if not path or not isinstance(path, str):
        return None
    if is_legacy_art(path):
        logger.info("Refusing legacy art %s — the site shows the new style only.",
                    path)
        return None
    return path.replace(os.sep, "/") if Path(path).exists() else None


def _manifest_art(slug, manifest):
    """The character's image from cast_manifest.json, if the roster
    generation has delivered one. Accepts either a flat `board`-style
    entry or an explicit `scene`/`final` key, and ignores layer sets —
    those are the old paper-doll art."""
    characters = (manifest or {}).get("characters")
    if not isinstance(characters, dict):
        return None
    active = (manifest or {}).get("active_style")
    for key, character in characters.items():
        if not isinstance(character, dict):
            continue
        if slugify(character.get("name") or key.split("-")[0]) != slug:
            continue
        styles = character.get("styles")
        if not isinstance(styles, dict):
            return None
        # the active style first, then any other style the character has
        ordered = ([styles[active]] if isinstance(styles.get(active), dict) else [])
        ordered += [v for k, v in styles.items() if k != active and isinstance(v, dict)]
        for assets in ordered:
            for field in ("scene", "final", "board"):
                found = _usable(assets.get(field))
                if found:
                    return found
    return None


def slugify(name):
    return "".join(c.lower() if c.isalnum() else "-" for c in (name or "")).strip("-")


def image_aspect(path):
    """(w / h) for a scene image, or None if it cannot be read. Lets the
    card use a clean fill when the art is the agreed 3:4 and fall back to
    a contained, blurred-fill treatment when it is not."""
    try:
        from PIL import Image
        with Image.open(path) as img:
            if img.height:
                return round(img.width / img.height, 4)
    except Exception:  # noqa: BLE001 - an unreadable file is simply unmeasurable
        pass
    return None


TARGET_ASPECT = 0.75          # 3:4 portrait, the agreed roster spec
ASPECT_TOLERANCE = 0.04       # anything this close fills the frame cleanly


def character_art(slug, cfg=None, manifest=None):
    """The one image for this character, wherever they are displayed.

    Resolution order — new art only, at every step:
      1. config.yml showcase.scenes.<slug>   (officer override)
      2. cast_manifest.json                  (the roster generation)
      3. cast/<slug>/<slug>_anime_final.png  (filesystem convention)
    """
    slug = slugify(slug)
    override = (((cfg or {}).get("showcase") or {}).get("scenes") or {}).get(slug)
    src = (_usable(override)
           or _manifest_art(slug, manifest)
           or _usable(NEW_ART_TEMPLATE.format(slug=slug)))

    aspect = image_aspect(src) if src else None
    fills = aspect is not None and abs(aspect - TARGET_ASPECT) <= ASPECT_TOLERANCE
    return {
        "src": src,
        "setting": SETTINGS.get(slug, ""),
        "pending": src is None,
        "aspect": aspect,
        # True once the art matches the 3:4 roster spec, so the card can
        # fill edge to edge instead of letterboxing.
        "fills": bool(fills),
    }


def resolve_scene(slug, cfg=None, manifest=None):
    """Back-compatible name used by the trial cards."""
    return character_art(slug, cfg, manifest)


def build_cards(crew, profiles_by_slug, cfg=None, manifest=None):
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
            "scene": resolve_scene(slug, cfg, manifest),
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


def build_roster_cards(crew, profiles_by_slug, cfg=None, manifest=None):
    """A card for EVERY crew member who has new-style art, in deck order.

    The trial is three characters; as the roster generation delivers, this
    grows on its own with no code change.
    """
    cards = []
    for member in crew or []:
        art = character_art(member["slug"], cfg, manifest)
        if art["pending"]:
            continue
        cards.append({
            "slug": member["slug"],
            "member": member,
            "profile": profiles_by_slug.get(member["slug"]) or {},
            "scene": art,
        })
    return cards

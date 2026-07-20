"""The crew: who stands on the deck, what role they play, and where the
ship currently is on the voyage.

Everything here is REAL-DATA-FIRST and fails open:

  * Roles come from Blizzard's profile cache (active spec -> role) when
    the art/profile pipeline has written one. That file is the single
    source of truth for class/spec/gender/race.
  * When there is no profile cache yet, we fall back ONLY to characters
    whose class or role is actually evidenced somewhere in this repo
    (a parse record naming their spec, the debt gag naming Brewzleeh's
    monk, the rakdisc cast art being a priest). Every fallback entry
    carries the receipt in `evidence` and is tagged source="derived",
    so nothing on the board is silently invented.
  * A crew member we cannot place gets role "unknown": they still stand
    on the deck under "All Hands", they just do not claim a role tab.

The art slot for each member is a transparent PNG under cast/<slug>/.
Missing art degrades to a silhouette placeholder — never a broken page.
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

PROFILE_CACHE = "blizzard_profile_cache.json"
CAST_DIR = Path("cast")
PLACEHOLDER_DIR = CAST_DIR / "placeholders"

# Standard WoW spec -> role. Used only to translate a REAL active_spec
# from the profile cache; it never guesses at a character we have no
# spec for.
SPEC_ROLE = {
    # tanks
    "Protection": "tank", "Blood": "tank", "Guardian": "tank",
    "Brewmaster": "tank", "Vengeance": "tank",
    # healers
    "Holy": "healer", "Discipline": "healer", "Restoration": "healer",
    "Mistweaver": "healer", "Preservation": "healer",
    # everything else is damage
    "Arms": "dps", "Fury": "dps", "Retribution": "dps", "Frost": "dps",
    "Unholy": "dps", "Feral": "dps", "Balance": "dps", "Windwalker": "dps",
    "Havoc": "dps", "Beast Mastery": "dps", "BeastMastery": "dps",
    "Marksmanship": "dps", "Survival": "dps", "Assassination": "dps",
    "Outlaw": "dps", "Subtlety": "dps", "Arcane": "dps", "Fire": "dps",
    "Affliction": "dps", "Demonology": "dps", "Destruction": "dps",
    "Elemental": "dps", "Enhancement": "dps", "Shadow": "dps",
    "Devastation": "dps", "Augmentation": "dps",
}

# "Protection" and "Frost" and "Holy" are ambiguous across classes; these
# (class, spec) pairs settle the ones that actually differ.
CLASS_SPEC_ROLE = {
    ("Paladin", "Holy"): "healer",
    ("Priest", "Holy"): "healer",
    ("Warrior", "Protection"): "tank",
    ("Paladin", "Protection"): "tank",
    ("Death Knight", "Frost"): "dps",
    ("Mage", "Frost"): "dps",
    ("Shaman", "Restoration"): "healer",
    ("Druid", "Restoration"): "healer",
}

ROLE_LABEL = {"tank": "Tank", "healer": "Healer", "dps": "DPS",
              "unknown": "Deckhand"}

# The crew we can stand up from evidence already in this repository.
# `evidence` is the receipt for why we believe the class/role — if you
# cannot point at one, the character does not get a role here.
DERIVED_CREW = {
    "amrevenge": {
        "display": "Amrevenge", "cls": "Hunter", "spec": "Beast Mastery",
        "evidence": "board_state.json records.best_dps_parse (BeastMastery Hunter, 97)",
    },
    "phyrthepali": {
        "display": "Phyrthepali", "cls": "Paladin", "spec": "Holy",
        "evidence": "board_state.json records.best_hps_parse (Holy Paladin, 96)",
    },
    "rakdisc": {
        "display": "Rakdisc", "cls": "Priest", "spec": "Discipline",
        "evidence": "cast/rakdisc/ light+shadow priest art set",
    },
    "brewzleeh": {
        "display": "Brewzleeh", "cls": "Monk", "spec": None,
        "evidence": "theme.yml footer.debt.interest_note ('collateral: his monk')",
    },
}

# Catchphrases are GAGS, not data — pure theme.yml territory. These are
# the shipped defaults; theme.yml `crew.catchphrases.<slug>` overrides
# any of them, and an unknown crew member simply gets no bubble.
DEFAULT_CATCHPHRASES = {
    "brewzleeh": "One more roll and I'm even.",
    "rakdisc": "I can fix him. (I cannot fix him.)",
    "amrevenge": "Pet's doing 40% of that, actually.",
    "phyrthepali": "You are welcome. You are ALL welcome.",
    "healmates": "Stood in the fire. On purpose. For the bit.",
}

# The three canonical themes, exactly as locked in the design direction.
# theme.yml `crew.themes.<key>.<token>` overrides any single token; a
# typo'd or missing token falls back to the value here, so the page can
# never render without a palette.
CREW_THEMES = {
    "codex": {
        "label": "Illuminated Codex",
        "bg": "#e7d3ad", "text": "#3a2c17", "heading": "#4a2f12",
        "accent": "#9b5e1f", "panel": "#f7eed8", "line": "#c8ad7e",
        "muted": "#6b5637", "display": "Cinzel Decorative", "body": "Inter",
        "scheme": "light",
    },
    "console": {
        "label": "Arcane Console",
        "bg": "#120c1e", "text": "#e7dcf7", "heading": "#e7dcf7",
        "accent": "#38e0c8", "panel": "#191128", "line": "#33264d",
        "muted": "#9d8fbb", "display": "JetBrains Mono", "body": "Inter",
        "scheme": "dark",
    },
    "chronicle": {
        "label": "Chronicle",
        "bg": "#180f28", "text": "#efe7dd", "heading": "#efe7dd",
        "accent": "#d8a24a", "panel": "#20152c", "line": "#3c2e4a",
        "muted": "#b0a08f", "display": "Cinzel Decorative", "body": "Inter",
        "scheme": "dark",
    },
}

THEME_ORDER = ["codex", "console", "chronicle"]

# Role accent tints, per the locked design direction.
ROLE_TINT = {"tank": "#6f9fd0", "healer": "#4fc9a2", "dps": "#b07fe0",
             "unknown": "#9b8f7a"}


def role_for(cls, spec):
    """Real class+spec -> role. Returns "unknown" when we cannot tell."""
    cls = (cls or "").strip()
    spec = (spec or "").strip()
    if not spec:
        return "unknown"
    if (cls, spec) in CLASS_SPEC_ROLE:
        return CLASS_SPEC_ROLE[(cls, spec)]
    return SPEC_ROLE.get(spec, "unknown")


def slugify(name):
    return "".join(c.lower() if c.isalnum() else "-" for c in (name or "")).strip("-")


def _is_cutout(path):
    """True only for a PNG that is actually cut out — i.e. it has an
    alpha channel with real transparent pixels.

    The deck stands the crew on a ship; a raw generation still sitting on
    its solid studio background would paste a white rectangle onto the
    board. So the contract with the art pipeline is explicit: the deck
    accepts transparent PNGs, and anything else falls back to the
    silhouette slot instead of rendering wrong.
    """
    try:
        from PIL import Image
    except ImportError:
        # No Pillow to inspect with — trust only the explicitly curated
        # filename, which the pipeline controls.
        return Path(path).name == "board.png"
    try:
        with Image.open(path) as img:
            if img.mode not in ("RGBA", "LA", "PA"):
                return False
            alpha = img.getchannel("A")
            return alpha.getextrema()[0] < 250
    except Exception:  # noqa: BLE001 - an unreadable file is simply not art
        return False


def _cutouts(slug, pattern="*.png"):
    """Every transparent PNG in a crew member's art folder, sorted."""
    folder = CAST_DIR / slug
    if not folder.is_dir():
        return []
    return [p for p in sorted(folder.glob(pattern)) if _is_cutout(p)]


def _art_slot(slug):
    """Transparent-PNG slot for a crew member. The art pipeline drops
    cut-outs in cast/<slug>/; until then we hand back the placeholder
    and flag it so the caller can label what is still stubbed.
    """
    folder = CAST_DIR / slug
    if folder.is_dir():
        # An explicit "board.png" is the pipeline's curated pick.
        preferred = folder / "board.png"
        if preferred.exists() and _is_cutout(preferred):
            return str(preferred).replace(os.sep, "/"), True
        cutouts = _cutouts(slug)
        if cutouts:
            return str(cutouts[0]).replace(os.sep, "/"), True
    placeholder = PLACEHOLDER_DIR / "crew_slot.png"
    if placeholder.exists():
        return str(placeholder).replace(os.sep, "/"), False
    return None, False


def _shadow_art(slug):
    """Rakdisc's Shadowform alternate, if the art set has a cut-out one."""
    for png in _cutouts(slug, "*shadow*.png"):
        return str(png).replace(os.sep, "/")
    return None


def _light_art(slug):
    for png in _cutouts(slug, "*light*.png"):
        return str(png).replace(os.sep, "/")
    return None


def load_profiles(path=PROFILE_CACHE):
    """The Blizzard profile cache the art pipeline writes, or {} if it
    has not landed yet."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return (json.load(fh) or {}).get("characters") or {}
    except (OSError, ValueError) as exc:
        logger.info("No Blizzard profile cache yet (%s); using derived crew.", exc)
        return {}


def build_crew(cfg, theme, season_scores=None, profiles=None, limit=10):
    """The cast standing on the deck.

    Ordered by real season M+ score (highest first) so the deck reflects
    the actual ladder. Role/class come from the profile cache when it
    exists, else from DERIVED_CREW's evidenced entries.
    """
    season_scores = season_scores or {}
    profiles = load_profiles() if profiles is None else profiles
    crew_cfg = (cfg or {}).get("cast") or {}
    opt_out = {n.lower() for n in (crew_cfg.get("opt_out") or [])}
    phrases = dict(DEFAULT_CATCHPHRASES)
    phrases.update(((theme or {}).get("crew") or {}).get("catchphrases") or {})

    # Candidate slugs: everyone we have a profile for, plus everyone we
    # have repo evidence for, intersected with people who actually have
    # a real season score (i.e. they really play).
    candidates = {}
    for key, profile in (profiles or {}).items():
        slug = slugify((profile.get("name") or key).split("-")[0])
        candidates[slug] = {
            "display": profile.get("name") or slug.title(),
            "cls": profile.get("class"),
            "spec": profile.get("active_spec"),
            "evidence": "blizzard_profile_cache.json",
            "source": "real",
        }
    for slug, entry in DERIVED_CREW.items():
        if slug in candidates:
            continue
        candidates[slug] = dict(entry, source="derived")

    # Fill the remaining deck slots with the top of the REAL season
    # ladder. We know these people play and we know their score; we do
    # not know their spec until the profile cache lands, so they stand
    # as role-less deckhands rather than getting a guessed role.
    for slug, _score in sorted(season_scores.items(), key=lambda kv: -kv[1]):
        if len(candidates) >= limit + len(opt_out):
            break
        if slug in candidates:
            continue
        candidates[slug] = {
            "display": slug.title(), "cls": None, "spec": None,
            "evidence": "board_state.json season_scores (real M+ score)",
            "source": "derived",
        }

    crew = []
    for slug, entry in candidates.items():
        if slug in opt_out or f"{slug}-" in opt_out:
            continue
        role = role_for(entry.get("cls"), entry.get("spec"))
        art, art_is_real = _art_slot(slug)
        shadow = _shadow_art(slug)
        light = _light_art(slug)
        crew.append({
            "slug": slug,
            "name": entry["display"],
            "cls": entry.get("cls") or "",
            "spec": entry.get("spec") or "",
            "role": role,
            "role_label": ROLE_LABEL.get(role, "Deckhand"),
            "tint": ROLE_TINT.get(role, ROLE_TINT["unknown"]),
            "score": season_scores.get(slug),
            "art": art,
            "art_is_real": art_is_real,
            # Shadowform belongs to Priests, so the toggle is offered to
            # any real Priest. When the art set actually has light+shadow
            # renders we swap the image; until then the toggle still
            # works and is expressed purely in CSS — the interaction
            # never waits on the art pipeline.
            "has_shadowform": (entry.get("cls") == "Priest") or bool(shadow and light),
            "shadow_art": shadow if (shadow and light) else None,
            "light_art": light if (shadow and light) else None,
            "catchphrase": phrases.get(slug),
            "evidence": entry.get("evidence"),
            "source": entry.get("source", "derived"),
        })

    # Real ladder order; unscored crew trail behind, alphabetically.
    crew.sort(key=lambda c: (c["score"] is None, -(c["score"] or 0), c["name"]))
    return crew[:limit]


def role_counts(crew):
    counts = {"all": len(crew), "tank": 0, "healer": 0, "dps": 0, "unknown": 0}
    for member in crew:
        counts[member["role"]] = counts.get(member["role"], 0) + 1
    return counts


def resolve_themes(theme):
    """The three palettes, with theme.yml overrides deep-merged in.

    A non-coder edits theme.yml:

        crew:
          themes:
            codex:
              accent: "#b06a12"

    Anything they omit or mistype keeps the shipped value.
    """
    crew_cfg = (theme or {}).get("crew") or {}
    if not isinstance(crew_cfg, dict):
        crew_cfg = {}
    overrides = crew_cfg.get("themes") or {}
    if not isinstance(overrides, dict):
        logger.info("theme.yml crew.themes is not a mapping; using shipped palettes.")
        overrides = {}
    out = {}
    for key in THEME_ORDER:
        palette = dict(CREW_THEMES[key])
        per_theme = overrides.get(key) or {}
        if not isinstance(per_theme, dict):
            logger.info("theme.yml crew.themes.%s is not a mapping; ignored.", key)
            per_theme = {}
        for token, value in per_theme.items():
            if token in palette and isinstance(value, str) and value.strip():
                palette[token] = value.strip()
            elif token not in palette:
                logger.info("theme.yml crew.themes.%s.%s is not a known token; ignored.",
                            key, token)
        out[key] = palette
    return out


def default_theme_key(theme):
    key = (((theme or {}).get("crew") or {}).get("default_theme") or "").strip()
    return key if key in CREW_THEMES else "codex"


def load_islands(cfg, board_state=None):
    """The voyage map's islands.

    Consumes guild_board.voyage (the data model the art/data workstream
    owns) when it is importable. If it is not present on this branch
    yet, we degrade to a clearly-labelled sample chain so the map still
    renders and the interface stays exercised.

    TODO(wire-real-data): once guild_board/voyage.py lands on the shared
    branch, the fallback below becomes dead code and can be deleted.
    """
    try:
        from guild_board import voyage as voyage_mod
    except ImportError:
        logger.warning("guild_board.voyage not on this branch; using sample islands.")
        return _sample_islands(), None, False

    try:
        islands = voyage_mod.build_islands()
        current = voyage_mod.current_island_id(cfg)
    except Exception as exc:  # noqa: BLE001 - the map must never break the page
        logger.warning("Voyage data model raised (%s); using sample islands.", exc)
        return _sample_islands(), None, False

    # Attach per-island data from records we already have on disk. The
    # dungeon fetcher hits the network, so it is NOT called here — the
    # renderer stays offline-safe and the island shows "no record yet"
    # until the data workstream's fetch populates it.
    for island in islands:
        island["data"] = None
        if island["kind"] == "raid_boss" and board_state:
            try:
                island["data"] = voyage_mod.fetch_raid_island_data(
                    board_state, island["name"])
            except Exception:  # noqa: BLE001
                island["data"] = None
    return islands, current, True


def _sample_islands():
    """Interface-shaped sample data: same keys guild_board.voyage emits
    ({id, name, kind, flavor, data}), so wiring the real module in is a
    drop-in swap."""
    sample = [
        ("Ara-Kara, City of Echoes", "dungeon"),
        ("City of Threads", "dungeon"),
        ("The Dawnbreaker", "dungeon"),
        ("The Stonevault", "dungeon"),
        ("Imperator Averzian", "raid_boss"),
    ]
    return [{"id": slugify(name), "name": name, "kind": kind,
             "flavor": "", "data": None, "sample": True}
            for name, kind in sample]

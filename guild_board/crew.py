"""The crew: who stands on the deck, what role they play, and where the
ship currently is on the voyage.

Everything here is REAL-DATA-FIRST and fails open:

  * The ROSTER comes from the backend's live pull (competition.json)
    when it is present: all members, keyed `name-realm` — the only key
    that survives two crewmates sharing a name (there are two Berobens).
    URL slugs stay short for unique names and disambiguate only on
    collision, so no existing page address breaks without cause.
  * Roles come from the live pull, else Blizzard's profile cache
    (active spec -> role) when the art/profile pipeline has written one.
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

from guild_board import paperdoll

logger = logging.getLogger(__name__)

PROFILE_CACHE = "blizzard_profile_cache.json"
CAST_MANIFEST = "cast_manifest.json"
# The merged roster the bounty extract produces from the live pull PLUS
# data/roster_supplement.json (the pull alone is a floor, not the guild —
# it missed a real, actively-raiding member on the guild's own realm).
# extract_roster.py also owns the slug policy: short names, accent-folded,
# ordinals only for true collisions. One derivation, consumed everywhere.
CREW_ROSTER = "roster.json"
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


# ---------------------------------------------------------------------
#  cast_manifest.json — the shared contract with the art pipeline.
#
#  { "active_style": "one_piece", "styles_available": [...],
#    "characters": { "<slug>": {
#        "name","realm","race","class","spec","gender","role",
#        "transmog_fingerprint","render_url",
#        "styles": { "<style>": {
#            "board": "cast/<slug>/<style>/board.png",
#            "forms": {"light": "...", "shadow": "..."},
#            "version": N, "generated_at": "ISO" } },
#        "history": [...] } } }
#
#  The pipeline owns this file. We only ever READ it, and every field is
#  treated as optional — a half-written manifest degrades to silhouettes
#  rather than breaking the board.
# ---------------------------------------------------------------------

def load_manifest(path=CAST_MANIFEST):
    """The art pipeline's cast manifest, or {} until it lands."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        logger.info("No cast manifest yet (%s); falling back to derived crew.", exc)
        return {}
    if not isinstance(data, dict):
        logger.warning("cast_manifest.json is not an object; ignoring it.")
        return {}
    return data


def resolve_style(manifest, theme=None, override=None):
    """Which art style the board renders.

    Precedence: an explicit override (CLI/preview) > theme.yml's
    crew.style > the manifest's own active_style. A style nobody has
    assets for still resolves — per-character lookup falls back on its
    own, so a bad value can never blank the deck.
    """
    manifest = manifest or {}
    available = manifest.get("styles_available") or []
    if not isinstance(available, list):
        available = []

    for candidate, source in (
        (override, "override"),
        ((((theme or {}).get("crew") or {}) if isinstance((theme or {}).get("crew"), dict)
          else {}).get("style"), "theme.yml crew.style"),
        (manifest.get("active_style"), "manifest active_style"),
    ):
        if candidate and isinstance(candidate, str):
            if available and candidate not in available:
                logger.info("Style %r (%s) is not in styles_available %s; using it "
                            "anyway if assets exist.", candidate, source, available)
            return candidate
    # Nothing declared anywhere — take the first style the manifest lists.
    return available[0] if available else None


def _manifest_style_assets(character, style):
    """(assets, style_used) for one character, or (None, None).

    If the character has no assets for the requested style we fall back
    to any style they DO have, so flipping active_style before every
    character has been regenerated leaves a full deck rather than a row
    of silhouettes.
    """
    styles = (character or {}).get("styles")
    if not isinstance(styles, dict) or not styles:
        return None, None
    if style and isinstance(styles.get(style), dict):
        return styles[style], style
    for key, assets in styles.items():
        if isinstance(assets, dict):
            return assets, key
    return None, None


def _usable_cutout(path):
    """A manifest path is only usable if the file is really there and
    really transparent — the deck must never paste a solid rectangle."""
    if not path or not isinstance(path, str):
        return None
    candidate = Path(path)
    if not candidate.exists() or not _is_cutout(candidate):
        return None
    return str(candidate).replace(os.sep, "/")


def manifest_art(character, style):
    """Resolve one character's art from the manifest.

    Returns a dict the deck can render directly. Every field degrades on
    its own: a missing/opaque board falls back to the silhouette, and
    missing forms simply mean no art swap on the Shadowform toggle.
    """
    assets, style_used = _manifest_style_assets(character, style)
    if not assets:
        return None

    board = _usable_cutout(assets.get("board"))
    forms = assets.get("forms") if isinstance(assets.get("forms"), dict) else {}
    light = _usable_cutout(forms.get("light"))
    shadow = _usable_cutout(forms.get("shadow"))

    # A character with only form art and no board pick still stands:
    # the light form is the natural default.
    if not board:
        board = light or shadow
    if not board:
        return None

    return {
        "art": board,
        "art_is_real": True,
        "light_art": light,
        "shadow_art": shadow,
        "style_used": style_used,
        "style_is_fallback": bool(style and style_used and style_used != style),
        "version": assets.get("version"),
        "generated_at": assets.get("generated_at"),
    }


def load_profiles(path=PROFILE_CACHE):
    """The Blizzard profile cache the art pipeline writes, or {} if it
    has not landed yet."""
    try:
        with open(path, encoding="utf-8") as fh:
            return (json.load(fh) or {}).get("characters") or {}
    except (OSError, ValueError) as exc:
        logger.info("No Blizzard profile cache yet (%s); using derived crew.", exc)
        return {}


def load_crew_roster(path=CREW_ROSTER):
    """The extract's merged roster: every member, keyed `name-realm`,
    slug policy already applied (see extract_roster.py in the docs repo).

    This is the roster authority when present (133 members: the 132-row
    2026-07-20 pull + the evidence-mandatory supplement). Returns [] when
    the file is absent or unreadable so build_crew can fall back to the
    legacy candidate sources — fail open, never fail the render.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh) or {}
    except (OSError, ValueError) as exc:
        logger.info("No %s (%s); crew falls back to legacy sources.", path, exc)
        return []
    rows = data.get("characters")
    rows = [r for r in rows if isinstance(r, dict)
            and r.get("name") and r.get("slug") and r.get("key")] \
        if isinstance(rows, list) else []
    if rows:
        meta = data.get("meta") or {}
        logger.info("Roster from %s: %d members (pull %s, %d supplemented).",
                    path, len(rows), meta.get("based_on", "undated"),
                    meta.get("supplement_count", 0))
    return rows


def build_crew(cfg, theme, season_scores=None, profiles=None, limit=10,
               manifest=None, style=None, competition=None):
    """The cast standing on the deck.

    Ordered by real season M+ score (highest first) so the deck reflects
    the actual ladder.

    Source precedence for who someone IS:
      1. cast_manifest.json  — the art pipeline's contract (richest: real
         race/class/spec/gender/role straight off their WoW character)
      2. blizzard_profile_cache.json
      3. DERIVED_CREW        — only what this repo can evidence
      4. season_scores       — a real player with a real score, no role

    Art always comes from the manifest's active style when it is there,
    and degrades to the silhouette slot when it is not.
    """
    season_scores = season_scores or {}
    profiles = load_profiles() if profiles is None else profiles
    manifest = load_manifest() if manifest is None else manifest
    style = resolve_style(manifest, theme) if style is None else style
    characters = manifest.get("characters") if isinstance(manifest, dict) else None
    characters = characters if isinstance(characters, dict) else {}
    # The caller opts in to the live pull explicitly (render_crew_board
    # passes load_competition()). No silent disk read here: what a test
    # or preview builds must not depend on the working directory.
    competition = competition or []

    crew_cfg = (cfg or {}).get("cast") or {}
    opt_out = {n.lower() for n in (crew_cfg.get("opt_out") or [])}
    phrases = dict(DEFAULT_CATCHPHRASES)
    phrases.update(((theme or {}).get("crew") or {}).get("catchphrases") or {})

    candidates = {}

    if competition:
        # ------------------------------------------------------------------
        # THE MERGED ROSTER IS THE AUTHORITY. Every member of the guild,
        # keyed name-realm — the only keying that keeps two same-named
        # crewmates apart. Legacy sources below ENRICH these entries (art,
        # race/gender) but may not add members: someone in an old cache but
        # not in the roster is not on the crew (they are parked instead).
        # ------------------------------------------------------------------
        def _bare_spec(spec, cls):
            """'Protection Paladin' -> 'Protection': some sources suffix the
            class onto the spec; every other source here keeps them apart."""
            s, c = (spec or "").strip(), (cls or "").strip()
            if c and s.lower().endswith(" " + c.lower()):
                return s[:-(len(c) + 1)].strip()
            return s

        # {"healing"/"heal" -> "healer"} etc: the extract says "healing"
        # where the deck says "healer". Unknown strings still derive from
        # the real spec rather than being trusted.
        role_alias = {"healing": "healer", "heal": "healer", "damage": "dps"}

        name_counts = {}
        for row in competition:
            n = slugify(row.get("name"))
            name_counts[n] = name_counts.get(n, 0) + 1
        for row in competition:
            key, slug = row["key"], row["slug"]
            name_slug = slugify(row.get("name"))
            declared = (row.get("role") or "").strip().lower()
            candidates[slug] = {
                "display": row.get("name") or slug.title(),
                "cls": row.get("class"),
                "spec": _bare_spec(row.get("spec"), row.get("class")),
                "declared_role": role_alias.get(declared, declared) or None,
                "evidence": f"roster.json (live pull + supplement, {key})",
                "source": "real",
                "key": key,
                "realm": row.get("realm"),
                "realm_slug": row.get("realm_slug") or key[len(name_slug) + 1:] or None,
                # A zero is NOT a score (§5.6: never render 0 where a score
                # belongs, never sort the scoreless as if they placed last).
                "comp_score": row.get("score") or None,
                "comp_rank": row.get("rank"),
                # Bare-name data (board_state deltas, streaks, catchphrases)
                # may only be matched when the name is unambiguous. The
                # diacritic-preserving name slug is the board_state key.
                "legacy_slug": name_slug if name_counts.get(name_slug) == 1 else None,
            }
    else:
        # Candidate slugs: everyone we have a profile for, plus everyone we
        # have repo evidence for, intersected with people who actually have
        # a real season score (i.e. they really play).
        for key, profile in (profiles or {}).items():
            slug = slugify((profile.get("name") or key).split("-")[0])
            candidates[slug] = {
                "display": profile.get("name") or slug.title(),
                "cls": profile.get("class"),
                "spec": profile.get("active_spec"),
                "evidence": "blizzard_profile_cache.json",
                "source": "real",
            }

    # The manifest outranks the caches for art identity: it is the
    # pipeline's own record of the character it actually rendered.
    for manifest_id, character in characters.items():
        if not isinstance(character, dict):
            continue
        # The manifest keys characters as "<name>-<realm>". With the live
        # pull present that key matches directly; without it, every other
        # data source keys by bare name, so fall back to the name.
        slug = None
        if competition:
            for cand_slug, cand in candidates.items():
                if cand.get("key") == manifest_id:
                    slug = cand_slug
                    break
            if slug is None:
                name_slug = slugify(character.get("name") or manifest_id.split("-")[0])
                slug = name_slug if name_slug in candidates else None
            if slug is None:
                # In the manifest but not the live pull: keep the art on
                # file, but a non-member does not stand on the deck.
                logger.info("cast_manifest character %s is not in the live "
                            "pull; not adding them to the crew.", manifest_id)
                continue
            candidates[slug].update({
                "manifest_id": manifest_id,
                "race": character.get("race"),
                "gender": character.get("gender"),
                "render_url": character.get("render_url"),
                "_character": character,
            })
            # The live pull's class/spec/role are fresher than the
            # manifest's copy; only fill gaps, never overwrite.
            for field in ("cls", "spec"):
                src = character.get("class" if field == "cls" else "spec")
                if not candidates[slug].get(field) and src:
                    candidates[slug][field] = src
            continue
        slug = slugify(character.get("name") or manifest_id.split("-")[0])
        candidates[slug] = {
            "manifest_id": manifest_id,
            "display": character.get("name") or slug.title(),
            "cls": character.get("class"),
            "spec": character.get("spec"),
            "race": character.get("race"),
            "gender": character.get("gender"),
            # The pipeline may state the role outright; we still validate
            # it rather than trusting an arbitrary string.
            "declared_role": character.get("role"),
            "render_url": character.get("render_url"),
            "evidence": "cast_manifest.json (real WoW character)",
            "source": "manifest",
            "_character": character,
        }

    for slug, entry in DERIVED_CREW.items():
        if slug in candidates:
            continue
        if competition:
            # Evidenced in this repo but absent from the live pull. Kept as
            # PARKED (page renders, excluded from counts and boards) until
            # Zach resolves whether they are real. As of 2026-07-22 this is
            # exactly one character: phyrthepali.
            candidates[slug] = dict(entry, source="unresolved", parked=True,
                                    legacy_slug=slug)
            logger.info("%s is evidenced locally but absent from the live "
                        "pull; parked (page only, no counts).", slug)
            continue
        candidates[slug] = dict(entry, source="derived")

    # EVERY player with a real season score is a candidate. This loop
    # used to stop once `limit` candidates existed, which meant that once
    # the art manifest held more characters than the deck had slots, the
    # deck was drawn from "who has art" instead of "who ranks highest" —
    # silently dropping the guild's #2, #3, #6 and #10 players because
    # they had not been generated yet. Membership is decided by score;
    # having art is not a qualification for being on the board.
    # (With the live pull present the roster is already complete — a
    # bare-name score can add nobody the pull does not know.)
    if not competition:
        for slug, _score in sorted(season_scores.items(), key=lambda kv: -kv[1]):
            if slug in candidates:
                continue
            candidates[slug] = {
                "display": slug.title(), "cls": None, "spec": None,
                "evidence": "board_state.json season_scores (real M+ score)",
                "source": "derived",
            }

    crew = []
    for slug, entry in candidates.items():
        key = entry.get("key") or slug
        if (slug in opt_out or f"{slug}-" in opt_out
                or key in opt_out or entry.get("legacy_slug") in opt_out):
            continue

        # ---- role: a declared role is honoured only if it is a real
        # role name; otherwise we derive it from the real spec, and only
        # then fall back to "unknown". No step ever guesses.
        declared = (entry.get("declared_role") or "").strip().lower()
        if declared in ("tank", "healer", "dps"):
            role = declared
        else:
            if declared:
                logger.info("cast_manifest role %r for %s is not a known role; "
                            "deriving from spec instead.", declared, slug)
            role = role_for(entry.get("cls"), entry.get("spec"))

        # ---- art: the manifest's active style first, then the legacy
        # folder scan, then the silhouette. Art directories are keyed by
        # the pipeline's name-realm key when we know it (cast/<key>/),
        # falling back to the page slug for pre-keyed art.
        art_info = manifest_art(entry.get("_character"), style)
        if art_info is None:
            art, art_is_real = _art_slot(key)
            if not art_is_real and key != slug:
                art, art_is_real = _art_slot(slug)
            shadow, light = _shadow_art(slug), _light_art(slug)
            art_info = {
                "art": art, "art_is_real": art_is_real,
                "light_art": light if (shadow and light) else None,
                "shadow_art": shadow if (shadow and light) else None,
                "style_used": None, "style_is_fallback": False,
                "version": None, "generated_at": None,
            }

        # ---- paper-doll assembly: the layer stack this character is
        # built from. Falls back to the flat cut-out, then to nothing,
        # in which case the silhouette below carries the slot.
        style_assets, used_style = _manifest_style_assets(entry.get("_character"), style)
        doll = paperdoll.assemble(style_assets, fallback_board=art_info["art"])
        if doll["mode"] == "none" and art_info["art"]:
            doll = paperdoll.assemble({"board": art_info["art"]})

        # A character assembled from real layers HAS real art, even though
        # a layered manifest carries no flat `board` key for the older
        # cut-out path to find.
        if doll["mode"] == "layered":
            art_info["art_is_real"] = True
            art_info["art"] = doll["layers"][0]["src"]
            if art_info["style_used"] is None:
                art_info["style_used"] = used_style
                art_info["style_is_fallback"] = bool(
                    style and used_style and used_style != style)

        has_forms = bool(art_info["light_art"] and art_info["shadow_art"])
        # Score: the live pull's own number first (it is per name-realm,
        # so both Berobens keep their real scores); a bare-name score may
        # only fill in when the name is unambiguous.
        legacy = entry.get("legacy_slug")
        if legacy is None and "key" not in entry:
            legacy = slug  # legacy sources are bare-name keyed already
        score = entry.get("comp_score")
        if score is None and legacy:
            score = season_scores.get(legacy)
        crew.append({
            "slug": slug,
            "key": key,
            "legacy_slug": legacy,
            "realm": entry.get("realm"),
            "realm_slug": entry.get("realm_slug"),
            "rank": entry.get("comp_rank"),
            "parked": bool(entry.get("parked")),
            "manifest_id": entry.get("manifest_id"),
            "doll": doll,
            "name": entry["display"],
            "cls": entry.get("cls") or "",
            "spec": entry.get("spec") or "",
            "race": entry.get("race") or "",
            "role": role,
            "role_label": ROLE_LABEL.get(role, "Deckhand"),
            "tint": ROLE_TINT.get(role, ROLE_TINT["unknown"]),
            "score": score,
            "art": art_info["art"],
            "art_is_real": art_info["art_is_real"],
            "style_used": art_info["style_used"],
            "style_is_fallback": art_info["style_is_fallback"],
            "art_version": art_info["version"],
            # Shadowform belongs to Priests, so the toggle is offered to
            # any real Priest. When the art set actually has light+shadow
            # cut-outs we swap the image; until then the toggle still
            # works and is expressed purely in CSS — the interaction
            # never waits on the art pipeline.
            "has_shadowform": (entry.get("cls") == "Priest") or has_forms,
            "shadow_art": art_info["shadow_art"] if has_forms else None,
            "light_art": art_info["light_art"] if has_forms else None,
            "catchphrase": phrases.get(legacy or slug),
            "evidence": entry.get("evidence"),
            "source": entry.get("source", "derived"),
        })

    # Real ladder order; unscored crew trail behind, alphabetically;
    # parked (unresolved) members trail everyone — page only, no billing.
    crew.sort(key=lambda c: (c.get("parked", False), c["score"] is None,
                             -(c["score"] or 0), c["name"]))
    return crew[:limit]


# ---------------------------------------------------------------------
#  SCENES — the layer BEHIND the crew.
#
#  The cast are transparent cut-outs composited over this layer, so a
#  scene can change or animate underneath without touching the character
#  art. A scene is deliberately thin: a tint plus an optional image. The
#  tint is blended against the active theme's own colors in CSS, so one
#  scene definition reads correctly in all three themes.
# ---------------------------------------------------------------------

DEFAULT_SCENES = {
    "open_sea": {"label": "Open sea", "tint": None, "image": None},
    "dungeon": {"label": "Dungeon approach", "tint": None, "image": None},
    "raid_boss": {"label": "Boss arena", "tint": "#a3335c", "image": None},
}


def resolve_scenes(theme):
    """Scene definitions, theme.yml overridable:

        crew:
          scenes:
            grim-batol:
              tint: "#8a3b1f"
              image: "assets/scenes/grim_batol.png"

    Keys may be an island id (most specific) or one of the built-in
    kinds. Anything missing falls back to the shipped definition, and an
    image that is not actually on disk is dropped rather than rendering
    as a broken tile.
    """
    crew_cfg = (theme or {}).get("crew") or {}
    if not isinstance(crew_cfg, dict):
        crew_cfg = {}
    overrides = crew_cfg.get("scenes") or {}
    if not isinstance(overrides, dict):
        logger.info("theme.yml crew.scenes is not a mapping; using shipped scenes.")
        overrides = {}

    scenes = {key: dict(value) for key, value in DEFAULT_SCENES.items()}
    for key, value in overrides.items():
        if not isinstance(value, dict):
            logger.info("theme.yml crew.scenes.%s is not a mapping; ignored.", key)
            continue
        scene = dict(scenes.get(key) or {"label": str(key), "tint": None, "image": None})
        tint = value.get("tint")
        if isinstance(tint, str) and tint.strip():
            scene["tint"] = tint.strip()
        image = value.get("image")
        if isinstance(image, str) and image.strip():
            if Path(image.strip()).exists():
                scene["image"] = image.strip().replace(os.sep, "/")
            else:
                logger.info("Scene image %s for %r is not on disk; using the "
                            "tint alone.", image, key)
        label = value.get("label")
        if isinstance(label, str) and label.strip():
            scene["label"] = label.strip()
        scenes[key] = scene
    return scenes


def scene_for_island(island, scenes):
    """The scene an island washes over the board: its own definition if
    the theme names it, else the default for its kind."""
    scenes = scenes or {}
    island = island or {}
    for key in (island.get("id"), island.get("kind")):
        if key and key in scenes:
            return dict(scenes[key], key=key)
    fallback = scenes.get("open_sea") or DEFAULT_SCENES["open_sea"]
    return dict(fallback, key="open_sea")


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

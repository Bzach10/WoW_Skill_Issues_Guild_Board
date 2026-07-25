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

import json
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
# Legacy detection is by FILENAME, not by directory.
#
# It used to key on "/one_piece/" and "/board.png", which was fine while
# those only ever held paper-doll layers — but the roster generation
# writes its new art to exactly those paths in its own worktree, so the
# directory name is no longer a discriminator. What actually identifies
# the old art is the paper-doll LAYER filenames and the pre-restyle
# scene picks.
LEGACY_FILENAMES = {
    "body.png", "legs.png", "chest.png", "arms.png", "face.png",
    "head.png", "headgear.png", "cloak.png", "composite.png",
    "weapon_main.png", "weapon_off.png",
}

LEGACY_PATTERNS = (
    "cast/_trial/",      # the earlier IP-Adapter handoff
    "scene1_raidhall", "scene2_dungeon", "scene3_vista",
    "_tavern_", "_dragonflight_", "_plainbg_",
    "char_flat_", "char_form_", "il_light_", "il2_light_",
    "il_shadow_", "il2_shadow_", "hybrid_", "nightborne_",
)

# The roster generation's worktree. Art resolved from here is new by
# definition — it is a separate tree that only ever held restyle output.
DEFAULT_ROSTER_ROOT = "C:/wt/cg"

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
    if Path(probe).name in LEGACY_FILENAMES:
        return True
    return any(pattern.lower() in probe for pattern in LEGACY_PATTERNS)


def roster_root(cfg=None):
    """Where the roster generation writes. Overridable in config.yml:

        showcase:
          roster_root: "C:/wt/cg"
    """
    configured = ((cfg or {}).get("showcase") or {}).get("roster_root")
    root = configured if isinstance(configured, str) and configured.strip() else DEFAULT_ROSTER_ROOT
    return Path(root)


def _usable(path, root=None):
    """A path that exists on disk AND is not legacy art.

    `root` is the roster generation's worktree; its paths are relative to
    that root and are trusted as new art regardless of filename, because
    that tree only ever held restyle output.
    """
    if not path or not isinstance(path, str):
        return None
    candidate = Path(path)
    trusted = False
    if root is not None and not candidate.is_absolute():
        rooted = Path(root) / path
        if rooted.exists():
            candidate, trusted = rooted, True
    if not trusted and is_legacy_art(path):
        logger.info("Refusing legacy art %s — the site shows the new style only.",
                    path)
        return None
    if not candidate.exists():
        return None
    return str(candidate).replace(os.sep, "/")


def flagged_cutouts(cfg=None):
    """Character keys whose transparent cutout the generation flagged as
    imperfect (a leftover un-removed blob from rich fire/magic scenes).
    Those fall back to the full scene rather than showing a bad cutout."""
    path = roster_root(cfg) / "cast" / "_rnd_img2img" / "roster_progress.json"
    try:
        with open(path, encoding="utf-8") as fh:
            flagged = (json.load(fh) or {}).get("flagged_cutouts") or []
        return {str(k).lower() for k in flagged} if isinstance(flagged, list) else set()
    except (OSError, ValueError):
        return set()


def _manifest_entry(slug, manifest):
    """(character_key, style_assets) for this slug, or (None, None)."""
    characters = (manifest or {}).get("characters")
    if not isinstance(characters, dict):
        return None, None
    active = (manifest or {}).get("active_style")
    for key, character in characters.items():
        if not isinstance(character, dict):
            continue
        if slugify(character.get("name") or key.split("-")[0]) != slug:
            continue
        styles = character.get("styles")
        if not isinstance(styles, dict):
            return key, None
        ordered = ([styles[active]] if isinstance(styles.get(active), dict) else [])
        ordered += [v for k, v in styles.items() if k != active and isinstance(v, dict)]
        return key, (ordered[0] if ordered else None)
    return None, None


def _manifest_art(slug, manifest, cfg=None):
    """Back-compatible single-image lookup (the scene WITH background)."""
    _key, assets = _manifest_entry(slug, manifest)
    if not assets:
        return None
    root = roster_root(cfg)
    fields = ("profile", "scene", "final")
    if not assets.get("layers"):
        # `board` is only the roster's new cutout when the entry is NOT a
        # paper-doll layer set; in a layered entry it is the old flat art.
        fields += ("board",)
    for field in fields:
        found = _usable(assets.get(field), root)
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


# The cutout pipeline is being repaired separately — weapons and other
# parts were being over-removed, and 30 of 81 cutouts are flagged. The
# scene images keep their backgrounds and are unaffected, so the board
# uses those everywhere until the fix lands. Flip this back on (or set
# showcase.use_cutouts: true in config.yml) once it does.
USE_CUTOUTS_DEFAULT = False


def cutouts_enabled(cfg=None):
    value = ((cfg or {}).get("showcase") or {}).get("use_cutouts")
    return bool(value) if isinstance(value, bool) else USE_CUTOUTS_DEFAULT


TARGET_ASPECT = 0.75          # 3:4 portrait, the agreed roster spec
ASPECT_TOLERANCE = 0.04       # anything this close fills the frame cleanly


def character_art(slug, cfg=None, manifest=None):
    """Everything a surface needs to show this character.

    The roster generation ships TWO images per character:
      * `profile` — the full scene WITH its background, for the profile
        page and the showcase cards
      * `board`   — the same character as a transparent cutout, for the
        animated crew standing over the board's own scene layer

    A cutout the generation flagged as imperfect is not used; that
    character falls back to their scene image on the deck too.
    """
    slug = slugify(slug)
    root = roster_root(cfg)
    key, assets = _manifest_entry(slug, manifest)
    assets = assets or {}

    override = (((cfg or {}).get("showcase") or {}).get("scenes") or {}).get(slug)
    scene = (_usable(override, root)
             or _usable(assets.get("profile"), root)
             or _usable(assets.get("scene"), root)
             or _usable(assets.get("final"), root)
             or _usable(NEW_ART_TEMPLATE.format(slug=slug), root))

    flagged = (key or "").lower() in flagged_cutouts(cfg)
    # Same rule for the deck cutout: a layered entry's `board` is legacy.
    cutout = (None if (flagged or assets.get("layers")
                       or not cutouts_enabled(cfg))
              else _usable(assets.get("board"), root))

    aspect = image_aspect(scene) if scene else None
    fills = aspect is not None and abs(aspect - TARGET_ASPECT) <= ASPECT_TOLERANCE
    return {
        "src": scene,                 # what the cards and profile show
        "cutout": cutout,             # transparent, for the crew deck
        "cutout_flagged": flagged,
        "setting": SETTINGS.get(slug, ""),
        "pending": scene is None,
        "aspect": aspect,
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
            "scene": member.get("art") or resolve_scene(slug, cfg, manifest),
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
        # Reuse the art already resolved AND staged onto the member;
        # re-resolving here would re-introduce absolute worktree paths.
        art = member.get("art") or character_art(member["slug"], cfg, manifest)
        if art["pending"]:
            continue
        cards.append({
            "slug": member["slug"],
            "member": member,
            "profile": profiles_by_slug.get(member["slug"]) or {},
            "scene": art,
        })
    return cards


# ---------------------------------------------------------------------
#  Staging
#
#  The roster generation lives in its own worktree, so the art it
#  produces resolves to an ABSOLUTE path outside this tree. An absolute
#  Windows path is not a usable URL in a rendered page, and it cannot be
#  bundled. Staging copies each referenced image into the local tree
#  under a stable relative path, so the page is portable.
# ---------------------------------------------------------------------

STAGE_DIR = "cast/_roster"
STAGE_MAX_WIDTH = 900     # ~2x the largest size the board ever draws


def _has_alpha(img):
    return img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info


def _downscale(source, dest, max_width):
    """Write a display-sized copy. Returns the actual destination path, or
    None if Pillow could not handle it.

    Scene images carry no transparency, so they are stored as JPEG — as
    PNG they run ~1.7MB each and a roster-sized build becomes too big to
    hand to anyone. Cutouts keep their alpha and stay PNG.
    """
    try:
        from PIL import Image
        with Image.open(source) as img:
            if img.width > max_width:
                height = round(img.height * max_width / img.width)
                img = img.resize((max_width, height), Image.LANCZOS)
            if _has_alpha(img):
                img.save(dest, optimize=True)
                return dest
            jpeg = dest.with_suffix(".jpg")
            img.convert("RGB").save(jpeg, quality=86, optimize=True,
                                    progressive=True)
            return jpeg
    except Exception as exc:  # noqa: BLE001
        logger.info("Could not downscale %s (%s); copying as-is.", source, exc)
        return None


def stage_art(art, slug, repo_root=".", stage_dir=STAGE_DIR):
    """Copy this character's art into the local tree and return the same
    dict with repo-relative paths. Already-relative art is left alone."""
    import shutil

    repo_root = Path(repo_root)
    staged = dict(art)
    for field, filename in (("src", "profile.png"), ("cutout", "board.png")):
        value = art.get(field)
        if not value:
            continue
        source = Path(value)
        if not source.is_absolute():
            continue                      # already local and relative
        rel = f"{stage_dir}/{slug}/{filename}"
        dest = repo_root / rel
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            written = None
            for existing in (dest, dest.with_suffix(".jpg")):
                if existing.exists() and existing.stat().st_mtime >= source.stat().st_mtime:
                    written = existing
                    break
            if written is None:
                # The generator outputs ~2K; the board renders these at a
                # few hundred px. Staging at display size keeps a
                # roster-sized build shareable instead of ~150MB.
                written = _downscale(source, dest, STAGE_MAX_WIDTH)
                if written is None:
                    shutil.copy2(source, dest)
                    written = dest
            staged[field] = f"{stage_dir}/{slug}/{written.name}"
        except OSError as exc:
            logger.warning("Could not stage %s for %s (%s); leaving it out.",
                           source, slug, exc)
            staged[field] = None
    return staged

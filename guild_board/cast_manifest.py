"""cast_manifest.json — the single source of truth for every generated
cast character: their real Blizzard identity, which style(s) they've been
rendered in, where those images live on disk, and a version history so a
bad regeneration can be rolled back. The front-end consumes this exact
schema, so treat field names/shape as a contract — don't rename or add
required fields without updating this docstring and the front-end too.

Schema::

    {
      "active_style": "one_piece",
      "styles_available": ["one_piece"],
      "characters": {
        "<slug>": {
          "name": str, "realm": str, "race": str, "class": str,
          "spec": str, "gender": str, "role": str,
          "transmog_fingerprint": str,
          "render_url": str,
          "styles": {
            "<style>": {
              "board": "cast/<slug>/<style>/board.png",
              "forms": {"light": "...", "shadow": "..."},
              "version": int,
              "generated_at": "<ISO 8601>",
              "source_render": "cast/<slug>/_render.png"
            }
          },
          "history": [
            {"style": "<style>", "version": int, "board": "...",
             "forms": {...}, "generated_at": "...", "replaced_at": "..."}
          ]
        }
      }
    }

Every write goes through record_style_result(), which handles the
version bump + history push itself — callers never hand-edit a
character's "styles" entry directly.
"""

import json
import os
from datetime import datetime, timezone

MANIFEST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cast_manifest.json")

EMPTY_MANIFEST = {
    "active_style": None,
    "styles_available": [],
    "characters": {},
}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_manifest(path=None):
    """Fails open: a missing or broken manifest is just an empty one —
    the pipeline should never crash because of a corrupt JSON file.
    """
    path = path or MANIFEST_PATH
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {**EMPTY_MANIFEST, "characters": {}}
    merged = {**EMPTY_MANIFEST, **data}
    merged.setdefault("characters", {})
    merged.setdefault("styles_available", [])
    return merged


def save_manifest(manifest, path=None):
    path = path or MANIFEST_PATH
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True, ensure_ascii=False)
    return path


def add_character(manifest, slug, profile, transmog_fingerprint=None):
    """profile: a blizzard_profile_cache.json character entry (or
    equivalent dict with name/realm/race/class/active_spec/gender). Role
    (tank/healer/dps) isn't in the Blizzard profile — pass it in profile
    as "role" if known, else it's left unset. Does nothing if the
    character already exists (use record_style_result to update one).
    """
    if slug in manifest["characters"]:
        return manifest
    manifest["characters"][slug] = {
        "name": profile.get("name", slug),
        "realm": profile.get("realm", ""),
        "race": profile.get("race", ""),
        "class": profile.get("class", ""),
        "spec": profile.get("active_spec") or profile.get("spec", ""),
        "gender": profile.get("gender", ""),
        "role": profile.get("role", ""),
        "transmog_fingerprint": transmog_fingerprint or "",
        "render_url": profile.get("transmog_render_url", ""),
        "styles": {},
        "history": [],
    }
    return manifest


def remove_character(manifest, slug):
    """Drops a character entirely (does not delete files on disk — the
    caller decides whether to clean those up separately)."""
    manifest["characters"].pop(slug, None)
    return manifest


def register_style(manifest, style_name):
    if style_name not in manifest["styles_available"]:
        manifest["styles_available"].append(style_name)
    return manifest


def set_active_style(manifest, style_name):
    """Only switches if the style has actually been generated for at
    least one character — refusing silently (fail open) rather than
    pointing the whole board at a style with no art yet.
    """
    if style_name in manifest["styles_available"]:
        manifest["active_style"] = style_name
    return manifest


def record_style_result(manifest, slug, style_name, board_path, forms=None,
                        source_render=None, transmog_fingerprint=None):
    """Store a fresh generation result for one character/style. Bumps the
    version, pushes whatever was there before into history (so it can be
    rolled back), and registers the style as available.
    """
    if slug not in manifest["characters"]:
        raise KeyError(f"add_character({slug!r}, ...) before recording a style result")
    char = manifest["characters"][slug]
    existing = char["styles"].get(style_name)
    next_version = (existing["version"] + 1) if existing else 1

    if existing:
        char["history"].append({
            "style": style_name,
            "version": existing["version"],
            "board": existing["board"],
            "forms": existing.get("forms", {}),
            "generated_at": existing["generated_at"],
            "replaced_at": _now_iso(),
        })

    char["styles"][style_name] = {
        "board": board_path,
        "forms": forms or {},
        "version": next_version,
        "generated_at": _now_iso(),
        "source_render": source_render or existing.get("source_render", "") if existing else (source_render or ""),
    }
    if transmog_fingerprint is not None:
        char["transmog_fingerprint"] = transmog_fingerprint

    register_style(manifest, style_name)
    if manifest["active_style"] is None:
        manifest["active_style"] = style_name
    return manifest


def set_primary_form(manifest, slug, style_name, form_name):
    """Swap which stored pose/form becomes the primary "board" image for
    a character's style, without any new generation — e.g. picking
    Shadowform instead of Light as the character's default portrait.
    Versioned + historied like any other style-result write.
    """
    char = manifest["characters"][slug]
    style_entry = char["styles"][style_name]
    forms = style_entry.get("forms", {})
    if form_name not in forms:
        raise KeyError(f"no stored form {form_name!r} for {slug}/{style_name}")
    return record_style_result(
        manifest, slug, style_name, forms[form_name], forms=forms,
        source_render=style_entry.get("source_render"))


def rollback_style(manifest, slug, style_name, to_version):
    """Restore a prior version of a character's style from history. The
    current version is itself pushed to history first (nothing is lost —
    you can roll forward again if you roll back by mistake).
    """
    char = manifest["characters"][slug]
    candidates = [h for h in char["history"]
                  if h["style"] == style_name and h["version"] == to_version]
    if not candidates:
        raise KeyError(f"no history entry for {slug}/{style_name} version {to_version}")
    target = candidates[-1]
    return record_style_result(
        manifest, slug, style_name, target["board"], forms=target.get("forms", {}),
        source_render=char["styles"].get(style_name, {}).get("source_render"))


def character_slugs_needing_refresh(manifest, blizzard_characters, fingerprint_fn):
    """Diff step for the weekly runner: given the freshly-fetched
    blizzard_profile_cache.json characters dict, return the slugs that
    are either new or whose transmog fingerprint changed since the
    manifest last recorded them. `fingerprint_fn` computes a fingerprint
    from one profile dict (see guild_board.transmog_fingerprint).
    """
    changed = []
    for slug, profile in blizzard_characters.items():
        new_fp = fingerprint_fn(profile)
        existing = manifest["characters"].get(slug)
        if existing is None or existing.get("transmog_fingerprint") != new_fp:
            changed.append(slug)
    return changed

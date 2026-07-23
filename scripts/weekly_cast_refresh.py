"""Weekly cast-art refresh: re-fetch Blizzard profiles, diff each opted-in
character's transmog fingerprint against cast_manifest.json, and
regenerate ONLY the characters whose gear actually changed since the
last run.

This is GPU-bound (ComfyUI must be running locally) so it is NOT a
GitHub Actions job — GitHub has no GPU. It's meant to run as a local
Windows Task Scheduler job; see scripts/setup_cast_refresh_task.ps1 for
the (one-time, opt-in) scheduler registration step.

Idempotent: with no upstream transmog changes, the fingerprint diff
finds nothing and this is a no-op. Fail-open per character: one
character's generation failing is logged and skipped, never aborting
the rest of the run or touching that character's last-good art.

Usage: python scripts/weekly_cast_refresh.py [--style one_piece] [--force]
"""

import logging
import os
import sys
from pathlib import Path

# Run directly (python scripts/weekly_cast_refresh.py), Python only puts
# this file's own directory on sys.path, not the repo root — same fix
# scripts/refresh_blizzard_profiles.py already uses.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guild_board.blizzard import refresh_profile_cache  # noqa: E402
from guild_board.cast_art import opted_in_characters  # noqa: E402
from guild_board.cast_manifest import (  # noqa: E402
    add_character,
    character_slugs_needing_refresh,
    load_manifest,
    record_style_result,
    save_manifest,
)
from guild_board.config import load_config, load_roster_cache  # noqa: E402
from guild_board.render_pipeline import (  # noqa: E402
    CAST_ROOT,
    render_cast_member,
    stage_render_from_url,
)
from guild_board.transmog_fingerprint import compute_transmog_fingerprint  # noqa: E402

REPO_ROOT = os.path.dirname(CAST_ROOT)
LOG_PATH = os.path.join(REPO_ROOT, "logs", "weekly_cast_refresh.log")


def _relpath(path):
    """Manifest paths are stored repo-relative with forward slashes (the
    front-end contract), never the absolute local disk path."""
    return os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")


def _setup_logging():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger("weekly_cast_refresh")


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    force = "--force" in argv
    style_name = "one_piece"
    if "--style" in argv:
        style_name = argv[argv.index("--style") + 1]

    log = _setup_logging()
    cfg = load_config()

    roster, _ = load_roster_cache(cfg)
    if not roster:
        log.info("roster_cache.json is empty or missing; nothing to refresh.")
        return 0

    max_age_days = 0 if force else 7
    characters, _ = refresh_profile_cache(cfg, roster, max_age_days=max_age_days)
    if not characters:
        log.info("No Blizzard profile data available (cache empty and refresh "
                  "skipped or failed); nothing to do. See SETUP_BLIZZARD.md.")
        return 0

    characters = opted_in_characters(cfg, characters)
    manifest = load_manifest()

    needing_refresh = character_slugs_needing_refresh(
        manifest, characters, compute_transmog_fingerprint)
    if not needing_refresh:
        log.info("No transmog changes detected for any opted-in character "
                  "(%d checked); nothing to regenerate.", len(characters))
        return 0

    log.info("Regenerating %d character(s): %s",
              len(needing_refresh), ", ".join(sorted(needing_refresh)))

    succeeded, failed = [], []
    for slug in needing_refresh:
        profile = characters[slug]
        render_url = profile.get("transmog_render_url")
        if not render_url:
            log.warning("Skipping %s: no transmog_render_url in its profile.", slug)
            failed.append(slug)
            continue
        try:
            fingerprint = compute_transmog_fingerprint(profile)
            add_character(manifest, slug, profile, transmog_fingerprint=fingerprint)
            staged_filename = stage_render_from_url(render_url, f"{slug}_transmog.png")
            board_path, source_render = render_cast_member(
                slug, staged_filename, style_name=style_name)
            record_style_result(
                manifest, slug, style_name, _relpath(board_path),
                source_render=_relpath(source_render),
                transmog_fingerprint=fingerprint)
            succeeded.append(slug)
            log.info("Regenerated %s -> %s", slug, _relpath(board_path))
        except Exception:
            log.warning("Failed to regenerate %s; leaving its prior art in "
                        "place.", slug, exc_info=True)
            failed.append(slug)

    save_manifest(manifest)
    log.info("Done. %d succeeded, %d failed: %s",
              len(succeeded), len(failed), ", ".join(failed) if failed else "none")
    return 1 if failed and not succeeded else 0


if __name__ == "__main__":
    sys.exit(main())

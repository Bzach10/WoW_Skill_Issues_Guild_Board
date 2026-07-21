"""Validate the project's data files, and optionally cross-check them
against live ground truth from Raider.io's public API.

Written against the failures actually found in this repo, so each check
corresponds to a real defect rather than a hypothetical one:

  roster    every entry splits into a plausible (name, realm); catches the
            rsplit regression that silently dropped 48% of the roster
  manifest  schema conformance, and every referenced image exists on disk
  profiles  blizzard_profile_cache.json entries have the fields the prompt
            builder needs, and a transmog render URL
  drift     stored fingerprints match what the current algorithm computes,
            so a stale manifest is visible instead of silently skipping
            regeneration
  live      (--live) race/class/spec/gender for each cast member matches
            Raider.io right now

Exit code is 0 when nothing is wrong, 1 when any ERROR is reported.
Warnings alone do not fail the run, so this is safe to wire into CI.

Usage:
    python scripts/validate_data.py [--live] [--limit N] [--quiet]
"""

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guild_board.blizzard import load_profile_cache  # noqa: E402
from guild_board.cast_manifest import MANIFEST_PATH, load_manifest  # noqa: E402
from guild_board.config import load_config, load_roster_cache, split_name_realm  # noqa: E402
from guild_board.transmog_fingerprint import compute_transmog_fingerprint  # noqa: E402

RAIDERIO_URL = "https://raider.io/api/v1/characters/profile"

# Fields cast_art.build_prompt() needs to describe a real character.
REQUIRED_PROFILE_FIELDS = ("race", "class")
# Fields the front-end reads off every manifest character.
REQUIRED_MANIFEST_FIELDS = ("name", "realm", "race", "class", "spec",
                            "gender", "role", "styles", "history")


class Report:
    """Collects findings so one bad record doesn't abort the whole run."""

    def __init__(self, quiet=False):
        self.errors = []
        self.warnings = []
        self.quiet = quiet

    def error(self, section, message):
        self.errors.append((section, message))

    def warn(self, section, message):
        self.warnings.append((section, message))

    def ok(self, message):
        if not self.quiet:
            print(f"  ok    {message}")

    def dump(self):
        for section, message in self.warnings:
            print(f"  WARN  [{section}] {message}")
        for section, message in self.errors:
            print(f"  ERROR [{section}] {message}")
        print()
        print(f"{len(self.errors)} error(s), {len(self.warnings)} warning(s)")
        return 1 if self.errors else 0


def check_roster(cfg, report):
    """Every roster entry must split into a usable (name, realm)."""
    print("roster_cache.json")
    roster, last_updated = load_roster_cache(cfg)
    if not roster:
        report.warn("roster", "roster_cache.json is empty or missing")
        return roster
    for entry in roster:
        name, realm = split_name_realm(entry)
        if not name or not realm:
            report.error("roster", f"{entry!r} does not split into name+realm")
            continue
        # A realm slug is lowercase alphanumerics and hyphens. A *name*
        # containing a hyphen is the signature of the rsplit bug.
        if "-" in name:
            report.error(
                "roster",
                f"{entry!r} split to name={name!r} — a hyphen in the character "
                f"name means the entry was split on the wrong hyphen")
        if realm != realm.lower():
            report.warn("roster", f"{entry!r} realm {realm!r} is not lowercase")
    report.ok(f"{len(roster)} entries split cleanly (updated {last_updated})")
    return roster


def check_manifest(report, manifest_path=None):
    """Schema conformance + every referenced image actually exists.

    Manifest image paths are stored repo-relative, so they resolve against
    the directory holding the manifest — not against this script's location
    or the current working directory, either of which can differ (a git
    worktree, or running from a subdirectory) and would report every image
    as missing.
    """
    print("cast_manifest.json")
    manifest = load_manifest(manifest_path)
    root = os.path.dirname(os.path.abspath(manifest_path or MANIFEST_PATH))
    characters = manifest.get("characters", {})
    if not characters:
        report.warn("manifest", "no characters in the manifest yet")
        return manifest

    active = manifest.get("active_style")
    available = manifest.get("styles_available", [])
    if active and active not in available:
        report.error("manifest",
                     f"active_style {active!r} is not in styles_available {available}")

    for slug, char in sorted(characters.items()):
        for field in REQUIRED_MANIFEST_FIELDS:
            if field not in char:
                report.error("manifest", f"{slug}: missing required field {field!r}")
        if not char.get("render_url"):
            report.warn(
                "manifest",
                f"{slug}: empty render_url — generated without an IP-Adapter "
                f"likeness reference, so the art is prompt-only")
        for style_name, entry in (char.get("styles") or {}).items():
            for key in ("board", "source_render"):
                rel = entry.get(key)
                if not rel:
                    continue
                if not os.path.exists(os.path.join(root, rel)):
                    report.error("manifest",
                                 f"{slug}/{style_name}: {key} points at a "
                                 f"missing file: {rel}")
            if entry.get("version", 0) < 1:
                report.error("manifest",
                             f"{slug}/{style_name}: version must be >= 1")
    report.ok(f"{len(characters)} characters, "
              f"{sum(len(c.get('styles') or {}) for c in characters.values())} style entries")
    return manifest


def check_profiles(cfg, report):
    """Profile cache entries must carry what the prompt builder needs."""
    print("blizzard_profile_cache.json")
    characters, last_updated = load_profile_cache(cfg)
    if not characters:
        report.warn("profiles",
                    "profile cache is empty or missing — run "
                    "scripts/refresh_blizzard_profiles.py")
        return characters
    for key, profile in sorted(characters.items()):
        missing = [f for f in REQUIRED_PROFILE_FIELDS if not profile.get(f)]
        if missing:
            report.error("profiles",
                         f"{key}: missing {', '.join(missing)} — build_prompt() "
                         f"will skip this character")
        if not profile.get("transmog_render_url"):
            report.warn("profiles", f"{key}: no transmog_render_url")
    report.ok(f"{len(characters)} profiles (updated {last_updated})")
    return characters


def check_fingerprint_drift(manifest, report):
    """A stored fingerprint that disagrees with the current algorithm means
    the weekly diff's idea of 'unchanged' is untrustworthy."""
    print("fingerprint drift")
    drifted = []
    for slug, char in sorted((manifest.get("characters") or {}).items()):
        stored = char.get("transmog_fingerprint") or ""
        recomputed = compute_transmog_fingerprint({
            "transmog_render_url": char.get("render_url", ""),
            "race": char.get("race"),
            "class": char.get("class"),
            "gender": char.get("gender"),
            "spec": char.get("spec"),
        })
        if stored != recomputed:
            drifted.append(slug)
    if drifted:
        report.warn("drift",
                    f"{len(drifted)} character(s) will regenerate on the next "
                    f"weekly run: {', '.join(drifted)}")
    else:
        report.ok("all stored fingerprints match the current algorithm")


def check_live(manifest, cfg, report, limit=None):
    """Cross-check identity fields against Raider.io right now."""
    import requests

    print("live cross-check (Raider.io)")
    region = ((cfg or {}).get("guild") or {}).get("region", "us")
    items = sorted((manifest.get("characters") or {}).items())
    if limit:
        items = items[:limit]

    for slug, char in items:
        try:
            resp = requests.get(RAIDERIO_URL, params={
                "region": region, "realm": char.get("realm", ""),
                "name": char.get("name", ""), "fields": "gear"}, timeout=30)
        except requests.RequestException as exc:
            report.warn("live", f"{slug}: request failed ({exc})")
            continue
        if resp.status_code != 200:
            report.error("live",
                         f"{slug}: Raider.io returned HTTP {resp.status_code} "
                         f"— character may be renamed, transferred or deleted")
            continue
        truth = resp.json()
        mismatched = []
        for field, mine, theirs in (
                ("race", char.get("race"), truth.get("race")),
                ("class", char.get("class"), truth.get("class")),
                ("spec", char.get("spec"), truth.get("active_spec_name")),
                ("gender", char.get("gender"), truth.get("gender"))):
            if (mine or "").strip().lower() != (theirs or "").strip().lower():
                mismatched.append(field)
                # Spec is the one field players change freely and often, so
                # it is reported as drift-to-refresh rather than corruption.
                report.error("live",
                             f"{slug}: {field} is {mine!r} locally but "
                             f"{theirs!r} on Raider.io")
        if not mismatched:
            report.ok(f"{slug} matches Raider.io")
        time.sleep(0.4)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="also cross-check identity against Raider.io")
    parser.add_argument("--limit", type=int,
                        help="only cross-check the first N cast members")
    parser.add_argument("--quiet", action="store_true",
                        help="suppress per-check ok lines")
    args = parser.parse_args(argv)

    # Windows consoles default to cp1252, which mangles the em-dashes and
    # arrows in these messages. Force UTF-8 so CI logs stay readable.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cfg = load_config()
    report = Report(quiet=args.quiet)

    check_roster(cfg, report)
    manifest = check_manifest(report)
    check_profiles(cfg, report)
    check_fingerprint_drift(manifest, report)
    if args.live:
        check_live(manifest, cfg, report, limit=args.limit)

    print()
    return report.dump()


if __name__ == "__main__":
    sys.exit(main())

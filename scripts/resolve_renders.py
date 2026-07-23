#!/usr/bin/env python3
"""Resolve real transmog-render PNGs for the guild roster via Raider.io (no auth needed).

Raider.io's public character-profile API returns a `thumbnail_url` on the
render.worldofwarcraft.com CDN, e.g. .../243420911-avatar.jpg. Swapping the
suffix for -main-raw.png gives the same full-body transparent-bg render used
by the Blizzard Game Data API, without needing Blizzard OAuth credentials.

Usage: python scripts/resolve_renders.py
Writes cast/_renders_cache/<name-realm>.png for every roster member that
resolves, and cast/_renders_cache/_resolve_report.json summarizing hits/misses.
"""
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parents[1]
ROSTER_PATH = REPO_ROOT / "roster_cache.json"
OUT_DIR = REPO_ROOT / "cast" / "_renders_cache"
REPORT_PATH = OUT_DIR / "_resolve_report.json"

UA = {"User-Agent": "wow-skill-issues-guild-board/character-gen (contact: guild admin)"}


def raiderio_thumbnail(name, realm, region="us"):
    qs = urllib.parse.urlencode({
        "region": region, "realm": realm, "name": name, "fields": "guild",
    })
    url = f"https://raider.io/api/v1/characters/profile?{qs}"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data


def main():
    all_members = json.loads(ROSTER_PATH.read_text())["members"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    retry_only = "--retry-missing" in sys.argv
    prior = json.loads(REPORT_PATH.read_text()) if (retry_only and REPORT_PATH.exists()) else None

    if prior:
        roster = [m["entry"] for m in prior["missing"]]
        resolved = prior["resolved"]
        missing = []
    else:
        roster = all_members
        resolved = []
        missing = []

    for i, entry in enumerate(roster):
        name, realm = entry.rsplit("-", 1) if entry.count("-") == 1 else (entry.rsplit("-", 1))
        # some realm slugs are themselves hyphenated (e.g. bleeding-hollow); split on last hyphen only works
        # for single-word realms. Handle multi-word realms by trying progressively shorter name prefixes.
        parts = entry.split("-")
        # realm slug candidates: last 1, 2, or 3 tokens
        candidates = []
        for n in (1, 2, 3):
            if len(parts) > n:
                candidates.append(("-".join(parts[:-n]), "-".join(parts[-n:])))
        if not candidates:
            candidates = [(entry, "")]

        out_path = OUT_DIR / f"{entry}.png"
        ok = False
        last_err = None
        for name, realm in candidates:
            try:
                data = raiderio_thumbnail(name, realm)
                thumb = data.get("thumbnail_url")
                if not thumb:
                    last_err = "no thumbnail_url in response"
                    continue
                main_raw = re.sub(r"-avatar\.jpg.*$", "-main-raw.png", thumb)
                req = urllib.request.Request(main_raw, headers=UA)
                with urllib.request.urlopen(req, timeout=20) as resp:
                    img_bytes = resp.read()
                out_path.write_bytes(img_bytes)
                resolved.append({
                    "entry": entry, "name": data.get("name"), "realm": data.get("realm"),
                    "class": data.get("class"), "race": data.get("race"),
                    "spec": data.get("active_spec_name"), "render_url": main_raw,
                    "out_path": str(out_path),
                })
                ok = True
                break
            except urllib.error.HTTPError as e:
                last_err = f"HTTP {e.code}"
            except Exception as e:
                last_err = str(e)
        if not ok:
            missing.append({"entry": entry, "error": last_err})
            print(f"[{i+1}/{len(roster)}] MISS  {entry}  ({last_err})")
        else:
            print(f"[{i+1}/{len(roster)}] ok    {entry}")
        time.sleep(0.15)  # be polite to raider.io's free API

    report = {
        "total": len(all_members),
        "resolved_count": len(resolved),
        "missing_count": len(missing),
        "resolved": resolved,
        "missing": missing,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResolved {len(resolved)}/{len(all_members)}. Missing {len(missing)}.")
    print(f"Report: {REPORT_PATH}")


if __name__ == "__main__":
    main()

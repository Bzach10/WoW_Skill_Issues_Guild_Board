#!/usr/bin/env python3
"""Build a PRIVATE, self-contained trial of the board.

Writes a folder Zach can open with a double-click. Nothing here touches
Discord, GitHub Pages, or any live path — it renders the preview board,
the profile pages, and copies every asset they reference into one
portable directory.

    python scripts/build_trial.py --out "C:/path/to/GuildBoardTrial"

By default the bundle is written OUTSIDE the repository so it cannot ride
along in a commit.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT.parent / "GuildBoardTrial"

# Anything the rendered pages can reference, relative to the repo root.
ASSET_ROOTS = ["cast"]

SRC_RE = re.compile(r'(?:src|href)="((?!https?:|mailto:|data:|#)[^"]+)"')
URL_RE = re.compile(r"""url\(\s*['"]?(?!https?:|data:)([^'")]+?)['"]?\s*\)""")


def _refs(text):
    """Every local reference in a page: src/href AND CSS url()."""
    return SRC_RE.findall(text) + URL_RE.findall(text)


def run(cmd):
    print("  $", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])
        raise SystemExit(f"command failed: {' '.join(cmd)}")
    return result


def referenced_assets(html_paths):
    """Every local file the built pages actually point at."""
    wanted = set()
    for path in html_paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for ref in _refs(text):
            ref = ref.split("?")[0].split("#")[0]
            if not ref or ref.endswith(".html"):
                continue
            # references are relative to the page they appear in
            candidate = (path.parent / ref).resolve()
            try:
                candidate.relative_to(ROOT)
            except ValueError:
                continue
            if candidate.is_file():
                wanted.add(candidate)
    return wanted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--crew-limit", type=int, default=40,
                    help="How many characters stand on the deck.")
    args = ap.parse_args()
    out = Path(args.out).resolve()

    try:
        out.relative_to(ROOT)
        print(f"WARNING: {out} is inside the repository. A trial build should "
              f"live outside it so it cannot be committed.")
    except ValueError:
        pass

    print("1/4  rendering the preview board + profile pages")
    run([sys.executable, "scripts/render_crew_board.py", "--out", "crew_board.html",
         "--crew-limit", str(args.crew_limit)])

    board = ROOT / "crew_board.html"
    trial = ROOT / "trial.html"
    voyage = ROOT / "voyage.html"
    profiles = sorted((ROOT / "p").glob("*.html"))
    if not board.exists():
        raise SystemExit("crew_board.html was not produced")

    pages = ([board] + profiles + ([trial] if trial.exists() else [])
             + ([voyage] if voyage.exists() else []))
    print(f"2/4  collecting assets for {len(pages)} pages")
    assets = referenced_assets(pages)
    print(f"     {len(assets)} asset files referenced")

    print(f"3/4  writing the bundle to {out}")
    # A live tunnel may be serving `out`. Never delete it: build into a
    # sibling staging directory and sync in, so the folder is always
    # present and the link never 404s mid-rebuild.
    live = out.exists()
    staging = out.with_name(out.name + "__staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    build_target, out = out, staging

    # The trial showcase is the front door; the animated board sits
    # behind it, linked from the call to action.
    if trial.exists():
        shutil.copy2(trial, out / "index.html")
        shutil.copy2(board, out / "crew_board.html")
    else:
        shutil.copy2(board, out / "index.html")
    if voyage.exists():
        shutil.copy2(voyage, out / "voyage.html")   # the nav's Voyage link
    (out / "p").mkdir()
    for page in profiles:
        # profiles link back to ../index.html, which now exists
        shutil.copy2(page, out / "p" / page.name)
    for asset in sorted(assets):
        rel = asset.relative_to(ROOT)
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(asset, dest)

    # The board links to profiles as p/<slug>.html — already correct.
    readme = out / "READ_ME_FIRST.txt"
    readme.write_text(
        "PRIVATE TRIAL BUILD — The Guild Board\n"
        "=====================================\n\n"
        "Open index.html in any browser (double-click it).\n\n"
        "This is a LOCAL PREVIEW ONLY. It is not connected to Discord, it is\n"
        "not published to the guild's website, and nothing in this folder\n"
        "goes anywhere unless you send it yourself.\n\n"
        "What to try:\n"
        "  - Hover the role tabs (Tanks / Healers / DPS) to spotlight a role\n"
        "  - Click a tab to filter the deck\n"
        "  - Hover an island on the Voyage to change the scene behind the crew\n"
        "  - Click a character's name to open their profile page\n"
        "  - Switch themes with the buttons at the top right\n\n"
        "The characters with real art are the ones the art pipeline has\n"
        "finished so far. The grey silhouettes are placeholders waiting on\n"
        "their art — they are not broken.\n",
        encoding="utf-8")

    print("4/4  verifying the bundle is self-contained")
    missing = []
    checkable = [out / "index.html"] + sorted((out / "p").glob("*.html"))
    if (out / "crew_board.html").exists():
        checkable.append(out / "crew_board.html")
    for page in checkable:
        text = page.read_text(encoding="utf-8", errors="ignore")
        for ref in _refs(text):
            ref = ref.split("?")[0].split("#")[0]
            if not ref:
                continue
            if not (page.parent / ref).exists():
                missing.append(f"{page.name} -> {ref}")
    if missing:
        print("  MISSING REFERENCES:")
        for m in missing[:20]:
            print("   ", m)
    else:
        print("  every local reference resolves")

    # ---- sync staging -> live, in place -------------------------------
    out, staging = build_target, out
    if live:
        print(f"     syncing into the live folder (kept in place)")
    out.mkdir(parents=True, exist_ok=True)
    written = set()
    for src in staging.rglob("*"):
        rel = src.relative_to(staging)
        dest = out / rel
        if src.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        # write to a temp name then replace, so a reader never sees a
        # half-written file
        tmp = dest.with_name(dest.name + ".tmp")
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
        written.add(rel)
    # drop files from a previous, larger build
    removed = 0
    for existing in sorted(out.rglob("*"), key=lambda p: -len(p.parts)):
        rel = existing.relative_to(out)
        if existing.is_file() and rel not in written and not str(rel).startswith("_preview_media"):
            existing.unlink()
            removed += 1
        elif existing.is_dir() and not any(existing.iterdir()):
            existing.rmdir()
    if removed:
        print(f"     removed {removed} stale file(s)")
    shutil.rmtree(staging, ignore_errors=True)

    total = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"\nBundle ready: {out}")
    print(f"  entry point : {out / 'index.html'}")
    print(f"  pages       : 1 board + {len(profiles)} profiles")
    print(f"  size        : {total / 1024 / 1024:.1f} MB")
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())

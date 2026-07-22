#!/usr/bin/env python3
"""Refresh the private rough draft against whatever art has landed.

One command for the whole job: rebuild the bundle from the current
roster manifest, then capture full-page and screen-sized screenshots.

    python scripts/refresh_draft.py

Nothing here publishes. The bundle is written outside the repository and
the renderer refuses to write into site/.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BUNDLE = Path("C:/Users/zachf/Desktop/GuildBoardTrial")
PREVIEWS = ROOT / "previews"

# Full-page shots are ~3000px wide and many thousands tall — great for
# detail, unusable on a phone. Each one also gets a screen-sized copy.
PHONE_WIDTH = 1080


def run(cmd):
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout[-3000:])
        print(result.stderr[-3000:])
        raise SystemExit(f"failed: {' '.join(cmd)}")
    return result.stdout


def roster_state(cfg_root):
    """What the generation session has produced so far."""
    try:
        manifest = json.loads((cfg_root / "cast_manifest.json").read_text(encoding="utf-8"))
        progress = json.loads(
            (cfg_root / "cast" / "_rnd_img2img" / "roster_progress.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {
        "characters": len(manifest.get("characters") or {}),
        "done": progress.get("done"),
        "total": progress.get("total"),
        "spend": progress.get("spend_total"),
        "flagged_cutouts": len(progress.get("flagged_cutouts") or []),
    }


def screen_sized(source, dest, width=PHONE_WIDTH, max_height=14000):
    """A phone-friendly copy: narrower, height-capped, and JPEG so it
    actually sends. A 40-card page is tens of thousands of pixels tall;
    past a point extra height is unreadable weight, so it is scaled to
    fit rather than kept at full size."""
    with Image.open(source) as img:
        if img.width > width:
            img = img.resize((width, round(img.height * width / img.width)),
                             Image.LANCZOS)
        if img.height > max_height:
            scale = max_height / img.height
            img = img.resize((max(round(img.width * scale), 1), max_height),
                             Image.LANCZOS)
        img.convert("RGB").save(dest, quality=82, optimize=True, progressive=True)
    return dest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", default=str(DEFAULT_BUNDLE))
    ap.add_argument("--crew-limit", type=int, default=40)
    ap.add_argument("--theme", default="codex")
    args = ap.parse_args()
    bundle = Path(args.bundle)

    est = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=-4)))
    print(f"refresh at {est:%Y-%m-%d %I:%M %p} EDT")

    state = roster_state(Path("C:/wt/cg"))
    if state:
        print(f"  roster: {state['done']}/{state['total']} generated, "
              f"${state['spend']:.2f} spent, "
              f"{state['flagged_cutouts']} cutouts flagged")

    print("  building bundle")
    out = run([sys.executable, "scripts/build_trial.py", "--out", str(bundle),
               "--crew-limit", str(args.crew_limit)])
    for line in out.splitlines():
        if any(k in line for k in ("resolves", "MISSING", "size", "pages")):
            print("   ", line.strip())

    PREVIEWS.mkdir(exist_ok=True)
    shots = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 1000},
                                device_scale_factor=2)
        errors = []
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.goto((bundle / "index.html").as_uri(), wait_until="domcontentloaded")
        try:
            page.wait_for_function("document.fonts.ready", timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        page.click(f'.themeswitch button[data-theme="{args.theme}"]')
        # every image must decode before a full-page shot, or the tail of
        # a long page captures blank frames
        page.evaluate("""async () => { await Promise.all([...document.images].map(i =>
            i.complete ? 0 : new Promise(r => { i.onload = i.onerror = r; }))); }""")
        page.wait_for_timeout(1800)

        stats = page.evaluate("""() => ({
            cards: document.querySelectorAll('.card').length,
            withArt: document.querySelectorAll('.card .scene img').length,
            pending: document.querySelectorAll('.card .pending').length,
            broken: [...document.images].filter(i => !i.naturalWidth).length,
        })""")
        print(f"  cards {stats['cards']} · with art {stats['withArt']} · "
              f"pending {stats['pending']} · broken {stats['broken']}")

        full = PREVIEWS / "draft_site_full.png"
        page.screenshot(path=str(full), full_page=True)
        shots.append(full)
        page.close()

        # the crew deck, which shows who is still a placeholder
        page = browser.new_page(viewport={"width": 1500, "height": 1000},
                                device_scale_factor=2)
        page.goto((bundle / "crew_board.html").as_uri(), wait_until="domcontentloaded")
        page.wait_for_timeout(2200)
        deck = PREVIEWS / "draft_site_deck.png"
        page.screenshot(path=str(deck), full_page=True)
        shots.append(deck)
        page.close()

        # a real phone viewport, not just a downscale
        page = browser.new_page(viewport={"width": 390, "height": 844},
                                device_scale_factor=2)
        page.goto((bundle / "index.html").as_uri(), wait_until="domcontentloaded")
        page.evaluate("""async () => { await Promise.all([...document.images].map(i =>
            i.complete ? 0 : new Promise(r => { i.onload = i.onerror = r; }))); }""")
        page.wait_for_timeout(1800)
        # A full-page phone capture is ~24MB of PNG and thousands of
        # pixels tall — keep only a right-sized JPEG, which is the thing
        # anyone will actually open on a phone.
        phone_raw = PREVIEWS / "_phone_raw.png"
        page.screenshot(path=str(phone_raw), full_page=True)
        page.close()
        browser.close()

        if errors:
            print("  console errors:", errors[:5])

    print("  screen-sized copies")
    small = []
    for shot in shots:
        dest = shot.with_name(shot.stem + "_small.jpg")
        screen_sized(shot, dest)
        small.append(dest)
    if phone_raw.exists():
        phone_small = PREVIEWS / "draft_site_phone.jpg"
        screen_sized(phone_raw, phone_small, width=760)
        phone_raw.unlink()
        small.append(phone_small)

    print("\nscreenshots:")
    for path in shots + small:
        print(f"  {path}  ({path.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"\nbundle: {bundle / 'index.html'}")
    return stats


if __name__ == "__main__":
    main()

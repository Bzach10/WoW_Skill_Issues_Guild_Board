#!/usr/bin/env python3
"""Screenshot the Grand Hall (B-02) — full-cast hero wall — for review.

    python -m http.server 8790 --directory C:/wt/GuildBoardTrial
    python scripts/shoot_hall.py --url http://localhost:8790/hall.html
"""

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "previews"

SHOTS = [
    # (label, width, height, theme, full_page)
    ("hall_desktop_codex", 1440, 950, "codex", False),
    ("hall_desktop_console", 1440, 950, "console", False),
    ("hall_full_codex", 1440, 950, "codex", True),
    ("hall_mobile_codex", 390, 844, "codex", False),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8790/hall.html")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for label, w, h, theme, full in SHOTS:
            page = browser.new_page(viewport={"width": w, "height": h},
                                    device_scale_factor=2)
            page.goto(args.url, wait_until="networkidle")
            try:
                page.wait_for_function("document.fonts.ready", timeout=6000)
            except Exception:  # noqa: BLE001
                pass
            page.click(f'.themeswitch button[data-theme="{theme}"]')
            # let the staggered rise finish before capturing
            page.wait_for_timeout(3600)
            page.screenshot(path=str(OUT / f"{label}.png"), full_page=full)
            print("shot", label)
            page.close()
        browser.close()


if __name__ == "__main__":
    main()

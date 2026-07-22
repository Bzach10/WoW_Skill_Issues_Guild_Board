#!/usr/bin/env python3
"""Screenshot the Voyage Map's scene-ports (VOY-07) for review.

Captures the ports route and an open diorama, phone-sized, per theme.
Serve the bundle first (or point --page at a rendered voyage.html):

    python -m http.server 8790 --directory C:/wt/GuildBoardTrial
    python scripts/shoot_voyage_ports.py --url http://localhost:8790/voyage.html
"""

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "previews"

THEMES = ["codex", "console", "chronicle"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8790/voyage.html")
    ap.add_argument("--prefix", default="voy07_")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    pfx = args.prefix

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme in THEMES:
            page = browser.new_page(viewport={"width": 390, "height": 844},
                                    device_scale_factor=2)
            page.goto(args.url, wait_until="domcontentloaded")
            try:
                page.wait_for_function("document.fonts.ready", timeout=6000)
            except Exception:  # noqa: BLE001
                pass
            page.click(f'.themeswitch button[data-theme="{theme}"]')
            page.wait_for_timeout(700)
            # the ports route, in place near the top of the map
            page.evaluate("document.querySelector('.ports').scrollIntoView({block:'center'})")
            page.wait_for_timeout(500)
            page.screenshot(path=str(OUT / f"{pfx}ports_{theme}.png"))
            print("shot", pfx + "ports_" + theme)

            # dock at the current port — open its diorama
            page.evaluate("""() => {
              const jul = [...document.querySelectorAll('.port')]
                .find(b => b.classList.contains('here')) ||
                document.querySelector('.port');
              jul.click();
            }""")
            page.wait_for_timeout(700)
            page.screenshot(path=str(OUT / f"{pfx}diorama_{theme}.png"))
            print("shot", pfx + "diorama_" + theme)
            page.close()
        browser.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Screenshot the rendered crew board at desktop + phone widths, for each
theme. Run scripts/render_crew_board.py first.

    python scripts/shoot_crew_board.py
"""

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "crew_board.html"
OUT = ROOT / "previews"

SHOTS = [
    # (label, width, height, theme, full_page)
    ("desktop_codex", 1440, 950, "codex", True),
    ("desktop_console", 1440, 950, "console", False),
    ("desktop_chronicle", 1440, 950, "chronicle", False),
    ("mobile_codex", 390, 844, "codex", True),
    ("mobile_console", 390, 844, "console", False),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", default=str(PAGE))
    ap.add_argument("--prefix", default="")
    args = ap.parse_args()
    page_path = Path(args.page)
    if not page_path.is_absolute():
        page_path = ROOT / page_path
    if not page_path.exists():
        sys.exit(f"{page_path} not found — run scripts/render_crew_board.py first.")
    OUT.mkdir(exist_ok=True)
    url = page_path.as_uri()
    pfx = args.prefix

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for label, w, h, theme, full in SHOTS:
            page = browser.new_page(viewport={"width": w, "height": h},
                                    device_scale_factor=2)
            page.goto(url, wait_until="domcontentloaded")
            # Webfonts are a network fetch; never let them hold the shot.
            try:
                page.wait_for_function("document.fonts.ready", timeout=6000)
            except Exception:  # noqa: BLE001
                pass
            # Click the real switch rather than poking the attribute, so
            # the captured page shows the true pressed state.
            page.click(f'.themeswitch button[data-theme="{theme}"]')
            page.wait_for_timeout(900)
            page.screenshot(path=str(OUT / f"{pfx}{label}.png"), full_page=full)
            print("shot", pfx + label)
            page.close()

        # The signature interaction, caught mid-spotlight: hover the
        # Healers tab and capture the deck popping.
        page = browser.new_page(viewport={"width": 1440, "height": 950},
                                device_scale_factor=2)
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(700)
        page.hover(".tab[data-role='healer']")
        page.wait_for_timeout(900)
        page.screenshot(path=str(OUT / f"{pfx}interaction_healer_spotlight.png"))
        print("shot", pfx + "interaction_healer_spotlight")

        # Shadowform, toggled on.
        page.evaluate("document.querySelector('[data-shadowtoggle]').click()")
        page.wait_for_timeout(700)
        page.screenshot(path=str(OUT / f"{pfx}interaction_shadowform.png"))
        print("shot", pfx + "interaction_shadowform")
        # A scene change: hover a raid-boss island so the backdrop washes
        # crimson. The crew's cut-outs must be identical to the shot above.
        page = browser.new_page(viewport={"width": 1440, "height": 950},
                                device_scale_factor=2)
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(800)
        # Dispatch the hover WITHOUT scrolling the island into view, so the
        # crew stage stays framed — the whole point is that the backdrop
        # changed while the cast did not.
        changed = page.evaluate("""() => {
            const b = document.querySelector(".island[data-kind='raid_boss']");
            if (!b) return false;
            b.dispatchEvent(new MouseEvent('mouseenter'));
            return true;
        }""")
        if changed:
            page.wait_for_timeout(1400)
            page.screenshot(path=str(OUT / f"{pfx}scene_boss_island.png"))
            print("shot", pfx + "scene_boss_island")
        page.close()
        browser.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Record a short guided tour of the trial board, plus stills.

Drives the real page in a real browser and records it, so what Zach sees
is exactly what the board does — no mock-ups.

    python scripts/record_trial.py --bundle "C:/.../GuildBoardTrial"

Outputs into <bundle>/_preview_media/:
    board_tour.webm     the screen recording
    board_tour.gif      the same tour, shareable inline
    shot_*.png          stills of each beat
"""

import argparse
import shutil
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

W, H = 1360, 860


def beat(page, label, shots, ms=1100):
    """Hold a moment so the recording reads, and grab a still."""
    page.wait_for_timeout(ms)
    path = shots / f"shot_{label}.png"
    page.screenshot(path=str(path))
    print("   ·", label)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    args = ap.parse_args()
    bundle = Path(args.bundle).resolve()
    index = bundle / "index.html"
    if not index.exists():
        raise SystemExit(f"{index} not found — run build_trial.py first")

    media = bundle / "_preview_media"
    if media.exists():
        shutil.rmtree(media)
    media.mkdir(parents=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": W, "height": H},
                                  record_video_dir=str(media),
                                  record_video_size={"width": W, "height": H})
        page = ctx.new_page()
        page.goto(index.as_uri(), wait_until="domcontentloaded")
        try:
            page.wait_for_function("document.fonts.ready", timeout=6000)
        except Exception:  # noqa: BLE001
            pass

        print("  recording the tour")
        # 0. the trial page — the front door Zach opens
        beat(page, "00_trial_top", media, 2400)
        page.evaluate("document.querySelector('.cast').scrollIntoView({block:'center'})")
        beat(page, "01_trial_cast", media, 2600)
        # hover a card so the scene art breathes
        page.hover(".card[data-role='healer']")
        beat(page, "02_trial_card_hover", media, 1800)
        page.evaluate("document.querySelector('.steps').scrollIntoView({block:'center'})")
        beat(page, "03_how_it_works", media, 2200)
        page.evaluate("document.querySelector('.notes').scrollIntoView({block:'center'})")
        beat(page, "04_what_changed", media, 2400)
        # themes on the trial page
        for key, label in (("chronicle", "05_trial_chronicle"),
                           ("console", "06_trial_console"),
                           ("codex", "07_trial_codex")):
            page.click(f'.themeswitch button[data-theme="{key}"]')
            page.evaluate("document.querySelector('.cast').scrollIntoView({block:'center'})")
            beat(page, label, media, 1500)

        # then through to the animated board
        board = bundle / "crew_board.html"
        if board.exists():
            page.goto(board.as_uri(), wait_until="domcontentloaded")
            page.wait_for_timeout(900)
        page.evaluate("document.querySelector('.stage').scrollIntoView({block:'center'})")
        beat(page, "08_deck_idle", media, 2200)

        # 2. role spotlight — the signature interaction
        page.hover(".tab[data-role='healer']")
        beat(page, "09_healer_spotlight", media, 1600)
        page.hover(".tab[data-role='tank']")
        beat(page, "10_tank_spotlight", media, 1600)

        # 3. summon a character forward.
        # Move the pointer off the tabs first, or the role spotlight from
        # the previous beat is still applied and the summon reads as a
        # continuation of it rather than its own interaction.
        page.mouse.move(W // 2, H - 40)
        page.evaluate("""() => {
            document.querySelectorAll('.tab').forEach(t =>
              t.dispatchEvent(new MouseEvent('mouseleave', {bubbles:true})));
        }""")
        page.wait_for_timeout(900)
        page.evaluate("""() => {
            const m = [...document.querySelectorAll('.member')]
              .find(x => x.querySelector('.doll[data-mode="layered"]'));
            if (m) m.dispatchEvent(new MouseEvent('mouseenter', {bubbles:true}));
        }""")
        beat(page, "11_summon", media, 1700)

        # 4. scene change behind a constant cast
        page.evaluate("""() => {
            const b = document.querySelector(".island[data-kind='raid_boss']");
            if (b) b.dispatchEvent(new MouseEvent('mouseenter'));
        }""")
        beat(page, "12_scene_change", media, 1800)

        # 5. themes
        for key, label in (("console", "13_board_console"),
                           ("chronicle", "14_board_chronicle"),
                           ("codex", "15_board_codex")):
            page.click(f'.themeswitch button[data-theme="{key}"]')
            beat(page, label, media, 1400)

        # 6. the data cards
        page.evaluate("document.querySelector('.cards').scrollIntoView({block:'start'})")
        beat(page, "16_cards", media, 1800)

        # 7. into a profile page
        page.evaluate("document.querySelector('.stage').scrollIntoView({block:'center'})")
        page.wait_for_timeout(600)
        href = page.evaluate("""() => {
            const a = [...document.querySelectorAll('.member .plate a.plink')]
              .find(x => x.closest('.member').querySelector('.doll[data-mode="layered"]'));
            return a ? a.getAttribute('href') : null;
        }""")
        if href:
            page.goto((bundle / href).as_uri(), wait_until="domcontentloaded")
            beat(page, "17_profile", media, 2400)

        ctx.close()          # finalises the video
        browser.close()

    # name the video predictably
    videos = sorted(media.glob("*.webm"))
    if videos:
        target = media / "board_tour.webm"
        videos[0].rename(target)
        print(f"  video: {target.name} ({target.stat().st_size/1024/1024:.1f} MB)")

    # a GIF of the same beats, for inline sharing
    stills = sorted(media.glob("shot_*.png"))
    if stills:
        frames = []
        for path in stills:
            img = Image.open(path).convert("RGB")
            img = img.resize((img.width // 2, img.height // 2), Image.LANCZOS)
            frames += [img] * 3          # hold each beat ~0.9s
        frames[0].save(media / "board_tour.gif", save_all=True,
                       append_images=frames[1:], duration=300, loop=0,
                       optimize=True)
        print(f"  gif  : board_tour.gif ({(media/'board_tour.gif').stat().st_size/1024/1024:.1f} MB)")
    print(f"  stills: {len(stills)}")
    print(f"\nMedia in {media}")


if __name__ == "__main__":
    main()

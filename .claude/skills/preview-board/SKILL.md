---
name: preview-board
description: Render the guild board locally with canned data (desktop, mobile, and web HTML plus optional PNG) and show the result. No API keys or network needed.
disable-model-invocation: true
---

# Preview the guild board

Render the board from `scripts/preview_board.py`'s built-in fake week (it
exercises every section: parses, keys, records with NEW flags, streaks,
graveyard, roast) and show the user the result.

## Steps

1. From the repo root, render HTML plus screenshots:

   ```powershell
   $env:PYTHONIOENCODING='utf-8'; python scripts/preview_board.py --png
   ```

   This writes `board_render.html` (desktop), `board_mobile_render.html`,
   `board_web_render.html`, and — with `--png` — `board_preview.png` and
   `board_mobile.png` via Playwright.

2. If the user passed arguments, honor them: `html` skips `--png` (faster,
   no Playwright); `mobile`/`web` means they mainly care about that variant.

3. Show the result: send `board_preview.png` (and `board_mobile.png` if
   mobile is relevant) with SendUserFile using `display: render`. If PNG
   generation failed (Playwright missing), open `board_render.html` in the
   in-app browser via its `file://` URI instead and screenshot it.

4. All outputs are gitignored — never commit them, never write to `site/`.

If the render fails, check that the command ran from the repo root
(`assets/` paths resolve relative to cwd) before digging deeper.

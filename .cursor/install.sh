#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for the Skill Issues Guild Board.
# Mirrors the setup the weekly-board GitHub Actions workflow performs so the
# offline dev flow (pytest, ruff, scripts/preview_board.py) works out of the box.
set -euo pipefail

cd "$(dirname "$0")/.."

# apt needs root; use sudo when we are not already it.
if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
elif command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
else
  SUDO=""
fi

# DejaVu fonts: the Pillow board renderer (board_image.py) draws text with them.
$SUDO apt-get update -qq
$SUDO apt-get install -y -qq --no-install-recommends fonts-dejavu-core

# Python deps: render = Playwright (HTML/paper screenshots), dev = pytest/ruff/mypy.
pip install -e ".[render,dev]"

# Chromium + its OS libraries drive both the classic and paper render paths.
python3 -m playwright install --with-deps chromium

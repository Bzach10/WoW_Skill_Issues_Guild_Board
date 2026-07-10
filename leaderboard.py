#!/usr/bin/env python3
"""Backwards-compatible entry point for the WoW Guild Weekly Board.

The logic now lives in the `guild_board` package. This file exists so the
GitHub Actions workflow and any existing instructions keep working.
"""

from guild_board.main import main

if __name__ == "__main__":
    main()

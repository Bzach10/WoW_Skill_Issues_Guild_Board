"""PreToolUse hook: block Edit/Write on CI-owned state files.

GitHub Actions commits these back with `[skip ci]` after every run
(weekly-board, board-vote, blizzard-profile-refresh). Hand edits get
overwritten or cause merge conflicts, so Claude is not allowed to
touch them. Exit code 2 blocks the tool call; stderr becomes the
explanation Claude sees.
"""

import json
import os
import sys

CI_OWNED = {
    "board_state.json",
    "roster_cache.json",
    "weekly_state.json",
    "blizzard_profile_cache.json",
    # data/accounts.json — the Ship's Articles. scripts/refresh_articles.py
    # is its ONLY writer, and a hand edit here does not just get overwritten:
    # it forges a signature on the account<->character mapping that every
    # share, card and board is keyed on. Change the code, never the ledger.
    "accounts.json",
}


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return  # malformed input: allow rather than break every edit

    file_path = (payload.get("tool_input") or {}).get("file_path", "")
    name = os.path.basename(str(file_path))
    if name in CI_OWNED:
        print(
            f"{name} is CI-owned: GitHub Actions regenerates and commits it "
            "with [skip ci]. Manual edits are overwritten on the next run or "
            "cause merge conflicts. If it truly needs to change, change the "
            "code/workflow that produces it, or let the user edit it "
            "deliberately outside Claude.",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()

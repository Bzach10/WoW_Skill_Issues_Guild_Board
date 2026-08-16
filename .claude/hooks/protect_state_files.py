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
}

# Whole directories the pipeline writes and nobody edits by hand. The
# season ledger is APPEND-ONLY (a hand edit rewrites history that is meant
# to be permanent) and data/seasons/ holds season freezes that are written
# once and never again — an editor is the one tool that can defeat both
# guarantees. Change the code that produces them instead.
CI_OWNED_DIRS = (
    ("season_ledger",),
    ("data", "seasons"),
)


def _in_ci_owned_dir(file_path: str) -> bool:
    parts = [p for p in str(file_path).replace("\\", "/").split("/") if p]
    for owned in CI_OWNED_DIRS:
        for i in range(len(parts) - len(owned)):
            if tuple(parts[i:i + len(owned)]) == owned:
                return True
    return False


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

    if _in_ci_owned_dir(file_path):
        print(
            f"{file_path} is pipeline-owned. season_ledger/ is APPEND-ONLY "
            "(guild_board/season_ledger.py writes one line per character per "
            "raid week, forever) and data/seasons/ holds season freezes that "
            "are written ONCE. Editing either by hand destroys the guarantee "
            "the surfaces read them under. Change the code that produces "
            "them, or let the user edit deliberately outside Claude.",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()

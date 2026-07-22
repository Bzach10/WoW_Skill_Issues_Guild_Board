"""PostToolUse hook: lint a just-edited Python file with ruff.

Config lives in [tool.ruff] in pyproject.toml. Exit code 2 feeds the
findings back to Claude (the edit already happened) so it cleans up
immediately. If ruff isn't installed, stay silent rather than nag on
every edit.
"""

import json
import subprocess
import sys


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    file_path = str((payload.get("tool_input") or {}).get("file_path", ""))
    if not file_path.endswith(".py"):
        return

    try:
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", file_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return

    if result.returncode != 0:
        output = (result.stdout + result.stderr).strip()
        if "No module named" in output:
            return  # ruff not installed in this environment
        print(f"ruff found issues in the file you just edited:\n{output}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()

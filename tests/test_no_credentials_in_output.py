"""Build gate: no credential names or credential-shaped values in shipped output.

Why this exists
---------------
`WCL_CLIENT_ID` / `WCL_CLIENT_SECRET` were written into member-facing copy on
the ship page — the empty-state path that the unranked members hit, on a page
roughly 150 guild members read. They were variable *names*, not values, so
nothing was leaked. But the reason it was worth fixing is the reason it is
worth *guarding*: build-log text kept escaping onto a members' page, and the
next thing to escape that way might not be a name.

This project's postmortem records that it repeats its mistakes when a fix is
recorded only as prose in a doc. So this is a test, not a note.

It runs two ways on purpose:

    pytest tests/test_no_credentials_in_output.py     # in CI
    python tests/test_no_credentials_in_output.py     # as a build gate,
                                                      # no pytest required

The second form matters: the sandbox this was written in has no PyPI egress
and cannot install pytest, so a pytest-only guard would have shipped unrun.

It deliberately does NOT print any value it finds. A failure reports the file,
the line number and the *kind* of match. Printing the secret into CI logs to
prove a secret is in CI logs would be its own incident.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------- what we scan
# Anything a guild member's browser can fetch, plus the templates that
# generate it (so a bad string fails before it is ever rendered).
SCAN_GLOBS = (
    "*.html",
    "p/*.html",
    "web/*.html", "web/**/*.html",
    "guild_board/templates/**/*.j2",
    "web_stats.json", "site_data.json", "roster.json",
    "board_state.json", "voyage_data.json", "competition.json",
    "data/*.json",
    # The parse products: the browsable bundle layers the site serves, the
    # committed sample fallbacks the front-end degrades to, and the raw WCL
    # sweep cache they are all built from.
    "web_data/*.json",
    "samples/*.json",
    "parses_cache.json",
)

# --------------------------------------------------------- rule 1: variable names
# Naming these in shipped copy is not a leak, but it is build-log text on a
# members' page, and it is how the habit starts. Operator-facing explanations
# belong in the log and in docs/RUNBOOK.md.
FORBIDDEN_NAMES = (
    "WCL_CLIENT_ID", "WCL_CLIENT_SECRET",
    "BLIZZARD_CLIENT_ID", "BLIZZARD_CLIENT_SECRET",
    "DISCORD_WEBHOOK_URL", "DISCORD_BOT_TOKEN",
    "RUNPOD_API_KEY",
)

# --------------------------------------------------------- rule 2: value shapes
# These would be an actual exposure. None are currently present anywhere in
# this repo or its history (verified 2026-07-22); the guard is here so that
# stays true.
VALUE_PATTERNS = (
    ("runpod api key",      re.compile(r"\brpa_[A-Za-z0-9]{20,}")),
    ("discord webhook url", re.compile(r"https://discord(?:app)?\.com/api/webhooks/\d+/[\w-]{20,}")),
    ("discord bot token",   re.compile(r"\b[A-Za-z0-9_-]{24}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}")),
    ("bearer token",        re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}=*")),
    ("assigned secret",     re.compile(
        r"(?i)\b(?:client_secret|api[_-]?key|access[_-]?token|password|secret)\b"
        r"\"?\s*[:=]\s*\"?[A-Za-z0-9_\-]{20,}")),
)

# Long opaque strings that are legitimately in built output and must not trip
# the "assigned secret" rule.
ALLOW = (
    re.compile(r"data:[a-z]+/[a-z0-9.+-]+;base64,"),   # inlined images/fonts
    re.compile(r"integrity=\"sha\d{3}-"),               # SRI hashes
    re.compile(r"(?i)\bsecret\"?\s*[:=]\s*\"?(?:null|none|true|false|\"\")"),
)


def _iter_files():
    import glob
    seen = set()
    for pattern in SCAN_GLOBS:
        for path in glob.glob(os.path.join(ROOT, pattern), recursive=True):
            if os.path.isfile(path) and path not in seen:
                seen.add(path)
                yield path


def find_violations():
    """Return [(relpath, lineno, kind)] — never the matched text itself."""
    violations = []
    for path in _iter_files():
        rel = os.path.relpath(path, ROOT)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, 1):
            if any(a.search(line) for a in ALLOW):
                continue
            for name in FORBIDDEN_NAMES:
                if name in line:
                    violations.append((rel, lineno, f"credential variable name {name!r} "
                                       "in shipped output"))
            for kind, pattern in VALUE_PATTERNS:
                if pattern.search(line):
                    violations.append((rel, lineno,
                                       f"credential-shaped value ({kind})"))
    return violations


def _format(violations):
    lines = [f"{len(violations)} credential violation(s) in shipped output:"]
    lines += [f"  {rel}:{lineno} — {msg}" for rel, lineno, msg in violations]
    lines.append("")
    lines.append("Operator-facing text belongs in the build log and "
                 "docs/RUNBOOK.md, never in rendered copy.")
    lines.append("Values are never printed here by design — open the file "
                 "at the line above to see what matched.")
    return "\n".join(lines)


def test_no_credentials_in_shipped_output():
    violations = find_violations()
    assert not violations, _format(violations)


if __name__ == "__main__":
    found = find_violations()
    if found:
        print(_format(found))
        sys.exit(1)
    print("OK — no credential names or credential-shaped values in shipped output.")
    sys.exit(0)

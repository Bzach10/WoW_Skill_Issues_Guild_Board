"""Refuse the weekly post if the paper has stopped carrying something.

    python scripts/check_paper_parity.py [URL]

THE PAPER IS THE POST, and the paper is built in another repo on another
schedule. Nothing in this repo would notice if a block quietly left the
sheet -- the shot would still succeed, the post would still go out, and the
guild would simply stop being told something it used to be told.

So: before the run reaches the step that holds the webhook, fetch the live
page and check it against parity_manifest.yml. This is deliberately the
CHEAP check -- one GET, no browser, no credentials -- so a paper that has
regressed kills the run early and loudly. paper_shot.shoot_paper runs the
same check a second time on the real rendered DOM; this one exists so the
failure lands before any secret is in the environment.

Exit 0 when every kept datum is present, 1 when one is missing, 2 when the
page could not be fetched at all (a fetch fault is not a parity verdict --
the run should fall back to the classic renderer, not conclude the paper is
empty). Console output is ASCII-safe.
"""

import html
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from guild_board.paper_shot import (  # noqa: E402
    BOARD_URL,
    check_parity,
    load_parity_manifest,
)

# Cloudflare Pages answers a bare urllib request with 403; a normal browser
# UA is not a trick, it is the only way to read a page meant for browsers.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _say(msg):
    print(str(msg).encode("ascii", "backslashreplace").decode("ascii"))


def page_text(url, timeout=45):
    """The paper's readable text: scripts and styles out, tags out, entities
    decoded, whitespace collapsed -- as close as a plain GET gets to the
    innerText the browser check reads."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    body = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw)
    body = re.sub(r"(?s)<!--.*?-->", " ", body)
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    return re.sub(r"\s+", " ", html.unescape(body)).strip()


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    url = (args[0] if args else None) or os.environ.get("PAPER_BOARD_URL") or BOARD_URL
    manifest = load_parity_manifest(str(ROOT / "parity_manifest.yml"))
    if manifest is None:
        _say("PARITY: no parity_manifest.yml -- nothing to check. "
             "The paper would be posted UNGATED.")
        return 0

    try:
        text = page_text(url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _say(f"PARITY: could not fetch {url} ({exc}). This is a FETCH fault, "
             "not a parity verdict -- the post falls back to the classic "
             "renderer rather than treating an unreachable paper as an empty one.")
        return 2

    missing, checked = check_parity(text, manifest)
    _say(f"PARITY: {checked} kept datum(s) checked against {url} "
         f"({len(text):,} characters of paper).")
    if not missing:
        _say("PARITY: the paper still carries every datum the board used to publish.")
        return 0

    _say("")
    _say("!! " + "=" * 72)
    _say("!! PARITY FAILURE -- THE POST IS REFUSED")
    _say("!! " + "=" * 72)
    for m in missing:
        _say(f"!!   {m.get('datum')}")
        _say(f"!!     was : {m.get('was')}")
        _say(f"!!     page: {m.get('page')}   anchor: {m.get('anchor')}")
        _say(f"!!     want: {m.get('expect')}")
    _say("!!")
    _say("!! The paper is no longer printing something the weekly board used to.")
    _say("!! Either the site regressed (fix it there and re-run this workflow),")
    _say("!! or the datum was dropped ON PURPOSE -- in which case move its entry")
    _say("!! from `kept` to `dropped` in parity_manifest.yml, with the reason.")
    _say("!! Do NOT delete the entry to silence this.")
    _say("!! " + "=" * 72)
    return 1


if __name__ == "__main__":
    sys.exit(main())

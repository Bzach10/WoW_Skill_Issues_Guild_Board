"""Post a board-skin vote to Discord: two board images in one message.

Usage: python scripts/post_vote.py <image_a> <image_b>
Needs DISCORD_WEBHOOK_URL in the environment (same secret the weekly
board uses). Attachment order matters: A renders first in the gallery.
"""

import json
import os
import sys

import requests

VOTE_TEXT = (
    "## \U0001f5f3️ BOARD SKIN SHOWDOWN\n"
    "Two looks for the weekly board — same data, different vibe. "
    "**You** pick what posts every Tuesday.\n\n"
    "\U0001f170️ **Stone & Torchlight** (first image) — carved plaque, "
    "graveyard memorial, animated embers\n"
    "\U0001f171️ **Ember Terminal** (second image) — by our own guildie, "
    "fel-green accents, terminal type\n\n"
    "Vote by reacting \U0001f170️ or \U0001f171️. Polls close before "
    "next reset. Campaigning, bribery and healer-blaming are all permitted."
)


def main():
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        print("DISCORD_WEBHOOK_URL not set", file=sys.stderr)
        return 1
    paths = sys.argv[1:3]
    if len(paths) != 2 or not all(os.path.exists(p) for p in paths):
        print(f"usage: post_vote.py <image_a> <image_b> (got {paths})", file=sys.stderr)
        return 1

    files = {}
    handles = []
    try:
        for i, p in enumerate(paths):
            f = open(p, "rb")
            handles.append(f)
            mime = "image/gif" if p.lower().endswith(".gif") else "image/png"
            files[f"files[{i}]"] = (os.path.basename(p), f, mime)
        payload = {"content": VOTE_TEXT}
        resp = requests.post(webhook, data={"payload_json": json.dumps(payload)},
                             files=files, timeout=60)
        resp.raise_for_status()
    finally:
        for f in handles:
            f.close()
    print("Vote posted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Post the board REDESIGN candidates to Discord as a numbered vote.

This is a proposal poll, not the weekly board. It attaches one
screenshot per candidate, labels them Option 1..N, and seeds 1..N
reactions so members can vote with one tap.

    python scripts/post_redesign_vote.py                    # uses the default set
    python scripts/post_redesign_vote.py --dry-run          # print, send nothing
    python scripts/post_redesign_vote.py --option ember_terminal__emberforge "Ember Terminal" \
                                         --option codex__gildedcodex "Gilded Codex"

Environment (the same secrets the weekly board already uses):
    DISCORD_WEBHOOK_URL   required — where the board normally posts
    DISCORD_BOT_TOKEN     optional — only used to SEED the reactions

Reaction seeding needs the bot to be in the channel with "Add
Reactions". Without a token, or if the bot lacks the permission, the
post still goes out and simply asks members to react themselves — the
message text says so either way, so it never reads as broken.

Nothing here fires on its own: the workflow that calls it is
workflow_dispatch-only.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "redesign_previews"
DISCORD_API = "https://discord.com/api/v10"

NUMBER_EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣",
                "5️⃣", "6️⃣", "7️⃣", "8️⃣"]

# The candidates, in posting order: (preview stem, display name, one-liner).
# Stems match redesign_previews/<stem>.png.
DEFAULT_OPTIONS = [
    ("ember_terminal__emberforge", "Emberforge Console",
     "A scrying console in a molten forge — torn iron slates that overlap, "
     "live art behind everything, rankings as console readouts."),
    ("chronicle__arcanevault", "Arcane Chronicle",
     "A magazine front page — one huge headline over the artwork, then a "
     "lead column of standings with the guild's jokes running down the side."),
    ("codex__gildedcodex", "Gilded Codex",
     "An illuminated manuscript on real vellum — ink on light paper, each "
     "section a chapter with a gold initial. The only non-dark option."),
    # poster's parchment glaze is warm, so it needs a warm theme — the
    # cool palettes wash it out to mint/lavender
    ("poster__emberforge", "Forge Bounty",
     "The WANTED posters you know, but real paper — actually-torn edges, "
     "different sizes, nailed up crooked instead of four tidy boxes."),
]


def build_message(options, guild_name="Skill Issues"):
    """The vote text. Explicitly frames these as proposals."""
    lines = [
        "# \U0001f5f3️  GUILD BOARD REDESIGN — VOTE",
        "",
        f"We're redesigning the **{guild_name}** web board and **you** pick which "
        "direction it goes. Same data every week — ranks, parses, keys, streaks, "
        "the debt, the graveyard, the roast — arranged four different ways.",
        "",
        "⚠️ **These are proposals, not live.** The current board is untouched "
        "and stays up until this vote decides otherwise.",
        "",
    ]
    for i, (_stem, name, blurb) in enumerate(options, 1):
        lines.append(f"{NUMBER_EMOJI[i - 1]} **Option {i} — {name}**  \n{blurb}")
        lines.append("")
    lines += [
        "⬇️ Screenshots are attached **in order** — Option 1 first.",
        "",
        "**Vote by reacting with the matching number below.** "
        "Campaigning, bribery and healer-blaming are all permitted.",
    ]
    return "\n".join(lines)


def vote_cards(options, width=1100, max_ratio=1.9):
    """Turn the tall full-page screenshots into Discord-friendly cards.

    A full-page shot is 8-14MB and up to 6000px tall: four of them blow
    past Discord's attachment cap and render as unreadable slivers in
    the client. Each card is instead the TOP of the page — masthead,
    headline and the first rankings, which is what actually distinguishes
    the options — scaled to `width` and capped at `max_ratio` tall, saved
    as JPEG.

    Returns the list of card paths (falls back to the originals if
    Pillow isn't available, so the script still runs).
    """
    try:
        from PIL import Image
    except ImportError:
        print("Pillow not installed; attaching the full-size screenshots as-is.")
        return [str(SHOTS / f"{s}.png") for s, _n, _b in options]

    out_dir = SHOTS / "vote"
    out_dir.mkdir(parents=True, exist_ok=True)
    cards = []
    for stem, _name, _blurb in options:
        src = SHOTS / f"{stem}.png"
        with Image.open(src) as im:
            im = im.convert("RGB")
            crop_h = min(im.height, int(im.width * max_ratio))
            im = im.crop((0, 0, im.width, crop_h))
            if im.width != width:
                im = im.resize((width, int(im.height * width / im.width)),
                               Image.LANCZOS)
            dest = out_dir / f"{stem}.jpg"
            im.save(dest, quality=86, optimize=True, progressive=True)
        cards.append(str(dest))
    return cards


def _post_webhook(webhook, content, paths):
    """Multipart post with ?wait=true so Discord returns the message
    object (we need its id + channel_id to seed reactions)."""
    boundary = "----guildboard{}".format(int(time.time() * 1000))
    parts, body = [], b""
    payload = json.dumps({"content": content,
                          "allowed_mentions": {"parse": []}})
    parts.append((b'Content-Disposition: form-data; name="payload_json"\r\n'
                  b"Content-Type: application/json\r\n\r\n"
                  + payload.encode("utf-8")))
    for i, p in enumerate(paths):
        data = Path(p).read_bytes()
        head = ('Content-Disposition: form-data; name="files[{}]"; filename="{}"\r\n'
                "Content-Type: image/png\r\n\r\n").format(i, Path(p).name)
        parts.append(head.encode("utf-8") + data)
    for part in parts:
        body += ("--" + boundary + "\r\n").encode() + part + b"\r\n"
    body += ("--" + boundary + "--\r\n").encode()

    sep = "&" if "?" in webhook else "?"
    req = urllib.request.Request(
        f"{webhook}{sep}wait=true", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def _seed_reactions(token, channel_id, message_id, count):
    """Best-effort: add 1..count as reactions so voting is one tap.
    Returns True only if every reaction landed."""
    ok = True
    for emoji in NUMBER_EMOJI[:count]:
        quoted = urllib.parse.quote(emoji, safe="")
        req = urllib.request.Request(
            f"{DISCORD_API}/channels/{channel_id}/messages/{message_id}"
            f"/reactions/{quoted}/@me",
            method="PUT",
            headers={"Authorization": f"Bot {token}", "Content-Length": "0"})
        try:
            urllib.request.urlopen(req, timeout=30)
            time.sleep(0.35)          # stay under the reaction rate limit
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            print(f"  ! could not seed {emoji}: HTTP {exc.code} {detail}")
            ok = False
            break                      # almost always a missing permission
        except Exception as exc:
            print(f"  ! could not seed {emoji}: {exc}")
            ok = False
            break
    return ok


def main():
    # The message is full of emoji; a legacy Windows console is cp1252 and
    # would raise on print(). Never let that be the thing that fails.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="Post the redesign vote to Discord")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the message and the files, send nothing")
    ap.add_argument("--option", nargs=2, action="append", metavar=("STEM", "NAME"),
                    help="override the candidate set (repeatable)")
    ap.add_argument("--guild-name", default="Skill Issues")
    args = ap.parse_args()

    if args.option:
        options = [(stem, name, "") for stem, name in args.option]
    else:
        options = DEFAULT_OPTIONS

    missing = [s for s, _n, _b in options if not (SHOTS / f"{s}.png").exists()]
    if missing:
        print("Missing screenshots (run: python scripts/render_redesign_previews.py --png)",
              file=sys.stderr)
        for stem in missing:
            print(f"  - redesign_previews/{stem}.png", file=sys.stderr)
        return 1
    paths = vote_cards(options)
    content = build_message(options, args.guild_name)

    if args.dry_run:
        print("=" * 72)
        print(content)
        print("=" * 72)
        print("\nAttachments, in order:")
        for i, p in enumerate(paths, 1):
            print(f"  {i}. {Path(p).name}  ({os.path.getsize(p) / 1e6:.1f} MB)")
        print(f"\nWould seed reactions: {' '.join(NUMBER_EMOJI[:len(options)])}")
        print("DRY RUN — nothing was sent.")
        return 0

    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        print("DISCORD_WEBHOOK_URL is not set — nothing sent.", file=sys.stderr)
        return 1

    # Discord caps attachments at 25MB total on most guilds; full-page
    # shots are big, so fail loudly here rather than getting a 413.
    total = sum(os.path.getsize(p) for p in paths)
    if total > 24 * 1024 * 1024:
        print(f"Attachments total {total / 1e6:.1f} MB, over Discord's limit. "
              "Re-run the renderer to produce smaller shots.", file=sys.stderr)
        return 1

    print(f"Posting {len(paths)} option(s)...")
    message = _post_webhook(webhook, content, paths)
    message_id = message.get("id")
    channel_id = message.get("channel_id")
    print(f"Posted. message_id={message_id} channel_id={channel_id}")

    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("No DISCORD_BOT_TOKEN — members will add their own reactions "
              "(the message asks them to).")
    elif message_id and channel_id:
        print("Seeding vote reactions...")
        if _seed_reactions(token, channel_id, message_id, len(options)):
            print("Reactions seeded.")
        else:
            print("Reaction seeding incomplete (bot likely lacks Add Reactions). "
                  "The post still stands and asks members to react.")

    if message_id and channel_id:
        guild_id = message.get("guild_id")
        if guild_id:
            print(f"Link: https://discord.com/channels/{guild_id}/{channel_id}/{message_id}")
        else:
            print(f"Link: https://discord.com/channels/@me/{channel_id}/{message_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

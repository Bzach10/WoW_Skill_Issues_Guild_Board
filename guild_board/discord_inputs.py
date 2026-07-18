"""Read board inputs straight from Discord channels.

The weekly run (GitHub Actions) has no live bot process, but a bot token
can still READ channels over the REST API. That turns Discord itself into
the input form:

- Roast channel: members post roasts during the week; reactions with the
  vote emoji (🔥 by default) are the ballots. The top-voted message since
  the week started becomes Roast of the Week.
- Announcement channel: officers/GM post there (lock it to officers in
  Discord permissions); the latest message becomes the board announcement.
"""

import logging
import re

import requests

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"
DISCORD_EPOCH_MS = 1_420_070_400_000


def _get_messages(bot_token, channel_id, limit=100):
    resp = requests.get(
        f"{DISCORD_API}/channels/{channel_id}/messages",
        headers={"Authorization": f"Bot {bot_token}"},
        params={"limit": limit},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _snowflake_ms(snowflake):
    """Discord IDs encode their creation time."""
    return (int(snowflake) >> 22) + DISCORD_EPOCH_MS


def _author_name(message):
    author = message.get("author") or {}
    return author.get("global_name") or author.get("username") or "Anonymous"


def _vote_count(message, emoji):
    for reaction in message.get("reactions") or []:
        if (reaction.get("emoji") or {}).get("name") == emoji:
            return int(reaction.get("count") or 0)
    return 0


def fetch_top_roast(bot_token, channel_id, since_ms, vote_emoji="\U0001F525", min_votes=1):
    """Return the most-voted roast message posted since since_ms, or None."""
    messages = _get_messages(bot_token, channel_id)
    best = None
    best_votes = min_votes - 1
    for message in messages:
        content = (message.get("content") or "").strip()
        if not content:
            continue
        if (message.get("author") or {}).get("bot"):
            continue
        if _snowflake_ms(message["id"]) < since_ms:
            continue
        votes = _vote_count(message, vote_emoji)
        if votes > best_votes:
            best, best_votes = message, votes

    if best is None:
        return None

    target = ""
    mentions = best.get("mentions") or []
    if mentions:
        target = mentions[0].get("global_name") or mentions[0].get("username") or ""

    content = best.get("content").strip()
    # Replace raw <@123> mention markup with the readable name
    content = re.sub(r"<@!?\d+>", target or "them", content).strip()

    return {
        "roast": content,
        "winner": _author_name(best),
        "target": target,
        "votes": best_votes,
    }


def fetch_latest_announcement(bot_token, channel_id):
    """Return the newest human-authored message in the announcement channel."""
    messages = _get_messages(bot_token, channel_id, limit=10)
    for message in messages:  # Discord returns newest first
        content = (message.get("content") or "").strip()
        if content and not (message.get("author") or {}).get("bot"):
            return {"text": content, "author": _author_name(message)}
    return None

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


def _get_json(bot_token, path, params=None):
    resp = requests.get(
        f"{DISCORD_API}{path}",
        headers={"Authorization": f"Bot {bot_token}"},
        params=params or {},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _get_messages(bot_token, channel_id, limit=100):
    return _get_json(bot_token, f"/channels/{channel_id}/messages", {"limit": limit})


def _collect_messages(bot_token, channel_id, max_threads=8):
    """Messages in a channel PLUS its recent threads.

    Roasts often live in threads (the board footer literally says "drop
    roasts in the thread"), and forum-style channels store every post as a
    thread — so reading only the channel itself misses them all.
    """
    messages = []
    try:
        messages.extend(_get_messages(bot_token, channel_id))
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        if status in (401, 403, 404):
            # Make missing access loud — it looks identical to an empty channel otherwise
            logger.warning(
                "Cannot read channel %s (HTTP %s). Check the bot has View Channel + "
                "Read Message History there and the ID is right.", channel_id, status)
        else:
            # Forum channels reject /messages; their threads below still work.
            logger.debug("Channel %s message list unavailable: %s", channel_id, exc)

    thread_ids = []
    try:
        channel = _get_json(bot_token, f"/channels/{channel_id}")
        guild_id = channel.get("guild_id")
        if guild_id:
            active = _get_json(bot_token, f"/guilds/{guild_id}/threads/active")
            for thread in active.get("threads") or []:
                if str(thread.get("parent_id")) == str(channel_id):
                    thread_ids.append(str(thread["id"]))
    except requests.HTTPError as exc:
        logger.debug("Active thread lookup failed for %s: %s", channel_id, exc)

    try:
        archived = _get_json(bot_token, f"/channels/{channel_id}/threads/archived/public",
                             {"limit": 25})
        for thread in archived.get("threads") or []:
            thread_ids.append(str(thread["id"]))
    except requests.HTTPError as exc:
        logger.debug("Archived thread lookup failed for %s: %s", channel_id, exc)

    # Newest threads first, capped so one busy channel can't eat the run
    thread_ids = list(dict.fromkeys(thread_ids))
    thread_ids.sort(key=_snowflake_ms, reverse=True)
    for thread_id in thread_ids[:max_threads]:
        try:
            messages.extend(_get_json(bot_token, f"/channels/{thread_id}/messages", {"limit": 50}))
        except requests.HTTPError as exc:
            logger.debug("Thread %s read failed: %s", thread_id, exc)

    unique = {m["id"]: m for m in messages if m.get("id")}
    return list(unique.values())


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


def fetch_top_roast(bot_token, channel_ids, since_ms, vote_emoji="\U0001F525", min_votes=1):
    """Return the most-voted roast posted since since_ms across the given
    channel(s) — including their threads — or None.

    With min_votes <= 1, an unvoted submission still qualifies (newest
    wins), so a fresh roast nobody reacted to isn't silently dropped.
    With min_votes > 1, only genuinely voted roasts win.
    """
    if isinstance(channel_ids, (str, int)):
        channel_ids = [channel_ids]

    messages = []
    for channel_id in channel_ids:
        channel_id = str(channel_id).strip()
        if not channel_id:
            continue
        try:
            messages.extend(_collect_messages(bot_token, channel_id))
        except requests.RequestException as exc:
            logger.warning("Roast channel %s read failed: %s", channel_id, exc)

    candidates = []
    for message in messages:
        content = (message.get("content") or "").strip()
        if not content:
            continue
        if (message.get("author") or {}).get("bot"):
            continue
        if _snowflake_ms(message["id"]) < since_ms:
            continue
        candidates.append(message)

    logger.info("Roast scan: %s message(s) found across %s channel(s), %s human post(s) this week",
                len(messages), len(channel_ids), len(candidates))

    qualified = [m for m in candidates if _vote_count(m, vote_emoji) >= min_votes]
    if not qualified and min_votes <= 1:
        qualified = candidates
    if not qualified:
        return None

    best = max(qualified, key=lambda m: (_vote_count(m, vote_emoji), _snowflake_ms(m["id"])))
    best_votes = _vote_count(best, vote_emoji)

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

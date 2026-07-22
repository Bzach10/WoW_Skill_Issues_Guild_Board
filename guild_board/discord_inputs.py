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
    empty_recent = 0
    for message in messages:
        if (message.get("author") or {}).get("bot"):
            continue
        if _snowflake_ms(message["id"]) < since_ms:
            continue
        content = (message.get("content") or "").strip()
        if not content:
            empty_recent += 1
            continue
        candidates.append(message)

    logger.info("Roast scan: %s message(s) found across %s channel(s), %s human post(s) this week",
                len(messages), len(channel_ids), len(candidates))
    if empty_recent and not candidates:
        logger.warning(
            "%s recent human message(s) came back with EMPTY content. Discord strips message "
            "text unless the bot's 'Message Content Intent' is enabled — flip it on at "
            "discord.com/developers -> your app -> Bot -> Privileged Gateway Intents.",
            empty_recent)

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


# ---------------------------------------------------------------------------
# Guild Pulse — a living feed of guild-public channel highlights for the
# website (chat highlights, memes, banter, notable reactions).
#
# PRIVACY MODEL (read this before touching anything here):
#   1. ALLOWLIST ONLY. Only channels explicitly listed in config
#      (discord_inputs.pulse_channels) are ever read. DMs and private
#      channels are never in that list, and the bot physically cannot read a
#      channel it has not been granted View + Read Message History on
#      (Discord returns 403). There is no "read the whole server" path here.
#   2. PER-MESSAGE OPT-OUT. Anyone can drop a message from the feed by
#      reacting with the exclude emoji (🙈 by default) or putting the opt-out
#      marker text ("[nofeed]" by default) anywhere in it. No mod action needed.
#   3. CONTENT BLOCKLIST. A configurable list of substrings drops any
#      message that matches, for standing exclusions.
#   4. Bot messages are skipped. Author identity is exposed as a DISPLAY
#      NAME only — never the numeric user id or discriminator.
# ---------------------------------------------------------------------------

DEFAULT_EXCLUDE_EMOJI = "\U0001F648"  # 🙈 see-no-evil
DEFAULT_OPT_OUT_MARKER = "[nofeed]"
_MENTION_RE = re.compile(r"<@!?(\d+)>")
_CUSTOM_EMOJI_RE = re.compile(r"<a?(:\w+:)\d+>")
_SNIPPET_MAX = 280


def _message_timestamp_iso(message):
    """Prefer Discord's own ISO timestamp (UTC); fall back to the snowflake.
    Never returns local server time — everything here is UTC."""
    ts = message.get("timestamp")
    if ts:
        return ts
    mid = message.get("id")
    if mid:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(_snowflake_ms(mid) / 1000,
                                      tz=timezone.utc).isoformat()
    return None


def _resolve_mentions(content, message):
    """Replace raw <@id> markup with @DisplayName using the message's own
    mention list, and flatten custom-emoji markup to :name:. Keeps the feed
    readable without exposing numeric ids."""
    names = {}
    for m in message.get("mentions") or []:
        names[str(m.get("id"))] = m.get("global_name") or m.get("username") or "someone"

    def _sub(match):
        return "@" + names.get(match.group(1), "someone")

    content = _MENTION_RE.sub(_sub, content)
    content = _CUSTOM_EMOJI_RE.sub(r"\1", content)
    return content.strip()


def _snippet(message):
    """A clean, length-capped text snippet with mentions resolved."""
    content = (message.get("content") or "").strip()
    if not content:
        return ""
    content = _resolve_mentions(content, message)
    if len(content) > _SNIPPET_MAX:
        content = content[:_SNIPPET_MAX].rstrip() + "…"
    return content


def _message_reactions(message, top=5):
    """[{emoji, count}] sorted by count desc. Unicode emoji come through as
    the character; custom guild emoji as :name:."""
    out = []
    for r in message.get("reactions") or []:
        emoji = r.get("emoji") or {}
        name = emoji.get("name")
        if not name:
            continue
        # Custom emoji have an id; present them as :name: rather than raw.
        display = f":{name}:" if emoji.get("id") else name
        out.append({"emoji": display, "count": int(r.get("count") or 0)})
    out.sort(key=lambda x: x["count"], reverse=True)
    return out[:top]


def _message_media(message):
    """Public media on a message: uploaded attachments plus embedded
    images/gifs/videos (memes channel). Returns [{url, content_type,
    width, height, is_image}]. Discord CDN urls are public but may be
    signed/expiring, so the feed is meant to be refreshed regularly."""
    media = []
    for att in message.get("attachments") or []:
        ctype = att.get("content_type") or ""
        media.append({
            "url": att.get("url"),
            "content_type": ctype,
            "width": att.get("width"),
            "height": att.get("height"),
            "is_image": ctype.startswith("image/"),
            "filename": att.get("filename"),
        })
    for emb in message.get("embeds") or []:
        img = emb.get("image") or emb.get("thumbnail") or {}
        vid = emb.get("video") or {}
        url = img.get("url") or vid.get("url")
        if url:
            media.append({
                "url": url,
                "content_type": "video" if vid.get("url") else "image",
                "width": (img or vid).get("width"),
                "height": (img or vid).get("height"),
                "is_image": not vid.get("url"),
                "filename": None,
            })
    return media


def _is_excluded(message, exclude_emoji, opt_out_marker, blocklist):
    """Apply the per-message privacy filters. Returns True to DROP."""
    # Opt-out reaction.
    for r in message.get("reactions") or []:
        if (r.get("emoji") or {}).get("name") == exclude_emoji:
            return True
    content = (message.get("content") or "")
    lower = content.lower()
    # Opt-out marker anywhere in the text.
    if opt_out_marker and opt_out_marker.lower() in lower:
        return True
    # Standing content blocklist.
    for term in blocklist or []:
        if term and term.lower() in lower:
            return True
    return False


def fetch_channel_pulse(bot_token, channel, since_ms, per_channel_limit=20,
                        exclude_emoji=DEFAULT_EXCLUDE_EMOJI,
                        opt_out_marker=DEFAULT_OPT_OUT_MARKER, blocklist=None):
    """Pulse items from one configured channel (+ its threads).

    channel: {"id": str, "label": str, "kind": str} — label is the human
    channel name for the feed, kind is a category the UI can group by
    (e.g. "chat", "memes", "banter", "gambling").
    """
    channel_id = str(channel.get("id", "")).strip()
    if not channel_id:
        return []
    label = channel.get("label") or channel_id
    kind = channel.get("kind") or "chat"

    try:
        messages = _collect_messages(bot_token, channel_id)
    except requests.RequestException as exc:
        logger.warning("Pulse channel %s (%s) read failed: %s", label, channel_id, exc)
        return []

    items = []
    for message in messages:
        if (message.get("author") or {}).get("bot"):
            continue
        if _snowflake_ms(message["id"]) < since_ms:
            continue
        if _is_excluded(message, exclude_emoji, opt_out_marker, blocklist):
            continue
        snippet = _snippet(message)
        media = _message_media(message)
        # Nothing to show if there's neither text nor media.
        if not snippet and not media:
            continue
        items.append({
            "author": _author_name(message),
            "snippet": snippet,
            "channel": label,
            "kind": kind,
            "timestamp": _message_timestamp_iso(message),
            "reactions": _message_reactions(message),
            "media": media,
            "has_media": bool(media),
        })
    items.sort(key=lambda it: it["timestamp"] or "", reverse=True)
    return items[:per_channel_limit]


def fetch_guild_pulse(bot_token, channels, since_ms, per_channel_limit=20,
                      exclude_emoji=DEFAULT_EXCLUDE_EMOJI,
                      opt_out_marker=DEFAULT_OPT_OUT_MARKER, blocklist=None):
    """The living feed: pulse items across every configured (allowlisted)
    guild-public channel, newest first.

    channels: list of {"id", "label", "kind"} — the ONLY channels read.
    Returns a flat list of items (see fetch_channel_pulse for the shape).
    """
    all_items = []
    for channel in channels or []:
        all_items.extend(fetch_channel_pulse(
            bot_token, channel, since_ms, per_channel_limit=per_channel_limit,
            exclude_emoji=exclude_emoji, opt_out_marker=opt_out_marker,
            blocklist=blocklist))
    all_items.sort(key=lambda it: it["timestamp"] or "", reverse=True)
    return all_items


def fetch_latest_announcement(bot_token, channel_id):
    """Return the newest human-authored message in the announcement channel."""
    messages = _get_messages(bot_token, channel_id, limit=10)
    empty_human = 0
    for message in messages:  # Discord returns newest first
        if (message.get("author") or {}).get("bot"):
            continue
        content = (message.get("content") or "").strip()
        if content:
            return {"text": content, "author": _author_name(message)}
        empty_human += 1
    if empty_human:
        logger.warning(
            "Announcement channel has %s human message(s) with EMPTY content — enable the "
            "bot's 'Message Content Intent' (Developer Portal -> Bot -> Privileged Gateway Intents).",
            empty_human)
    return None

"""Tests for the Guild Pulse Discord feed (discord_inputs) and its layer-6
producer (web_data.build_guild_pulse).

No network — _collect_messages is stubbed. The privacy filters are the most
important thing here: a message must never reach the feed if it was opted
out, blocklisted, from a bot, or outside the window, and the output must
never carry a numeric user id.
"""

from datetime import datetime, timezone

from guild_board import discord_inputs as di
from guild_board import web_data

# A snowflake for "now-ish" so the since-window includes it.
NOW_MS = int(datetime(2026, 7, 20, tzinfo=timezone.utc).timestamp() * 1000)
SINCE_MS = int(datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp() * 1000)
OLD_MS = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp() * 1000)


def _snowflake(ms):
    return str((ms - di.DISCORD_EPOCH_MS) << 22)


def _msg(content="hi", ms=NOW_MS, author="Bravo", bot=False, reactions=None,
         attachments=None, embeds=None, mentions=None, ts=None):
    return {
        "id": _snowflake(ms),
        "content": content,
        "author": {"global_name": author, "username": author.lower(),
                   "id": "999", "bot": bot},
        "timestamp": ts or datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(),
        "reactions": reactions or [],
        "attachments": attachments or [],
        "embeds": embeds or [],
        "mentions": mentions or [],
    }


CHANNEL = {"id": "555", "label": "memes", "kind": "memes"}


def _run(messages, monkeypatch, **kw):
    monkeypatch.setattr(di, "_collect_messages", lambda tok, cid, **k: messages)
    return di.fetch_channel_pulse("tok", CHANNEL, SINCE_MS, **kw)


# --- privacy filters (the important part)

def test_bot_messages_are_dropped(monkeypatch):
    out = _run([_msg("beep", author="Board Bot", bot=True)], monkeypatch)
    assert out == []


def test_messages_before_the_window_are_dropped(monkeypatch):
    out = _run([_msg("old news", ms=OLD_MS)], monkeypatch)
    assert out == []


def test_exclude_emoji_reaction_drops_message(monkeypatch):
    m = _msg("secret plans", reactions=[{"emoji": {"name": di.DEFAULT_EXCLUDE_EMOJI},
                                         "count": 1}])
    assert _run([m], monkeypatch) == []


def test_opt_out_marker_drops_message(monkeypatch):
    assert _run([_msg("don't post this [nofeed] thanks")], monkeypatch) == []


def test_blocklist_substring_drops_message(monkeypatch):
    out = _run([_msg("this has a badword in it")], monkeypatch,
               blocklist=["badword"])
    assert out == []


def test_output_never_contains_a_user_id(monkeypatch):
    m = _msg("hey <@999> nice one", mentions=[{"id": "999", "global_name": "Zeb"}])
    out = _run([m], monkeypatch)
    assert out
    blob = repr(out[0])
    assert "999" not in blob            # numeric id never leaks
    assert out[0]["snippet"] == "hey @Zeb nice one"   # resolved to display name


def test_only_configured_channels_are_read(monkeypatch):
    """fetch_guild_pulse must read exactly the channels it is given — there
    is no path that discovers other channels."""
    seen = []

    def fake_collect(tok, cid, **k):
        seen.append(cid)
        return [_msg("hi from " + cid)]

    monkeypatch.setattr(di, "_collect_messages", fake_collect)
    di.fetch_guild_pulse("tok", [{"id": "111", "label": "a", "kind": "chat"},
                                 {"id": "222", "label": "b", "kind": "memes"}],
                         SINCE_MS)
    assert sorted(seen) == ["111", "222"]


# --- content extraction

def test_reactions_are_counted_and_sorted(monkeypatch):
    m = _msg("lol", reactions=[{"emoji": {"name": "😭"}, "count": 3},
                               {"emoji": {"name": "🔥"}, "count": 9},
                               {"emoji": {"name": "kekw", "id": "42"}, "count": 5}])
    out = _run([m], monkeypatch)[0]
    assert out["reactions"][0] == {"emoji": "🔥", "count": 9}       # highest first
    assert {"emoji": ":kekw:", "count": 5} in out["reactions"]     # custom -> :name:


def test_image_attachment_is_captured_as_media(monkeypatch):
    m = _msg("", attachments=[{"url": "https://cdn/x.png", "content_type": "image/png",
                               "width": 800, "height": 600, "filename": "x.png"}])
    out = _run([m], monkeypatch)[0]
    assert out["has_media"] is True
    assert out["media"][0]["is_image"] is True
    assert out["media"][0]["url"] == "https://cdn/x.png"


def test_embedded_gif_is_captured(monkeypatch):
    m = _msg("check this", embeds=[{"video": {"url": "https://tenor/x.mp4",
                                              "width": 480, "height": 270}}])
    out = _run([m], monkeypatch)[0]
    assert out["media"][0]["is_image"] is False


def test_media_only_message_is_kept(monkeypatch):
    """A meme with no text but an image must still appear."""
    m = _msg("", attachments=[{"url": "https://cdn/m.png", "content_type": "image/png"}])
    assert len(_run([m], monkeypatch)) == 1


def test_text_and_media_less_message_is_dropped(monkeypatch):
    assert _run([_msg("")], monkeypatch) == []


def test_snippet_is_truncated(monkeypatch):
    out = _run([_msg("x" * 400)], monkeypatch)[0]
    assert len(out["snippet"]) <= di._SNIPPET_MAX + 1
    assert out["snippet"].endswith("…")


def test_items_sorted_newest_first(monkeypatch):
    a = _msg("older", ms=int(datetime(2026, 7, 10, tzinfo=timezone.utc).timestamp() * 1000))
    b = _msg("newer", ms=int(datetime(2026, 7, 18, tzinfo=timezone.utc).timestamp() * 1000))
    out = _run([a, b], monkeypatch)
    assert [i["snippet"] for i in out] == ["newer", "older"]


# --- layer 6 producer

def test_build_guild_pulse_degrades_without_items():
    p = web_data.build_guild_pulse(None)
    assert p["available"] is False
    assert p["status"] == "pending_discord_refresh"
    assert p["items"] == []


def test_build_guild_pulse_packages_items_with_kind_counts():
    items = [{"kind": "memes", "author": "A", "snippet": "x"},
             {"kind": "memes", "author": "B", "snippet": "y"},
             {"kind": "chat", "author": "C", "snippet": "z"}]
    p = web_data.build_guild_pulse(items)
    assert p["available"] is True
    assert p["item_count"] == 3
    assert p["by_kind"] == {"memes": 2, "chat": 1}


def test_build_site_data_includes_pulse_layer():
    site = web_data.build_site_data(pulse_items=[{"kind": "chat", "author": "A",
                                                 "snippet": "hi"}])
    assert site["guild_pulse"]["available"] is True
    assert site["guild_pulse"]["item_count"] == 1

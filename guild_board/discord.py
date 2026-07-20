import json
import logging
import os
import time

import requests

from guild_board.wcl import wcl_guild_url

logger = logging.getLogger(__name__)


def post_to_discord(webhook_url, embed, content=None, image_path=None, cfg=None,
                    extra_image_paths=None):
    """Post a Discord embed with an optional image attachment.

    extra_image_paths (e.g. the phone-readable companion board) ride along
    as additional attachments on the same message.

    Link buttons ride along when cfg provides guild info. Channel webhooks
    (non-application-owned) only accept link buttons when the request sets
    the ``with_components=true`` query parameter; if Discord still rejects
    the payload, retry once without the buttons so the board always posts.
    """
    components = _build_link_buttons(cfg) if cfg else None
    payload = {"embeds": [embed]}
    if content:
        payload["content"] = content
    if components:
        payload["components"] = components

    try:
        return _execute_webhook(webhook_url, payload, image_path, extra_image_paths)
    except requests.HTTPError as exc:
        resp = exc.response
        status = resp.status_code if resp is not None else "?"
        body = (resp.text or "")[:500] if resp is not None else ""
        if components and resp is not None and 400 <= resp.status_code < 500:
            logger.warning(
                "Discord rejected the post with link buttons (HTTP %s: %s); retrying without them.",
                status, body)
            payload.pop("components", None)
            return _execute_webhook(webhook_url, payload, image_path, extra_image_paths)
        logger.error("Discord webhook post failed (HTTP %s): %s", status, body)
        raise


def _mime(path):
    return "image/gif" if path.lower().endswith(".gif") else "image/png"


def _execute_webhook(webhook_url, payload, image_path=None, extra_image_paths=None,
                     _retried=False):
    url = webhook_url
    if payload.get("components"):
        sep = "&" if "?" in webhook_url else "?"
        url = f"{webhook_url}{sep}with_components=true"

    paths = [p for p in ([image_path] + list(extra_image_paths or []))
             if p and os.path.exists(p)]
    if paths:
        handles = []
        try:
            files = {}
            for i, p in enumerate(paths):
                f = open(p, "rb")
                handles.append(f)
                files[f"files[{i}]"] = (os.path.basename(p), f, _mime(p))
            data = {"payload_json": json.dumps(payload)}
            resp = requests.post(url, data=data, files=files, timeout=30)
        finally:
            for f in handles:
                f.close()
    else:
        resp = requests.post(url, json=payload, timeout=30)

    if resp.status_code == 429 and not _retried:
        retry_after = 2.0
        try:
            retry_after = float(resp.json().get("retry_after", retry_after))
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
        logger.warning("Discord rate limited the webhook; retrying in %.1fs", retry_after)
        time.sleep(min(retry_after, 10))
        return _execute_webhook(webhook_url, payload, image_path, extra_image_paths,
                                _retried=True)

    resp.raise_for_status()
    return resp


def _build_link_buttons(cfg):
    """Build a Discord action row of link buttons for the guild."""
    if not cfg:
        return None
    guild = cfg.get("guild", {})
    name = guild.get("name")
    realm = guild.get("realm_slug")
    region = guild.get("region")
    if not (name and realm and region):
        return None

    buttons = [
        {
            "type": 2,
            "style": 5,
            "label": "Guild Logs",
            "url": wcl_guild_url(name, realm, region),
        }
    ]

    roast_form = cfg.get("roast_form_url")
    if roast_form:
        buttons.append({
            "type": 2,
            "style": 5,
            "label": "Submit Roast",
            "url": roast_form,
        })

    return [{"type": 1, "components": buttons}]

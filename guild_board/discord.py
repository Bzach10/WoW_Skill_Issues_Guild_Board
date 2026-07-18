import json
import logging
import os
import time

import requests

from guild_board.wcl import wcl_guild_url

logger = logging.getLogger(__name__)


def post_to_discord(webhook_url, embed, content=None, image_path=None, cfg=None):
    """Post a Discord embed with an optional image attachment.

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
        return _execute_webhook(webhook_url, payload, image_path)
    except requests.HTTPError as exc:
        resp = exc.response
        status = resp.status_code if resp is not None else "?"
        body = (resp.text or "")[:500] if resp is not None else ""
        if components and resp is not None and 400 <= resp.status_code < 500:
            logger.warning(
                "Discord rejected the post with link buttons (HTTP %s: %s); retrying without them.",
                status, body)
            payload.pop("components", None)
            return _execute_webhook(webhook_url, payload, image_path)
        logger.error("Discord webhook post failed (HTTP %s): %s", status, body)
        raise


def _execute_webhook(webhook_url, payload, image_path=None, _retried=False):
    url = webhook_url
    if payload.get("components"):
        sep = "&" if "?" in webhook_url else "?"
        url = f"{webhook_url}{sep}with_components=true"

    if image_path and os.path.exists(image_path):
        with open(image_path, "rb") as f:
            files = {"file": (os.path.basename(image_path), f, "image/png")}
            data = {"payload_json": json.dumps(payload)}
            resp = requests.post(url, data=data, files=files, timeout=30)
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
        return _execute_webhook(webhook_url, payload, image_path, _retried=True)

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

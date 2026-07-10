import json
import logging
import os

import requests

from guild_board.wcl import wcl_guild_url

logger = logging.getLogger(__name__)


def post_to_discord(webhook_url, embed, content=None, image_path=None, cfg=None):
    """Post a Discord embed with an optional image attachment."""
    payload = {
        "embeds": [embed],
        "components": _build_link_buttons(cfg) if cfg else None,
    }
    if content:
        payload["content"] = content
    if payload["components"] is None:
        del payload["components"]

    if image_path and os.path.exists(image_path):
        with open(image_path, "rb") as f:
            files = {"file": (os.path.basename(image_path), f, "image/png")}
            data = {"payload_json": json.dumps(payload)}
            resp = requests.post(webhook_url, data=data, files=files, timeout=30)
    else:
        resp = requests.post(webhook_url, json=payload, timeout=30)
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

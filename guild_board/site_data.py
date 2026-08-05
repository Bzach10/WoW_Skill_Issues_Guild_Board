"""Consumer for the backend's web-data contract (WEB_DATA_CONTRACT.md).

The backend emits its JSON layers as
`web_data/<layer>.json`, with a committed `samples/<layer>.sample.json`
for developing against populated states before a live run.

This is the front end's read side. It is deliberately forgiving: a layer
that is absent, malformed, or a schema version we don't understand
returns None, and every view degrades to its own empty state rather than
breaking the page.

Resolution order for a layer, first hit wins:
  1. web_data/<layer>.json      — a real backend run
  2. samples/<layer>.sample.json — the committed sample bundle
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
LIVE_DIR = Path("web_data")
SAMPLE_DIR = Path("samples")

LAYERS = ("recap_ribbon", "records_leaderboard", "weekly_board",
          "guild_achievements", "island_completion", "transmog_changes",
          "guild_pulse", "competition", "parses")


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def layer(name, live_dir=LIVE_DIR, sample_dir=SAMPLE_DIR):
    """One data layer, from a live run if present else the sample, or None.

    A payload whose `schema_version` we don't understand is refused rather
    than mis-parsed — the contract says to check it before parsing.
    """
    if name not in LAYERS:
        raise ValueError(f"unknown web-data layer {name!r}")
    for candidate in (Path(live_dir) / f"{name}.json",
                      Path(sample_dir) / f"{name}.sample.json"):
        data = _read(candidate)
        if data is None:
            continue
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            logger.info("Ignoring %s: schema_version %r != %d.",
                        candidate, version, SCHEMA_VERSION)
            continue
        data["_from_sample"] = bool(data.get("_sample")) or candidate.match(
            "*.sample.json")
        logger.info("web-data %s from %s%s", name, candidate,
                    " (sample)" if data["_from_sample"] else "")
        return data
    return None


def bundle(live_dir=LIVE_DIR, sample_dir=SAMPLE_DIR):
    """Every available layer, keyed by name; missing ones simply absent."""
    out = {}
    for name in LAYERS:
        got = layer(name, live_dir, sample_dir)
        if got is not None:
            out[name] = got
    return out

"""Wait until the deployed website reports the current producer bundle.

The consumer should publish a small JSON health document containing either
``source_generated_at`` or ``generated_at``. This turns a Cloudflare deploy
hook response into an end-to-end freshness assertion instead of assuming a
successful trigger means fresh data reached the site.
"""

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime


def _timestamp(payload):
    if not isinstance(payload, dict):
        return None
    value = payload.get("source_generated_at") or payload.get("generated_at")
    if value:
        return value
    source = payload.get("source") or payload.get("site_data") or {}
    return source.get("generated_at") if isinstance(source, dict) else None


def _parse(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def is_fresh(live_payload, expected_payload):
    live = _parse(_timestamp(live_payload))
    expected = _parse(_timestamp(expected_payload))
    return bool(live and expected and live >= expected)


def wait_for_fresh(url, expected, timeout=900, interval=15):
    deadline = time.monotonic() + timeout
    last = "no response"
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "guild-board-freshness-check/1"})
            with urllib.request.urlopen(req, timeout=30) as response:
                live = json.load(response)
            last = f"live timestamp={_timestamp(live)!r}"
            if is_fresh(live, expected):
                print(f"Website is fresh: {last}")
                return True
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last = str(exc)
        print(f"Website not fresh yet ({last}); retrying...")
        time.sleep(interval)
    print(f"Website freshness check timed out: {last}")
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--expected", default="web_data_public/site_data.json")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--interval", type=int, default=15)
    args = parser.parse_args(argv)
    with open(args.expected, encoding="utf-8") as source:
        expected = json.load(source)
    return 0 if wait_for_fresh(
        args.url, expected, timeout=args.timeout, interval=args.interval) else 1


if __name__ == "__main__":
    raise SystemExit(main())

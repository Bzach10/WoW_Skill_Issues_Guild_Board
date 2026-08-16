"""Wait until the website serves the exact producer ``site_data.json``."""

import argparse
import hashlib
import hmac
import time
import urllib.error
import urllib.parse
import urllib.request

MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Health URLs are fixed deployment endpoints, never redirectors."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def is_fresh(live_bytes, expected_bytes):
    return hmac.compare_digest(_digest(live_bytes), _digest(expected_bytes))


def _validate_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("website data URL must be an absolute HTTPS URL")


def _fetch(opener, url, timeout):
    req = urllib.request.Request(
        url, headers={"User-Agent": "guild-board-freshness-check/1"})
    with opener.open(req, timeout=timeout) as response:
        if urllib.parse.urlsplit(response.geturl()).hostname != (
                urllib.parse.urlsplit(url).hostname):
            raise ValueError("website data URL changed host")
        data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("website data response exceeds 8 MiB")
    return data


def wait_for_fresh(url, expected_bytes, timeout=900, interval=15):
    _validate_url(url)
    opener = urllib.request.build_opener(NoRedirect)
    deadline = time.monotonic() + timeout
    last = "no response"
    while time.monotonic() < deadline:
        try:
            remaining = max(deadline - time.monotonic(), 0.1)
            live = _fetch(opener, url, timeout=min(30, remaining))
            last = f"live sha256={_digest(live)}"
            if is_fresh(live, expected_bytes):
                print(f"Website serves the exact producer bundle: {last}")
                return True
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last = str(exc).replace("\r", " ").replace("\n", " ")[:500]
        print(f"Website not fresh yet ({last}); retrying...")
        time.sleep(min(interval, max(deadline - time.monotonic(), 0)))
    print(f"Website freshness check timed out: {last}")
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--expected", default="web_data_public/site_data.json")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--interval", type=int, default=15)
    args = parser.parse_args(argv)
    with open(args.expected, "rb") as source:
        expected = source.read()
    return 0 if wait_for_fresh(
        args.url, expected, timeout=args.timeout, interval=args.interval) else 1


if __name__ == "__main__":
    raise SystemExit(main())

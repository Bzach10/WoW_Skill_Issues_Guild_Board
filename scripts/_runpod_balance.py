#!/usr/bin/env python3
"""Live RunPod account balance, via GraphQL (NOT the /v2 inference host).

The inference calls in runpod_edit.py / _run_full_roster.py hit
api.runpod.ai/v2/<model>/runsync. Account balance lives on a different
host+API entirely: api.runpod.io/graphql, authenticated via ?api_key=
(a Bearer header 403s here), and it 404s/1010s without a normal
browser-looking User-Agent.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_api_key():
    import os
    key = os.environ.get("RUNPOD_API_KEY")
    if key:
        return key
    for line in (REPO_ROOT / ".env").read_text().splitlines():
        if line.startswith("RUNPOD_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("RUNPOD_API_KEY not found")


def get_balance():
    key = load_api_key()
    query = {"query": "query Me { myself { id clientBalance } }"}
    url = "https://api.runpod.io/graphql?api_key=" + urllib.parse.quote(key)
    req = urllib.request.Request(
        url,
        data=json.dumps(query).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["data"]["myself"]["clientBalance"]


if __name__ == "__main__":
    print(f"{get_balance():.4f}")

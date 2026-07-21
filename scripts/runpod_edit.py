#!/usr/bin/env python3
"""Thin client for RunPod public image-edit endpoints (runsync).

Usage:
    python scripts/runpod_edit.py <model_key> <out_path> --prompt "..." \
        --image path1.png [--image path2.png ...] [--extra k=v ...]

Appends every call's cost to cast/_rnd_img2img/model_bakeoff/spend_log.json
so total spend against the $20 budget stays visible.
"""
import argparse
import base64
import json
import mimetypes
import os
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEND_LOG = REPO_ROOT / "cast" / "_rnd_img2img" / "model_bakeoff" / "spend_log.json"

MODELS = {
    "nano-banana-edit": {
        "slug": "nano-banana-edit",
        "images_field": "images",
        "max_images": 4,
    },
    "nano-banana-pro-edit": {
        "slug": "nano-banana-pro-edit",
        "images_field": "images",
        "max_images": 14,
    },
    "seedream-4-edit": {
        "slug": "seedream-v4-edit",
        "images_field": "images",
        "max_images": None,
    },
    "qwen-image-edit-2511": {
        "slug": "qwen-image-edit-2511",
        "images_field": "images",
        "max_images": 3,
    },
    "qwen-image-edit-2511-lora": {
        "slug": "qwen-image-edit-2511-lora",
        "images_field": "images",
        "max_images": 3,
    },
    "flux-kontext-dev": {
        "slug": "black-forest-labs-flux-1-kontext-dev",
        "images_field": "image",  # singular, one image only
        "max_images": 1,
    },
}


def load_api_key():
    key = os.environ.get("RUNPOD_API_KEY")
    if key:
        return key
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("RUNPOD_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("RUNPOD_API_KEY not found in env or .env")


def to_data_uri(path):
    mime, _ = mimetypes.guess_type(path)
    mime = mime or "image/png"
    data = Path(path).read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def log_spend(model_key, cost, out_path, request_id):
    SPEND_LOG.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    if SPEND_LOG.exists():
        entries = json.loads(SPEND_LOG.read_text())
    entries.append({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": model_key,
        "cost_usd": cost,
        "out_path": str(out_path),
        "request_id": request_id,
    })
    SPEND_LOG.write_text(json.dumps(entries, indent=2))
    total = sum(e["cost_usd"] for e in entries)
    print(f"[spend] +${cost:.4f}  running total ${total:.4f} / $20.00")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model_key", choices=sorted(MODELS.keys()))
    ap.add_argument("out_path")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--image", action="append", required=True, dest="images")
    ap.add_argument("--extra", action="append", default=[], help="key=value extra input fields")
    args = ap.parse_args()

    cfg = MODELS[args.model_key]
    if cfg["max_images"] and len(args.images) > cfg["max_images"]:
        raise SystemExit(f"{args.model_key} accepts at most {cfg['max_images']} images")

    api_key = load_api_key()
    data_uris = [to_data_uri(p) for p in args.images]

    payload_input = {"prompt": args.prompt}
    if cfg["images_field"] == "image":
        payload_input["image"] = data_uris[0]
    else:
        payload_input[cfg["images_field"]] = data_uris

    for kv in args.extra:
        k, v = kv.split("=", 1)
        if v.lower() in ("true", "false"):
            v = v.lower() == "true"
        elif v.lstrip("-").isdigit():
            v = int(v)
        payload_input[k] = v

    url = f"https://api.runpod.ai/v2/{cfg['slug']}/runsync"
    body = json.dumps({"input": payload_input}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    print(f"[call] {args.model_key} -> {url}  ({len(body)/1024:.0f} KB payload)")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"[error] HTTP {e.code}: {e.read().decode('utf-8', 'replace')}", file=sys.stderr)
        sys.exit(1)
    dt = time.time() - t0

    status = result.get("status")
    if status != "COMPLETED":
        print(f"[error] status={status} body={json.dumps(result)[:2000]}", file=sys.stderr)
        sys.exit(1)

    output = result.get("output", {})
    image_url = output.get("image_url") or output.get("result")
    cost = output.get("cost", 0.0)
    if not image_url:
        print(f"[error] no image_url in output: {json.dumps(result)[:2000]}", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if image_url.startswith("data:"):
        header, b64 = image_url.split(",", 1)
        out_path.write_bytes(base64.b64decode(b64))
    else:
        urllib.request.urlretrieve(image_url, out_path)

    print(f"[done] {dt:.1f}s -> {out_path}  cost=${cost:.4f}  request_id={result.get('id')}")
    log_spend(args.model_key, cost, out_path, result.get("id"))


if __name__ == "__main__":
    main()

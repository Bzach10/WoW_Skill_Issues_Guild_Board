import json
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "cast" / "_rnd_img2img" / "model_bakeoff"
SPEND_LOG = OUT_DIR / "spend_log.json"

RECOVER = [
    ("nano-banana-edit", "sync-8e2f1072-b81e-48b5-b9b5-8a9a80734782-u1", 0.038,
     "https://image.runpod.ai/nano-banana/edit/a967f775344c4437bcb214a7dc2c9325/result.jpg"),
    ("seedream-4-edit", "sync-3c2e6906-2cb5-4d9f-8f73-ee525e1cf0bb-u2", 0.027,
     "https://image.runpod.ai/seedream-v4/edit/d80b19637d6744598ea2dbe379d1f542/result.jpg"),
    ("qwen-image-edit-2511", "sync-fa9288f2-562f-469a-a389-4b9c71dcffe5-u2", 0.02,
     "https://d2h7xmz5gqybh9.cloudfront.net/output/d6e4cbef-d6f6-4e02-8f79-c38094780ebd-u1_537465e2-76f4-4174-a697-9fede1bf7adf.jpeg"),
    ("qwen-image-edit-2511-lora", "sync-c687b54d-f0fb-4c69-b35f-2a4626269de3-u1", 0.025,
     "https://d2h7xmz5gqybh9.cloudfront.net/output/1cdc5f07-5f24-4c36-8a3c-87b3f44b2d08-u1_fb8db748-a923-4adf-861a-e9a95545d54d.jpeg"),
    ("flux-kontext-dev", "sync-35c969df-b040-487f-ac3e-78d4949d4606-u1", 0.025,
     "https://d2h7xmz5gqybh9.cloudfront.net/output/0e5bfa34-6f6d-4cb5-a317-b9a98373cac4-u1_d5bc1811-7075-4491-a23e-86b01e5d5f48.jpeg"),
    ("nano-banana-pro-edit", "sync-7a925a7e-e8ee-4868-95da-a6994d828a58-u1", 0.14,
     "https://image.runpod.ai/nano-banana-pro-edit/a4a7fa41deca4aa88f94b9b763e4c5bf/result.jpg"),
]

entries = []
if SPEND_LOG.exists():
    entries = json.loads(SPEND_LOG.read_text())

for model_key, req_id, cost, url in RECOVER:
    out_path = OUT_DIR / f"rakdisc_{model_key}.png"
    urllib.request.urlretrieve(url, out_path)
    print(f"[recovered] {model_key} -> {out_path}")
    entries.append({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": model_key,
        "cost_usd": cost,
        "out_path": str(out_path),
        "request_id": req_id,
    })

SPEND_LOG.parent.mkdir(parents=True, exist_ok=True)
SPEND_LOG.write_text(json.dumps(entries, indent=2))
total = sum(e["cost_usd"] for e in entries)
print(f"[spend] running total ${total:.4f} / $20.00")

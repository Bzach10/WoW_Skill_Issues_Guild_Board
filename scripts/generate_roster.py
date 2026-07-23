#!/usr/bin/env python3
"""Batch-restyle the resolved guild roster into the approved bold-ink anime
style via RunPod Nano Banana Pro Edit, at a consistent 3:4 portrait aspect.

Resumable: skips any entry whose output file already exists. Tracks spend
in cast/_rnd_img2img/model_bakeoff/spend_log.json and hard-stops before a
configurable cap, printing the remaining unprocessed entries so the run can
be resumed later.

Usage: python scripts/generate_roster.py [--limit N] [--cap 19.5] [--pilots-first]
"""
import argparse
import base64
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / "cast" / "_renders_cache" / "_resolve_report.json"
STYLE_REF = REPO_ROOT / "cast" / "rakdisc" / "scene1_raidhall_w025.png"
OUT_DIR = REPO_ROOT / "cast" / "crew"
SPEND_LOG = REPO_ROOT / "cast" / "_rnd_img2img" / "model_bakeoff" / "spend_log.json"
MANIFEST_PATH = REPO_ROOT / "cast_manifest.json"

MODEL_SLUG = "nano-banana-pro-edit"
MODEL_KEY = "nano-banana-pro-edit"

PILOTS = {"rakdisc-proudmoore", "floofwall-queldorei", "healyeah-queldorei"}

SCENE_HINTS = {
    "Priest": "in a sunlit stone temple or cathedral, holy light motifs",
    "Paladin": "on a golden battlefield with holy light radiating around them",
    "Warrior": "on a rugged battlefield, dust and debris in the air",
    "Death Knight": "in a frozen unholy battlefield with dark blue-green necrotic energy",
    "Mage": "in an arcane library or crackling with arcane energy",
    "Warlock": "in a fel-green demonic ritual circle with eerie green fire",
    "Shaman": "amid swirling elemental energy (lightning, fire, water, or earth)",
    "Hunter": "in the wilderness with their loyal beast companion nearby",
    "Rogue": "in a shadowy alley or rooftop at dusk, daggers drawn",
    "Druid": "in an enchanted moonlit forest, nature energy swirling",
    "Monk": "in a cozy tavern or serene dojo courtyard",
    "Demon Hunter": "amid fel-scarred ruins, green fel fire around their blades",
    "Evoker": "in a majestic dragon-isles sky with floating stone platforms at sunset",
}

UA = {"User-Agent": "wow-skill-issues-guild-board/character-gen (contact: guild admin)"}


def load_api_key():
    import os
    key = os.environ.get("RUNPOD_API_KEY")
    if key:
        return key
    env_path = REPO_ROOT / ".env"
    for line in env_path.read_text().splitlines():
        if line.startswith("RUNPOD_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("RUNPOD_API_KEY not found")


def to_data_uri(path):
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "image/png"
    b64 = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def build_prompt(entry):
    cls = entry.get("class") or "adventurer"
    race = entry.get("race") or ""
    spec = entry.get("spec") or ""
    hint = SCENE_HINTS.get(cls, "in a fitting class-fantasy scene")
    return (
        f"Image 1 is the exact character/gear reference: a World of Warcraft {race} {cls} "
        f"({spec} spec). Image 2 is the target art style reference — match its exact clean "
        f"bold-ink One Piece / anime art style, linework, and rendering. Redraw the character "
        f"from Image 1 in that exact style, full body portrait, dynamic {cls.lower()}-appropriate "
        f"action pose, {hint}. Preserve their exact gear, weapons, colors, and silhouette "
        f"precisely as shown in Image 1 — do not invent or change armor pieces. Bold clean ink "
        f"outlines, vibrant flat-cel anime shading, expressive anime eyes, dramatic lighting."
    )


def call_nano_banana_pro(prompt, image_paths, aspect_ratio="3:4", resolution="2k"):
    api_key = load_api_key()
    images = [to_data_uri(p) for p in image_paths]
    payload = {
        "input": {
            "prompt": prompt,
            "images": images,
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
        }
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.runpod.ai/v2/{MODEL_SLUG}/runsync",
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if result.get("status") != "COMPLETED":
        raise RuntimeError(f"status={result.get('status')} body={json.dumps(result)[:1500]}")
    output = result.get("output", {})
    url = output.get("image_url") or output.get("result")
    cost = output.get("cost", 0.0)
    if not url:
        raise RuntimeError(f"no image url: {json.dumps(result)[:1500]}")
    return url, cost, result.get("id")


def load_spend_entries():
    if SPEND_LOG.exists():
        return json.loads(SPEND_LOG.read_text(encoding="utf-8"))
    return []


def save_spend_entry(entries, model, cost, out_path, request_id):
    entries.append({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": model,
        "cost_usd": cost,
        "out_path": str(out_path),
        "request_id": request_id,
    })
    SPEND_LOG.parent.mkdir(parents=True, exist_ok=True)
    SPEND_LOG.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def update_manifest(entry_key, char_info, out_path, cost):
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    chars = manifest.setdefault("characters", {})
    node = chars.setdefault(entry_key, {})
    node["name"] = char_info.get("name")
    node["realm"] = char_info.get("realm")
    node["class"] = char_info.get("class")
    node["race"] = char_info.get("race")
    node["spec"] = char_info.get("spec")
    node["anime_render"] = str(out_path.relative_to(REPO_ROOT)).replace("\\", "/")
    node["anime_render_model"] = MODEL_KEY
    node["anime_render_aspect"] = "3:4"
    node["anime_render_cost_usd"] = cost
    node["anime_render_generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--cap", type=float, default=19.5)
    args = ap.parse_args()

    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    resolved = report["resolved"]

    # pilots first, then the rest in original order
    pilots = [r for r in resolved if r["entry"] in PILOTS]
    rest = [r for r in resolved if r["entry"] not in PILOTS]
    queue = pilots + rest

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    spend_entries = load_spend_entries()
    running_total = sum(e["cost_usd"] for e in spend_entries)
    print(f"[start] running total so far: ${running_total:.4f}  cap=${args.cap:.2f}")

    done = 0
    skipped_existing = 0
    failed = []
    processed_batch = []  # for periodic reporting

    for i, entry in enumerate(queue):
        if args.limit and done >= args.limit:
            break
        key = entry["entry"]
        out_path = OUT_DIR / f"{key}.png"
        if out_path.exists():
            skipped_existing += 1
            continue

        projected = running_total + 0.14
        if projected > args.cap:
            print(f"[stop] projected ${projected:.4f} would exceed cap ${args.cap:.2f}. Stopping.")
            remaining = [e["entry"] for e in queue[i:] if not (OUT_DIR / f"{e['entry']}.png").exists()]
            print(f"[stop] {len(remaining)} characters not yet processed: {remaining}")
            break

        render_path = Path(entry["out_path"])
        prompt = build_prompt(entry)
        try:
            url, cost, req_id = call_nano_banana_pro(prompt, [render_path, STYLE_REF])
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as resp:
                out_path.write_bytes(resp.read())
            running_total += cost
            save_spend_entry(spend_entries, MODEL_KEY, cost, out_path, req_id)
            update_manifest(key, entry, out_path, cost)
            done += 1
            processed_batch.append(key)
            print(f"[{i+1}/{len(queue)}] ok    {key}  cost=${cost:.4f}  total=${running_total:.4f}")
        except Exception as e:
            failed.append({"entry": key, "error": str(e)})
            print(f"[{i+1}/{len(queue)}] FAIL  {key}  ({e})")
        time.sleep(0.3)

    print(f"\n[done] generated={done} skipped_existing={skipped_existing} failed={len(failed)}")
    print(f"[done] running total ${running_total:.4f} / $20.00")
    if failed:
        print(f"[done] failed entries: {json.dumps(failed, indent=2)}")
    print(f"[done] this batch: {processed_batch}")


if __name__ == "__main__":
    main()

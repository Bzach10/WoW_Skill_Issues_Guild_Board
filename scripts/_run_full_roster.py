#!/usr/bin/env python3
"""Full-roster Nano Banana Pro generation + rembg cutout + cast_manifest.json.

Resumable and budget-capped. Reuses the 10 characters already generated in
the model-quality comparison (no regeneration, just cutout + manifest).
For everyone else: crop the Blizzard render to 3:4, call nano-banana-pro-edit
with the SAME prompt template used for the comparison pilots, save the full
scene as the profile image, run rembg to produce a transparent cutout for
the animated crew, and record both in cast_manifest.json.

Usage: python scripts/_run_full_roster.py [--cap 19.9]
"""
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
SPEND_LOG = REPO_ROOT / "cast" / "_rnd_img2img" / "model_bakeoff" / "spend_log.json"
MANIFEST_PATH = REPO_ROOT / "cast_manifest.json"
COMPARE_OUT = REPO_ROOT / "cast" / "_rnd_img2img" / "model_bakeoff_v2" / "outputs"
PROGRESS_PATH = REPO_ROOT / "cast" / "_rnd_img2img" / "roster_progress.json"

STYLE = "one_piece"
MODEL_SLUG = "nano-banana-pro-edit"
MODEL_KEY = "nano-banana-pro-edit"

ALREADY_DONE = {
    "rakdisc-proudmoore", "floofwall-queldorei", "healyeah-queldorei",
    "balcmeg-queldorei", "jilk-eldrethalas", "mushabi-anubarak",
    "beroben-emerald-dream", "kathrobbin-zuljin", "yur-whisperwind",
    "flemel-area-52",
}

PROMPT_TEMPLATE = (
    "Restyle this World of Warcraft character transmog render into clean "
    "bold-ink anime art in the style of One Piece: bold black linework, "
    "flat cel shading, vibrant saturated colors, dynamic heroic action "
    "pose. This character is a {race} {klass}. Preserve the character's "
    "exact armor, weapons, colors, and gear details from the reference "
    "image precisely, do not invent new equipment. Keep the character's "
    "race accurate (skin tone, ears, tusks, horns, fur, or other racial "
    "features exactly as shown). Add a fitting class-fantasy background "
    "scene matching their class and spec. Full character visible head to "
    "toe, portrait framing, 3:4 aspect ratio."
)

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


API_KEY = load_api_key()


def to_data_uri(path):
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "image/png"
    b64 = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def bbox_of_content(im, bg_thresh=245):
    gray = im.convert("L")
    px = gray.load()
    w, h = gray.size
    left, top, right, bottom = w, h, 0, 0
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            if px[x, y] < bg_thresh:
                if x < left:
                    left = x
                if x > right:
                    right = x
                if y < top:
                    top = y
                if y > bottom:
                    bottom = y
    if right <= left or bottom <= top:
        return 0, 0, w, h
    return left, top, right, bottom


def crop_3x4(im):
    from PIL import Image
    w, h = im.size
    left, top, right, bottom = bbox_of_content(im)
    cx, cy = (left + right) / 2, (top + bottom) / 2
    content_h = bottom - top
    target_h = min(content_h * 1.24, h)
    target_w = target_h * 3 / 4
    if target_w > w:
        target_w = w
        target_h = target_w * 4 / 3
    x0, x1 = cx - target_w / 2, cx + target_w / 2
    y0, y1 = cy - target_h / 2, cy + target_h / 2
    if x0 < 0:
        x1 -= x0; x0 = 0
    if x1 > w:
        x0 -= (x1 - w); x1 = w
    if y0 < 0:
        y1 -= y0; y0 = 0
    if y1 > h:
        y0 -= (y1 - h); y1 = h
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    return im.crop((int(x0), int(y0), int(x1), int(y1)))


def prep_input(render_path):
    from PIL import Image
    raw = Image.open(render_path)
    if raw.mode in ("RGBA", "LA") or "transparency" in raw.info:
        raw = raw.convert("RGBA")
        white_bg = Image.new("RGB", raw.size, (255, 255, 255))
        white_bg.paste(raw, mask=raw.split()[-1])
        im = white_bg
    else:
        im = raw.convert("RGB")
    return crop_3x4(im)


def call_pro(prompt, cropped_im, attempts=2):
    import io
    buf = io.BytesIO()
    cropped_im.save(buf, format="PNG")
    data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    payload = {
        "input": {
            "prompt": prompt,
            "images": [data_uri],
            "resolution": "2K",
            "aspect_ratio": "3:4",
        }
    }
    body = json.dumps(payload).encode("utf-8")
    last_err = None
    for attempt in range(attempts):
        req = urllib.request.Request(
            f"https://api.runpod.ai/v2/{MODEL_SLUG}/runsync",
            data=body, method="POST",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=170) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            last_err = str(e)
            continue
        if result.get("status") == "COMPLETED":
            output = result.get("output", {})
            url = output.get("image_url") or output.get("result")
            cost = output.get("cost", 0.0)
            if url:
                return url, cost, result.get("id")
            last_err = f"no image url: {json.dumps(result)[:500]}"
        else:
            last_err = f"status={result.get('status')} body={json.dumps(result)[:500]}"
    raise RuntimeError(last_err)


def load_spend_entries():
    if SPEND_LOG.exists():
        return json.loads(SPEND_LOG.read_text(encoding="utf-8"))
    return []


def save_spend_entry(entries, cost, out_path, request_id):
    entries.append({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": MODEL_KEY,
        "cost_usd": cost,
        "out_path": str(out_path),
        "request_id": request_id,
    })
    SPEND_LOG.parent.mkdir(parents=True, exist_ok=True)
    SPEND_LOG.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def load_manifest():
    if MANIFEST_PATH.exists():
        try:
            data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"active_style": STYLE, "styles_available": [STYLE], "characters": {}}


def save_manifest(manifest):
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def update_manifest(manifest, key, entry, profile_rel, board_rel):
    chars = manifest.setdefault("characters", {})
    node = chars.setdefault(key, {})
    node["name"] = entry.get("name")
    node["realm"] = entry.get("realm")
    node["race"] = entry.get("race")
    node["class"] = entry.get("class")
    node["spec"] = entry.get("spec")
    node["render_url"] = entry.get("render_url")
    styles = node.setdefault("styles", {})
    prev_version = (styles.get(STYLE) or {}).get("version", 0)
    styles[STYLE] = {
        "board": board_rel,
        "profile": profile_rel,
        "forms": {},
        "version": prev_version + 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    node.setdefault("history", [])
    save_manifest(manifest)


def cutout(rembg_session, profile_path, board_path):
    from rembg import remove
    from PIL import Image
    with open(profile_path, "rb") as f:
        input_bytes = f.read()
    out_bytes = remove(input_bytes, session=rembg_session)
    board_path.parent.mkdir(parents=True, exist_ok=True)
    board_path.write_bytes(out_bytes)
    # sanity: confirm real transparency, matching the frontend's _is_cutout contract
    with Image.open(board_path) as im:
        if im.mode not in ("RGBA", "LA", "PA"):
            return False, True
        alpha = im.getchannel("A")
        lo, hi = alpha.getextrema()
        if lo >= 250:
            return False, True
        # heuristic: a leftover detached background blob (fire swirl, magic
        # aura not touching the body) tends to push the opaque bbox to
        # fill nearly the whole canvas edge-to-edge. A clean character
        # cutout on our 3:4 portraits normally does not.
        mask = alpha.point(lambda p: 255 if p > 10 else 0)
        bbox = mask.getbbox()
        if not bbox:
            return True, True
        w, h = im.size
        bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
        area_frac = (bw * bh) / (w * h)
        flagged = area_frac > 0.92
        return True, not flagged


def write_progress(done, total, failed, skipped_budget, spend, flagged=None):
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_PATH.write_text(json.dumps({
        "done": done, "total": total, "failed": failed,
        "skipped_budget": skipped_budget, "spend_total": round(spend, 4),
        "flagged_cutouts": flagged or [],
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }, indent=2), encoding="utf-8")


def main():
    cap = 19.9
    if "--cap" in sys.argv:
        cap = float(sys.argv[sys.argv.index("--cap") + 1])

    from rembg import new_session
    rembg_session = new_session("isnet-anime")

    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    resolved = report["resolved"]

    spend_entries = load_spend_entries()
    running_total = sum(e["cost_usd"] for e in spend_entries)
    manifest = load_manifest()

    print(f"[start] baseline spend ${running_total:.4f}  cap=${cap:.2f}", flush=True)

    done, failed, skipped_budget, flagged = 0, [], [], []
    total = len(resolved)

    for i, entry in enumerate(resolved):
        key = entry["entry"]
        char_dir = REPO_ROOT / "cast" / key / STYLE
        profile_path = char_dir / "profile.png"
        board_path = char_dir / "board.png"

        if profile_path.exists() and board_path.exists():
            print(f"[{i+1}/{total}] skip  {key}  (already has profile+board)", flush=True)
            update_manifest(manifest, key, entry,
                             str(profile_path.relative_to(REPO_ROOT)).replace("\\", "/"),
                             str(board_path.relative_to(REPO_ROOT)).replace("\\", "/"))
            done += 1
            continue

        try:
            if key in ALREADY_DONE:
                src = COMPARE_OUT / f"{key}_pro.png"
                if not src.exists():
                    raise RuntimeError(f"expected comparison output missing: {src}")
                char_dir.mkdir(parents=True, exist_ok=True)
                profile_path.write_bytes(src.read_bytes())
                cost = 0.0
                req_id = "reused-from-comparison"
            else:
                projected = running_total + 0.14
                if projected > cap:
                    print(f"[stop] projected ${projected:.4f} would exceed cap ${cap:.2f}", flush=True)
                    remaining = [e["entry"] for e in resolved[i:]
                                 if not (REPO_ROOT / "cast" / e["entry"] / STYLE / "profile.png").exists()]
                    skipped_budget = remaining
                    print(f"[stop] {len(remaining)} characters not processed: {remaining}", flush=True)
                    break

                render_path = Path(entry["out_path"])
                cropped = prep_input(render_path)
                prompt = PROMPT_TEMPLATE.format(race=entry.get("race") or "", klass=entry.get("class") or "adventurer")
                url, cost, req_id = call_pro(prompt, cropped)
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=60) as resp:
                    char_dir.mkdir(parents=True, exist_ok=True)
                    profile_path.write_bytes(resp.read())
                running_total += cost
                save_spend_entry(spend_entries, cost, profile_path, req_id)

            ok, clean = cutout(rembg_session, profile_path, board_path)
            if not clean:
                flagged.append(key)
            update_manifest(manifest, key, entry,
                             str(profile_path.relative_to(REPO_ROOT)).replace("\\", "/"),
                             str(board_path.relative_to(REPO_ROOT)).replace("\\", "/"))
            done += 1
            tag = "reused" if key in ALREADY_DONE else "gen"
            cutout_note = "ok" if ok and clean else ("FLAGGED" if ok else "NOT-TRANSPARENT")
            print(f"[{i+1}/{total}] {tag:6s} {key}  cost=${cost:.4f}  total=${running_total:.4f}  cutout={cutout_note}", flush=True)
        except Exception as e:
            failed.append({"entry": key, "error": str(e)})
            print(f"[{i+1}/{total}] FAIL  {key}  ({e})", flush=True)

        write_progress(done, total, failed, skipped_budget, running_total, flagged)
        time.sleep(0.2)

    print(f"\n[done] generated/reused={done} failed={len(failed)} skipped_budget={len(skipped_budget)} flagged={len(flagged)}", flush=True)
    print(f"[done] running total ${running_total:.4f} / $20.00", flush=True)
    if failed:
        print(f"[done] failed entries: {json.dumps(failed, indent=2)}", flush=True)
    if flagged:
        print(f"[done] flagged cutouts (may need plain-bg variant): {flagged}", flush=True)
    write_progress(done, total, failed, skipped_budget, running_total, flagged)


if __name__ == "__main__":
    main()

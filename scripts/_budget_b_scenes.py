#!/usr/bin/env python3
"""BUDGET B: generate WoW environment scenes (wide/landscape, anime
One-Piece style) for site headers/footers/section backgrounds, then
composite a few clean character cutouts into each.

Checks the LIVE RunPod balance before every generation call and stops at
$9 spent from a fresh baseline recorded at the start of this script,
independent of Budget A's own tracking.
"""
import base64
import io
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _run_full_roster import UA  # noqa: E402
from _runpod_balance import load_api_key  # noqa: E402
from _runpod_balance import get_balance  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SCENES_DIR = REPO_ROOT / "cast" / "_scenes"
LOG_PATH = SCENES_DIR / "budget_b_log.json"
POT_CAP = 9.0

# Characters confirmed clean under the new chroma-key cutout method —
# safe to composite without risking a missing-limb cutout showing up on
# the marketing scenes. Extended as Budget A fixes more.
SAFE_CUTOUTS = [
    "cast/rakdisc-proudmoore/one_piece/board.png",
    "cast/floofwall-queldorei/one_piece/board.png",
    "cast/chohno-stormrage/one_piece/board.png",
    "cast/aiime-bleeding-hollow/one_piece/board.png",
]

SCENE_PROMPT_TEMPLATE = (
    "A wide 16:9 landscape environment illustration in clean bold-ink "
    "anime art style (One Piece): {description} Epic, painterly "
    "environment art — dramatic lighting, vibrant saturated colors, bold "
    "black linework consistent with a cel-shaded shonen anime aesthetic. "
    "NO characters or people in the image — pure environment/architecture/"
    "landscape art. Leave the lower-center third of the frame relatively "
    "open and uncluttered (like an empty stage floor) so characters can "
    "be composited into the scene afterward. Wide cinematic landscape "
    "composition, 16:9 aspect ratio."
)

SCENES = [
    ("silvermoon_city", "Silvermoon City",
     "The regal red-and-gold elven capital city of Silvermoon, tall sun-motif "
     "spires and archways, glowing floating crystals drifting above ornate "
     "rooftops, elegant elven architecture with red banners and gold trim, "
     "warm magical light."),
    ("stormwind_city", "Stormwind City",
     "The grand human capital Stormwind City at golden hour: blue-tiled "
     "rooftops, a towering stone cathedral with stained glass, canals "
     "reflecting warm sunset light, stone bridges, banners fluttering."),
    ("orgrimmar", "Orgrimmar",
     "The mighty Horde fortress-city Orgrimmar: red iron walls and spiked "
     "fortifications, massive gates, war banners, dramatic orange dusk sky, "
     "rugged orcish architecture."),
    ("dark_portal", "The Dark Portal",
     "The Dark Portal: a huge ancient stone arch crackling with swirling "
     "fel-green energy in its center, set in the scorched red wasteland of "
     "the Blasted Lands, ominous green sky, cracked earth."),
    ("dalaran", "Dalaran",
     "The violet mage city of Dalaran floating serenely in the clouds under "
     "a starry night sky, glowing arcane purple magic lights, spired "
     "wizard-tower architecture, a shimmering magical shield dome overhead."),
    ("icecrown_citadel", "Icecrown Citadel",
     "Icecrown Citadel: a jagged fortress of black ice and frozen spires "
     "rising from a frozen wasteland, eerie green aurora borealis lighting "
     "the sky, cold blue moonlight, ominous and imposing scale."),
    ("elwynn_forest", "Elwynn Forest",
     "Elwynn Forest: lush rolling green hills and forest, warm sunbeams "
     "breaking through tall trees, a rustic stone bridge over a sparkling "
     "stream, peaceful idyllic daytime lighting."),
    ("mount_hyjal", "Mount Hyjal / World Tree Nordrassil",
     "Mount Hyjal with the colossal World Tree Nordrassil towering at epic "
     "scale in the distance, its massive glowing canopy dwarfing the "
     "mountain ridge, golden-green magical light, sweeping vista."),
    ("ironforge", "Ironforge",
     "The great dwarven halls of Ironforge: a molten forge chamber with "
     "rivers of glowing lava, massive bronze gates and anvils, sparks "
     "flying, warm orange forge-light against dark stone architecture."),
    ("caverns_of_time", "Caverns of Time / Tanaris",
     "A golden desert canyon in Tanaris opening into the Caverns of Time: "
     "a swirling glowing time portal of gold and bronze energy set into "
     "sandstone cliffs, dramatic desert sunset, ancient bronze-dragon "
     "architecture."),
    ("ungoro_crater", "Un'Goro Crater",
     "Un'Goro Crater: a lush prehistoric jungle crater with towering "
     "waterfalls cascading down volcanic cliffs, a dramatic active volcano "
     "in the background, and several large, prominent, dynamic DINOSAURS "
     "(a roaring devilsaur, a herd of duskstriders) as a featured highlight "
     "of the scene, vibrant green jungle colors, mist and warm light."),
]


def load_log():
    if LOG_PATH.exists():
        return json.loads(LOG_PATH.read_text(encoding="utf-8"))
    return {"generated": [], "composited": [], "failed": [], "spend_checkpoints": []}


def save_log(log):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(log, indent=2), encoding="utf-8")


MODEL_SLUG = "nano-banana-pro-edit"


def generate_scene(description, attempts=2):
    """Wide 16:9 scene generation. The edit model still wants a
    reference image, so we feed a blank neutral-gray 16:9 canvas — the
    explicit "no characters, pure environment" prompt gives the model
    full authority to repaint it as a fresh scene rather than treat the
    placeholder as content to preserve.
    """
    from PIL import Image
    placeholder = Image.new("RGB", (1024, 576), (200, 200, 200))
    buf = io.BytesIO()
    placeholder.save(buf, format="PNG")
    data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    prompt = SCENE_PROMPT_TEMPLATE.format(description=description)
    payload = {
        "input": {
            "prompt": prompt,
            "images": [data_uri],
            "resolution": "2K",
            "aspect_ratio": "16:9",
        }
    }
    body = json.dumps(payload).encode("utf-8")
    api_key = load_api_key()
    last_err = None
    for _ in range(attempts):
        req = urllib.request.Request(
            f"https://api.runpod.ai/v2/{MODEL_SLUG}/runsync",
            data=body, method="POST",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
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


def composite_characters(scene_path, out_path, cutout_paths, n=3):
    from PIL import Image
    scene = Image.open(scene_path).convert("RGBA")
    sw, sh = scene.size
    chosen = cutout_paths[:n]
    count = len(chosen)
    if count == 0:
        scene.save(out_path)
        return
    target_h = int(sh * 0.55)
    slot_w = sw // (count + 1)
    for i, cp in enumerate(chosen):
        full_path = REPO_ROOT / cp
        if not full_path.exists():
            continue
        char = Image.open(full_path).convert("RGBA")
        scale = target_h / char.height
        new_w = int(char.width * scale)
        char = char.resize((new_w, target_h), Image.LANCZOS)
        x = slot_w * (i + 1) - new_w // 2
        y = sh - target_h - int(sh * 0.03)
        scene.alpha_composite(char, (x, y))
    scene.convert("RGB").save(out_path)


def main():
    baseline = get_balance()
    print(f"[budget-b] baseline balance ${baseline:.4f}  cap: stop at ${POT_CAP:.2f} spent", flush=True)

    log = load_log()
    done = set(log["generated"])

    for i, (key, label, description) in enumerate(SCENES):
        scene_dir = SCENES_DIR / key
        raw_path = scene_dir / "raw.png"
        composited_path = scene_dir / "composited.png"

        if key in done and raw_path.exists():
            print(f"[{i+1}/{len(SCENES)}] skip  {label} (already generated)", flush=True)
            continue

        balance = get_balance()
        spent = baseline - balance
        if spent >= POT_CAP:
            remaining = [s[1] for s in SCENES[i:] if s[0] not in done]
            print(f"[stop] Budget B spent ${spent:.4f} >= ${POT_CAP:.2f} cap.", flush=True)
            print(f"[stop] {len(remaining)} scenes not generated: {remaining}", flush=True)
            break

        try:
            url, cost, req_id = generate_scene(description)
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as resp:
                scene_dir.mkdir(parents=True, exist_ok=True)
                raw_path.write_bytes(resp.read())

            composite_characters(raw_path, composited_path, SAFE_CUTOUTS, n=3)

            log["generated"].append(key)
            log["composited"].append(key)
            done.add(key)

            new_balance = get_balance()
            spent_now = baseline - new_balance
            log["spend_checkpoints"].append({"key": key, "balance": new_balance, "spent_from_baseline": round(spent_now, 4)})
            save_log(log)
            print(f"[{i+1}/{len(SCENES)}] done  {label}  raw={raw_path}  composited={composited_path}  "
                  f"balance=${new_balance:.4f}  spent=${spent_now:.4f}/{POT_CAP:.2f}", flush=True)
        except Exception as e:
            log["failed"].append(key)
            save_log(log)
            print(f"[{i+1}/{len(SCENES)}] FAIL  {label}  ({e})", flush=True)

        time.sleep(0.3)

    final_balance = get_balance()
    print(f"\n[done] Budget B actual spend: ${baseline - final_balance:.4f} "
          f"(baseline ${baseline:.4f} -> ${final_balance:.4f})", flush=True)
    print(f"[done] generated={len(log['generated'])} failed={len(log['failed'])}", flush=True)


if __name__ == "__main__":
    main()

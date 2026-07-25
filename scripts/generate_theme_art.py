"""Generate the board's themed artwork locally on the guild PC's GPU.

Reads the art direction from assets/art_prompts.yml and renders each
theme's slots through a local ComfyUI server (SDXL on the RTX 4080).
Nothing is uploaded anywhere and no API key exists — the model runs on
this machine.

    # see exactly what WOULD be generated, no GPU needed
    python scripts/generate_theme_art.py --dry-run

    # generate everything (or one theme / one slot)
    python scripts/generate_theme_art.py
    python scripts/generate_theme_art.py --theme emberforge
    python scripts/generate_theme_art.py --theme emberforge --slot header

Output lands in assets/generated/<theme>/<slot>.png, which is exactly
where themes/theme.<theme>.yml points its backgrounds.* keys.

Starting the server (it is not running by default):

    "%LOCALAPPDATA%\\Comfy-Desktop\\ComfyUI-Installs\\ComfytUI\\ComfyUI\\.venv\\Scripts\\python.exe" \\
        -s main.py --port 8199 \\
        --base-directory "%LOCALAPPDATA%\\Comfy-Desktop\\ComfyUI-Shared"

Fails open by design: an unreachable server, a missing checkpoint or a
single bad slot logs a warning and moves on. Art that fails to generate
simply isn't written, and the theme falls back to whatever art is
already committed — the board never breaks because of this script.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC_FILE = ROOT / "assets" / "art_prompts.yml"
OUT_ROOT = ROOT / "assets" / "generated"
DEFAULT_SERVER = "http://127.0.0.1:8199"


def load_spec(path=SPEC_FILE):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _join(text, suffix):
    """Prompt + shared house style, whitespace-normalised."""
    return " ".join(f"{(text or '').strip()}, {(suffix or '').strip()}".split())


def resolve_jobs(spec, only_theme=None, only_slot=None):
    """Flatten the spec into concrete (theme, slot, prompt, size, seed) jobs."""
    style = spec.get("style_suffix", "")
    negative = spec.get("negative_suffix", "")
    sizes = spec.get("sizes") or {}
    jobs = []
    for theme_name, theme in (spec.get("themes") or {}).items():
        if only_theme and theme_name != only_theme:
            continue
        base_seed = int(theme.get("seed", 0))
        for i, (slot, prompt) in enumerate((theme.get("slots") or {}).items()):
            if only_slot and slot != only_slot:
                continue
            width, height = sizes.get(slot, [1024, 1024])
            jobs.append({
                "theme": theme_name,
                "slot": slot,
                "positive": _join(prompt, style),
                "negative": negative.strip(),
                "width": int(width),
                "height": int(height),
                # distinct but reproducible seed per slot
                "seed": base_seed + i,
            })
    return jobs


def build_workflow(job, model):
    """Minimal SDXL text-to-image graph in ComfyUI's API format."""
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": model["checkpoint"]}},
        "2": {"class_type": "CLIPTextEncode",
              "inputs": {"text": job["positive"], "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": job["negative"], "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage",
              "inputs": {"width": job["width"], "height": job["height"], "batch_size": 1}},
        "5": {"class_type": "KSampler",
              "inputs": {"seed": job["seed"], "steps": int(model["steps"]),
                         "cfg": float(model["cfg"]), "sampler_name": model["sampler"],
                         "scheduler": model["scheduler"], "denoise": 1.0,
                         "model": ["1", 0], "positive": ["2", 0],
                         "negative": ["3", 0], "latent_image": ["4", 0]}},
        "6": {"class_type": "VAEDecode",
              "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage",
              "inputs": {"filename_prefix": f"board/{job['theme']}_{job['slot']}",
                         "images": ["6", 0]}},
    }


def _get(server, path, timeout=30):
    with urllib.request.urlopen(f"{server}{path}", timeout=timeout) as r:  # nosec B310 - server scheme pinned to http(s) in main()
        return json.loads(r.read())


def available_checkpoint(server, wanted):
    """The wanted checkpoint if the server has it, else whatever it does
    have (so a renamed model file doesn't stop the run)."""
    try:
        info = _get(server, "/object_info/CheckpointLoaderSimple")
        names = info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
    except Exception as exc:
        print(f"  ! could not list checkpoints ({exc}); trying '{wanted}' as-is")
        return wanted
    if wanted in names:
        return wanted
    if names:
        print(f"  ! checkpoint '{wanted}' not installed; using '{names[0]}'")
        return names[0]
    return wanted


def submit(server, workflow):
    payload = json.dumps({"prompt": workflow}).encode()
    req = urllib.request.Request(f"{server}/prompt", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:  # nosec B310 - server scheme pinned to http(s) in main()
        return json.loads(r.read())["prompt_id"]


def wait_for(server, prompt_id, timeout=600):
    """Poll history until the job reports images; returns their descriptors."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            hist = _get(server, f"/history/{prompt_id}")
        except Exception:
            hist = {}
        entry = hist.get(prompt_id)
        if entry:
            status = (entry.get("status") or {}).get("status_str")
            if status == "error":
                raise RuntimeError("ComfyUI reported an execution error")
            for node in (entry.get("outputs") or {}).values():
                if node.get("images"):
                    return node["images"]
            if entry.get("status", {}).get("completed"):
                raise RuntimeError("job completed but produced no image")
        time.sleep(2)
    raise TimeoutError(f"timed out after {timeout}s")


def fetch_image(server, descriptor):
    query = urllib.parse.urlencode({
        "filename": descriptor["filename"],
        "subfolder": descriptor.get("subfolder", ""),
        "type": descriptor.get("type", "output"),
    })
    with urllib.request.urlopen(f"{server}/view?{query}", timeout=120) as r:  # nosec B310 - server scheme pinned to http(s) in main()
        return r.read()


def run_job(server, job, model):
    out_dir = OUT_ROOT / job["theme"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{job['slot']}.png"
    workflow = build_workflow(job, model)
    prompt_id = submit(server, workflow)
    images = wait_for(server, prompt_id)
    out_path.write_bytes(fetch_image(server, images[0]))
    return out_path


def main():
    ap = argparse.ArgumentParser(description="Generate themed board art via local ComfyUI")
    ap.add_argument("--server", default=DEFAULT_SERVER, help="ComfyUI base URL")
    ap.add_argument("--theme", help="only this theme")
    ap.add_argument("--slot", help="only this slot (header/middle/footer/poster/crest)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the resolved prompts without generating")
    args = ap.parse_args()

    # --server is pasted by hand and then concatenated into every request
    # URL below. Pin it to http(s) so a typo can't turn these into file://
    # reads that get handed straight back to a server.
    if not args.server.startswith(("http://", "https://")):
        print(f"--server must be an http:// or https:// URL, got {args.server!r}")
        return 1

    try:
        spec = load_spec()
    except (OSError, yaml.YAMLError) as exc:
        print(f"Cannot read {SPEC_FILE}: {exc}")
        return 1

    jobs = resolve_jobs(spec, args.theme, args.slot)
    if not jobs:
        print("No jobs matched — check --theme / --slot spelling.")
        return 1
    model = dict(spec.get("model") or {})
    model.setdefault("checkpoint", "sd_xl_base_1.0.safetensors")
    model.setdefault("steps", 32)
    model.setdefault("cfg", 7.0)
    model.setdefault("sampler", "dpmpp_2m")
    model.setdefault("scheduler", "karras")

    if args.dry_run:
        for job in jobs:
            print(f"\n=== {job['theme']} / {job['slot']} "
                  f"({job['width']}x{job['height']}, seed {job['seed']}) ===")
            print(f"  POSITIVE: {job['positive']}")
            print(f"  NEGATIVE: {job['negative']}")
        print(f"\n{len(jobs)} image(s) would be generated with "
              f"{model['checkpoint']} @ {model['steps']} steps.")
        return 0

    try:
        _get(args.server, "/system_stats", timeout=10)
    except Exception as exc:
        print(f"ComfyUI is not reachable at {args.server} ({exc}).\n"
              "Start it first — see the header of this file — or run with "
              "--dry-run to review the prompts. Nothing was changed.")
        return 1

    model["checkpoint"] = available_checkpoint(args.server, model["checkpoint"])

    ok, failed = 0, 0
    for i, job in enumerate(jobs, 1):
        label = f"[{i}/{len(jobs)}] {job['theme']}/{job['slot']}"
        print(f"{label} ... ", end="", flush=True)
        started = time.time()
        try:
            path = run_job(args.server, job, model)
            print(f"OK  {path.relative_to(ROOT)}  ({time.time() - started:.0f}s)")
            ok += 1
        except Exception as exc:
            # One bad slot must never sink the batch.
            print(f"FAILED ({exc})")
            failed += 1
    print(f"\nDone: {ok} generated, {failed} failed.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

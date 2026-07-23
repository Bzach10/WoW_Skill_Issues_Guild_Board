"""Overnight art engine: a ComfyUI client that survives the night alone.

Three things this module exists to do, none of which the ad-hoc scripts do:

1. TELL A SLOW RENDER FROM A HANG. Tiled VAE decode on --lowvram is slow
   enough to look dead. So we never time out on wall-clock alone: we poll
   /prompt and /queue and treat *observable progress* (queue depth moving,
   history growing, the node counter advancing) as liveness. Only when the
   server stops answering, or answers but makes no progress for a long
   stretch, do we call it hung.

2. RECOVER ONCE, THEN STOP. Per the run policy: detect and alert by
   default; at most ONE guarded relaunch on a confirmed sustained hang.
   If that attempt does not produce a healthy server, we stop touching it
   and leave a loud alert. We never kill in a loop — a dead engine nobody
   can revive costs more than a paused queue.

3. CHECKPOINT EVERY ASSET. Each finished layer is recorded to a state
   file the moment it lands, so a resume skips it. Any single asset may
   fail without taking down the run.

Log: logs/overnight_build.log   State: logs/overnight_state.json
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import settings  # noqa: E402
from transport import ComfyTransport  # noqa: E402

_TRANSPORT = None


def _transport():
    """Module-level transport for the free functions that need one."""
    global _TRANSPORT
    if _TRANSPORT is None:
        _TRANSPORT = ComfyTransport()
    return _TRANSPORT

LOG_PATH = REPO / "logs" / "overnight_build.log"
STATE_PATH = REPO / "logs" / "overnight_state.json"
ALERT_PATH = REPO / "logs" / "ALERT.txt"

CKPT = "Illustrious-XL-v1.1.safetensors"
LORA = "one_piece_wano_style.safetensors"

# The contract's canvas. Also a native SDXL aspect, so no upscale pass.
CANVAS_W, CANVAS_H = 832, 1216

# The desktop app owns the backend's lifecycle. Relaunching THIS is the
# recovery step that actually works on this machine; see recover_once().
DESKTOP_APP = (r"C:\Users\zachf\AppData\Local\Programs\Comfy Desktop"
               r"\Comfy Desktop.exe")

# The exact backend invocation, read off the live process at recovery time
# rather than hardcoded, so a Comfy Desktop update doesn't strand us.
BACKEND_FALLBACK = [
    r"C:\Users\zachf\AppData\Local\Comfy-Desktop\ComfyUI-Installs\ComfytUI"
    r"\ComfyUI\.venv\Scripts\python.exe",
    "-s", "ComfyUI\\main.py", "--enable-manager", "--lowvram",
]


# ---------------------------------------------------------------- logging

def log(msg, level="INFO"):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    line = f"[{stamp}] {level:5} {msg}"
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def alert(msg):
    """Loud, out-of-band, and impossible to miss in the morning."""
    log(msg, level="ALERT")
    with open(ALERT_PATH, "a", encoding="utf-8") as f:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        f.write(f"[{stamp}] {msg}\n")


# ------------------------------------------------------------ checkpoint

def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            log(f"state file unreadable ({exc}) — starting fresh", "WARN")
    return {"done": {}, "failed": {}, "started": None}


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(STATE_PATH)  # atomic: a crash mid-write never corrupts state


def mark_done(state, key, path):
    state["done"][key] = {"path": str(path), "at": _now()}
    state.get("failed", {}).pop(key, None)
    save_state(state)


def mark_failed(state, key, reason):
    state.setdefault("failed", {})[key] = {"reason": str(reason)[:500], "at": _now()}
    save_state(state)


def _now():
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------- resources

def resources():
    """RAM/VRAM snapshot, logged every cycle so a slow leak is visible."""
    out = {}
    try:
        stats = _transport().system_stats()
        dev = (stats.get("devices") or [{}])[0]
        out["vram_free_mb"] = int(dev.get("vram_free", 0) / 1024 / 1024)
        out["vram_total_mb"] = int(dev.get("vram_total", 0) / 1024 / 1024)
        out["ram_free_mb"] = int(stats.get("system", {}).get("ram_free", 0) / 1024 / 1024)
        out["ram_total_mb"] = int(stats.get("system", {}).get("ram_total", 0) / 1024 / 1024)
    except Exception as exc:  # never let telemetry break the run
        out["error"] = str(exc)
    return out


def log_resources(tag=""):
    r = resources()
    if "error" in r:
        log(f"resources {tag}: unavailable ({r['error']})", "WARN")
        return r
    log(f"resources {tag}: RAM {r['ram_free_mb']}/{r['ram_total_mb']} MB free, "
        f"VRAM {r['vram_free_mb']}/{r['vram_total_mb']} MB free")
    if r["ram_free_mb"] < 800:
        log("RAM is thin — throttling (longer pause between assets)", "WARN")
    return r


# ------------------------------------------------------------ the client

class Hung(RuntimeError):
    """ComfyUI is confirmed unresponsive or stalled, not merely slow."""


class ComfyClient:
    def __init__(self, base_url=None):
        self.relaunch_attempted = False
        self.transport = ComfyTransport(base_url)
        self.remote = settings.is_remote() if base_url is None else (
            "127.0.0.1" not in base_url and "localhost" not in base_url)

    # -- health -----------------------------------------------------
    def healthy(self, timeout=10):
        return self.transport.healthy()

    def queue_remaining(self):
        return self.transport.queue_remaining()

    # -- submit / wait ----------------------------------------------
    def submit(self, graph, client_id="overnight"):
        return self.transport.submit(graph, client_id)

    def wait(self, prompt_id, stall_limit_s=900, hard_cap_s=3600):
        """Block until the prompt finishes.

        Liveness, not wall-clock, is the signal. `stall_limit_s` is how
        long the server may make NO observable progress before we call it
        hung — generous on purpose, because a tiled VAE decode of a
        832x1216 on --lowvram can sit silent for minutes. `hard_cap_s` is
        the absolute ceiling for one asset so a pathological graph can
        still not eat the whole night.
        """
        start = time.time()
        last_progress = time.time()
        last_fingerprint = None
        unreachable_since = None

        while True:
            if time.time() - start > hard_cap_s:
                raise Hung(f"prompt {prompt_id} exceeded hard cap {hard_cap_s}s")

            try:
                hist = self.transport.history(prompt_id)
                unreachable_since = None
            except Exception as exc:
                # A blip is normal under load; sustained silence is not.
                if unreachable_since is None:
                    unreachable_since = time.time()
                    log(f"comfy unreachable ({exc}) — watching", "WARN")
                elif time.time() - unreachable_since > 180:
                    raise Hung(f"comfy unreachable for >180s: {exc}")
                time.sleep(5)
                continue

            entry = hist.get(prompt_id)
            if entry:
                status = entry.get("status", {}) or {}
                if status.get("status_str") == "error":
                    raise RuntimeError(f"execution error: {json.dumps(status)[:800]}")
                if entry.get("outputs"):
                    return entry["outputs"]

            # Progress fingerprint: queue depth + how far execution got.
            remaining = self.queue_remaining()
            done_nodes = len((entry or {}).get("status", {}).get("messages", []))
            fingerprint = (remaining, done_nodes, bool(entry))
            if fingerprint != last_fingerprint:
                last_fingerprint = fingerprint
                last_progress = time.time()

            stalled = time.time() - last_progress
            if stalled > stall_limit_s:
                raise Hung(f"no progress for {int(stalled)}s on {prompt_id}")
            if stalled > stall_limit_s / 2 and int(stalled) % 120 < 5:
                log(f"{prompt_id}: quiet for {int(stalled)}s "
                    f"(tiled VAE can look like this) — still watching", "WARN")

            time.sleep(5)

    # -- recovery ---------------------------------------------------
    def recover_once(self):
        """One guarded relaunch of the DESKTOP APP. True only if Comfy returns.

        Launching "Comfy Desktop.exe" rather than re-spawning the backend
        python directly is deliberate, and is the whole point of this
        ladder: the desktop app owns the backend's lifecycle, so it
        respawns a healthy one with the right environment, model paths and
        flags. A headless kill-and-respawn recreates the process but not
        the app state that supervises it — which is why the GUI restart
        has been the reliable fix on this machine.

        Strictly one-shot. If this does not work we stop, log loudly, and
        leave it for a human GUI restart. Repeat-killing a wedged engine
        has never once fixed it and reliably makes the morning worse.
        """
        if self.remote:
            # There is no local process to kill or app to launch. A remote
            # instance recovers by waiting (transient API/network blip, or
            # a pod still warming) or, if genuinely dead, by reprovisioning
            # — which is a human decision because it costs money.
            log("remote endpoint unhealthy — waiting for it to recover", "WARN")
            for attempt in range(30):
                time.sleep(10)
                if self.healthy():
                    log(f"remote endpoint healthy again after "
                        f"{(attempt + 1) * 10}s")
                    return True
            alert("Remote ComfyUI endpoint did not recover within 300s. "
                  "STOPPING — check the RunPod pod is running "
                  "(console.runpod.io) and COMFY_BASE_URL is correct.")
            return False

        if self.relaunch_attempted:
            alert("ComfyUI hung again after its one allowed relaunch. "
                  "STOPPING recovery — needs a manual Comfy Desktop GUI restart.")
            return False
        self.relaunch_attempted = True
        alert("ComfyUI confirmed hung. Attempting the ONE allowed guarded "
              "relaunch via the Comfy Desktop app.")

        # Clear the wedged backend first: the app will not respawn one
        # while a stuck instance still holds the port.
        self._kill_backend()
        time.sleep(10)

        if not self._launch_desktop_app():
            alert("could not launch Comfy Desktop. STOPPING — needs a manual "
                  "GUI restart.")
            return False

        # Cold start = app boot + model load. Give it a genuine chance
        # before declaring failure; 10 minutes is not too long to wait
        # when the alternative is losing the rest of the night.
        for attempt in range(60):
            time.sleep(10)
            if self.healthy():
                log(f"relaunch succeeded after {(attempt + 1) * 10}s — "
                    f"ComfyUI is healthy again")
                return True

        alert("Comfy Desktop relaunch did not restore the API within 600s. "
              "STOPPING recovery — needs a manual GUI restart. "
              "No further kill attempts will be made.")
        return False

    def _launch_desktop_app(self):
        """Start the Comfy Desktop app if it is not already running."""
        exe = Path(DESKTOP_APP)
        if not exe.exists():
            log(f"Comfy Desktop not found at {exe}", "ERROR")
            return False
        try:
            subprocess.Popen([str(exe)], cwd=str(exe.parent),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
            log(f"launched {exe.name}")
            return True
        except Exception as exc:
            log(f"failed to launch Comfy Desktop: {exc}", "ERROR")
            return False

    def _live_backend_argv(self):
        """Read the real command line off the running backend if we can."""
        ps = (
            "Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" | "
            "Where-Object { $_.CommandLine -like '*ComfyUI*main.py*' } | "
            "Select-Object -First 1 -ExpandProperty CommandLine"
        )
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=30).stdout.strip()
            if "main.py" in out:
                import shlex
                argv = shlex.split(out, posix=False)
                argv = [a.strip('"') for a in argv]
                exe = Path(argv[0])
                cwd = exe.parents[2] if len(exe.parents) >= 3 else None
                log(f"recovered backend argv from live process ({len(argv)} args)")
                return argv, str(cwd) if cwd else None
        except Exception as exc:
            log(f"could not read live backend argv ({exc}) — using fallback", "WARN")
        exe = Path(BACKEND_FALLBACK[0])
        return list(BACKEND_FALLBACK), str(exe.parents[2])

    def _kill_backend(self):
        ps = (
            "Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" | "
            "Where-Object { $_.CommandLine -like '*ComfyUI*main.py*' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
            "-ErrorAction SilentlyContinue }"
        )
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=60)
            log("stopped the wedged backend process(es)")
        except Exception as exc:
            log(f"kill step failed: {exc}", "WARN")

    # -- the one call callers use -----------------------------------
    def run(self, graph, label, stall_limit_s=900):
        """Submit and wait, recovering once if the engine is confirmed hung.

        Raises on failure. Callers treat that as a per-asset failure and
        move on — the night continues.
        """
        if not self.healthy():
            log(f"{label}: comfy not answering pre-flight", "WARN")
            if not self.recover_once():
                raise Hung("engine down and unrecoverable")
        try:
            pid = self.submit(graph)
            return self.wait(pid, stall_limit_s=stall_limit_s)
        except Hung as exc:
            log(f"{label}: {exc}", "ERROR")
            if not self.recover_once():
                raise
            log(f"{label}: retrying once on the recovered engine")
            pid = self.submit(graph)
            return self.wait(pid, stall_limit_s=stall_limit_s)


# --------------------------------------------------------------- graphs

def txt2img_graph(positive, negative, seed, prefix,
                  w=CANVAS_W, h=CANVAS_H, steps=30, cfg=6.5, lora_strength=0.75):
    """SDXL + the Wano LoRA, decoded tiled so --lowvram never OOMs."""
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": CKPT}},
        "2": {"class_type": "LoraLoader",
              "inputs": {"lora_name": LORA, "strength_model": lora_strength,
                         "strength_clip": lora_strength,
                         "model": ["1", 0], "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": positive, "clip": ["2", 1]}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative, "clip": ["2", 1]}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": w, "height": h, "batch_size": 1}},
        "6": {"class_type": "KSampler",
              "inputs": {"seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": "dpmpp_2m", "scheduler": "karras",
                         "denoise": 1.0, "model": ["2", 0],
                         "positive": ["3", 0], "negative": ["4", 0],
                         "latent_image": ["5", 0]}},
        "7": {"class_type": "VAEDecodeTiled",
              "inputs": {"samples": ["6", 0], "vae": ["1", 2],
                         "tile_size": 512, "overlap": 64,
                         "temporal_size": 64, "temporal_overlap": 8}},
        "9": {"class_type": "SaveImage",
              "inputs": {"images": ["7", 0], "filename_prefix": prefix}},
    }


def stage_input(src_path, name):
    """Make an image visible to ComfyUI's LoadImage. Returns its name.

    Uploaded over HTTP rather than copied into a local directory, so this
    works identically against a local instance and a RunPod pod. The old
    filesystem copy was the single thing that made the pipeline
    local-only.
    """
    return _transport().upload_image(src_path, name)


def img2img_graph(image_name, positive, negative, seed, prefix,
                  denoise=0.55, steps=30, cfg=6.5, lora_strength=0.40):
    """Repaint an existing render, keeping its composition.

    This is what makes gear layers ALIGN. A robe generated from scratch
    has no relationship to the base body; a robe painted onto the base
    body at partial denoise sits on the same shoulders, and the pixels
    that did not change are, by construction, still the body. That lets
    us diff the two and recover the gear alone.

    Keep `denoise` low enough that the silhouette holds (~0.5-0.65) —
    above that the pose drifts and alignment is lost.
    """
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": CKPT}},
        "2": {"class_type": "LoraLoader",
              "inputs": {"lora_name": LORA, "strength_model": lora_strength,
                         "strength_clip": lora_strength,
                         "model": ["1", 0], "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": positive, "clip": ["2", 1]}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative, "clip": ["2", 1]}},
        "10": {"class_type": "LoadImage",
               "inputs": {"image": image_name}},
        "11": {"class_type": "VAEEncode",
               "inputs": {"pixels": ["10", 0], "vae": ["1", 2]}},
        "6": {"class_type": "KSampler",
              "inputs": {"seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": "dpmpp_2m", "scheduler": "karras",
                         "denoise": denoise, "model": ["2", 0],
                         "positive": ["3", 0], "negative": ["4", 0],
                         "latent_image": ["11", 0]}},
        "7": {"class_type": "VAEDecodeTiled",
              "inputs": {"samples": ["6", 0], "vae": ["1", 2],
                         "tile_size": 512, "overlap": 64,
                         "temporal_size": 64, "temporal_overlap": 8}},
        "9": {"class_type": "SaveImage",
              "inputs": {"images": ["7", 0], "filename_prefix": prefix}},
    }


CONTROLNET = "controlnet-union-sdxl-1.0.safetensors"


def controlnet_graph(image_name, positive, negative, seed, prefix,
                     strength=0.75, end_percent=0.65, steps=30, cfg=6.5,
                     lora_strength=0.40, w=CANVAS_W, h=CANVAS_H,
                     low_threshold=0.20, high_threshold=0.55):
    """Full-denoise generation, locked to the base body's edges.

    img2img could not do this job: at a denoise low enough to hold the
    pose, the existing composition dominated and the gear never rendered
    at all (measured IoU 0.96 with a robe that simply was not there).

    So we generate FRESH from an empty latent — the robe is drawn with no
    leotard to fight — and use a canny edge map of the base body as
    ControlNet conditioning so the fresh render lands on the same
    skeleton. `end_percent` releases the control partway through, which
    lets cloth drape past the body's outline instead of shrink-wrapping
    to it, while the early steps have already fixed the pose.
    """
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": CKPT}},
        "2": {"class_type": "LoraLoader",
              "inputs": {"lora_name": LORA, "strength_model": lora_strength,
                         "strength_clip": lora_strength,
                         "model": ["1", 0], "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": positive, "clip": ["2", 1]}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative, "clip": ["2", 1]}},
        "10": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "12": {"class_type": "Canny",
               "inputs": {"image": ["10", 0], "low_threshold": low_threshold,
                          "high_threshold": high_threshold}},
        "13": {"class_type": "ControlNetLoader",
               "inputs": {"control_net_name": CONTROLNET}},
        "14": {"class_type": "ControlNetApplyAdvanced",
               "inputs": {"positive": ["3", 0], "negative": ["4", 0],
                          "control_net": ["13", 0], "image": ["12", 0],
                          "strength": strength, "start_percent": 0.0,
                          "end_percent": end_percent}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": w, "height": h, "batch_size": 1}},
        "6": {"class_type": "KSampler",
              "inputs": {"seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": "dpmpp_2m", "scheduler": "karras",
                         "denoise": 1.0, "model": ["2", 0],
                         "positive": ["14", 0], "negative": ["14", 1],
                         "latent_image": ["5", 0]}},
        "7": {"class_type": "VAEDecodeTiled",
              "inputs": {"samples": ["6", 0], "vae": ["1", 2],
                         "tile_size": 512, "overlap": 64,
                         "temporal_size": 64, "temporal_overlap": 8}},
        "9": {"class_type": "SaveImage",
              "inputs": {"images": ["7", 0], "filename_prefix": prefix}},
    }


FETCH_DIR = REPO / "cast" / "_incoming"


def collect_outputs(outputs, node="9"):
    """Download the images a finished prompt produced; return local paths.

    Fetched over /view rather than read off a shared output directory —
    the pod's filesystem is not ours, and going through HTTP locally too
    means this path is exercised on every run instead of first executing
    against production.
    """
    tr = _transport()
    FETCH_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    for img in (outputs.get(node, {}) or {}).get("images", []):
        filename = img["filename"]
        try:
            data = tr.fetch_image(filename, img.get("subfolder", ""),
                                  img.get("type", "output"))
        except Exception as exc:
            log(f"could not fetch {filename}: {settings.redact(exc)}", "ERROR")
            continue
        dest = FETCH_DIR / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        paths.append(dest)
    return paths

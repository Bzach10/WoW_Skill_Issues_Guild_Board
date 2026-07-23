"""Provision / inspect / tear down the RunPod ComfyUI pod.

Deliberately NOT automatic. Every subcommand that costs money requires an
explicit flag and prints the hourly rate first, because an accidentally
orphaned pod bills continuously and silently.

    python scripts/overnight/runpod_pod.py check      # key + account, free
    python scripts/overnight/runpod_pod.py gpus       # list GPU types, free
    python scripts/overnight/runpod_pod.py volume --create --size 100
    python scripts/overnight/runpod_pod.py up --confirm
    python scripts/overnight/runpod_pod.py status
    python scripts/overnight/runpod_pod.py down --pod <id> --confirm

API: https://rest.runpod.io/v1   (Bearer auth)
Docs: https://docs.runpod.io/api-reference/pods/POST/pods
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import settings  # noqa: E402

API = "https://rest.runpod.io/v1"

# RTX 4090, the agreed target. Order matters — RunPod rents in sequence,
# so listing fallbacks avoids "no capacity" hard-failing the whole run.
GPU_PREFERENCE = [
    "NVIDIA GeForce RTX 4090",
    "NVIDIA GeForce RTX 5090",
    "NVIDIA RTX A5000",
]

# Network volumes are Secure Cloud only, so the pod must match.
CLOUD_TYPE = "SECURE"
VOLUME_MOUNT = "/workspace"
COMFY_PORT = 8188

# ComfyUI images that ship the API enabled on :8188. Verify in the RunPod
# Hub UI before first use — template names drift.
DEFAULT_IMAGE = "runpod/worker-comfyui:latest"


def _req(method, path, payload=None):
    url = f"{API}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {settings.runpod_api_key()}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            body = r.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:500]
        except Exception:
            pass
        raise RuntimeError(settings.redact(
            f"{method} {path} -> HTTP {exc.code}: {detail}")) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(settings.redact(f"{method} {path}: {exc}")) from exc


def proxy_url(pod_id, port=COMFY_PORT):
    return f"https://{pod_id}-{port}.proxy.runpod.net"


# ----------------------------------------------------------- commands

def cmd_check(_argv):
    """Free. Proves the key works without spending anything."""
    print("Settings:")
    print(settings.describe())
    print("\nCalling RunPod API…")
    pods = _req("GET", "/pods")
    vols = _req("GET", "/networkvolumes")
    pods = pods if isinstance(pods, list) else pods.get("data", [])
    vols = vols if isinstance(vols, list) else vols.get("data", [])
    print(f"  key accepted. {len(pods)} pod(s), {len(vols)} network volume(s).")
    for p in pods:
        print(f"    POD  {p.get('id')}  {p.get('name')}  "
              f"{p.get('desiredStatus')}  -> {proxy_url(p.get('id'))}")
    for v in vols:
        print(f"    VOL  {v.get('id')}  {v.get('name')}  "
              f"{v.get('size')}GB  {v.get('dataCenterId')}")
    return 0


def cmd_gpus(_argv):
    data = _req("GET", "/gpuTypes")
    data = data if isinstance(data, list) else data.get("data", [])
    for g in data:
        gid = g.get("id") or g.get("displayName")
        if any(p.lower() in str(gid).lower() for p in ("4090", "5090", "a5000")):
            print(f"  {gid}   secure=${g.get('securePrice')}/hr  "
                  f"community=${g.get('communityPrice')}/hr")
    return 0


def cmd_volume(argv):
    if "--create" not in argv:
        vols = _req("GET", "/networkvolumes")
        vols = vols if isinstance(vols, list) else vols.get("data", [])
        for v in vols:
            print(f"  {v.get('id')}  {v.get('name')}  {v.get('size')}GB  "
                  f"{v.get('dataCenterId')}")
        return 0
    size = int(_flag(argv, "--size", "100"))
    dc = _flag(argv, "--dc", "US-KS-2")
    print(f"Creating {size}GB network volume in {dc} "
          f"(storage bills ~$0.07/GB/month, separate from pod time).")
    vol = _req("POST", "/networkvolumes",
               {"name": "guildboard-models", "size": size, "dataCenterId": dc})
    print(f"  created: {vol.get('id')}")
    print(f"  add to .env:  RUNPOD_NETWORK_VOLUME_ID={vol.get('id')}")
    return 0


def cmd_up(argv):
    if "--confirm" not in argv:
        print("This starts a billable GPU pod (~$0.69/hr for a 4090).\n"
              "Re-run with --confirm to actually create it.")
        return 1
    vol_id = _flag(argv, "--volume", settings.get("RUNPOD_NETWORK_VOLUME_ID"))
    image = _flag(argv, "--image", DEFAULT_IMAGE)

    body = {
        "name": "guildboard-comfyui",
        "imageName": image,
        "gpuTypeIds": GPU_PREFERENCE,
        "gpuCount": 1,
        "cloudType": CLOUD_TYPE,
        "containerDiskInGb": 50,
        "ports": [f"{COMFY_PORT}/http", "22/tcp"],
        "volumeMountPath": VOLUME_MOUNT,
        "env": {"COMFYUI_PORT": str(COMFY_PORT)},
    }
    if vol_id:
        # Must be attached at creation; it cannot be added later.
        body["networkVolumeId"] = vol_id
    else:
        body["volumeInGb"] = 60
        print("WARNING: no network volume. Models will not persist across "
              "pod restarts and must be re-downloaded each time.")

    print(f"Creating pod (image={image}, gpu={GPU_PREFERENCE[0]})…")
    pod = _req("POST", "/pods", body)
    pod_id = pod.get("id")
    url = proxy_url(pod_id)
    print(f"  pod id : {pod_id}")
    print(f"  comfy  : {url}")
    print(f"\n  Add to .env:   COMFY_BASE_URL={url}")
    print(f"  Stop it with:  python {Path(__file__).name} down "
          f"--pod {pod_id} --confirm")
    return 0


def cmd_status(argv):
    pods = _req("GET", "/pods")
    pods = pods if isinstance(pods, list) else pods.get("data", [])
    if not pods:
        print("  no pods running (nothing billing)")
        return 0
    for p in pods:
        pid = p.get("id")
        print(f"  {pid}  {p.get('name')}  {p.get('desiredStatus')}  "
              f"{proxy_url(pid)}")
    return 0


def cmd_down(argv):
    pod_id = _flag(argv, "--pod", None)
    if not pod_id or "--confirm" not in argv:
        print("usage: down --pod <id> --confirm")
        return 1
    _req("DELETE", f"/pods/{pod_id}")
    print(f"  terminated {pod_id} — billing stopped")
    return 0


def cmd_wait(argv):
    """Poll the proxy until ComfyUI answers. Cold start is 2-3 min."""
    url = _flag(argv, "--url", settings.get("COMFY_BASE_URL"))
    if not url:
        print("need --url or COMFY_BASE_URL")
        return 1
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from transport import ComfyTransport
    tr = ComfyTransport(url, timeout=20, retries=1)
    for i in range(60):
        if tr.healthy():
            print(f"  ComfyUI is up after ~{i * 10}s: {url}")
            return 0
        time.sleep(10)
    print("  timed out after 600s — check the pod in the RunPod console")
    return 1


def _flag(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


COMMANDS = {"check": cmd_check, "gpus": cmd_gpus, "volume": cmd_volume,
            "up": cmd_up, "status": cmd_status, "down": cmd_down,
            "wait": cmd_wait}


def main(argv):
    if not argv or argv[0] not in COMMANDS:
        print(__doc__)
        return 1
    try:
        return COMMANDS[argv[0]](argv[1:])
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

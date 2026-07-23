"""HTTP transport to a ComfyUI instance — local or RunPod, same code path.

The old engine reached into ComfyUI's input/output DIRECTORIES on disk.
That works only when ComfyUI is the same machine, and it was the single
thing tying the pipeline to a local install.

ComfyUI exposes `/upload/image` and `/view` over HTTP, so we use those
for local runs too. One code path, exercised on every local run, which
means the RunPod switch is a base-URL change rather than an untested
second implementation that first executes in production.

Retries are here rather than in the caller because the failure profile
differs by verb: a GET can be retried freely, but re-POSTing a prompt
would queue a duplicate render, so submits are NOT auto-retried.
"""

import json
import mimetypes
import random
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import settings

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


class TransportError(RuntimeError):
    pass


class ComfyTransport:
    def __init__(self, base_url=None, timeout=120, retries=4):
        self.base = (base_url or settings.comfy_base_url()).rstrip("/")
        self.timeout = timeout
        self.retries = retries

    # -- low level ---------------------------------------------------
    def _request(self, method, path, data=None, headers=None, retry=True):
        url = f"{self.base}{path}"
        last = None
        attempts = self.retries if retry else 1
        for attempt in range(attempts):
            req = urllib.request.Request(url, data=data, method=method,
                                          headers=headers or {})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return r.read()
            except urllib.error.HTTPError as exc:
                last = exc
                body = ""
                try:
                    body = exc.read().decode("utf-8", "replace")[:400]
                except Exception:
                    pass
                if exc.code not in RETRY_STATUS or attempt == attempts - 1:
                    raise TransportError(settings.redact(
                        f"{method} {path} -> HTTP {exc.code}: {body}")) from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = exc
                if attempt == attempts - 1:
                    raise TransportError(settings.redact(
                        f"{method} {path} unreachable: {exc}")) from exc
            # Exponential backoff with jitter: a cold pod and a rate limit
            # both resolve with time, and synchronised retries do not help.
            delay = min(2 ** attempt, 8) + random.uniform(0, 0.6)
            time.sleep(delay)
        raise TransportError(settings.redact(f"{method} {path} failed: {last}"))

    def get_json(self, path, retry=True):
        return json.loads(self._request("GET", path, retry=retry))

    def post_json(self, path, payload, retry=False):
        body = json.dumps(payload).encode()
        return json.loads(self._request(
            "POST", path, data=body,
            headers={"Content-Type": "application/json"}, retry=retry))

    # -- the four things the pipeline needs --------------------------
    def system_stats(self):
        return self.get_json("/system_stats")

    def healthy(self):
        try:
            self.system_stats()
            return True
        except Exception:
            return False

    def upload_image(self, src_path, name=None, overwrite=True):
        """PUT an image into ComfyUI's input dir over HTTP. Returns its name."""
        src = Path(src_path)
        name = name or src.name
        boundary = f"----guildboard{uuid.uuid4().hex}"
        ctype = mimetypes.guess_type(name)[0] or "image/png"

        parts = []
        for field, value in (("overwrite", "true" if overwrite else "false"),
                             ("type", "input")):
            parts.append(
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{field}"\r\n\r\n'
                f"{value}\r\n".encode())
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{name}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n".encode())
        parts.append(src.read_bytes())
        parts.append(f"\r\n--{boundary}--\r\n".encode())

        resp = self._request(
            "POST", "/upload/image", data=b"".join(parts),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            retry=True)
        try:
            return json.loads(resp).get("name", name)
        except ValueError:
            return name

    def fetch_image(self, filename, subfolder="", folder_type="output"):
        """Download a generated image as bytes."""
        q = urllib.parse.urlencode({"filename": filename,
                                    "subfolder": subfolder,
                                    "type": folder_type})
        return self._request("GET", f"/view?{q}")

    def queue_remaining(self):
        try:
            return self.get_json("/prompt").get(
                "exec_info", {}).get("queue_remaining", 0)
        except Exception:
            return None

    def submit(self, graph, client_id="guildboard"):
        """Submit a prompt. Deliberately NOT retried — a retried submit
        queues a second render of the same asset."""
        return self.post_json(
            "/prompt", {"prompt": graph, "client_id": client_id},
            retry=False)["prompt_id"]

    def history(self, prompt_id):
        return self.get_json(f"/history/{prompt_id}")

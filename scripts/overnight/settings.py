"""Credential and endpoint loading — the only place secrets are read.

Rules this module enforces, so no caller has to remember them:

  * a secret is NEVER returned by __repr__, logged, or printed
  * `describe()` reports only presence and length, never a value
  * `redact()` scrubs a secret out of any string before it can reach a
    log line or an exception message

Resolution order for every setting: real environment variable first
(so CI and one-off shells win), then the gitignored .env file.
"""

import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENV_FILE = REPO / ".env"

_LOADED = False


def _load_env_file():
    """Parse .env into os.environ without overwriting real env vars."""
    global _LOADED
    if _LOADED or not ENV_FILE.exists():
        _LOADED = True
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        # A real environment variable always beats the file.
        if key and value and key not in os.environ:
            os.environ[key] = value
    _LOADED = True


def _windows_user_env(name):
    """Read a user environment variable straight from the registry.

    `setx` writes to HKCU\\Environment and only affects processes started
    afterwards — so a long-lived shell (and anything it spawns) cannot see
    a key that was just set, which looks exactly like "the key is missing".

    Read via winreg rather than by shelling out, so the value never
    appears on a command line where it could reach shell history, a
    process list, or a log.
    """
    if os.name != "nt":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return value or None
    except (ImportError, OSError, FileNotFoundError):
        return None


def get(name, default=None):
    _load_env_file()
    value = os.environ.get(name)
    if not value:
        # Last resort: a variable set by `setx` in another shell.
        value = _windows_user_env(name)
        if value:
            os.environ[name] = value
    return value if value else default


def require(name):
    """Fetch a setting or fail with an actionable message — never the value."""
    value = get(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set.\n"
            f"  Add it to {ENV_FILE}  (that file is gitignored)\n"
            f"  e.g.   {name}=your-value-here\n"
            f"  or export it in the shell for a one-off run."
        )
    return value


def runpod_api_key():
    return require("RUNPOD_API_KEY")


def comfy_base_url(default="http://127.0.0.1:8188"):
    """Where to generate. Local unless COMFY_BASE_URL says otherwise."""
    return (get("COMFY_BASE_URL") or default).rstrip("/")


def is_remote():
    return "127.0.0.1" not in comfy_base_url() and "localhost" not in comfy_base_url()


def redact(text):
    """Scrub any known secret out of a string before it is logged.

    Belt and braces: also masks anything shaped like a RunPod key, so a
    key we were never told about cannot leak through an error message.
    """
    out = str(text)
    for name in ("RUNPOD_API_KEY",):
        secret = get(name)
        if secret and len(secret) > 6:
            out = out.replace(secret, f"<{name}:REDACTED>")
    out = re.sub(r"rpa_[A-Za-z0-9]{8,}", "rpa_<REDACTED>", out)
    out = re.sub(r"(Bearer\s+)[A-Za-z0-9._\-]{12,}", r"\1<REDACTED>", out)
    return out


def describe():
    """Presence report for humans. Never prints a secret."""
    _load_env_file()
    rows = []
    for name in ("RUNPOD_API_KEY", "COMFY_BASE_URL", "RUNPOD_NETWORK_VOLUME_ID"):
        value = get(name)
        if not value:
            rows.append(f"  {name:<26} NOT SET")
        elif name.endswith("_KEY"):
            rows.append(f"  {name:<26} set (length {len(value)}, "
                        f"starts {value[:4]}…)")
        else:
            rows.append(f"  {name:<26} {value}")
    rows.append(f"  .env file{'':<17} "
                f"{'present' if ENV_FILE.exists() else 'absent'} ({ENV_FILE})")
    rows.append(f"  generating against{'':<8} {comfy_base_url()} "
                f"({'REMOTE' if is_remote() else 'LOCAL'})")
    return "\n".join(rows)


if __name__ == "__main__":
    print("Settings:")
    print(describe())

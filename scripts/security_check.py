#!/usr/bin/env python3
"""On-demand security check — the same one CI runs weekly and on every PR.

    python scripts/security_check.py           # everything
    python scripts/security_check.py --quick   # skip the git-history sweep
    python scripts/security_check.py --list    # names of the checks, no run

Four checks, no third-party GitHub Actions involved (nothing to pin, nothing
that can be swapped under us):

  deps      pip-audit against requirements.txt      -- known CVEs
  static    bandit over our own Python              -- medium+ severity only
  secrets   regex sweep of tracked files, and of
            every blob in git history unless --quick
  actions   workflow lint: ${{ }} spliced into a
            run: body, and jobs with no permissions

Exit code is the number of checks that failed, so CI fails loudly and
`&&` chains behave. Missing scanners are reported as SKIP, not failure --
the script stays useful on a machine that only has the stdlib.
"""

import argparse
import base64
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Source dirs we wrote ourselves. Vendored/generated art tooling under
# assets/ is deliberately out of scope.
OUR_CODE = ["guild_board", "scripts", "leaderboard.py"]

# Extensions worth sweeping for secrets. Binaries and art are skipped.
TEXTY = {".py", ".yml", ".yaml", ".json", ".md", ".txt", ".j2", ".html",
         ".cfg", ".ini", ".toml", ".sh", ".ps1"}

# A secret is a long opaque string sitting next to a name that implies one.
# Written to catch real leaks while staying quiet on this repo's many
# legitimate mentions of the *names* (os.environ.get("DISCORD_BOT_TOKEN")).
SECRET_PATTERNS = [
    ("Discord webhook URL",
     re.compile(r"discord(?:app)?\.com/api/webhooks/\d{5,}/[\w-]{20,}")),
    ("Discord bot token",
     re.compile(r"\b[A-Za-z0-9_-]{24}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}\b")),
    ("assigned credential literal",
     re.compile(r"(?i)\b(?:client_secret|client_id|api_key|apikey|password|passwd|"
                r"secret|token|bearer)\b\s*[:=]\s*[\"']([A-Za-z0-9/+_\-]{16,})[\"']")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key block",
     re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
]

# Values that match the patterns above but are obviously not secrets.
SECRET_ALLOW = re.compile(
    r"(?i)^(?:true|false|none|null|null|changeme|example|placeholder|"
    r"your[_-]?\w*|xxx+|\.{3,}|\$\{.*|<.*>|test[_-]?\w*|dummy\w*)$")


def _run(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          errors="replace", **kw)


def _module_available(mod):
    return _run([sys.executable, "-c", f"import {mod}"]).returncode == 0


# --------------------------------------------------------------------------
# deps
# --------------------------------------------------------------------------

def check_deps():
    """Known CVEs in our pinned dependencies."""
    if not _module_available("pip_audit"):
        print("  SKIP  pip-audit not installed (pip install pip-audit)")
        return None
    r = _run([sys.executable, "-m", "pip_audit", "-r", "requirements.txt",
              "--progress-spinner", "off"])
    out = (r.stdout + r.stderr).strip()
    if r.returncode == 0:
        print("  ok    no known vulnerabilities in requirements.txt")
        return True
    print(out)
    return False


# --------------------------------------------------------------------------
# static
# --------------------------------------------------------------------------

def check_static():
    """Bandit, medium severity and up — low is almost all false positives here."""
    if not _module_available("bandit"):
        print("  SKIP  bandit not installed (pip install bandit)")
        return None
    r = _run([sys.executable, "-m", "bandit", "-r", *OUR_CODE,
              "-ll", "-q", "-f", "txt"])
    out = (r.stdout + r.stderr).strip()
    if r.returncode == 0:
        print("  ok    no medium-or-higher findings")
        return True
    print(out)
    return False


# --------------------------------------------------------------------------
# secrets
# --------------------------------------------------------------------------

def _scan_text(where, text, found):
    for label, pattern in SECRET_PATTERNS:
        for m in pattern.finditer(text):
            value = m.group(1) if m.groups() else m.group(0)
            if m.groups() and SECRET_ALLOW.match(value):
                continue
            # Report a fingerprint, never the value itself -- this output
            # goes to a CI log that is often world-readable.
            digest = base64.b16encode(value[:8].encode()).decode()[:12]
            found.append(f"  FOUND {label} in {where} (fp {digest})")


def check_secrets(quick=False):
    """Committed credentials, in the working tree and in history."""
    found = []

    tracked = _run(["git", "ls-files"]).stdout.split()
    for rel in tracked:
        p = ROOT / rel
        if p.suffix.lower() not in TEXTY or not p.is_file():
            continue
        try:
            _scan_text(rel, p.read_text(encoding="utf-8", errors="replace"), found)
        except OSError:
            continue
    print(f"  ..    swept {len(tracked)} tracked files")

    if not quick:
        # Every blob ever committed. A secret that was committed and then
        # removed is still a live secret until it is rotated.
        blobs = _run(["git", "rev-list", "--objects", "--all"]).stdout.splitlines()
        names = {}
        for line in blobs:
            sha, _, name = line.partition(" ")
            if name and Path(name).suffix.lower() in TEXTY:
                names[sha] = name
        for sha, name in names.items():
            body = _run(["git", "cat-file", "-p", sha]).stdout
            _scan_text(f"history:{name}@{sha[:8]}", body, found)
        print(f"  ..    swept {len(names)} historical blobs")

    if found:
        print("\n".join(sorted(set(found))))
        print("  !!    a hit here means ROTATE THE CREDENTIAL first; scrubbing")
        print("        history does not un-leak it.")
        return False
    print("  ok    no credential material found")
    return True


# --------------------------------------------------------------------------
# actions
# --------------------------------------------------------------------------

# ${{ }} that expands attacker-influenceable text. github.event.* and inputs.*
# are user-supplied; secrets.* and github.ref_name are not attacker-chosen but
# still belong in env: rather than spliced into shell.
RISKY_EXPR = re.compile(r"\$\{\{\s*(github\.event\.[\w.\-]+|inputs\.[\w.\-]+|"
                        r"github\.head_ref|github\.ref_name)\s*\}\}")


def check_actions():
    """Untrusted ${{ }} inside run: bodies, and jobs without permissions."""
    problems = []
    wf_dir = ROOT / ".github" / "workflows"
    for wf in sorted(wf_dir.glob("*.yml")) + sorted(wf_dir.glob("*.yaml")):
        text = wf.read_text(encoding="utf-8", errors="replace")
        rel = wf.relative_to(ROOT)

        # Walk run: blocks by indentation and flag risky expressions inside.
        lines = text.splitlines()
        in_run = False
        run_indent = 0
        for n, line in enumerate(lines, 1):
            stripped = line.strip()
            indent = len(line) - len(line.lstrip())
            if re.match(r"-?\s*run:\s*[|>]", stripped):
                in_run, run_indent = True, indent
                continue
            if in_run and stripped and indent <= run_indent:
                in_run = False
            if in_run:
                for m in RISKY_EXPR.finditer(line):
                    problems.append(
                        f"  FOUND {rel}:{n} untrusted {m.group(0)} spliced into "
                        f"run: -- bind it to env: and use \"$VAR\"")

        if "permissions:" not in text:
            problems.append(
                f"  FOUND {rel} declares no permissions: -- it inherits the "
                f"repo default (often read+write on every scope)")

    if problems:
        print("\n".join(problems))
        return False
    print("  ok    no run: injection, every workflow scopes its permissions")
    return True


CHECKS = [
    ("deps", "dependency CVEs (pip-audit)", check_deps),
    ("static", "static analysis (bandit)", check_static),
    ("secrets", "committed credentials", check_secrets),
    ("actions", "workflow injection + least privilege", check_actions),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true",
                    help="skip the git-history blob sweep (much faster)")
    ap.add_argument("--only", metavar="NAME",
                    help="run a single check: " + ", ".join(n for n, _, _ in CHECKS))
    ap.add_argument("--list", action="store_true", help="list checks and exit")
    args = ap.parse_args()

    if args.list:
        for name, desc, _ in CHECKS:
            print(f"{name:9} {desc}")
        return 0

    selected = [c for c in CHECKS if not args.only or c[0] == args.only]
    if not selected:
        print(f"no such check: {args.only}", file=sys.stderr)
        return 1

    failed, skipped = [], []
    for name, desc, fn in selected:
        print(f"\n[{name}] {desc}")
        result = fn(quick=args.quick) if name == "secrets" else fn()
        if result is False:
            failed.append(name)
        elif result is None:
            skipped.append(name)

    print("\n" + "-" * 60)
    if failed:
        print(f"FAIL  {len(failed)} check(s) failed: {', '.join(failed)}")
    else:
        print("PASS  all checks clean")
    if skipped:
        print(f"      {len(skipped)} skipped (scanner not installed): "
              f"{', '.join(skipped)}")
    return len(failed)


if __name__ == "__main__":
    sys.exit(main())

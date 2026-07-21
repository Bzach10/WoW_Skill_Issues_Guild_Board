"""The security checks are only useful if they still catch what they were
written for. These lock in the two detectors that encode real findings from
the hardening pass: workflow script injection, and committed credentials.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    "security_check", ROOT / "scripts" / "security_check.py")
security_check = importlib.util.module_from_spec(spec)
sys.modules["security_check"] = security_check
spec.loader.exec_module(security_check)


# --------------------------------------------------------------------------
# workflow injection
# --------------------------------------------------------------------------

INJECTABLE = """\
name: demo
permissions:
  contents: read
jobs:
  go:
    steps:
      - name: build
        run: |
          echo "${{ github.event.inputs.roast }}"
"""

SAFE = """\
name: demo
permissions:
  contents: read
jobs:
  go:
    steps:
      - name: build
        env:
          IN_ROAST: ${{ github.event.inputs.roast }}
        run: |
          echo "$IN_ROAST"
"""


def _check_actions_against(tmp_path, monkeypatch, workflows):
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    for name, body in workflows.items():
        (wf_dir / name).write_text(body, encoding="utf-8")
    monkeypatch.setattr(security_check, "ROOT", tmp_path)
    return security_check.check_actions()


def test_flags_untrusted_input_spliced_into_run(tmp_path, monkeypatch, capsys):
    assert _check_actions_against(tmp_path, monkeypatch,
                                  {"bad.yml": INJECTABLE}) is False
    assert "spliced into run:" in capsys.readouterr().out


def test_passes_when_input_is_bound_to_env(tmp_path, monkeypatch):
    assert _check_actions_against(tmp_path, monkeypatch,
                                  {"good.yml": SAFE}) is True


def test_flags_workflow_with_no_permissions_block(tmp_path, monkeypatch, capsys):
    assert _check_actions_against(
        tmp_path, monkeypatch,
        {"open.yml": SAFE.replace("permissions:\n  contents: read\n", "")}) is False
    assert "no permissions:" in capsys.readouterr().out


def test_real_workflows_are_clean(capsys):
    """The repo's own workflows must stay free of both findings."""
    assert security_check.check_actions() is True


# --------------------------------------------------------------------------
# secret detection
# --------------------------------------------------------------------------

@pytest.mark.parametrize("sample", [
    'https://discord.com/api/webhooks/123456789012/AbCdEfGhIjKlMnOpQrStUvWxYz123456',
    'client_secret = "aB3dEfGh1jKlMn0pQrSt"',
    "AKIAIOSFODNN7EXAMPLE",
    "-----BEGIN RSA PRIVATE KEY-----",
])
def test_detects_credential_shapes(sample):
    found = []
    security_check._scan_text("sample.py", sample, found)
    assert found, f"missed: {sample}"


@pytest.mark.parametrize("sample", [
    # The repo legitimately names these constantly; naming is not leaking.
    'token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()',
    'DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}',
    'client_secret = "changeme"',
    'api_key = "your_api_key_here"',
])
def test_ignores_non_secrets(sample):
    found = []
    security_check._scan_text("sample.py", sample, found)
    assert not found, f"false positive: {sample} -> {found}"


def test_findings_never_echo_the_secret_value():
    """CI logs are often world-readable; report a fingerprint, not the key."""
    secret = "aB3dEfGh1jKlMn0pQrStUv"
    found = []
    security_check._scan_text("sample.py", f'client_secret = "{secret}"', found)
    assert found
    assert secret not in "\n".join(found)

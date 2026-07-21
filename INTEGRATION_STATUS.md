# Integration status

Owner: integration/build manager. Branch `integration`, worktree `C:/wt/int`.
Updated 2026-07-20.

## Build health

| gate | result |
|------|--------|
| pytest (full suite) | **331 passed, 1 failed** |
| module import smoke | 10/10 OK |
| `scripts/security_check.py` | **FAIL** — `actions`, `static`, `secrets` |

Baseline before integration: 127 tracked tests on `2.0`.

## Merged

| team | branch | at | notes |
|------|--------|----|-------|
| Security | `security-hardening` | 3954f2f | clean |
| Backend/Data-QA | `backend-data-qa` | 6626e31 | clean |
| Front-end | `frontend-crew-ui` | 1172d07 | 2 conflicts, resolved |
| (prod line) | `main` | 8ed452f | 1 conflict, resolved |

### Conflict resolutions

1. **`.gitignore`** (backend × frontend) — both pure additions, unioned.
   Frontend's `!cast/**/board.png` un-ignore rules preserved; without them
   the unanchored `board.png` rule swallows the art pipeline's cut-outs.
2. **`tests/test_cast_manifest.py`** (backend × frontend, add/add) — same
   filename, disjoint suites. Backend's tests the *producer*
   (`guild_board.cast_manifest`); frontend's tests the *consumer*
   (`guild_board.crew`). Backend keeps the name; frontend's moved to
   `tests/test_crew_manifest.py`. Both files byte-identical to their
   team's original — no logic touched.
3. **`guild_board/blizzard.py`** (main × backend, add/add) — backend's is a
   strict superset of main's (adds `split_name_realm`, which fixes the
   roster-drop bug, plus a ruff autofix). Took backend's.

## Open — needs a decision

### 1. BLOCKER: `main`'s workflow trips security's injection gate
`.github/workflows/blizzard-profile-refresh.yml:49,65` splices
`${{ github.event.inputs.force }}` and `${{ github.ref_name }}` into `run:`.
Line 65 is the step holding `GITHUB_TOKEN`.

Neither team could see this: Security hardened every workflow on the `2.0`
line and added a standing test that *all* workflows stay clean; `main` added
this workflow in parallel. They only meet here. This is the one failing test.

Fix is mechanical — security's own pattern from `weekly-board.yml`: bind to
`env:`, read as `"$VAR"`. **Awaiting sign-off on who applies it.**

### 2. Security's bandit gate now flags backend's `render_pipeline.py`
B310 (`urllib.request.urlopen`, medium) at lines 52 and 157. Backend never
ran bandit; the gate only existed on security's branch. Needs either a
scheme check or a reviewed `# nosec`. Backend's call.

### 3. Pre-existing: `secrets` check fails on its own branch
Fake credentials in security's own `tests/test_security_check.py` fixtures.
Not integration-caused — fails identically on `security-hardening` alone.
Security team to add a fixture allowlist.

## PRIVACY GUARDRAIL — the new board must not go live

Zach's constraint: the new animated board stays private until he approves.
Audited every publish path in the integrated build.

**Verdict: no automatic path exists from the new board to Discord or the web.**

| check | result |
|-------|--------|
| `integration` on remote / has upstream | **no** — local only, cannot trigger CI |
| cron fires from non-default branches | no — GitHub runs schedules from `main` only |
| new-board files on `origin/main` | **absent** (all 5 verified) |
| `crew.py` imported by `leaderboard.py`/`main.py`/`html_board.py` | **no** — only by manual `scripts/render_crew_board.py` |
| network/publish calls in new-board code | **none** in `crew.py`, `paperdoll.py`, `render_crew_board.py`, `shoot_crew_board.py`, `capture_idle.py` |
| new board writes live artifacts | no — reads `board_state.json`/`roster_cache.json`, writes gitignored `crew_board.html` |
| art assets / manifest committable | no — locally excluded via `.git/info/exclude` |

**The existing live board is untouched and separate.** Its path is
`leaderboard.py` → `main.py` → `html_board.generate_web_board()` →
`site/index.html` → gh-pages. `html_board.py` has zero references to
`crew`/`paperdoll`/`crew_deck`. Live Pages target is real and enabled:
`https://bzach10.github.io/wow-guild-board/`, cron Tue 13:00 UTC from `main`.

The two Discord vote workflows are `workflow_dispatch` only; `redesign-vote`
additionally requires `dry_run == false` **and** `confirm == 'POST'`.

### The one footgun
`scripts/render_crew_board.py` takes `--out`, and its own docstring shows
`--out site/index.html`. Pointing it there before a weekly run would publish
the new board publicly. Nothing does this automatically — but the suggestion
sits in the usage line. Recommend removing it from the docstring and/or
having the script refuse to write into `site/`.

### Merge-to-main consequence
`weekly-board.yml` runs `pytest` before posting. Merging integration to
`main` while `test_security_check` fails would **block the live weekly
post**. Fails safe (nothing leaks), but it would silently break the existing
board. Fix the workflow injection before any main merge.

## Trial build (private, local)

Rendered in `C:/wt/int` from real guild state:
`crew_board.html` + `previews/*.png` (8 shots: 3 desktop themes, 2 mobile,
2 interactions, 1 scene). All paths gitignored. Verified paper-doll
**`mode=layered`, 5 layers** for all 3 characters that have art; 7 of 10
crew still show silhouettes (no art generated yet).

## Contract conformance

**Corrected from the previous snapshot.** Against the Art team's real
`cast_manifest.json`, the pipeline conforms and works end to end: the
manifest publishes v2 (`layers[]` + `canvas`) *and* retains v1 `board`, so
frontend renders `mode=layered`. The earlier "feature is inert" reading came
from testing with a synthetic backend-written entry, not the real artifact.

**Real defect — backend's writer silently destroys the layer data.**
`cast_manifest.record_style_result()` replaces the whole style entry, so a
regen over a v2 entry drops `layers` and `canvas`:

```
BEFORE: version=2  layers=5  canvas=True
AFTER : version=3  layers=0  canvas=False
```

No error; the board just degrades to flat cut-outs and the paper-doll dies.
Latent today — the only caller is `scripts/weekly_cast_refresh.py`, which is
in no workflow, and its scheduled task (`WoWGuildBoard-WeeklyCastRefresh`)
is **not installed** on this machine. It arms the moment someone runs
`scripts/setup_cast_refresh_task.ps1`. Backend owns the fix: preserve
unknown keys instead of overwriting.

`LAYER_CONTRACT.md` (frontend, tracked) and `LAYER_CONTRACT_frontend.md`
(untracked, primary worktree) are two copies of one contract. The tracked
doc names the art pipeline as owner. Needs one canonical home.

## Risks

1. **The Art pipeline is deliberately outside git.** `.git/info/exclude`
   marks `cast_manifest.json` and `cast/*-*/` as "local sandbox copies of
   the pipeline session's files (never commit)". This is intentional, and it
   is what makes the privacy guarantee airtight — but it also means the sole
   producer of the layer contract, plus all its art, exists only in one
   working directory with no backup and no CI visibility. Worth confirming
   the posture is still right now that two teams depend on it.
2. **The primary worktree's green run is not reproducible.** Its 168-test
   pass included untracked tests. CI sees 127. `backend-data-qa` commits
   most of them; the gap is art-pipeline tests.
3. `frontend-crew-ui` moved during this pass (52fbbea → aa250d0). Re-merge
   before any ship.

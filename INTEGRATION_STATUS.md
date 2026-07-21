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

## Contract conformance

**`cast_manifest.json` — v1/v2 split, feature currently inert.**

- Backend's `record_style_result()` writes v1 flat:
  `{board, forms, version, generated_at, source_render}`. No `layers[]`.
- Frontend's `paperdoll.assemble()` reads v2 `layers[]`, and falls back to
  the flat `board` — so this **degrades, it does not crash**. Verified.
- Net: the board renders, but paper-doll layering — the point of the
  front-end and art work — never activates. Nothing in the committed tree
  writes `layers[]`. Every `layers` reference in tracked code is a consumer.

**The only v2 producer is untracked.** `scripts/overnight/publish.py` in the
primary worktree emits conforming v2 (`slot`/`src`/`anchor`/`z`, `canvas`,
`version: 2`) — and is not in git, on any branch. See risk below.

`LAYER_CONTRACT.md` (frontend, tracked) and `LAYER_CONTRACT_frontend.md`
(untracked, primary worktree) are two copies of one contract. The tracked
doc names the art pipeline as owner. Needs one canonical home.

## Risks

1. **The Art/Animation pipeline has no branch and no commits.** It exists as
   untracked files in the primary worktree on one machine: the v2 publisher,
   the `cast/` assets, and 6 test files. It is the sole producer of the
   layer contract two other teams build against, and one `git clean` from
   gone. **Highest-priority item in the program.**
2. **The primary worktree's green run is not reproducible.** Its 168-test
   pass included those untracked tests. CI sees 127. `backend-data-qa`
   commits most of them; the gap is art-pipeline tests.
3. `frontend-crew-ui` moved during this pass (52fbbea → aa250d0). Re-merge
   before any ship.

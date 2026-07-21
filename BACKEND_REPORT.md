# Backend & Data-Quality Report

Branch: `backend-data-qa` (worktree `C:/wt/bdq`) · 8 commits · 168 → 230 tests, all green

Everything below was verified against live APIs or measured, not inferred. Where I
could not verify something, it says so.

---

## Executive summary

Four defects were found, all of them silent — nothing in the pipeline logged an error
for any of them, and the existing 168-test suite passed through all four.

| # | Defect | Impact | Status |
|---|---|---|---|
| 1 | `rsplit("-", 1)` on roster entries | **48% of the roster never fetched** | Fixed + 26 tests |
| 2 | Raider.io scores published as WCL parse percentiles | Board showed **"456%"** parses | Fixed + 6 tests |
| 3 | Fingerprint ignored spec/race/class/gender | Respecced characters kept stale art forever | Fixed + 13 tests |
| 4 | Whole Blizzard/cast subsystem untracked in git | 20 files one `git clean` from gone | Committed |

Plus a measured **1.68× speedup** on the data fetch (~96s off a full run) and real
Python packaging (buildable, installable wheel).

**Data verdict:** the identity data you *do* have is correct — race, class, spec, gender
and realm for all three cast members match live Raider.io exactly. The problem was never
wrong values; it was **missing** members and **mislabelled** numbers.

---

## 1. Backend correctness

### What is solid

- **Blizzard OAuth** — textbook client-credentials grant, mirrors the WCL implementation.
- **Fail-open design throughout.** `load_manifest`, `load_profile_cache` and
  `refresh_profile_cache` all degrade to empty/cached rather than crashing. A corrupt
  JSON file cannot take down a scheduled run. This is genuinely well done.
- **Double-gated Blizzard integration.** `blizzard.enabled` *and* both env secrets must
  be present. It is a true no-op until deliberately switched on.
- **`generate_cast.py` refuses to invent data.** If the profile cache is empty it prints
  why and exits 0. Given that the whole point is real characters, this discipline is right.
- **Manifest versioning + history.** `record_style_result` bumps the version and pushes
  the previous entry to history, so a bad regeneration is recoverable. All three
  manifest entries' image paths resolve on disk.

### What was fragile

**The `_get()` 404-to-`None` contract.** `blizzard.py:59` converts 401/403/404 into
`None`, and `fetch_roster_profiles` silently omits those characters. That is reasonable
per character — but with no aggregate logging, a systemic fault looks identical to "a
few people transferred realms". This is precisely what hid defect #1 for the entire life
of the module. `fetch_roster_profiles` now logs the miss count.

**Coverage gaps.** The pre-existing suite tested happy paths thoroughly but no
cross-module contracts. Proof: I reverted the split fix and re-ran — **all 168 original
tests still passed**. The 62 new tests are concentrated exactly where the contracts sit.

**Not verifiable here:** the live Blizzard OAuth + profile path. No
`BLIZZARD_CLIENT_ID`/`BLIZZARD_CLIENT_SECRET` in this environment and
`blizzard_profile_cache.json` does not exist on disk, so the Blizzard client is covered
by mocked tests only. **Someone with the credentials should run
`scripts/refresh_blizzard_profiles.py --force` and then
`scripts/validate_data.py --live`** — that is the one untested seam, and defect #1 means
it has almost certainly never fetched more than ~70 of the 135 members.

---

## 2. Data accuracy

### Ground truth: identity data is correct

Cross-checked every cast member against Raider.io's live public API:

| Character | race | class | spec | gender | realm |
|---|---|---|---|---|---|
| `rakdisc-proudmoore` | Nightborne ✓ | Priest ✓ | Discipline ✓ | Female ✓ | proudmoore ✓ |
| `floofwall-queldorei` | Pandaren ✓ | Monk ✓ | Brewmaster ✓ | Male ✓ | queldorei ✓ |
| `healyeah-queldorei` | Dracthyr ✓ | Evoker ✓ | Augmentation* | Male ✓ | queldorei ✓ |

`rakdisc`'s stored render URL carries render id `243420911`, matching the id in
Raider.io's current thumbnail — the transmog reference is genuine and current.

\* **Live drift caught during this work.** `healyeah` read `Augmentation` on the first
check and `Preservation` about twenty minutes later — the player respecced mid-session.
That is not a bug, it is the thing the fingerprint has to notice, and defect #3 meant it
would not have.

### Defect 1 — 48% of the roster silently dropped 🔴

`blizzard.py:116` and `voyage.py:144` split roster entries on the **last** hyphen.
Entries are `name-realm-slug` and most realm slugs are hyphenated:

```
"dathar-area-52"  →  rsplit: name="dathar-area", realm="52"     ✗
                     split:  name="dathar",      realm="area-52" ✓
```

Verified live against Raider.io:

| entry | `rsplit` (was) | `split` (now) |
|---|---|---|
| `dathar-area-52` | HTTP 400 | HTTP 200 → Orc Warrior |
| `beroben-emerald-dream` | HTTP 400 | HTTP 200 → Gnome Mage |
| `glinkz-wyrmrest-accord` | HTTP 400 | HTTP 200 → Dwarf Mage |

**65 of 135 members (48%)** were affected. Non-200 means "skip this character", so they
vanished with no error and no log line.

The tell: all three characters that reached the manifest are on *single-token* realms
(proudmoore, queldorei) — the only ones the old split handled. The bug shaped your cast
and looked like it was working.

`raiderio.py` already had this correct. Three copies of the same rule had drifted apart;
there is now one, `config.split_name_realm()`, and all three call it.

### Defect 2 — fabricated parse percentages 🔴

`collect_mplus_wcl_parses()` claimed to fetch Warcraft Logs parse percentiles. It never
contacted WCL — it re-queried Raider.io (its `token` argument was unused), took
Raider.io's dungeon **score**, and tagged it `is_wcl=True`. `formatters.py:391` renders
anything so tagged with a percent sign:

```
🥇 Rakdisc (Discipline Priest) — 456% on Skyreach
```

A parse percentile is 0–100 by definition. Checked against a real character: **all 8**
of their best runs scored above 100, so every enriched line was wrong.

Second defect in the same function: it looked every character up on the *guild's* realm
slug regardless of their actual realm, so cross-realm members either missed or matched a
same-named stranger.

Now returns `[]` and says so. The caller's Raider.io results already carry
`is_wcl=False` and render correctly as `"<n> score"` — the board loses nothing true and
stops showing something false, and skips 15 redundant requests per run.

`WCL_MPLUS_QUERY` (defined in that module, never used) is what a real implementation
should drive. Left in place with a docstring pointing at it. **Real WCL M+ parse
enrichment is unimplemented** — worth knowing if the board is presented as showing them.

### Defect 3 — the fingerprint gated on the wrong inputs 🟠

`compute_transmog_fingerprint` decides whether to spend GPU time regenerating art. It
was wrong in both directions:

- **Under-sensitive (main path):** with a render URL it hashed *only* that URL. But
  `build_prompt()` also reads race, class, gender and `active_spec`, so a respecced
  character kept art built from their old spec's prompt indefinitely.
- **Over-sensitive (fallback):** with no render URL it hashed the *entire* profile dict,
  keying on incidental fields like `name`, so unrelated churn burned GPU time.

Two of three cast members (`floofwall`, `healyeah`) have an empty `render_url` and were
on the fallback path.

Now hashes exactly `ART_INPUT_FIELDS` — the transmog URL plus the four prompt fields —
and accepts the manifest's `spec` as an alias for the profile's `active_spec`.

**One-time cost:** this changes the digest for all three existing entries, so the next
`weekly_cast_refresh` regenerates all three. Unavoidable for any fix here, and two of
the three had a wrong-basis fingerprint to begin with.

### Open data issues (not fixed — they need your decision)

1. **Two of three cast members have an empty `render_url`.** Their art was generated
   without the IP-Adapter likeness reference, so it is prompt-only — it does not look
   like their actual transmog. Raider.io shows both *do* have live renders (ids
   `246827877`, `246412670`). Re-running the refresh with defect #1 fixed should populate
   them. Flagged as a warning by the validator.
2. **`cast_manifest.json` has 3 of 135 members.** Expected if the cast is deliberately a
   pilot; worth confirming that is intentional rather than the roster having been
   silently thinned by defect #1.
3. **`roster_cache.json` is from 2026-07-18 and contains obvious duplicates** —
   `tommybravo`/`tommybravoo`/`tommybravox`/`tommybravoxx`, `aiime`/`aime`/`aimme`,
   `shadoxi`/`shadoxii`. These are probably alts. If the cast is meant to be one entry
   per *player*, there is no alt-mapping anywhere in the codebase; you would need one.

### The validator

`scripts/validate_data.py` — checks the failure classes actually found here, not
hypothetical ones:

```
python scripts/validate_data.py          # offline: roster, manifest, profiles, drift
python scripts/validate_data.py --live   # + cross-check identity against Raider.io
```

Exit 0 clean, exit 1 on any error; warnings do not fail the run, so it is CI-safe as-is.
It catches a regression of defect #1 by flagging a hyphen landing in a character *name*.
Current output on real data: 1 error (the `healyeah` respec), 4 warnings.

**Recommend wiring it into CI** and into `weekly_cast_refresh.py` before generation, so
bad data is caught before it costs GPU time.

---

## 3. Optimization

### Measured and applied: pooled connections + shared rate limiter

Every Raider.io call used module-level `requests.get` — a fresh TCP+TLS handshake per
request — then slept a hardcoded 0.3s. Measured on the real code path, 20 roster members:

| | 20 members | extrapolated to 135 |
|---|---|---|
| before (`requests.get` + `sleep(0.3)`) | 11.74s | 79.2s |
| after (pooled session + 3/s limiter) | **6.97s** | **47.1s** |
| | **1.68×** | **32s saved per pass** |

The pipeline makes three full roster passes per run → **~96s off a run**, at a
*better-behaved* request rate than before.

The old `sleep(0.3)` was a latency floor, not a rate limit: it ignored request duration
and could not be shared, so three collectors in one run could stack to 3× the intended
rate. `guild_board/http.py`'s `RateLimiter` is a token bucket over wall-clock time
capping *aggregate* throughput.

### Recommended, not applied

**A. Collapse three roster passes into one — 3×, no rate-limit risk.**
`collect_mplus`, `collect_mplus_season_scores` and `collect_mplus_raiderio_season_runs`
each walk the full roster requesting different `fields`. Raider.io accepts them combined
in a single request — I verified all three field groups come back from one call:

```
fields=mythic_plus_weekly_highest_level_runs,mythic_plus_scores_by_season:current,mythic_plus_best_runs
→ HTTP 200, all three present
```

One pass feeding all three collectors: **~47s → ~16s**. Not applied because it means
restructuring three public collectors, which is exactly the kind of change that wants
review rather than a drive-by. Highest value-to-risk ratio remaining.

**B. Rate-limited concurrency — 1.8× on top of A.** Measured:

| config | 135 members | safe? |
|---|---|---|
| serial (today, after fix) | 47.1s | yes |
| 4 workers @ 3 req/s | 42.9s | yes |
| 5 workers @ 5 req/s | 25.8s | at the published limit |
| 5 workers, unthrottled | 3.4s | **no — 40 req/s, 8× over the limit** |

My first benchmark reached 40 req/s and I nearly reported it as a 25× win. It is not
usable: Raider.io publishes 300/min. Being throttled costs far more than the seconds
saved. If you want concurrency, 4 workers @ 3–4 req/s is the honest ceiling, and the
`RateLimiter` already supports it.

**C. Latent N+1 in the Voyage Map.** `fetch_dungeon_island_data` scans the entire roster
*per dungeon*. Today `render_voyage_map.py` only fetches the current island, so it is
135 requests. The moment the front-end populates all 10 islands it becomes **1,350
requests (~15 min)**. One roster pass can answer all 10 dungeons — the data is identical.
**Worth telling the web-runtime team before they wire up all islands.**

### Not profiled

Generation throughput and web render. Generation needs a live ComfyUI + GPU, which is
not available in this environment; the `cast_art` docstring already documents the
tiled-VAE finding (a plain `VAEDecode` hung under tight VRAM while tiled did not), which
is the kind of thing that matters most there. Web render is the web team's surface.

---

## 4. Code quality & packaging

**Packaging (done).** `pyproject.toml` had only pytest settings. Now full `[project]`
metadata, builds a wheel, and **verified to install clean in a fresh venv** — imports
resolve, templates ship via `package-data`. Dependencies gained upper bounds (an
unbounded `>=` lets a major release break a scheduled run silently). Playwright moved to
an optional `[render]` extra since the data pipeline does not need it.
`requirements.lock.txt` records the exact versions the 230-test suite is green on.

**Lint.** ruff configured; **54 findings**, all cosmetic — 13 redundant open modes, 11
unsorted imports, 7 ambiguous names. I autofixed only the backend modules this branch
owns; they pass clean. `html_board.py`, `formatters.py`, `board_image.py` and `theme*.py`
are deliberately untouched — the web and art teams have those open and an
import-ordering sweep would produce nothing but merge conflicts.

I checked the two `F841 unused-variable` hits rather than trusting the autofix, since a
computed-but-unwired graph node would be a real bug. `render_pipeline`'s `canvas` and
`last_lora_node` are both genuinely dead assignments — the LoRA chain is carried
correctly by `model_link`/`clip_link`. **No latent bug behind either.**

**Structural debt worth addressing (not done — needs coordination):**

- `board_image.py` is 1,181 lines and `test_guild_board.py` is 1,782. Both want splitting,
  but both are shared surfaces.
- `leaderboard.py.bak` — an 80k-line backup file committed to the repo. Should be deleted;
  git already has the history.
- Circular-ish imports: `raiderio` imports from `config`, and three functions inside
  `raiderio` do `from guild_board.config import resolve_roster` *at call time* to dodge a
  cycle. Worth untangling properly.
- No type annotations anywhere. mypy is configured permissively so it runs today; tighten
  per-module as annotations land.

---

## 5. Downloadable app — feasibility

**Recommendation: two-part product. Do not wrap the generator in a desktop shell. Not yet
— and probably not ever in the form the question implies.**

### The core problem

Image generation needs a local GPU, ComfyUI, and roughly **10 GB of models**
(Illustrious-XL ~6.5GB, CLIP-ViT-H ~2.5GB, IP-Adapter ~700MB, LoRA, upscaler). No
desktop framework changes that. Tauri vs Electron is a ~10MB vs ~100MB argument attached
to a 10GB payload — **the framework choice is nearly irrelevant to the actual difficulty.**

You also cannot legally or practically redistribute most of those checkpoints. A bundled
installer would have to download them post-install from upstream, which means you own
the failure modes: dead links, license changes, checksum drift, and a 10GB first-run
download on a user's connection.

### The asymmetry that decides it

- **The creator** (fetch → prompt → ComfyUI → manifest) is GPU-bound and run by
  essentially **one person** — the officer running the weekly job.
- **The board** is the thing 100+ guild members actually consume, and it is *already*
  static HTML.

Packaging a 10GB GPU application to serve an audience of one is a bad trade. The
shareable artifact is already shareable.

### Recommended architecture

1. **Creator stays a local Python app.** It already is one, driven by Task Scheduler.
   The wheel from this branch makes it `pip install`-able. If it needs a face, a small
   local web UI (Flask/FastAPI + the existing Jinja templates) costs days, not weeks, and
   reuses the rendering you already have.
2. **Board ships as static output.** Already the case. Publish to GitHub Pages or any
   static host. Zero install for the guild.
3. **ComfyUI stays a user-installed prerequisite**, detected at `127.0.0.1:8188` — which
   is exactly what `generate_cast.py` already does. Document it; do not bundle it.

### If you build a desktop shell anyway

Tauri over Electron — smaller, and the Python backend is a sidecar process either way, so
Electron's Node ecosystem buys you nothing here. Rough effort, assuming the pipeline is
already working:

| Piece | Estimate |
|---|---|
| Tauri shell + Python sidecar packaging | 1–2 weeks |
| ComfyUI detection / install guidance / health UI | 1 week |
| Model download manager (resume, checksums, licences) | **2–3 weeks — the real cost** |
| Auto-update for app *and* model set | 1–2 weeks |
| GPU/VRAM detection + graceful degradation | 1 week |
| **Total** | **6–9 weeks**, plus ongoing maintenance |

### Honest opinion

Six to nine weeks to give one person a window around a script that already runs, while
the artifact your guild actually looks at is already a static page. **The effort is
better spent on the board itself** — which is where every other team on this project is
already pointed.

Revisit if either changes: multiple guilds want to self-host their own creator (then the
model-download manager earns its keep), or generation moves to a hosted GPU (then the
local-GPU constraint disappears and a thin desktop or web client becomes easy).

---

## Coordination notes for the other teams

**Web-runtime team**
- `cast_manifest.json` schema is unchanged — no front-end changes needed from this branch.
- `transmog_fingerprint` values all change once; if anything caches on fingerprint, expect
  one invalidation.
- **Before you populate all 10 Voyage islands, read §3C** — the current call pattern
  becomes 1,350 requests. Ask for the batched version first.
- M+ season lines will render `"<n> score"` where some previously rendered `"<n>%"`. The
  percentages were wrong; this is the fix, and it may shift layout.

**Art team**
- Two of three cast members were generated *without* the IP-Adapter reference (empty
  `render_url`) — that art is prompt-only and does not reflect their transmog. Worth
  regenerating once the profile refresh is re-run.
- The next `weekly_cast_refresh` regenerates all three (fingerprint change). One-time.
- `styles/one_piece.yaml` was untracked; it is now committed on this branch because
  `test_styles.py` silently depends on it.

**Everyone**
- 20 backend files were untracked. They are committed on `backend-data-qa` as commit
  `4d86d24`, byte-for-byte unchanged, so nothing is lost — but until this branch merges,
  the copies in the main working tree remain the only ones. **Do not `git clean` the main
  worktree.**

---

## Commits

```
fec0561  Apply ruff autofixes to the backend modules
901814e  Drop build artifacts from the tree and gitignore them
cf5f575  Set up real Python packaging: buildable wheel, bounded deps, tool config
6badeb5  Pool HTTP connections and share one rate limiter across collectors
0a3b67d  Stop publishing Raider.io scores as Warcraft Logs parse percentiles
ee55368  Add scripts/validate_data.py: a data-quality gate for the pipeline
f16dfab  Fingerprint every generation input, not just the transmog URL
bd805ac  Fix name/realm split that silently dropped 48% of the roster
4d86d24  Preserve the untracked Blizzard/cast subsystem as a reviewable baseline
```

Every behavioural fix is paired with tests that fail against the original code — verified
by reverting each fix and confirming the new tests catch it (16 failures for the split
bug, 2 of 2 for the parse mislabelling).

---

## 6. Generation throughput

See [THROUGHPUT_ANALYSIS.md](THROUGHPUT_ANALYSIS.md) — measured from the art team logs,
no generations launched. Summary: the pipeline already caches shared layers, so the full
roster is ~60-140 min (not per-character); the largest safe win is parallelising the
CPU-only compositing step (~25 min saved, byte-identical output); cloud GPU is cheap but
the setup does not pay back yet.

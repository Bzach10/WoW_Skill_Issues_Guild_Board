# Generation Throughput Analysis

For the art team. Source: `logs/overnight_build.log` (two runs; the complete one is
03:44:58→03:57:32Z), `logs/overnight_state.json`, and `scripts/overnight/`.

**No generations were launched for this analysis.** The batch had already finished
(36 generated, 0 failed) when I read the logs — read-only throughout.

---

## The headline: this is already a shared-layer cache

The pipeline does **not** render one image per character. It renders a **matrix**:

```
body:<race_gender>              6 generated   (nightborne_female, pandaren_male, …)
gear:<race_gender>/<kit>       36 generated   (6 race_genders × 6 kits)
char:<slug>                     3 generated   (composite + idle.gif)
```

`overnight_state.json` checkpoints all 45 artifacts, so bodies and gear are **generated
once and reused by every character who shares them**. Cost scales with *distinct
race_gender combinations*, not headcount.

That is the most important fact for planning, and it is already built. Credit where due —
it is the right architecture.

---

## 1. Measured per-asset time

| Asset | Measured | Notes |
|---|---|---|
| One 832×1216 layer @ 30 steps | **15s** | pipeline's own smoke test |
| Body generation | ~10s | task start → `body … ->` line |
| Gear set (1 generation → 5 crops) | **19s median** (14–29s, n=32) | the 5 slot PNGs are crops of one render |
| Character composite + idle.gif | ~13s | **CPU/PIL only — no GPU** |
| Complete run | **754s (12.6 min)** for 36 assets | ≈21s/asset wall |

Current settings: Illustrious-XL + one_piece_wano LoRA, 832×1216, **steps=30**, cfg=6.5,
`dpmpp_2m`/`karras`, `VAEDecodeTiled` 512/64, `batch_size=1`, 3s pause between assets.

## 2. Full-roster estimate at current settings

`R` = distinct race_gender combos across 135 members, 6 kits:

| R | GPU (bodies+gear) | CPU (composites) | **Total** |
|---|---|---|---|
| 15 | 31 min | 29 min | **60 min** |
| 25 | 52 min | 29 min | **81 min** |
| 35 | 72 min | 29 min | **102 min** |
| 54 (every race×gender) | 112 min | 29 min | **141 min** |

**≈1–2.5 hours for the whole roster** — not the ~2h+ a naive per-character model predicts.
With the 6 race_genders already cached, the incremental build is ~69 min at R=25.

**Caveat:** I cannot pin `R` exactly. `blizzard_profile_cache.json` does not exist, so
nobody has race/gender for the other 132 members — and the `rsplit` defect (report §2)
meant the fetch that would populate it was dropping 48% of the roster. **Run the fixed
profile refresh and `R` becomes an exact count instead of a range.**

## 3. Safe speedups, highest value first

### A. Parallelise the composites — ~25 min saved, zero quality risk ⭐

`compose.py` is pure PIL (24 GIF frames, `alpha_composite` + LANCZOS). It never touches
the GPU, yet runs serially inside the GPU loop. At 135 characters that is **29 minutes of
single-threaded CPU work on a 16-core box**. A `multiprocessing.Pool` drops it to ~3–4 min.

Deterministic image ops — byte-identical output. **Do this first; it is free.**

### B. Steps 30 → 22–24 — potentially ~25% off GPU time, must be A/B'd

`dpmpp_2m` is a 2nd-order solver; on karras it typically converges well before 30 steps at
SDXL sizes. At R=25 that is 52 → ~39 min.

**I have not verified this on your model/LoRA and will not assert it blind.** Run one gear
set at 20/24/30 with a fixed seed (~1 min total) and compare. You already ran exactly this
kind of sweep for LoRA strength and denoise, so the harness exists.

### C. Batch the 6 kits per race_gender — ~2–5 min

Gear median is 19s but measured compute is ~15s; the ~4s delta is per-job setup. The 6 kits
for one race_gender share checkpoint, LoRA and base body, so they can go as one submission
(or back-to-back without teardown). Scales with the matrix, so it grows with `R`.

### D. Make the 3s inter-asset pause conditional — ~10 min at full scale

`throttle()` already hard-pauses 90s under real memory pressure, but the 3s floor is
unconditional. At ~200 tasks that is 10 minutes of deliberate idling. Gate it on the same
RAM check.

### E. Do not touch `VAEDecodeTiled`

It looks like an easy win to swap for plain `VAEDecode`. `cast_art.py` documents that a
plain decode **hung indefinitely** under tight VRAM while the tiled one did not. Leave it.

**Combined A + B + D at R=25: ~81 min → ~45 min**, with only B needing validation.

---

## ⚠️ RAM is the constraint, not VRAM

VRAM sat steady at 5928/16375 MB free all run — never the bottleneck.

**RAM ran at 3.1–5.2 GB free of 31.9 GB**, and the pipeline logged *"RAM is thin —
throttling"* at startup. `throttle()` pauses **90s** below 800 MB free.

The completed run was only 12.6 min. A full-roster run is 5–8× longer, so any slow
accumulation invisible tonight has far more room to bite — and each trip below the
threshold costs 90s. The engine already snapshots RAM every cycle (`engine.py:119`);
**watch that number for downward drift across the first long run.** This is the most
likely cause of a full-roster build overrunning its estimate.

---

## 4. Cloud GPU — feasible and cheap, but not worth it yet

The GPU work is embarrassingly parallel: each `(body + its 6 kits)` is independent, so it
shards by race_gender with no coordination.

| | |
|---|---|
| Rate (RTX 4090, RunPod/Vast community tier) | **~$0.25–0.70/hr** |
| GPU work per full build (R=25) | ~52 min ≈ **1 GPU-hour** |
| **Cost per full roster build** | **~$0.40–0.70** |
| Wall time, 4 pods + local card | ~52 min → **~10–13 min** |
| First-time setup | **2–4 hours** |

Setup is the real cost, not compute. ComfyUI + Illustrious-XL + LoRA + VAE is ~10 GB per
pod, needing either a RunPod network volume (~$0.07/GB/month, persists between runs) or a
baked template, plus job dispatch and artifact retrieval. Reproducibility also needs care —
same checkpoint hash, same LoRA, same seeds, or shards will not match visually.

**Verdict: not worth it for a one-time 60–100 min build the local card does overnight for
free.** Spending 2–4 hours of setup plus ongoing complexity to save ~40 minutes of
*unattended overnight* time is a bad trade.

**It flips if either happens:** the team starts iterating full-roster restyles repeatedly
(every re-render is another 60–100 min, and setup amortizes fast), or someone needs
same-day turnaround on a style change. The sharding is straightforward when that day comes,
because the matrix is already independent by race_gender.

**Do A, B and D locally first** — free, ~45 min saved, no new infrastructure.

---

## Recommendations for the next batch

1. **Parallelise composites** (`multiprocessing.Pool`) — ~25 min saved, no quality risk.
2. **A/B steps at 20/24/30** on one gear set, fixed seed — adopt the lowest that holds.
3. **Batch the 6 kits per race_gender** into one submission.
4. **Gate the 3s pause** on the existing RAM check.
5. **Watch free RAM across the first long run** — likeliest overrun cause.
6. **Run the fixed Blizzard profile refresh first** — it turns `R` from a guess into a
   count, and the current cast art was built without transmog references anyway
   (see report §2).

## Current vs optimized, for Zach

| | Current | Optimized (A+B+D) |
|---|---|---|
| Full roster, R=25 | **81 min** | **~45 min** |
| Full roster, R=35 | **102 min** | **~58 min** |
| Cost | free (local, overnight) | free (local, overnight) |
| Cloud alternative | — | ~12 min, ~$0.50/build, 2–4h setup — **not recommended yet** |

# Where the generation engine plugs in

Written so ComfyUI can be swapped for a different generator — a cloud
API, a different local runtime — without rebuilding the system around it.

**The short version:** the system already has a narrow seam. Everything
downstream of "produce a PNG from a prompt" knows nothing about ComfyUI.
Measured, not assumed:

| | LOC | Knows about ComfyUI? |
|---|---|---|
| `scripts/overnight/engine.py` | 518 | **yes — all of it** |
| `scripts/overnight/driver.py` | 357 | only via `engine` imports |
| `layers / compose / publish / hero / compare_transmog` | 718 | **no** |

A swap touches one file plus the four call sites in `driver.py`.

---

## 1. The seam

Every generation call in the pipeline is one of two shapes:

```
text_to_image(prompt, negative, seed, w, h)                    -> [png paths]
image_conditioned(ref_png, prompt, negative, seed, strength)   -> [png paths]
```

That is the entire generation contract. Everything else in the system —
layer extraction, compositing, the rig, the manifest, the runtime
verification — consumes **PNG files on disk** and has no opinion about
where they came from.

A replacement backend needs to satisfy this interface:

```python
class GenerationBackend(Protocol):
    def healthy(self) -> bool: ...

    def text_to_image(self, prompt: str, negative: str, seed: int,
                      width: int, height: int, **opts) -> list[Path]: ...

    def image_conditioned(self, ref_image: Path, prompt: str, negative: str,
                          seed: int, strength: float,
                          end_percent: float, **opts) -> list[Path]: ...
```

Three methods. That is the whole port.

---

## 2. What is ComfyUI-specific and dies with the swap

Inside `engine.py`, only these are actually Comfy concepts:

| Thing | Lines | Fate on a cloud API |
|---|---|---|
| HTTP endpoints (`/prompt`, `/history`, `/queue`, `/system_stats`) | ~60 | replaced by the vendor SDK |
| Graph JSON (`class_type` node dicts) | ~150 | **deleted** — cloud APIs take params, not graphs |
| Output collection from a shared output dir | ~10 | replaced by download-response-bytes |
| Recovery ladder (kill backend, launch desktop app, verify) | ~110 | **deleted entirely** |
| Keep-awake process | ~25 | **deleted entirely** |

**~300 of the 518 lines exist only because generation runs locally.** A
hosted generator removes the hang/restart failure class by construction,
along with the watchdog, the one-shot latch, and the keep-awake holder.

## 3. What is NOT engine-specific but currently lives in `engine.py`

These should be split out **before** any swap, so they survive it:

* `log()` / `alert()` — run logging
* `load_state()` / `save_state()` / `mark_done()` / `mark_failed()` —
  the checkpoint/resume system
* `resources()` / `log_resources()` — telemetry (VRAM half becomes
  meaningless on a hosted backend; RAM half stays useful)

Suggested shape:

```
scripts/overnight/
    run_state.py          logging + checkpoint      (engine-independent)
    backends/
        base.py           the Protocol above
        comfy.py          today's implementation
        <vendor>.py       the replacement
    driver.py             picks a backend, orchestrates
```

## 4. Engine-independent and fully preserved

None of this is affected by the tooling decision:

| Asset | Where | Value |
|---|---|---|
| Layer/anchor contract | `LAYER_CONTRACT_frontend.md`, `C:\wt\fc\guild_board\paperdoll.py` | canvas, z-order, bones, pivots — already consumed by the shipped runtime |
| Layer extraction | `layers.py` | base+gear → aligned transparent slots; pure PIL/numpy |
| Compositor + idle rig | `compose.py` | imports the runtime's own constants, so it cannot drift |
| Manifest + runtime verify | `publish.py` | writes v2 layers, proves the real runtime accepts them |
| Hero prop placement | `hero.py` | anchors props to measured head position |
| Comparison harness | `compare_transmog.py` | real-vs-doll decision artifact |
| Generated assets | `cast/_gear` (36 sets), `cast/_bodies` (6), `cast/_approved` (4) | ~150 MB |
| Checkpoint | `logs/overnight_state.json` | 45 entries; resume is free |
| `cast_manifest.json` | repo root | v2 layered entries for 3 roster characters |

---

## 5. Selection criteria for the replacement — in priority order

### 5.1 Image-structure conditioning is MANDATORY

The paper-doll approach works because a gear render is generated **from
the base body's own edge map**, so both describe the same body at the
same pixels and the difference between them is extractable as an aligned
garment layer.

Without structure conditioning there is no alignment, and without
alignment there are no layers — the whole paper-doll architecture
collapses back to flat per-character pictures.

Measured on the current stack: ControlNet canny at strength 0.85 holds
silhouette IoU **0.98** and head IoU **0.965** between base and gear
render. **Any candidate must demonstrate equivalent structural lock.**
Vendor terms for this vary — "structure reference", "control image",
"ControlNet", "composition reference". Verify it empirically; do not
trust the marketing name.

### 5.2 Custom LoRA support — the biggest migration risk

The entire established art style is `one_piece_wano_style.safetensors`
on Illustrious-XL-v1.1, at strength 0.40 (a value tuned in this session —
0.75 produced unusable elongated anatomy).

**Most hosted APIs will not load a third-party LoRA.** If the replacement
cannot, the art style changes, and every asset in section 4 must be
regenerated in the new style. That is not a blocker, but it is a
re-baseline of the entire look and Zach should agree to it deliberately
rather than discover it.

### 5.3 Content filtering

Base-body prompts describe figures in minimal clothing by design (the
base is only ever seen where gear fails to cover it). Some hosted
providers refuse or silently alter such prompts. Test this early — it is
a common late surprise.

### 5.4 Cost and latency at roster scale

Current local cost: **~15s per 832×1216 render, zero marginal cost.**
A full character is ~1–2 min of GPU. For a 100-character roster with
hero props, budget ~5–8 renders per character. Per-image pricing and
rate limits should be checked against that number.

---

## 6. A tension worth surfacing before the stack is chosen

"Anime-studio-grade animation" and the paper-doll architecture pull in
**opposite directions**.

The shipped runtime animates a **bone rig**: layers are rotated about
pivots by CSS transforms, 120 characters at 59.9 fps, degrading to a
static image with JS off. It animates because the character is *layers*.

A video-generation pipeline produces **flat frames** — an MP4, not a
riggable stack. Going that way means the layer contract, the pivots, the
bones, and the paper-doll extraction all become dead weight, and per-
character animation becomes a per-character render cost rather than a
free CSS transform.

Both are defensible. They are not compatible. Choosing "studio-grade
animation" without deciding this explicitly would quietly discard the
architecture in section 4.

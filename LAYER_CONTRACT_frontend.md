> **UPDATE 2026-07-21 — two breaking-ish additions, both back-compatible.
> Read this block if you read nothing else.**
>
> **1. Headgear was impossible.** `face` sat at the top of the head stack
> (z=61), so mitres/helms/hoods were drawn underneath it and occluded.
> There is now a **`headgear` slot at z=65, above `face`**. Ship headgear
> in that slot. It rides the `head` bone, so hats nod with the head.
>
> Please ALSO make `face` a **tight facial mask** — features only, on
> transparency — not a full-head crop. The new slot fixes occlusion of
> headgear, but a head-shaped `face` plate will still cover hair and the
> head silhouette that `head` (z=60) carries underneath.
>
> **2. Props were being stretched.** Every layer used to be stretched to
> the full 832×1216 body canvas, so a square-authored mitre or staff came
> out tall and thin. Props now declare their own square region:
>
> ```json
> {"slot": "headgear", "anchor": {"x": 208, "y": 0},
>  "size": {"w": 416, "h": 416}, "pivot": {"x": 416, "y": 365}, "z": 65}
> ```
>
> Applies to **`headgear`, `weapon_main`, `weapon_off`**: author the PNG
> square, declare `size` with equal w and h, position with `anchor`, and
> leave `pivot` in canvas coordinates (the runtime rebases it).
>
> **Recommended headgear box: `anchor {x:208, y:0}`, `size {w:416,h:416}`.**
> Derived from your own pilot art — the `face` layers span x 293–571,
> y 68–264 across Floofwall, Healyeah and Rakdisc, so that square contains
> every head with headroom for a tall hat.
>
> **Nothing you have already shipped breaks.** Existing body layers
> declare no `size` and keep the full-canvas behaviour. A prop without a
> `size` still renders (stretched) and the renderer logs a warning naming
> the slot.
>
> Verified end to end: a mitre and staff rendered on Rakdisc crown her
> head above the face with ears and hair visible, and both props measure
> a 1.000 aspect ratio in the browser. See
> `previews/headgear_check.png`.

# Paper-doll layer/anchor contract — what the web runtime consumes

The art pipeline session **owns** this contract. This document records
what the web runtime currently implements, so the two halves can be
diffed and reconciled. Where they disagree, the pipeline's published
version wins and this side changes.

`guild_board.paperdoll.contract_summary()` returns the machine-readable
version of everything below, and a test asserts the two never drift.

## Canvas

Every layer for a character is authored against one canvas, and all
anchors and pivots are in that canvas's pixels.

```json
"canvas": {"w": 832, "h": 1216}
```

Optional — defaults to 832×1216, matching the pilot renders. Layers are
positioned as percentages internally, so the doll scales to whatever size
the board renders it at.

## Manifest shape (v2, layered)

```json
"styles": {
  "one_piece": {
    "canvas": {"w": 832, "h": 1216},
    "layers": [
      {"slot": "cloak",  "src": "cast/<id>/one_piece/cloak.png",
       "anchor": {"x": 0, "y": 0}, "pivot": {"x": 416, "y": 290}, "z": 10},
      {"slot": "body",   "src": "...", "pivot": {"x": 416, "y": 1050}, "z": 20},
      {"slot": "legs",   "src": "...", "pivot": {"x": 416, "y": 700},  "z": 30},
      {"slot": "chest",  "src": "...", "pivot": {"x": 416, "y": 520},  "z": 40},
      {"slot": "arms",   "src": "...", "pivot": {"x": 416, "y": 370},  "z": 50},
      {"slot": "head",   "src": "...", "pivot": {"x": 416, "y": 300},  "z": 60},
      {"slot": "face",   "src": "...", "pivot": {"x": 416, "y": 300},  "z": 61},
      {"slot": "weapon_off",  "src": "...", "pivot": {"x": 248, "y": 535}, "z": 70},
      {"slot": "weapon_main", "src": "...", "pivot": {"x": 601, "y": 520}, "z": 71}
    ],
    "version": 1,
    "generated_at": "2026-07-21T03:00:00Z"
  }
}
```

### Fields

| field    | required | meaning |
|----------|----------|---------|
| `slot`   | yes | which layer this is (see z-order below) |
| `src`    | yes | repo-relative path to a **transparent** PNG |
| `anchor` | no  | top-left of this layer on the canvas, px. Default `{0,0}` — i.e. full-canvas layers, which is the simplest thing to author |
| `pivot`  | no  | the joint this layer rotates about, px. Defaults per slot |
| `z`      | no  | explicit stacking. Defaults per slot |
| `size`   | props | `{w,h}` of the region this layer occupies, canvas px. Omit for full-canvas body layers; **required for props** (see below) |

### z-order (low to high)

```
background < cloak < body < legs < chest < arms < head < face < headgear < weapons
  (scene)     10     20     30     40      50     60     61      65       70 / 71
```

**CHANGED 2026-07-21 — headgear.** `face` used to be the top of the head
stack at z=61, so any mitre, helm or hood was drawn *under* it and came
out occluded. There is now a dedicated `headgear` slot at **z=65, above
`face`**. This unblocks headgear for the whole cast.

Two rules go together here, and the second one matters even with the new
slot:

1. **`headgear` (z=65)** — mitres, helms, hoods, circlets. Rides the
   `head` bone, so a hat nods with the head.
2. **`face` must be a tight FACIAL MASK, not a full-head crop.** Ship
   only the features — eyes, brows, nose, mouth, facial markings — on
   transparency. If `face` is a full head-shaped plate it will still
   cover the hair and the head silhouette beneath it, and a hood that is
   meant to frame the face will read as sitting behind a floating head.
   `head` (z=60) carries the head, ears and hair.

### Props must be authored SQUARE (headgear + weapons)

**CHANGED 2026-07-21 — prop distortion.** Body layers are authored
full-canvas (832×1216) and the runtime stretches every layer to fill that
frame. A mitre or a staff authored the same way therefore comes out
squeezed into a 0.68:1 portrait box — tall and thin.

Props now declare their own region, and the runtime places them there
instead of stretching them:

```json
{"slot": "headgear", "src": "cast/<id>/one_piece/headgear.png",
 "anchor": {"x": 208, "y": 0},
 "size":   {"w": 416, "h": 416},
 "pivot":  {"x": 416, "y": 365}, "z": 65}
```

Rules for `headgear`, `weapon_main`, `weapon_off`:

* **Author the PNG square** — 416×416 or 512×512, your choice.
* **Declare `size` with equal `w` and `h`.** 416×416 on the 832×1216
  canvas renders as a genuinely square 416px box (50% of width, 34.21% of
  height — different percentages, same pixels).
* Position it with `anchor`, which is the top-left of that square.
* `pivot` stays in **canvas** coordinates. The runtime rebases it into
  the prop's own box, so a hat rotates about the neck rather than about a
  point outside itself.

Omit `size` and the prop still renders — it just falls back to
full-canvas and will look stretched. The renderer logs a warning naming
the slot when that happens.

#### The head box (measured from your own pilot art)

The `face` layers you shipped span **x 293–571, y 68–264** across
Floofwall, Healyeah and Rakdisc. So a 416×416 square at
**`anchor {x: 208, y: 0}`** contains every head with room above it for a
tall hat. That is the recommended headgear region; verified by rendering
a mitre on Rakdisc, where it crowns the head with ears and hair still
visible around it.

The **background is the board's layer, not the character's** — scenes are
composited under the whole cast so they can change while the characters
persist. Do not ship a background layer per character.

### Bones (what the runtime animates)

Each slot maps to a bone. The art never changes; only the transform on
each bone does, so one idle rig drives every character regardless of gear.

| slot | bone | idle motion |
|------|------|-------------|
| `body`, `chest` | `torso` | slow counter-rotation |
| `legs` | `legs` | slight counter-rotation |
| `arms` | `arms` | shoulder swing (±1.6°) |
| `head`, `face`, `headgear` | `head` | counter-bob (±0.9°) |
| `cloak` | `cloak` | trailing drift (±2.6°, 4.6s) |
| `weapon_main` | `weapon_main` | sway (±2.4°, 4.1s) |
| `weapon_off` | `weapon_off` | sway (±2.2°, 4.4s) |

The whole doll also breathes (3.4s bob). Per-character animation delay is
staggered so a line-up never pulses in unison.

**Pivots are what make this read as a rig rather than a slideshow.** A
pivot in the wrong place is the most likely source of "it looks broken" —
arms should pivot at the shoulder line, head/cloak at the neck, weapons
at the grip.

## What the runtime guarantees

Every one of these degrades rather than breaking:

* a layer whose `src` is missing on disk → that layer is dropped
* **all** layers missing → falls back to the flat `board` cut-out
* no `layers` key at all (v1 manifest) → flat `board` cut-out, mounted on
  the torso bone so it still breathes
* no usable art at all → the silhouette placeholder
* unknown `slot` → still renders, just above the body, on the torso bone
* non-numeric `anchor`/`pivot`/`z`/`size`, `layers` not a list, `canvas`
  garbage, the whole manifest not an object → contract defaults
* a prop with no `size` → renders full-canvas (stretched) plus a warning,
  rather than disappearing

There is no manifest shape that produces a broken character. That is
pinned by `tests/test_paperdoll.py`.

## Notes for the pipeline side

1. **Transparency is enforced.** Flat `board` cut-outs are alpha-checked
   and rejected if opaque. Layers are not alpha-checked (a layer is
   assumed to be authored transparent), so an opaque gear layer *will*
   hide everything beneath it.
2. **Character keys.** The manifest keys characters as `<name>-<realm>`,
   but every other real data source in this repo (season scores, streaks,
   catchphrases, opt-outs) keys by bare character name. The runtime keys
   on `name` and keeps `<name>-<realm>` as `manifest_id`. If you change
   the key format, nothing breaks — but tell this side.
3. **`.gitignore`.** The repo's unanchored `board.png` rule was silently
   ignoring `cast/**/board.png`. Un-ignored on this branch. If you add
   more common filenames (`body.png`, `head.png`), check they are not
   caught by a similar rule before assuming a commit landed.

## Performance

Measured on the real page, Chromium, 1440×900, with cloned characters:

| characters | animated bones | median frame | fps |
|-----------|----------------|--------------|-----|
| 10  | 34  | 16.7 ms | 59.9 |
| 60  | 204 | 16.7 ms | 59.9 |
| 120 | 408 | 16.7 ms | 59.9 |

Locked to the refresh rate with no dropped frames at 120 characters, so
the runtime is DOM + CSS transforms rather than PixiJS/canvas: no
dependency, no build step, works with the existing Jinja template, and
degrades to a static stacked image with JS off. Offscreen characters are
paused via `IntersectionObserver`, and `prefers-reduced-motion` stops the
rig entirely while leaving every character fully visible.

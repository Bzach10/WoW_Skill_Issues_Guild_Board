# Making artwork for the board (free, local, on your 4080)

Two tools are installed on this PC:

- **ComfyUI Desktop** (Start Menu → ComfyUI) — local AI image generation.
  First launch: accept the install location, let it download its runtime
  (~2GB, one time). Then **Workflow → Browse Templates → Image Generation**
  gives you a working text-to-image setup; when a model is missing it
  offers the download button.
- **Krita** (Start Menu → Krita) — free pro paint app for touch-ups,
  resizing, and layering generated art into final assets.

## The fast path: generate a whole theme's art from a prompt file

You don't have to click through ComfyUI to refresh the board's art. The
art direction for every theme lives in **`assets/art_prompts.yml`** —
plain YAML, one block per theme, editable by anyone — and a script feeds
it to the local ComfyUI server:

```
python scripts/generate_theme_art.py --dry-run          # just show the prompts
python scripts/generate_theme_art.py                    # generate everything
python scripts/generate_theme_art.py --theme emberforge # or one theme
```

Output lands in `assets/generated/<theme>/` (header, middle, footer,
poster, crest), which is where each `themes/theme.<name>.yml` already
points. A piece takes about 10 seconds on the 4080. Don't like an image?
Change that theme's `seed` in `art_prompts.yml` and re-run.

The script needs the ComfyUI **server** running — the start command is in
the header of `scripts/generate_theme_art.py`. If it isn't running the
script says so and changes nothing. The shared negative prompt in
`art_prompts.yml` is what keeps text out of the art; leave it alone.

## Models to grab (your RTX 4080 / 16GB runs all of these)

| Model | Why | Size |
|---|---|---|
| **FLUX.1-schnell (fp8)** | Best free quality-per-second, Apache licensed, 4-step fast | ~11GB |
| **Juggernaut XL** (SDXL) | Painterly fantasy look, huge community style range | ~7GB |
| **DreamShaper XL Turbo** | Very fast drafts for iterating on ideas | ~7GB |

ComfyUI's template picker offers these directly. Store them wherever it
defaults to — you have 800GB free.

## The board's asset slots (generate to these, keep the style)

House style: *dark stone, warm torchlight, aged parchment, iron & wood,
western wanted-poster grit.* Generate art **without text** — every word
on the board comes from the templates (AI-generated lettering looks
mangled; our fonts do the talking).

| Asset | File / theme key | Target size | Prompt starter |
|---|---|---|---|
| Header wall | `assets/wall_header.png` (`backgrounds.header`) | 3000×300 | "dark medieval dungeon stone brick wall, warm torchlight from above, drifting embers, moody fantasy tavern, wide seamless banner, no text" |
| Footer wall | `assets/wall_footer.png` (`backgrounds.footer`) | 3000×430 | same as header + "campfire glow from below" |
| Middle art | `assets/theme_art.png` (`backgrounds.middle`) | ~3000×1600 | "epic dark fantasy battlefield aftermath, embers and smoke, muted colors, cinematic wide shot, no text" (it gets darkened 87% behind the stats — bold shapes read best) |
| Guild plaque | `assets/plaque.png` | 520×248 | "aged brass plaque texture, brushed metal, worn edges, warm reflection, blank center, no text" |
| Item of the month | `assets/item_art.png` (`display.item_art` in config.yml) | ≤560×290 | "ornate fantasy game item on black, glowing runes, epic loot card style, dramatic rim light, no text" |
| Guild crest (new — web masthead / Discord) | `assets/crest.png` | 800×800 | "medieval guild heraldic crest, crossed swords over a cracked grinning skull, tattered banner ribbon, gold and deep crimson on black, emblem style, symmetrical, no text" |
| Poster parchment (for the WANTED columns) | future `backgrounds.poster` | 1024×1024 | "aged dark parchment texture, burnt tattered edges, leather-brown, subtle wood grain, iron nail hole top center, empty, no text" |

## Workflow that works

1. Generate 4-8 candidates in ComfyUI (it's fast — schnell does an image
   in ~2 seconds on your card).
2. Open the keeper in **Krita**: crop/scale to the target size above,
   nudge levels toward the board's warm-dark palette, export PNG.
3. Drop the file into `assets/` (keep the filename, or point the
   theme.yml key at your new file).
4. `python scripts/preview_board.py --open` — instant preview with the
   new art, no API keys.
5. Commit + push, run the workflow → it's on the board.

## Extras when you're ready

- **Krita AI plugin** (interstice.cloud → "AI Image Diffusion") connects
  Krita directly to your local ComfyUI — inpaint/extend art with a brush,
  which is perfect for fixing edges on wall textures.
- Upscaling: ComfyUI's "Upscale" template + 4x-UltraSharp model makes the
  3000px banners crisp from 1500px generations.

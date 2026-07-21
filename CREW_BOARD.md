# The Crew Board (front-end)

The public web board as a pirate crew standing on a ship's deck, with the
season's dungeons and raid bosses laid out behind them as islands.

Render it:

```
python scripts/render_crew_board.py      # writes crew_board.html
python scripts/shoot_crew_board.py       # writes previews/*.png
```

Both are offline — no credentials, no network, no CI. Open
`crew_board.html` in any browser.

## What a non-coder can change (theme.yml only)

Everything below goes in `theme.yml`. **You cannot break the page from
this file**: anything you delete, mistype, or fill in wrong falls back to
the shipped value.

### Pick the theme the board opens in

```yaml
crew:
  default_theme: chronicle    # codex | console | chronicle
```

(Visitors can still switch themes themselves with the buttons at the top
right, and the board remembers their choice.)

### Recolor a theme

Each theme has these tokens: `bg`, `text`, `heading`, `accent`, `panel`,
`line`, `muted`, `display` (title font), `body` (text font).

```yaml
crew:
  themes:
    codex:
      accent: "#b06a12"      # change just the gold
      display: "Cinzel"      # any Google Font name
```

Anything you leave out keeps the shipped value. A token name that isn't
in the list above is ignored with a note in the log.

### Change what the crew says

```yaml
crew:
  catchphrases:
    brewzleeh: "One more roll and I'm even."
    rakdisc: "I can fix him. (I cannot fix him.)"
```

Keys are the lowercase character name. Anyone without a line simply gets
no speech bubble.

### Keep someone off the board

`config.yml`:

```yaml
cast:
  opt_out:
    - "Somename-Somerealm"
```

### Move the ship

`config.yml`:

```yaml
voyage:
  current_island: "grim-batol"     # blank = the first dungeon
```

## The art contract — `cast_manifest.json`

The art pipeline owns `cast_manifest.json`; the board only reads it.

```json
{ "active_style": "one_piece",
  "styles_available": ["one_piece", "watercolor"],
  "characters": {
    "<slug>": {
      "name": "...", "realm": "...", "race": "...", "class": "...",
      "spec": "...", "gender": "...", "role": "healer",
      "transmog_fingerprint": "...", "render_url": "...",
      "styles": {
        "<style>": {
          "board": "cast/<slug>/<style>/board.png",
          "forms": { "light": "...", "shadow": "..." },
          "version": 3, "generated_at": "2026-07-20T12:00:00Z" } },
      "history": [] } } }
```

How the board uses it:

* **Art** comes from `styles[active_style].board`. If a character has no
  assets for the active style, they borrow a style they *do* have
  (flagged in the footer) rather than dropping to a silhouette.
* **`forms.light` / `forms.shadow`** drive the real art swap on the
  Shadowform toggle.
* **Roles** come from `role` when it is a real role name, else derived
  from the real `spec`. A nonsense role is not trusted.
* **Transparency is enforced.** A PNG with no alpha channel is rejected
  even when the manifest points straight at it — it would paste a solid
  rectangle onto the ship. Those members fall back to the silhouette.
* A missing file, a missing style, a malformed manifest, or no manifest
  at all all degrade to the silhouette slot. The board never breaks.

### Swapping the whole cast's style

Flip `active_style` in the manifest and re-render — the entire cast
reskins. Nothing is hardcoded to one style. To preview without editing
the manifest:

```
python scripts/render_crew_board.py --style watercolor
python scripts/render_crew_board.py --manifest path/to/other.json
```

`theme.yml`'s `crew.style` also overrides the manifest's `active_style`
if a guild wants to pin one.

## Scenes (the layer behind the crew)

The cast are transparent cut-outs composited **above** the scene layer,
so backgrounds can change or animate without touching the character art:

```
z 0  .scene       backdrop (tint + optional image), crossfades between plates
z 1  .deckboard   the ship's deck
z 2  .member      the cast — transparent PNGs, constant
```

Landing on an island washes that island's scene over the board. Define
scenes per island id, or per kind (`dungeon`, `raid_boss`, `open_sea`):

```yaml
crew:
  scenes:
    grim-batol:
      tint: "#8a3b1f"
      image: "assets/scenes/grim_batol.png"
```

The tint is blended against the live theme in CSS, so one scene reads
correctly in all three themes. An `image` that isn't on disk is dropped
and the tint carries the scene on its own.

## What is real and what is still stubbed

Real, from data already on disk:

* World/region/realm standing, season M+ ladder, and every score
  (`board_state.json`)
* Raider.io profile links per player (`roster_cache.json`)
* Roast of the week (`config.yml`)
* Brewzleeh's gambling debt, compounded with the same formula the printed
  board uses (`theme.yml`)
* The island chain and its flavor text (`guild_board/voyage.py`)
* Raid-boss island records (`board_state.json` parse records)

Stubbed, and labelled as such in the page footer:

* **Crew art** — silhouette slots until the art pipeline drops
  transparent cut-outs in `cast/<name>/`.
* **Roles** — a role is only shown when the repo can prove it (a parse
  record naming the spec, the debt gag naming Brewzleeh's monk, the
  rakdisc art set being a priest). Everyone else stands as a
  "Deckhand". Once `blizzard_profile_cache.json` lands, every member gets
  a real class/spec and a real role automatically.
* **Per-dungeon island records** — the dungeon fetcher hits the network,
  so the offline renderer leaves those as "no record yet".

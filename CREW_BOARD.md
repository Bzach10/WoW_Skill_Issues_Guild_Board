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

## The art contract

The deck expects **transparent PNG cut-outs** at `cast/<name>/`:

* `cast/<name>/board.png` is the curated pick, used first if present.
* Otherwise the first transparent PNG in that folder is used.
* A PNG with no alpha channel (a raw generation still on its studio
  background) is **rejected** — it would paste a solid rectangle onto the
  ship. Those members fall back to the silhouette slot instead.

A member with both `*light*.png` and `*shadow*.png` cut-outs gets a real
art swap on the Shadowform toggle. Any Priest gets the toggle regardless;
without the art it is expressed purely in CSS.

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

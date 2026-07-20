# Customizing the Guild Board

Everything about how the board **looks** lives in one file: **`theme.yml`**.
Everything about what **data** it shows lives in `config.yml`. You cannot break
the board from `theme.yml` — any key you delete, mistype, or mangle silently
falls back to the shipped design, and if a render ever fails completely the
old Pillow renderer takes over. Experiment freely.

**The edit loop (no software needed):**

1. Open `theme.yml` on the GitHub website and click the pencil icon.
2. Change what you want, commit to `main`.
3. Go to **Actions → Weekly Guild Board → Run workflow** to post the board now,
   or just wait for Tuesday.

**The fast local loop (if you have the repo cloned):**

```bash
python scripts/preview_board.py --open     # fake data, no API keys needed
```

This writes `board_render.html` (desktop) and `board_mobile_render.html`
(phone version) and opens the first in your browser. Edit `theme.yml`, run it
again, refresh. Add `--png` to also produce the exact PNGs Discord will see.

---

## Quick recipes

### Change a color

```yaml
colors:
  accent: "#7bd1ff"      # the gold — titles, bars, highlights — now ice blue
```

Any CSS hex color works. `accent` changes the personality of the whole board;
the rest (`background`, `panel`, `hairline`, …) are the dark chrome around
the data.

### Change the fonts

```yaml
fonts:
  display: "UnifrakturMaguntia"   # the big carved titles
  body: "Rubik"                   # all the stats text
```

Any name from [fonts.google.com](https://fonts.google.com), spelled exactly as
shown there.

### Swap the background art

Drop new images into `assets/` and either keep the same filenames
(`wall_header.png`, `theme_art.png`, `wall_footer.png`) or point at new ones:

```yaml
backgrounds:
  header: "assets/my_new_wall.png"
  middle: "assets/raid_screenshot.png"
  middle_tint: 0.9        # 0 = art at full strength, 1 = solid color
  footer: "assets/my_new_wall.png"
```

`middle_tint` is the readability knob — if text is hard to read over your art,
raise it.

### Change the jokes

Every gag is a line of text in `theme.yml`: the hanging sign (`header.sign_text`),
the widget one-liners, the fake raid debuffs (any
[Wowhead icon name](https://www.wowhead.com/icons)), the gambling-debt card
(`footer.debt` — retire it with `enabled: false`, or point it at a new victim
by changing the title and lines), the graveyard captions, and the rotating
`motd_quips` list. Add as many MOTD quips as you want; one rotates on per week.

### Swap the header or footer

```yaml
board:
  header: banner        # stone_torchlight (plaque + widgets + sign) or banner (big clean title)
  footer: simple        # graveyard (tombstones + debt + item) or simple (quiet strip)
```

### Make your own header or footer

1. Copy a built-in module out of `guild_board/templates/headers/` (or
   `footers/`) into **`board_templates/headers/my_header.html.j2`** at the
   repo root (create the folder). Files there are found first — you can even
   shadow a built-in by reusing its name.
2. Edit it — each module is self-contained HTML + CSS with access to the same
   data (`{{ guild_name }}`, `{{ wipes }}`, `{{ theme.colors.accent }}`, …).
3. Point the theme at it, and tell the animation encoder how tall it is:

```yaml
board:
  header: my_header
  header_height: 240    # px — the encoder freezes everything below the header
```

If your module has a typo, the render falls back to the default module and the
board still posts.

### Tune the weekly awards

Rotating spotlights that mid-pack players can win — IRON ATTENDANCE (longest
streak of active weeks) and BIGGEST CLIMB (largest M+ score gain since the
last board):

```yaml
awards:
  enabled: true
  per_week: 2
  top_n: 3
```

### The phone version

Every post now includes a second, portrait image built for phones (top-3 per
category, big text), plus TL;DR callout lines in the message itself so the
highlights land without opening any image. Turn the companion off in
`config.yml`:

```yaml
display:
  mobile_companion: false
```

---

## What lives where

| I want to change…                              | File                                  |
| ---------------------------------------------- | ------------------------------------- |
| Colors, fonts, backgrounds, jokes, awards      | `theme.yml`                           |
| Which header/footer frames the board           | `theme.yml` → `board:`                |
| A custom header/footer of your own             | `board_templates/headers|footers/`    |
| Which stats sections appear, guild name, top N | `config.yml`                          |
| Item of the month art                          | `assets/item_art.png` (swap the file) |
| The roast                                      | Discord roast channel (🔥 votes win)  |

## The safety net (why you can't break it)

- `theme.yml` missing, partial, or invalid → the shipped design fills every gap.
- A named header/footer module that doesn't exist → the default module renders.
- The HTML renderer fails for any reason → the Pillow renderer posts a plain board.
- The mobile companion fails → the desktop board still posts alone.
- Tests run in CI before every post; a broken commit fails loudly instead of
  posting a broken board.

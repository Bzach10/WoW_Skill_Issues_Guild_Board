# Skill Issues — custom header & footer (2a "War Room" + 2b "Graveyard Memorial")

Drop-in package for `Bzach10/WoW_Skill_Issues_Guild_Board`. Replaces the
theme-art splice bands with the approved designs, rendered natively in Pillow
with **live weekly data** (wipes, deaths, pulls, repair estimate, tombstones
ranked by deaths-per-pull).

## Files in this package

| File | Goes to |
|---|---|
| `theme_bands.py` | `guild_board/theme_bands.py` |
| `assets/wall_header.png` | `assets/wall_header.png` |
| `assets/wall_footer.png` | `assets/wall_footer.png` |
| `assets/plaque.png` | `assets/plaque.png` |
| `design-source/…dc.html` | reference only — the approved HTML design (do not commit) |

Optional: drop `Cinzel-Bold.ttf` + `Cinzel-Regular.ttf` (Google Fonts, OFL)
into `assets/fonts/` for the carved-stone display type. Without them the
plaque/GIT GUD text falls back to the same bold system font the board uses.

## Patch to `guild_board/board_image.py` (4 edits)

1. Add the import near the top:
```python
from guild_board import theme_bands
```

2. Change the two band-height constants:
```python
HEADER_ART_H = theme_bands.HEADER_BAND_H   # was 300
FOOTER_ART_H = theme_bands.FOOTER_BAND_H   # was 320
```

3. In `generate_board_image`, replace the header call:
```python
# was: _draw_header_art(img, theme, HEADER_ART_H)
theme_bands.draw_header_band(img, stats)
_band_seam(img, 0, HEADER_ART_H, at_top=True)
```

4. And the footer call:
```python
# was: _draw_footer_art(img, theme, height - FOOTER_ART_H, FOOTER_ART_H)
theme_bands.draw_footer_band(img, height - FOOTER_ART_H, stats,
                             week_index=start_dt.isocalendar()[1])
_band_seam(img, height - FOOTER_ART_H, FOOTER_ART_H, at_top=False)
```

Everything else (fire backdrop via `theme_art.png`, info strip, hero tiles,
columns, roast, watermark) stays untouched. `theme_art` stays in config —
it still paints the page backdrop.

## Prompt to paste into Claude Code

> Apply the handoff in ./handoff to this repo: copy theme_bands.py into
> guild_board/, copy the three PNGs into assets/, and apply the 4-edit patch
> from handoff/README.md to guild_board/board_image.py. The visual source of
> truth is handoff/design-source/*.dc.html — match its layout, colors and
> copy. Then run `python leaderboard.py --preview`, open board.png, and
> iterate on theme_bands.py until the header and footer match the design
> (plaque left, three widget cards, debuff bar, torch + GIT GUD shingle
> right; footer: rules tooltip, graveyard memorial with tombstones from this
> week's death leaders, recruiting tooltip, MOTD strip). Run pytest to make
> sure nothing broke, commit, push, then trigger the "Weekly Guild Board"
> workflow with dry_run off so the trial posts to Discord.

## Notes

- Tombstones auto-fill from `stats["deaths"]` (top 4 by count); the campfire
  plot is always reserved for Healmates.
- Repair bill estimate = `deaths*57 + pulls*23` gold — tune in
  `draw_header_band`.
- MOTD quip rotates by ISO week; add lines to `MOTD_QUIPS`.
- Debuff icons come from the same Wowhead CDN cache the board already uses;
  offline runs just skip them.

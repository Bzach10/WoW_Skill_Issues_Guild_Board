# Guild board redesign — options for review

Everything here is on branch **2.0**. `main` and the live site are
untouched.

**Start here:** open `redesign_previews/index.html` in a browser. It's a
contact sheet linking every option. Each one is a real rendered page —
click into it, resize the window, open it on your phone.

There are **3 brand-new layouts** (plus the current one, kept), **4
themes**, and **20 pieces of artwork that were actually generated**, not
mocked up.

---

## 1. The layouts

A *layout* is the structure — where things sit on the page. These are
not reskins of each other; they're three different ideas about what the
board *is*. All four keep every piece of data and every in-joke.

### `ember_terminal` — the scrying console
The one closest to the Ember Terminal look you pointed at. The board as
arcane machinery: full-bleed art backdrop, CRT scanlines, drifting
embers, a masthead sitting in its own art band. The four data columns
become **log blocks on a deliberately unequal grid** — 4/2/3/3 tracks
with vertical offsets, so nothing lines up in a rigid row. Every
ranking line reads as a console entry: `01  MAILLO ······ 92%`.

Best with: **emberforge**, **drownedgods**.

### `chronicle` — the weekly dispatch
The board as an **editorial front page**. One enormous headline over a
full-bleed art plate, a rule of stat numerals beneath it, then a
magazine grid: a wide lead column of standings against a narrow sidebar
that finally gives the running jokes real estate — the roast set as a
proper pull quote, the ledger, in memoriam. The hierarchy is the point:
one story is the biggest thing on the page.

Best with: **arcanevault**, **drownedgods**.

### `codex` — the illuminated record
The board as **a single bound manuscript page**. No columns, no cards,
no dashboard — one narrow measure running top to bottom the way a
chronicle is actually read. Each ranking column is a **chapter** with an
illuminated initial and a roman numeral, separated by ornamental rules,
on real paper texture. This is the ink-on-light-paper direction done as
a whole page instead of four poster cards.

Best with: **gildedcodex** (the light one).

### `poster` — what's live today
Kept, unchanged, so you can compare against it directly. It's still the
default; nothing switches until you say so.

---

## 2. The themes

A *theme* is the paint — colors, fonts, art, and the flavor copy. Any
theme works with any layout (all 16 combinations are rendered), though
the pairings above are the ones I'd show first.

| Theme | Feel | Palette |
|---|---|---|
| **emberforge** | Molten under-forge. Obsidian lit from inside. | black / molten orange |
| **arcanevault** | Astral archive. Deep, expensive-looking dark. | indigo / violet / ley-line cyan |
| **drownedgods** | Sunken temple to something that should've stayed sunk. | abyssal teal / bioluminescent green |
| **gildedcodex** | **Not dark.** Real cream vellum, iron-gall ink, gold leaf. | vellum / ink / gold / royal blue |

On the "weak flat dark" problem: the three dark themes get their depth
from **real generated art plus layered scrims**, not from a flat hex
color. And `gildedcodex` is there because you like ink on real paper —
it's a genuine light theme, not a dark theme with a pale panel.

### How to actually use one

Copy the theme file over the live one and run the workflow:

```
copy themes\theme.emberforge.yml theme.yml
```

Then GitHub → Actions → "Weekly Guild Board" → Run workflow.

To change only the layout and keep today's colors, edit `theme.yml`:

```yaml
board:
  web_layout: chronicle    # poster | chronicle | ember_terminal | codex
```

---

## 3. The artwork — this part is real

**All 20 images were generated on your PC during this session.** Not
placeholders, not stock, not reused. SDXL running on the 4080 through
ComfyUI's local server. Nothing was uploaded anywhere and there's no API
key or cost involved.

5 pieces × 4 themes, in `assets/generated/<theme>/`:
`header.png`, `middle.png`, `footer.png`, `poster.png`, `crest.png`.

The crests are new — the layouts use them as a masthead sigil, which the
old web board never had.

**The prompts live in `assets/art_prompts.yml`** — plain editable YAML,
one block per theme, no code. Change a line and re-run:

```
python scripts/generate_theme_art.py --theme emberforge
python scripts/generate_theme_art.py --dry-run     # just show the prompts
```

The generator needs the ComfyUI server running; the command to start it
is in the header of `scripts/generate_theme_art.py`. If it isn't
running, the script says so and changes nothing.

No text is baked into any image — the shared negative prompt in
`art_prompts.yml` enforces that, and all lettering still comes from the
templates and fonts.

### Honest caveats on the art
- Some pieces have faint smudges in a corner where the model *wanted* to
  write something. They're small and the layouts crop or veil those
  edges, but they're there if you look.
- `assets/item_art.png` (item of the month) and the Discord **image**
  board's own art are untouched — this pass was about the website.
- Each theme's art is one generation, not a curated pick of eight. If
  you like a direction but not a specific image, changing the `seed` in
  `art_prompts.yml` rolls a new one in about 10 seconds.

---

## 4. About the data in the previews

Judge the *designs*, not the weekly parse numbers.

**Real**, from your committed files:
- guild / realm / region, raid difficulty, and the roast of the week
  ("Healmates Sucks" — Rakdaddy) — from `config.yml`
- realm #49 / region #2,219 / world #6,855, the season M+ score ladder,
  Iron Attendance streaks, and the guild records including Amrevenge's
  +20 — from `board_state.json`

**Fixture**, from the existing preview fixture:
- this week's raid slice — best DPS/HPS/tank parses, deaths, pulls,
  kills, weekly M+ runs, Most Improved

Those weekly numbers come from Warcraft Logs at build time and aren't
persisted between runs, so they can't be replayed locally without API
keys. Every layout renders them identically, so the comparison is still
apples-to-apples.

---

## 5. Constraints I held to

- **Nothing is hardcoded.** Layout, colors, fonts, art paths and all
  flavor copy are `theme.yml` keys. The layout picker uses the same
  fail-open resolver as the header/footer modules.
- **It fails open.** An unknown `web_layout` falls back to `poster`;
  a missing art file heals to the shipped default via the existing
  integrity check (now covering the new `crest` key too); a bad theme
  value falls back to the shipped design. A broken page shouldn't be
  reachable from a theme edit.
- **All data preserved.** Cross-realm roster names, realm/region/world
  rank, season M+ ladder, best DPS/HPS parses, highest timed key, Iron
  Attendance streaks, Most Improved, records, awards — with WCL profile
  links, class colors and role tags intact in every layout.
- **The culture kept its slots.** Brewzleeh's Gambling Debt, the
  graveyard memorial, MOTD and the Roast all appear in all three new
  layouts. The old web board actually *didn't* have the debt card or the
  graveyard — those were image-board only. Now they're on the site.
- **Done features carried forward:** role filters, player search (both
  remembered across visits), per-player profile links, week archive.
  They now live in one shared partial, so any future layout inherits
  them.
- **Art-director automation still works.** Same `backgrounds.*` keys it
  already writes to; nothing renamed. `crest` is additive.

---

## 6. What I'd do next

- Pick a favorite and I'll tune that one properly — the three are
  deliberately at similar polish rather than one being finished.
- `poster` + a dark theme is the weakest combination in the matrix: the
  poster layout forces a light parchment glaze regardless of theme, so
  dark art behind light cards looks unresolved. Ignore those four cells
  unless you want the current design kept as-is.
- The Discord **image** board still uses the old Imperial Bounty look.
  If you like one of these, that's the follow-up.
- Mobile is verified by screenshot at 430px for every combination, but I
  haven't had it on a real phone.

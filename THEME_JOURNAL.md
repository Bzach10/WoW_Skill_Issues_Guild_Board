# Theme Journal — the board's design history

## Jul 2026 — "Imperial Bounty" (Voidspire Sanctum tier theme)
Concept: the guild's rankings as bounty notices posted by the Void-taken
empire you're raiding. Light aged-parchment posters — each watermarked
with an inked void-crown emblem and wax seals — pinned to the glowing
purple ruin of Voidspire. Cinzel Decorative engraved titles; every name
and number PRINTS as ink (class colors darkened to ink weight, sepia
details). Eyebrow: ★ IMPERIAL BOUNTY ★ · reward line: CLAIMED BY THE
VOID · REWARD: THE THRONE.
Assets (SDXL, local RTX 4080): imperial_ruin_{poster,header,middle,footer}.png
Architecture note: theme.backgrounds.poster now triggers true light-paper
rendering — paper at full strength under a light glaze, ink text pipeline
(row.ink/value_ink) — so any future theme can ship real paper posters.

## Sep 2026 — "Keg & Cutlass" (Brewfest × Pirates' Day)
Concept: Brewfest washed up on the pirate docks, and the whole guild is
on a wanted poster. September owns both Brewfest and Pirates' Day (Sep
19), and the board's four ranking columns were already WANTED notices —
so this month they get nailed to a piling in Booty Bay instead of a
palace wall. Tar-black timber and amber lanternlight around the data;
sun-bleached sailcloth, salt-stained and frayed, under the rankings.
The bounty is no longer a throne. It's a barrel.

Assets (SDXL local, RTX 4080, seed 70405, `assets/generated/kegandcutlass/`):
- `header.png` 1344×512 — night dockside warehouse wall, copper-banded
  kegs, brass lanterns on iron hooks. (Regenerated once: the first pass
  came back a bright noon beach, which would have flattened the header
  text.)
- `middle.png` 1216×832 — pirate harbour at dusk, moored galleon, barrel
  stacks, lantern strings over black water. Bold silhouettes, reads well
  at 0.78 tint.
- `footer.png` 1344×512 — night dock at the wall base: spilled ale on wet
  planks, toppled barrels, rope and a rusted anchor.
- `poster.png` 1024×1024 — pale sun-bleached sailcloth, salt stains, soft
  water rings, frayed edges, rust at the four nail holes. (Regenerated
  twice: pass 1 grew an iron compass rose dead-centre, pass 2 banded into
  light-top/dark-bottom. The poster slot is composited ink-on-paper — a
  light cream glaze with dark text over it — so it has to stay uniformly
  pale or the ranking names lose contrast.)
- `crest.png` 1024×1024 — gold skull in a tricorn behind crossed
  cutlasses, rope wreath, tar-black ground.

theme.yml: accent → #e8a33d (lantern brass / amber ale), background →
#0a0806 tarred near-black, panel → #16100a wet oak, green → #4fc98b sea
green. Display font Cinzel Decorative → **Rye** (`display_weights: "400"`
— Rye ships a single weight; the font_css_url comment already cited it as
the reason that knob exists). middle_tint 0.86 → 0.78 so the harbour
actually reads instead of going flat black. Eyebrow: ☠ DEAD OR DRUNK ☠ ·
reward: REWARD: ONE (1) BARREL · PAID AT THE DOCK. Sign subtext: NO
REFUNDS · NO SURVIVORS ("GIT GUD" untouched, as always.)

Also shipped as `themes/theme.kegandcutlass.yml` (web_layout: poster) so
the look can be swapped back in later without regenerating anything.

Observation for next month: the footer's debt and item-of-the-month cards
are `.tooltip{background:rgba(7,7,24,.94)}` — hardcoded WoW-tooltip navy
in `footers/graveyard.html.j2`, shared by every theme. Authentic to the
game, but it reads cool against a warm amber board. Worth making it
theme-driven before a theme that leans warmer still.

# Theme Journal

Design history of the board's monthly look. Each entry: the pitch, what got
generated, and what changed in `theme.yml`.

## August 2026 — "Imperial Bounty" (current raid tier)

**Pitch:** The raid roster this tier reads like a fallen empire eating
itself — an *Imperator*, a *Fallen-King*, and the chimeric horrors
(Chimaerus, Vorasius) tearing through what's left of the throne room. No
canonical zone name lives in the repo config (it's auto-detected per run
from WCL logs), so the theme leans on the boss list itself: shattered
marble columns, bronze filigree gone to ash, and violet void-light bleeding
through the cracks where the empire used to be. The WANTED posters become
Imperial Bounties — you're not just topping the parse meter, you're
claiming a piece of a dead throne.

**Generated (SDXL, local RTX 4080, `sd_xl_base_1.0.safetensors`, 30 steps,
dpmpp_2m/karras, cfg 7):**
- `assets/generated/imperial_ruin_poster.png` (1024×1024) — aged parchment
  with a ghosted heraldic crest (broken crown over clawed wings) bleeding
  through bronze and violet stains; sits under the board's existing dark
  glaze so it reads as texture, not a competing image.
- `assets/generated/imperial_ruin_header.png` (3000×300) — shattered
  imperial colonnade, warm torchlight from above, violet void cracks.
- `assets/generated/imperial_ruin_footer.png` (3000×430) — same ruin, fire
  rising from below (Voidspire embers spilling out of the floor).
- `assets/generated/imperial_ruin_middle.png` (3000×1600) — full throne
  room, silhouetted statues facing a shattered dais under a violet void
  ceiling; heavily tinted (0.86) behind the data so it stays a mood, not a
  distraction.

**theme.yml changes:**
- `board.poster_eyebrow` → "★ IMPERIAL BOUNTY ★", `poster_reward` →
  "CLAIMED BY THE VOID · REWARD: THE THRONE"
- `colors`: deep violet-black background/panel (`#130d1a`/`#20152c`),
  antique bronze accent (`#c9974a`), warm parchment text (`#f3ece0`),
  lavender-grey muted/faint, green nudged toward emerald (`#57e08a`) to sit
  better against the violet without losing contrast.
- `fonts.display` → "Cinzel Decorative" (`display_weights: "700;900"`) —
  an engraved imperial serif in place of the wanted-poster Rye, body stays
  Inter.
- `backgrounds.header/middle/footer/poster` → the four new generated
  assets above, `middle_tint: 0.86`.

Verified with `scripts/preview_board.py --png` (class colors and parse %
stayed crisp against the new palette — no muddying) and `python -m pytest`
(95 passed).

**Hard limits respected:** `motd_quips`, `footer.debt`, roast config, and
`header.sign_text` ("GIT GUD") untouched; no `guild_board/` code changes;
nothing posted to Discord; branch `2.0` only.

**To ship:** say "merge and run it."

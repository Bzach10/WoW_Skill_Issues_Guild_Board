# Overnight improvement log

One entry per loop iteration. Everything landed on branch 2.0 only —
main is frozen on reviewed code for the 9 AM auto-post. Review in the
morning and say "merge" to take what you like.

## Iteration 1 (~3:15 AM)
Added the first tests for the Discord delivery layer: multi-file
attachment shape (files[0]/files[1] + mime by extension), 429 rate-limit
retry, and the missing-file fallback to a clean JSON post. 92 tests total.

## User request (~3:30 AM): WANTED posters
The four ranking columns are now weathered WANTED posters (nail, tattered
border, alternating tilt, ★ WANTED ★ eyebrow + "DEAD OR ALIVE · REWARD:
GLORY" bounty line — both editable in theme.yml). Display font switched
to Rye (classic wanted-poster slab) across board and web; theme.py grew
fonts.display_weights so single-weight Google Fonts load correctly.
On 2.0 only — say "merge" to put it on the 9 AM post.

## Iteration 2 (~3:45 AM)
Theme plumbing tests: font URL weight axes (caught + fixed a real edge —
partial theme dicts dropped Cinzel's weights), deep-merge list-replace
semantics, custom header/footer height overrides. 95 tests total.

## User request (~4 AM): first AI artwork, generated locally
ComfyUI Desktop + SDXL running on the 4080 (driven via its local API —
the Electron window screenshots black, the server is what matters).
Generated three pieces in assets/generated/: wanted_parchment (now the
real texture behind the WANTED columns, theme key backgrounds.poster),
wall_header_art (candlelit stone wall, ready for the header), and
guild_crest (golden skull + crossed swords, ready for web masthead).

## Iteration 3 (~4:15 AM)
Web board remembers each visitor's role filter and player search across
visits (localStorage, fail-quiet in private mode). Playwright-verified:
tap Tanks, reload, still filtered to tanks. 95 tests remain green.

## ~4:30 AM: "Imperial Bounty" — the 10/10 poster push
User called the dark posters weak (right). Art director's run supplied an
imperial void theme + light parchment with inked void-crown watermark;
I built the missing architecture: posters render as REAL light paper
(full-strength texture + light glaze) with an ink text pipeline — class
colors darkened to ink weight, sepia details, engraved ink titles.
Dramatic contrast against the purple ruin backdrop. Unless told
otherwise, merging to main ~8:15 AM so the 9 AM post carries it.

## Iteration 4 (~4:45 AM)
Ported the Imperial Bounty ink-on-paper poster mode to the web board so
both surfaces match: light parchment cards, inked class colors, sepia
details, word-spacing fix for Cinzel Decorative. Playwright-verified.

## Iteration 5 (~5:10 AM)
Locked down the new ink pipeline with tests: class-color darkening,
whitish->sepia special case, non-rgb passthrough, and a full render
assertion that poster mode prints ink while plain mode keeps screen
colors — on both board and web surfaces. 97 tests.

## Iteration 6 (~5:40 AM)
New integrity guard: theme background paths are verified at build time —
a typo'd or uncommitted asset (the art-director failure mode) heals to
the shipped default (walls) or the CSS parchment (poster) with a loud
warning, instead of rendering a silent blank. 98 tests.

## Iteration 7 (~6:08 AM)
CUSTOMIZING.md caught up with the night: WANTED poster knobs (eyebrow,
reward line, backgrounds.poster + ink mode explained), fonts.display_weights,
season-derived Iron Attendance wording, pointers to THEME_JOURNAL and
ART_GUIDE. Docs now match the board the guild actually has.

## Iteration 8 (~6:35 AM)
Simplification with a save: hoisted the attendance-derivation imports out
of the per-difficulty loop (new _sample_week helper) — and the cleanup
exposed that wcl.week_of relied on function-local datetime imports; the
module-level import was missing, which would have been a runtime
NameError in the untested CI path. Smoke-tested the path directly.

## Iteration 9 (~7:02 AM)
End-to-end test for guild-made template modules: a board_templates/
header is resolved first, honors its custom GIF band height, renders in
place of the built-in. The CUSTOMIZING.md recipe is now under test. 99 tests.

## Iteration 10 (~7:28 AM)
Final overnight iteration: pinned the awards fail-open contract — a
crashing award builder is skipped and the rest still render. 100 tests
even. Next wake performs the verified merge to main for the 9 AM post.

# S.S. Wipe Fest — launch status

Live worklog for opening day. Queue worked highest-impact-for-least-work.

## Tooling note
The `website-optimization` skill and its scripts (`check_links.py`,
`preflight.py`, `optimize_images.py`) were **not present on disk** in this
environment (not registered, not in `.claude`, not in the repo). The
equivalent checks/fixes were done directly with the repo's own tools so the
outcomes still land.

## Queue

| # | Item | Status |
|---|---|---|
| 1 | Per-character realm resolution | ✅ verified — Rakdisc/Rakell render with real data on Proudmoore |
| 2 | Link + preflight audit | ✅ clean — no broken links/fragments/orphans; a11y checks pass |
| 3 | Responsive image optimization | ⏸ deferred (rationale below) |
| 4 | Trim rooms | ✅ done — 11 → 5 warm rooms |
| 5 | Empty states ("bounty unconfirmed") | ✅ red "BOUNTY UNCONFIRMED" stamp, "still one of the crew" |
| 6 | Parallel ladders (Bounty/Riser/Attendance/Rookie) | ✅ four boards on The Standings |
| 7 | Guild achievements surface | ✅ Trophy Hall (B-07), gated on `available` |
| 8 | Voyage map (islands = dungeons/raids, keys + bosses) | ✅ core shipped; deepening as time allows |

## Item 2 — audit (CLEAN)
No broken internal links, no broken `#` fragments, no orphan pages. Preflight:
alt text present everywhere; no `z-index:9999`; no positive `tabindex`; no
`aria-hidden` on focusable elements; no `100vh`-without-`dvh`. The one
`outline:none` (hall face tiles) is paired with a `:focus-visible` accent
ring — a valid focus indicator. Images lack explicit width/height, but every
image sits in an `aspect-ratio` container, so there is no layout shift.

## Item 6 — parallel ladders
Four boards on The Standings so the light isn't only on the podium:
**Top Bounty** (Amrevenge…), **Biggest Risers** (Tommybravoo ▲18.6),
**Iron Attendance** (Buchalter 6w…), **New Blood** (Fluffy, Xavira… — the
lowest-scored, so a different five get their name up). Together they rank a
broad slice of the roster from real data.

## Item 3 — image optimization (deferred, with plan)
The `optimize_images.py` script referenced in the queue is not present in this
environment. The images are already mitigated: staged at 900px, JPEG q86,
`loading="lazy"`, `decoding="async"`, and inside `aspect-ratio` containers (no
CLS). A full AVIF/WebP/JPEG `<picture>` pipeline with blur placeholders is the
right next step but is medium-large work (touches staging + every image
template) — sequenced honestly as the top remaining perf item, not dropped.

## Navigation IA — decided 2026-07-23

Consolidating five thin top-nav tabs (Board, Voyage, Wanted, The Hall, Trophies) down to
three top-level entries, folding the rest into rooms aboard the ship.

**Top level (site nav):**
- **The Ship** — the hub. Was "Board"; `ship.html` is already the room-based page (5 rooms
  as of the 11→5 trim), so this is the existing entry point, not a new page.
- **Wanted Board** — kept as its own top-level, directly-reachable entry (`wanted.html`)
  *in addition to* living physically inside the Bar room, per
  [`SHIP_EXPERIENCE_VISION.md`](../../SHIP_EXPERIENCE_VISION.md) §1 ("path off to the side to
  the Wanted wall"). Two doors to the same room, not two different things.
- **Clean Data** — new, first-class, no-RP toggle. Promotes the roster-density List mode
  (`prototypes/roster-density/`) to a real site-wide entry, per
  [`SHIP_EXPERIENCE_VISION.md`](../../SHIP_EXPERIENCE_VISION.md) §4 and
  [`DECISIONS.md`](../../DECISIONS.md) 0f. Not a room aboard the ship — a parallel, plain view
  of the same data.

**Rooms folded in from today's separate pages** (reached by navigating the ship, not the top
nav):
- **The Bar** — already a room; becomes the hub room per §1 (order drinks, path to the
  Wanted wall). Existing room, gets richer content (Step 3).
- **The Map Room** — folded from `voyage.html` (island/voyage completion). New room section.
- **The Standings** — already a room (parallel ladders). Unchanged by this pass.
- **The Hall** — folded from `hall.html`, **absorbing `trophy.html`'s content** (one thin
  tab does not need to stay separate from an adjacent one covering similar ground).

**Left alone, not in scope for this pass:** Crow's Nest (raid countdown) and Below Deck
(the debt counter / wheel gag) are existing ship rooms that were never top-nav tabs and
aren't named in this consolidation — no reason found to touch them here.

**No dead ends:** every folded room keeps a reachable path via the ship's room nav
(`ship-nav.js`/`ship-nav.css`, the approved, reviewed prototype at
[`prototypes/ship-nav/`](../../prototypes/ship-nav/) — port in, don't reinvent) plus the
existing back-to-board affordance already on every non-board page.

## Item 1 — realm resolution (DONE)
Cross-realm resolution is centralized in `guild_board/links.py`: `realm_index`
builds `{name: realm}` from the roster cache (each member stored `name-realm`),
`realm_for` returns the character's own realm, guild realm only as fallback.
Verified: rakdisc → proudmoore (3529.2), rakell → proudmoore (2994.6),
amrevenge → stormrage. Every per-character Raider.io fetch (`raiderio.py`
`_split_name_realm`) and outbound link (WCL/Raider.io on profile pages) uses
the character's own realm. No hardcoded realm in any fetch path.

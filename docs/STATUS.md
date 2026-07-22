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

## Item 1 — realm resolution (DONE)
Cross-realm resolution is centralized in `guild_board/links.py`: `realm_index`
builds `{name: realm}` from the roster cache (each member stored `name-realm`),
`realm_for` returns the character's own realm, guild realm only as fallback.
Verified: rakdisc → proudmoore (3529.2), rakell → proudmoore (2994.6),
amrevenge → stormrage. Every per-character Raider.io fetch (`raiderio.py`
`_split_name_realm`) and outbound link (WCL/Raider.io on profile pages) uses
the character's own realm. No hardcoded realm in any fetch path.

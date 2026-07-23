# 🌐 WEBSITE_IDEAS — Making the Guild Board Site the Best It Can Be

*All-hands creative push. Focus: the **website** specifically — 131 anime-styled character cards + profile pages, roster, rotating WoW scene backdrops, live WCL/Raider.io data, monthly theme rotation, island/voyage map, guild achievements.*

**Tags:** each idea is rated **Impact** / **Effort** (High / Med / Low). Grounded in the real stack: static GitHub Pages, weekly GitHub Actions render, CSS-transform paper-doll rig (120 chars @ 60fps proven), `theme.yml` layouts/themes, `board_state.json` + Raider.io/WCL data. Built to stay buildable solo on consumer hardware.

**Last updated:** 2026-07-20

---

## 1. 🚀 TOP 10 — Make the Website BETTER (highest-impact core upgrades)

| # | Idea (one-line pitch) | Impact | Effort |
|---|---|---|---|
| B-01 | **Voyage Map as the landing page** — open on the crew's ship docked at the live island, cast on deck, data one scroll below; the map *is* the homepage. | High | Med |
| B-02 | **Full-cast hero wall** — the entire 131-character line-up as one breathtaking animated grand hall on load; the signature "whoa" shot people screenshot and share. | High | Med |
| B-03 | **Real character profile pages** — every member gets a permalink: their doll, gear, records, streak, arc, catchphrase — the atom every other feature links back to. | High | Med |
| B-04 | **Scene backdrops behind the cast, not just decoration** — rotate the 12 WoW scene scenarios as living dioramas with their featured characters actually staged in them. | High | Med |
| B-05 | **Weekly Recap Ribbon up top** — an auto-generated 3–5 sentence in-world "story of the week" from real records/roast/climbs, so the site reads as a saga, not a spreadsheet. | High | Low |
| B-06 | **Transmog "what changed this week" view** — a before/after on each card driven by the fingerprint diff, making the weekly update feel alive and worth revisiting. | High | Med |
| B-07 | **Guild achievements as a real trophy hall** — a dedicated page of milestone banners (first +20, no-death kills, realm-rank climbs) instead of a buried section. | Med | Med |
| B-08 | **Records leaderboard hub** — one polished page for the season: DPS/HPS parses, highest key, season M+ ladder, Iron Attendance, Biggest Climb, all sortable. | High | Med |
| B-09 | **Result-driven character poses** — top parser strikes a victory pose, most-deaths slumps; the rig already breathes, real stats just pick the variant. | High | Med |
| B-10 | **Shareable per-character "trading card" export** — one-click download a slick card of your toon + week stats; free viral distribution back into Discord. | High | Med |

---

## 2. ✨ 10 IMPROVEMENTS — Polish, Quality-of-Life, Performance

| # | Idea (one-line pitch) | Impact | Effort |
|---|---|---|---|
| I-01 | **Sticky roster nav / jump bar** — pinned filter + search + "jump to section" so a 131-card page is never a scroll-hunt. | High | Low |
| I-02 | **Lazy-load cards + progressive image loading** — only render dolls near the viewport (IntersectionObserver already in the rig) so first paint is instant on 131 characters. | High | Low |
| I-03 | **Skeleton loaders + graceful data-empty states** — clean placeholders while weekly data lands, honest "no record yet" instead of blank gaps. | Med | Low |
| I-04 | **Mobile-first card layout pass** — verified single-column reflow, thumb-sized tap targets, no pinch-zoom on any card or the map. | High | Med |
| I-05 | **Legibility contrast pass** — audit class-color names and ink-on-parchment text against WCAG so nothing disappears on dark or light themes. | Med | Low |
| I-06 | **Compress + right-size doll PNGs (WebP/AVIF)** — shrink 131 character images dramatically for load speed with a build-step conversion, PNG fallback. | High | Med |
| I-07 | **Consistent card grid rhythm** — fix the "8-bit blocky" feel with unequal spans, torn edges and sub-degree tilts already proven in the redesign layouts. | Med | Low |
| I-08 | **`prefers-reduced-motion` + a motion toggle** — respect the OS setting (already wired) and add a visible on/off switch for animations. | Med | Low |
| I-09 | **Persisted view state** — remember each visitor's theme, filters and last-viewed character across visits (localStorage, fail-quiet). | Med | Low |
| I-10 | **Week archive + permalinks** — browse past weeks and deep-link any board/recap/record so nothing scrolls into oblivion. | Med | Med |

---

## 3. 🎮 10 INTERACTION Ideas — Engaging, Playful, Social

| # | Idea (one-line pitch) | Impact | Effort |
|---|---|---|---|
| X-01 | **Hover/tap a card → live tooltip** — real gear, spec, best parse, records and catchphrase flip up on the doll (data's already there). | High | Low |
| X-02 | **Click a character → they wave / emote** — a one-shot rig pose on click makes every card feel alive and clickable. | High | Low |
| X-03 | **Rich filters + instant search** — filter the wall by role/class/spec/realm with live count, plus "find my character" pan-and-highlight. | High | Low |
| X-04 | **Parallax scene depth on scroll** — backdrops drift behind the cast for cheap cinematic depth as you move down the page. | Med | Low |
| X-05 | **Clickable voyage islands** — tap an island to reveal its real record-holder / best key and its scene diorama. | Med | Med |
| X-06 | **"Guild photo" pose director** — click-drag to rearrange the line-up and export a custom group shot for Discord. | Med | Med |
| X-07 | **Boss-kill celebration burst** — when a boss falls, the whole wall does a synchronized cheer + confetti of class colors. | High | Med |
| X-08 | **Emote reactions on cards (🔥/💀/👑)** — the guild reacts to each other's dolls; counts persist via the existing Discord read layer or a tiny serverless counter. | High | Med |
| X-09 | **Mini-game: "Guess the Roast" / spin-the-wheel MVP** — a light click-toy on the site (e.g. Brewzleeh's gamble wheel) for idle fun between raid nights. | Med | Med |
| X-10 | **Ambient scene FX + click-to-poke props** — drifting embers, water shimmer, torch flicker matched to theme; poke a torch, a barrel, a pet and it reacts. | Med | Low |

---

*Cross-refs: draws on IDEAS_BACKLOG (VOY-01, WOW-01, ENG-01, STORY-01, INT-01/03/05, ANIM-01/02, WOW-03, DISC-08) but scoped tightly to the website surface. Everything here holds to the static-hosting, solo-build constraint; the only items needing a write-store (X-08 persisted reactions, ENG-style voting) are flagged as such in the backlog.*

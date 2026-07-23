# 💡 Skill Issues Guild Board — IDEAS BACKLOG

*The living idea list for the animated guild-board project. Owned by the Creative/Ideation team. Reviewed **daily** by Zach + the owner.*

**Last updated:** 2026-07-22
**Guild:** Skill Issues · Bleeding Hollow (US) · realm #49
**Vision:** 100+ guild members → consistent anime-styled paper-doll characters assembled from real WoW transmog data (fixed art style, only gear changes), on an interactive web board that updates weekly — growing into stories and eventually short films starring the cast.

---

## How to use this doc (daily ritual, ~5 min)

1. **Skim the "🎯 Next Up" shortlist** at the top — is it still what we want to build next?
2. **Scan "🆕 New since last review"** — the Creative team drops fresh ideas here each day. Promote, park, or kill each one.
3. **Move cards between statuses** by editing the `Status` cell: `💡 idea → 🎯 next → 🔨 building → ✅ shipped → 🗄️ parked/❌ killed`.
4. **Add your own** anywhere — one row, fill the columns, done. Reserve an ID from the counter below.
5. **Log the review** in the Changelog at the bottom (one line).

**ID counter — next free ID:** `INT-10, ENG-12, STORY-12, SEASON-08, ARC-10, VOY-08, DISC-11, ANIM-09, WOW-08`

### Legend

| Field | Values |
|---|---|
| **Impact** | 🟢 High · 🟡 Med · ⚪ Low (how much the guild would *feel* it) |
| **Effort** | S (hours) · M (a day or two) · L (a week+) · XL (multi-week / research) |
| **🔌 Discord** | ✅ = works today · 🔒 = **needs the live Discord integration** we don't have yet |
| **Status** | 💡 idea · 🎯 next · 🔨 building · ✅ shipped · 🗄️ parked · ❌ killed |

> **Feasibility rule:** this is a **solo build on consumer hardware** (one RTX 4080, ComfyUI local, free GitHub Actions, static GitHub Pages, no server). Every idea below is rated with that in mind — if a thing needs a always-on backend or a render farm, it's flagged XL and called out honestly.

---

## 🎯 Next Up — the current shortlist (top 5)

These are the Creative team's picks for what to build next. Rationale in the "Top 5" section at the bottom.

1. **STORY-01 — The Weekly Recap Ribbon → the "Captain's Log"** (HANGOUT_DESIGN adopts it by name as the centerpiece of the Bar and puts it in Phase 0 — same cheapest-high-impact move, now with a home)
2. **ENG-11 — "Deckhand" empty-state treatment** *(new)* (34 of 130 members have no M+ score and would render blank on launch day — turn scorelessness into an in-fiction crew role instead of a bug; PROJECT_CONTEXT flags this as a main path, not an edge case)
3. **VOY-01 — Make the Voyage Map the front door** (now formalized as the ship's **Helm & Chart Room** in the HANGOUT_DESIGN deck plan — same idea, now part of an approved spec)
4. **STORY-10 — Scene-of-the-Week rotation** (12 dioramas + mini-stories as the weekly featured moment; voy07/anim08 mockups in `previews/` show it composing well with the ports and manga-strip ideas)
5. **DISC-01 — Connect the live Discord read layer** (still the highest-leverage single move — now also gates the Bar's Guild Pulse *and* STORY-11, the Discord short stories Zach asked for)

*ENG-01 (profile pages) drops out of the Top 5 — still 🎯, but the launch-blocking empty-state work (ENG-11) takes its slot. ANIM-01 remains gated on the ANIM-06 layer decision.*

---

## 🆕 New since last review (2026-07-22)

*Grounded in what landed since yesterday: HANGOUT_DESIGN.md (the approved "ship" hangout spec — 11 rooms, Phases 0–4, Discord-bridge-not-backend locked in), the big PROJECT_CONTEXT.md audit (launch risks: 34/130 scoreless members, 36-realm roster, ship-name conflict, and an untracked Zach request), and a fresh crop of `previews/` mockups (anim08 manga, arc09 cameo, voy07 ports, wanted posters, ship room states).*

| ID | Theme | Idea | Impact | Effort | 🔌 | Status | One-line pitch |
|---|---|---|---|---|---|---|---|
| STORY-11 | 📖 Story | "Tales from Below Deck" — short stories from Discord chats | 🟢 | L | 🔒 | 🎯 | **Zach explicitly wants this and it's tracked nowhere** (PROJECT_CONTEXT §18): turn real Discord moments into short in-world stories starring the cast — needs a design + data-capture plan now so DISC-01 lands with the right channels retained. |
| ENG-11 | 🎮 Engagement | "Deckhand" empty-state — scoreless members get a role, not a blank | 🟢 | S | ✅ | 🎯 | 34 of 130 members have no M+ score and would render blank on launch; give them in-fiction crew status instead ("swabbing the deck," "stowaway," "new recruit — no bounty yet") so a quarter of the crew is flavor, not missing data. |
| INT-09 | 🖱️ Interactivity | Stats decide which room your doll is in | 🟢 | M | ✅ | 💡 | Weekly data assigns each doll a ship room — top parsers in the Captain's Quarters, most-deaths in the Hold, gamblers in the Casino, scoreless deckhands swabbing — so "where did I end up this week?" becomes the Tuesday ritual. |
| WOW-07 | ✨ Wow-factor | Ship-naming vote + christening reveal | 🟡 | S | ✅ | 💡 | The name is genuinely unsettled (*The Skill Issue* in HANGOUT_DESIGN vs *S.S. Wipe Fest* in PROJECT_CONTEXT's glossary) — let the guild settle it with the proven Discord vote flow, then stage a bottle-smash christening moment on the bow. Resolves an open decision *and* is content. |
| SEASON-07 | 🎃 Seasonal | "Home port" realm flair — 36 realms, one crew | 🟡 | S | ✅ | 💡 | 70% of members aren't on Bleeding Hollow (site copy must stop implying one realm) — show each member's realm as their "home port" on hover/profile and celebrate the fleet's spread; turns an audit-flagged copy risk into lore. |
| DISC-10 | 🤖 Discord | Captain's Log teaser auto-posted back to Discord | 🟡 | S | ✅ | 💡 | The bot already auto-posts the Tuesday board; add a 2-line Captain's Log excerpt + screenshot + "come aboard" link so the site gets weekly traffic from the place the guild actually lives. |

> **Feasibility note (new since yesterday):** the audit found the **art location of the ~67 generated characters is unverified** — worst case is ~$9 of paid regeneration, so nothing above assumes bulk re-generation. All six ideas are static-site-safe under the locked "Discord bridge, no backend" default; only STORY-11 is gated (on DISC-01 + a privacy/consent pass, since it narrativizes general chat).

---

## 1. 🖱️ Interactivity

*The board is currently a rendered image + a responsive read-only web page. These make it a place people poke at.*

| ID | Idea | Impact | Effort | 🔌 | Status | One-line pitch |
|---|---|---|---|---|---|---|
| INT-01 | Hover/tap a character → tooltip card | 🟢 | S | ✅ | 💡 | Real gear, spec, best parse, records, catchphrase pop up on hover (data already in `cast_manifest` + `board_state`). |
| INT-02 | Click a character → dedicated profile page | 🟢 | M | ✅ | 🎯 | Permalink per member (see ENG-01) — the atom every other feature links to. |
| INT-03 | Filter the cast line-up (role/class/spec) | 🟡 | S | ✅ | 💡 | Reuse the existing role-filter + player-search partial the web board already ships. |
| INT-04 | "Zoom to me" / find-my-character search | 🟡 | S | ✅ | 💡 | Type a name, board pans/highlights that doll — great for a 100+ line-up. |
| INT-05 | Transmog diff viewer ("what changed this week") | 🟢 | M | ✅ | 💡 | Slider between last week's doll and this week's; the fingerprint diff already tells us which slots changed. |
| INT-06 | Clickable Voyage Map islands | 🟡 | M | ✅ | 💡 | Tap an island → its real record-holder / best key (data via `voyage.fetch_*`). |
| INT-07 | Board "cursor presence" — see who else is viewing | ⚪ | XL | 🔒 | 🗄️ | Fun but needs a realtime backend; parked as incompatible with static hosting. |
| INT-08 | Emote buttons under each character (🔥/💀/👑) | 🟡 | L | 🔒 | 💡 | Guild reacts to each other's dolls; needs a write-store (Discord or a tiny serverless counter). |

## 2. 🎮 Engagement / Gamification

*Give the mid-pack reasons to show up, beyond top parses. Builds on the existing rotating `awards.py` (Iron Attendance, Biggest Climb).*

| ID | Idea | Impact | Effort | 🔌 | Status | One-line pitch |
|---|---|---|---|---|---|---|
| ENG-01 | Player profile card + permalink | 🟢 | M | ✅ | 🎯 | Every member gets a shareable page: doll, arc, records, streak, catchphrase, gear history. |
| ENG-02 | Title / epithet system ("Averzian's Bane", "Serial Wiper") | 🟢 | M | ✅ | 💡 | Auto-award earned titles from real events; shown under the doll's feet. |
| ENG-03 | Season-long XP / "reputation bar" per member | 🟡 | M | ✅ | 💡 | One number rolling up attendance + climb + kills, so consistency visibly compounds. |
| ENG-04 | Achievement shelf per character | 🟡 | M | ✅ | 💡 | WoW-style achievement pops for guild milestones (first +20, no-death kill, etc.). |
| ENG-05 | Guild-wide progress "raid bar" toward tier goal | 🟡 | S | ✅ | 💡 | A single hero meter — bosses down / total — front and center. |
| ENG-06 | Weekly prediction game ("who tops DPS Tuesday?") | 🟢 | L | 🔒 | 💡 | Members vote in Discord, board scores them next week — needs the read layer + a persisted tally. |
| ENG-07 | Loot-drama "MVP roll" spotlight | 🟡 | M | 🔒 | 💡 | Highlight the week's biggest roll win/heartbreak — needs loot data (Discord/manual). |
| ENG-08 | Streak-freeze / comeback mechanic | ⚪ | S | ✅ | 💡 | Softer attendance streaks so one missed week doesn't nuke a 12-week run; keeps people engaged. |
| ENG-09 | "Fantasy raid team" — pick 5, score by real parses | 🟡 | XL | 🔒 | 🗄️ | Great hook, but needs accounts + persistence; parked until there's a store. |
| ENG-10 | "Unlock the cast" progress meter | 🟡 | S | ✅ | 💡 | ~67 of 134 dolls exist; show ungenerated members as wanted-poster silhouettes with a guild-wide "cast completed" meter — turns the paid-generation rollout itself into content. |

## 3. 📖 Story / Narrative Engine

*The bridge from "leaderboard" to "cast of characters with a story." This is the vision's growth edge.*

| ID | Idea | Impact | Effort | 🔌 | Status | One-line pitch |
|---|---|---|---|---|---|---|
| STORY-01 | Weekly Recap Ribbon (auto "story of the week") | 🟢 | M | ✅ | 🎯 | Template-generate a 3–5 sentence in-world recap from the week's real records, roast, deaths, climbs. |
| STORY-02 | Persistent "lore ledger" per character | 🟢 | M | ✅ | 💡 | Append-only log of each member's real milestones → becomes their backstory over a season. |
| STORY-03 | Rivalries auto-detected from the data | 🟢 | L | ✅ | 💡 | Two players trading the #1 DPS slot week to week get framed as a running feud. |
| STORY-04 | Chapter/arc structure tied to raid progression | 🟡 | M | ✅ | 💡 | Each boss killed closes a "chapter"; the board narrates the arc as the tier unfolds. |
| STORY-05 | "The Crew" roster page with in-world roles | 🟡 | M | ✅ | 💡 | Cast page assigns pirate-crew jobs (navigator, cook, first mate) from real role/rank. |
| STORY-06 | LLM-authored flavor text (local or batched) | 🟢 | L | ✅ | 💡 | Feed real weekly stats to a model to write recaps/roasts/epithets in the guild's voice. Feasibility note: batch offline, review before publish — no live inference needed. |
| STORY-07 | Villain/antagonist framing of the raid tier | 🟡 | S | ✅ | 💡 | Lean into the Voidspire "Imperial Bounty" theme — the raid bosses are the season's recurring antagonists. |
| STORY-08 | Guild "canon" bible file the whole thing reads from | 🟡 | M | ✅ | 💡 | One YAML of established facts/personalities so recaps stay consistent as the story grows. |
| STORY-09 | Drama digest from chat (auto-narrativize the week) | 🟢 | L | 🔒 | 💡 | Turn real guild-chat moments into story beats — **needs the live Discord read of general channels**. |
| STORY-10 | Scene-of-the-Week rotation | 🟢 | S | ✅ | 🎯 | Rotate the 12 SCENE_SCENARIOS dioramas as the board's weekly featured moment, mini-story text as canon — art brief already written, style already approved. |

## 4. 🎃 Seasonal & Event Tie-ins

*Cheap, high-delight, recurring. The theme system (`theme.yml`, 4 layouts, 4 themes) makes reskins a one-line change.*

| ID | Idea | Impact | Effort | 🔌 | Status | One-line pitch |
|---|---|---|---|---|---|---|
| SEASON-01 | Auto-swapping seasonal themes | 🟡 | S | ✅ | 💡 | Board picks a theme by date (Hallow's End, Winter Veil, Noblegarden, Love is in the Air). |
| SEASON-02 | Tier-launch "premiere" board | 🟢 | M | ✅ | 💡 | A special big-reveal board when a new raid tier drops — new antagonist, fresh voyage leg. |
| SEASON-03 | WoW in-game holiday cosmetics on dolls | 🟡 | M | ✅ | 💡 | Sanctioned overlays (pumpkin head, party hat) composited as an extra rig layer for the week. |
| SEASON-04 | "Season in review" year-end montage | 🟢 | L | ✅ | 💡 | Spotify-Wrapped-style recap of the guild's season — top moments, MVPs, most deaths. |
| SEASON-05 | Guild anniversary / milestone boards | 🟡 | S | ✅ | 💡 | Auto-celebrate the guild's birthday and round-number kills. |
| SEASON-06 | Real-world event nights (transmog contest board) | 🟡 | M | 🔒 | 💡 | Run a fashion contest; board tallies votes — smoother with the Discord vote read layer. |

## 5. 🎭 Per-Character Arcs

*Making individuals feel seen. The cast pipeline + versioned `cast_manifest` history is the substrate.*

| ID | Idea | Impact | Effort | 🔌 | Status | One-line pitch |
|---|---|---|---|---|---|---|
| ARC-01 | Transmog evolution timeline per character | 🟢 | M | ✅ | 💡 | Scrub through every past doll version — the manifest already keeps full `history`. |
| ARC-02 | Personal catchphrase / signature line | 🟡 | S | ✅ | 💡 | Members set a line (or it's earned); shown on hover and in recaps. |
| ARC-03 | "Nemesis boss" per character | 🟡 | M | ✅ | 💡 | The boss that's killed them most becomes their personal antagonist tag. |
| ARC-04 | Class/role-flavored idle animations | 🟡 | L | ✅ | 💡 | Healers get a gentler bob, DKs a heavier stance — vary the rig by role, art unchanged. |
| ARC-05 | Milestone "glow-up" moments | 🟡 | S | ✅ | 💡 | First mythic kill / +20 key triggers a one-week aura or badge on the doll. |
| ARC-06 | Newcomer "trial → member" arc | 🟡 | M | 🔒 | 💡 | Track a trial's journey to full member as a mini story — richer with join/promo events from Discord. |
| ARC-07 | In-site character customization / editor | 🟢 | L | ✅ | 💡 | A WoW-creation-style in-browser editor letting a member tweak/override their generated doll (e.g. Rakdisc's blue eyes, features, details transmog can't capture) — manual overrides layered on the auto-generated look. |
| ARC-08 | Per-character gear/look overrides | 🟢 | M | ✅ | 💡 | Player-set preferences the pipeline can't infer — "show Rakdisc with minimal/no heavy gear" (robe caster), preferred pose/expression, hide/show specific gear slots. Complements ARC-07. |
| ARC-09 | Spotlight-fairness tracker ("cameo debt") | 🟡 | S | ✅ | 💡 | SCENE_SCENARIOS casts each member once; track who's never been featured in any scene/recap and auto-bias the next casting toward them so the mid-pack feels seen. |

## 6. 🗺️ The Voyage Map

*Already has real backing code (`voyage.py`, `render_voyage_map.py`) — this is a partly-built goldmine.*

| ID | Idea | Impact | Effort | 🔌 | Status | One-line pitch |
|---|---|---|---|---|---|---|
| VOY-01 | Ship the map as the board's front door | 🟢 | M | ✅ | 🎯 | The crew's ship docked at the live `current_island`, islands ahead — the board's signature view. |
| VOY-02 | Animate the ship sailing between islands on progress | 🟢 | M | ✅ | 💡 | When `current_island` advances, the ship visibly sails the leg — a satisfying weekly beat. |
| VOY-03 | Island "landing card" with real records | 🟡 | S | ✅ | 💡 | Dock an island → best key / record holder there (wired already via `fetch_*`, just needs UI). |
| VOY-04 | Fog-of-war on unreached islands | 🟡 | S | ✅ | 💡 | Undiscovered islands are misty until the guild arrives — visual progression hook. |
| VOY-05 | Crew placed on the map (cast on the ship deck) | 🟢 | L | ✅ | 💡 | The paper-doll cast stands on the ship — unifies the two biggest features into one scene. |
| VOY-06 | Map as a persistent season-long "campaign trail" | 🟡 | M | ✅ | 💡 | Past islands stay marked with the week they fell — the map becomes the season's timeline. |
| VOY-07 | Scene locations as voyage ports | 🟢 | M | ✅ | 💡 | Map the 12 scene backdrops onto the voyage route as visitable ports (SCENE_SCENARIOS already calls itself the map's backbone) — docking at an island opens its diorama. |

## 7. 🤖 Discord-Fed Drama & Automation

*The guild's Discord is alive (guild-chat, memes, healmates-bully-corner, gambling, anime, the-important-people, board-announcements). We currently only read the **roast** + **announcement** channels. **Everything here marked 🔒 is what connecting the full read layer would unlock.***

| ID | Idea | Impact | Effort | 🔌 | Status | One-line pitch |
|---|---|---|---|---|---|---|
| DISC-01 | Connect the live Discord read layer | 🟢 | M | 🔒→✅ | 🎯 | The keystone: extend the existing bot-read to general channels. Unlocks this whole section. |
| DISC-02 | "Quote of the week" from guild-chat | 🟢 | M | 🔒 | 💡 | Auto-surface the funniest/most-reacted line as a board pull-quote (reuse roast vote-count logic). |
| DISC-03 | Meme of the week from #memes | 🟡 | M | 🔒 | 💡 | Top-reacted image in #memes gets a framed slot on the board. |
| DISC-04 | Healmates Bully Corner → a real board module | 🟢 | M | 🔒 | 💡 | The channel's culture becomes a recurring "healer roast" card — the guild will love it. |
| DISC-05 | Gambling channel → on-board odds/leaderboard | 🟡 | L | 🔒 | 💡 | Extend the existing Brewzleeh "Gambling Debt" gag into a live standings card. |
| DISC-06 | Auto-detect drama spikes (reaction storms) | 🟡 | L | 🔒 | 💡 | A message that blows up becomes a flagged "incident" the recap can narrativize. |
| DISC-07 | "The Important People" → featured-member rotation | ⚪ | S | 🔒 | 💡 | Whatever that channel signals, surface it as a rotating spotlight. |
| DISC-08 | Two-way: board posts a reactable weekly poll | 🟡 | M | 🔒 | 💡 | Board asks a question, guild reacts, next board shows results (prediction-game plumbing). |
| DISC-09 | Guild votes the next scene | 🟢 | S | ✅ | 💡 | Reuse the proven board-vote/redesign-vote workflow: guild reacts in Discord to pick which scene gets generated next — engagement now, art budget spent where the guild wants it. |

## 8. 🎬 Animation & Scene Ideas

*The rig is real and performant (CSS transforms, 120 chars @ 60fps, `IntersectionObserver`, `prefers-reduced-motion`). These push toward the "short movies" ambition without a render farm.*

| ID | Idea | Impact | Effort | 🔌 | Status | One-line pitch |
|---|---|---|---|---|---|---|
| ANIM-01 | Result-driven reaction poses | 🟢 | M | ✅ | 🎯 | Top parser strikes a victory pose, most-deaths slumps — real stats drive the idle variant. |
| ANIM-02 | Parallax scene depth behind the cast | 🟡 | S | ✅ | 💡 | Background scene (tavern, ship, ruin) parallaxes as you scroll — cheap depth, big feel. |
| ANIM-03 | Ambient scene FX matched to the theme | 🟡 | S | ✅ | 💡 | Extend the existing embers/torches GIF FX into the web scene (drifting motes, water shimmer). |
| ANIM-04 | Weekly "cutscene" — cast reacts to the recap | 🟢 | L | ✅ | 💡 | A short scripted looped scene (rig poses + text) dramatizing the week — the first "mini episode". |
| ANIM-05 | Boss-kill celebration animation | 🟢 | M | ✅ | 💡 | When a boss falls, the whole line-up does a synchronized cheer beat. |
| ANIM-06 | Per-slot layered rig (the "only gear changes" dream) | 🟢 | XL | ✅ | 💡 | **Architecture gap:** pipeline outputs a flat cutout today; the layer contract wants per-slot layers. Cracking this makes gear swap seamless + unlocks real animation. |
| ANIM-07 | Idle "props" — class fantasy flourishes | ⚪ | M | ✅ | 💡 | A mage's floating orb, a hunter's pet at their feet — small looping accents per class. |
| ANIM-08 | Weekly 2-panel "manga strip" | 🟢 | M | ✅ | 💡 | Scene stills + speech bubbles + the recap's real events = a weekly comic panel; the cheapest real step toward "short movies," and it needs zero rig layers. |

## 9. ✨ Wow-Factor Moments

*The "whoa" screenshots that make people share the board.*

| ID | Idea | Impact | Effort | 🔌 | Status | One-line pitch |
|---|---|---|---|---|---|---|
| WOW-01 | The full 100+ cast "guild photo" hero shot | 🟢 | L | ✅ | 💡 | One breathtaking animated line-up of the entire guild — the project's signature image. |
| WOW-02 | Cinematic tier-kill splash | 🟢 | M | ✅ | 💡 | Final-boss kill triggers a full-screen cinematic card with the crew silhouetted against the throne. |
| WOW-03 | Shareable per-week "trading card" export | 🟢 | M | ✅ | 💡 | One-click download a slick card of your character + week stats — free viral distribution. |
| WOW-04 | Animated intro sequence on first load | 🟡 | M | ✅ | 💡 | Ship sails in, cast assembles, title drops — a 4-second reveal that sets the tone. |
| WOW-05 | "Boss looms over the cast" scene | 🟡 | M | ✅ | 💡 | Composite the current antagonist boss enormous behind the line-up — real stakes, one scene. |
| WOW-06 | Year-one "the movie" — stitched season montage | 🟢 | XL | ✅ | 💡 | The north-star payoff: a real short film cut from a season of recaps, poses, and scenes. |

---

## 🔌 What connecting the live Discord integration buys us

We currently read only the **roast** and **announcement** channels (via a read-only bot over Discord's REST API — see `guild_board/discord_inputs.py`). Extending that same mechanism to the general channels (DISC-01) is the **single highest-leverage unlock** in this whole backlog. It directly enables:

- **STORY-09** drama digest · **DISC-02–08** (quote/meme of the week, Bully Corner & Gambling modules, drama-spike detection, featured-member rotation, two-way polls)
- **ENG-06** prediction game · **ENG-07** loot-drama spotlight · **SEASON-06** event-night voting · **ARC-06** trial arcs

Nothing here needs a new server — it's the same free-tier, read-only pattern already proven for roasts, just pointed at more channels (with member consent + a privacy pass, since general chat is more sensitive than a roast box).

## 🧱 Feasibility reality check (solo + consumer hardware)

- **Green-light zone:** anything that's data-templating, theming, or CSS-transform animation. The web board is static HTML/CSS/JS on GitHub Pages, rendered weekly by free GitHub Actions — cheap and proven.
- **Art generation** runs locally on the RTX 4080 via ComfyUI (SDXL, img2img + ControlNet + rembg). Batch, review, commit. No cloud cost, but it's **the throughput bottleneck** for 100+ members — cast refreshes must stay incremental (only re-render changed transmogs; the fingerprint diff already does this).
- **The one hard architecture problem:** ANIM-06. The pipeline outputs a single flat cutout per character, but the paper-doll layer contract wants per-slot layers (cloak/body/legs/chest/arms/head/weapons). Until that's bridged, "only gear changes" is aspirational and animation is whole-body-only. Worth a dedicated R&D spike before over-investing in layered features. **Note:** the new customization ideas (ARC-07/ARC-08) also ride on this — per-slot layers are what make "hide the heavy gear" or "swap the eyes" a clean override rather than a full re-render.
- **Avoid (for now):** anything needing an always-on backend, realtime presence, or user accounts with writes (INT-07, ENG-09) — incompatible with static hosting until we choose a lightweight store.

---

## 🗄️ Parking Lot / Someday-Maybe

- Voice lines / TTS for characters in cutscenes (fun, heavy, later)
- Mobile app wrapper (the responsive web board covers 95% of this)
- Cross-guild "leaderboard of leaderboards" (out of scope until the guild board is loved)
- NFT / on-chain anything (explicitly not doing this)

## ✅ Recently Shipped (pull from the other teams' logs as they land)

- Weekly Discord board (WCL + Raider.io, auto-posts Tuesdays) — *live*
- Rotating awards: Iron Attendance, Biggest Climb — *live*
- Roast-of-the-week Discord voting — *live*
- Imperial Bounty theme + 4 web layouts / 4 themes — *branch 2.0, in review*
- Cast art pipeline (One Piece style, ComfyUI local) — *built*
- Voyage map data layer — *built, needs a front-door UI*

---

## 📓 Daily Review Changelog

*One line per review. Newest on top.*

- **2026-07-22** — Daily refresh. Added 6 ideas grounded in HANGOUT_DESIGN.md (ship spec), the PROJECT_CONTEXT.md audit, and the new previews: STORY-11 Discord short stories (Zach's untracked request, §18), ENG-11 deckhand empty-state (34/130 scoreless = launch blocker), INT-09 stats-pick-your-room, WOW-07 ship-naming vote + christening (resolves the *Skill Issue* vs *Wipe Fest* name conflict), SEASON-07 home-port realm flair (36 realms), DISC-10 Captain's Log Discord teaser. Re-prioritized Top 5: ENG-11 in at #2, ENG-01 out; STORY-01 reframed as the Captain's Log per HANGOUT_DESIGN Phase 0. Graduated the 07-21 batch (STORY-10, ANIM-08, VOY-07, DISC-09, ENG-10, ARC-09) from the New bucket into their category tables, statuses unchanged. Now 70 ideas. — *Creative team (automated daily run)*
- **2026-07-21** — Daily refresh. Added 6 ideas grounded in the last 24h of work (SCENE_SCENARIOS, WEBSITE_IDEAS, trial art, paid-generation handoff): STORY-10 scene-of-the-week, ANIM-08 manga strips, VOY-07 scenes-as-ports, DISC-09 vote-the-next-scene, ENG-10 unlock-the-cast meter, ARC-09 cameo-debt tracker. Re-prioritized Top 5: STORY-10 promoted to #3; ANIM-01 dropped out (single-image scene style approved for trial → pose variants gated on ANIM-06 layer decision). Added feasibility note: generation is now paid per-character API, not free local ComfyUI. Now 64 ideas. — *Creative team (automated daily run)*
- **2026-07-20** — Added 2 ideas from Zach: ARC-07 (in-site character customization / editor) and ARC-08 (per-character gear/look overrides). Backlog-only, queued behind the foundation work per Zach. Both depend on the ANIM-06 per-slot layer decomposition — noted in the feasibility check. Now 58 ideas. — *Creative team*
- **2026-07-20** — Backlog created. 56 ideas across 9 categories. Top 5 set: STORY-01, VOY-01, ANIM-01, DISC-01, ENG-01. Flagged ANIM-06 (layer gap) and DISC-01 (integration keystone) as the two decisions that gate the most downstream ideas. — *Creative team*

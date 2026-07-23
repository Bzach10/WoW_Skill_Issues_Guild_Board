# 🚢 HANGOUT_DESIGN — The Ship

*The guild's own vessel: the site as a ship the crew lives on — with a bar, a casino, a brig and a hold — sailing the Voyage Map. Approved metaphor (Zach, Jul 2026). This is the build spec; front-end can start Phase 0.*

**Last updated:** 2026-07-20
**Guild:** Skill Issues · Bleeding Hollow (US)

---

## Why the ship is the right call

It solves three problems with one idea:

1. **The site becomes a place**, not a page — you're *aboard* something, with rooms to wander into.
2. **It unifies the whole product.** The ship is the guildhall *and* it's the same ship already sailing the Voyage Map. The Helm shows where we are in the tier; the decks below are where the crew actually hangs out. One metaphor, no seams.
3. **It's uniquely theirs.** A bar stocked with Brewzleeh's brews, a casino he runs, a brig for the Bully Corner, a hold full of tombstones — no other guild's site looks like this.

**Ship name — recommend `The Skill Issue`** (singular, deadpan; "welcome aboard The Skill Issue"). Alternates if Zach prefers: *S.S. Corpse Run*, *The Wipefarer*, *The Reserved Plot*.

---

## STEP 1 — What gave the ORIGINAL board its soul (the diagnosis, unchanged)

The original product wasn't a website — it was the **weekly Discord "Guild Board."** From the actual code, its personality is loud and specific:

- **Roast of the Week** — members post roasts all week, the guild 🔥-votes, top one gets crowned. Real winner on file: *"Healmates Sucks" — Rakdaddy.* No submissions? The board says *"No roast submitted. Healers live to see another week."*
- **The Graveyard** — tombstone memorial with a flickering campfire and **reserved plots** for repeat offenders. Motto: *"Die in the fire, enter the leaderboard."*
- **Brewzleeh's Gambling Debt** — a glowing, **ticking counter** that only ever climbs (+1,337/tick), with an "interest note" and unhinged flavor lines, rendered as a fake legendary item.
- **Item of the Month** — a swappable gag item card.
- **Rotating awards the mid-pack can win** — Iron Attendance, Biggest Climb — so it isn't just the top-5 parsers hogging the light.
- **The voice** — self-deprecating, roasty, WoW-native gallows humor. Healers get bullied. Wiping is content. Nobody's safe, everybody's in on it.

Fed by real Discord culture: `#guild-chat`, `#memes`, `#healmates-bully-corner`, `#gambling`, `#the-important-people`, `#board-announcements`.

### What the polished dashboard LOST

1. **Jokes demoted to footer decoration** — the debt, graveyard and roast (the reasons people looked) became small modules at the bottom.
2. **It went read-only** — the original *responded to* what the guild did all week. The website just displays. No input = no ownership.
3. **The conversation vanished** — none of the Discord chatter, memes or drama energy is present.
4. **The characters are mannequins** — 131 gorgeous dolls standing in a grid, reacting to nothing.
5. **No "here" there** — no room, no corner, nowhere you'd say "meet you on the board."

**One sentence:** *the original board had a personality and invited the guild to talk back; the website is a trophy case with the guild locked outside the glass.*

**North star for the fix:** *would a guildie open this on a Tuesday just to hang out, even with zero raid that week?*

---

## STEP 2 — The Ship: deck plan

Navigation is an **illustrated cutaway of the ship** — a side-on cross-section where every room is a clickable hotspot. (Phase 0 ships a simple version: a deck-list nav + anchored sections. The full painted cutaway comes later.) Rooms run top-to-bottom exactly as you'd walk the ship, which doubles as a natural scroll order.

### ⬆️ ABOVE DECK

| Room | What lives here | Absorbs |
|---|---|---|
| 🔭 **The Crow's Nest** | Lookout / what's ahead: next island on the course, next boss, raid-night countdown, recruitment call, "incoming" alerts. The first thing you see. | New |
| ⚓ **Main Deck — The Crew** | All 131 cast characters on deck, milling around, reacting to real events. The hero wall. | Character grid |
| 🧭 **The Helm & Chart Room** | The Voyage Map: the season's course, islands taken vs. ahead, tier completion, the ship's current position. | Voyage map |
| 👑 **The Captain's Quarters** | Trophy room: records, achievements, leaderboards, season standings, the guild crest. | Stats sections |

### ⬇️ BELOW DECK

| Room | What lives here | Absorbs |
|---|---|---|
| 🍺 **The Bar** | **The hangout heart.** Guild pulse feed, banter, "who's popping off," the guestbook wall, inside-jokes shrine — and Brewzleeh's brews on tap. | New (landing after Crow's Nest) |
| 🍳 **The Galley** | Item of the Month, MOTD, guild "recipes" gag. A small nook off the Bar. | Footer item card |
| 🎰 **The Casino** | Brewzleeh's domain: the gambling-debt plaque + ticking counter, the Wheel of Debt, bets & polls. | Footer debt card, promoted |
| ⚙️ **The Engine Room** | The grind that moves the ship: M+ keys, season scores, Biggest Climb, weekly key runs. | M+ sections |
| 🧵 **The Slop Chest** (armory) | Transmog & gear: "what changed this week," gear history, and later the character customization/overrides (ARC-07/08). | New |
| 🔒 **The Brig** | The Bully Corner — "Healer of Shame," affectionate dunking, **opt-out honored**. | `#healmates-bully-corner` |
| ⚰️ **The Hold** | Memorial: graveyard tombstones + reserved plots, Roast of the Week, and the Hall of Flame roast archive. | Footer graveyard, promoted |

**Eleven rooms, one ship.** Data still lives aboard — but you arrive in a *room*, not a spreadsheet.

---

## A. SOUL — the guild's humor, welded to the hull

The gags stop being footer furniture and become the ship's fixtures.

- **Gags get rooms, not footers.** Brewzleeh's debt is a glowing brass plaque bolted in **the Casino**, counter ticking. The Graveyard is a room you walk into (**the Hold**). The Roast is pinned where you can't miss it.
- **Hall of Flame** (in the Hold) — every past Roast of the Week, browsable and re-votable. *"Healmates Sucks — Rakdaddy"* gets a permanent brass nameplate. Plus an all-time "most-roasted crewmember" counter (Healmates wins; that's the joke).
- **The Brig** — `#healmates-bully-corner` as a real room: a rotating "Healer of Shame" card, affectionate and guild-canon. **Opt-out list is honored** — anyone can leave the Brig permanently, no questions.
- **Nautical + WoW microcopy everywhere.** Loading → *"Weighing anchor…"*. Empty feed → *"Quiet week. Suspiciously quiet. Healmates definitely did something."* No roast → *"Healers live to see another week."* 404 → *"You've gone overboard. Swim back to the Bar."* Offline → *"Becalmed."*
- **Fake-legendary item styling** on the debt plaque, Item of the Month and earned titles — orange text, *"Requires: Level 60 Degeneracy."* A language the guild reads fluently.
- **Weekly Captain's Log** — the auto-generated recap, in the guild's voice, posted at the top of the Bar: what went down this week, stitched from real records/roast/deaths/climbs. (IDEAS_BACKLOG STORY-01/06)

## B. THE BAR — the gathering heart

The room that fixes "nowhere to hang out." Alive whether or not you raided.

- **🔥 The Guild Pulse (Discord feed).** A ribbon of the week's best moments pulled from the **fun guild-public channels: `#guild-chat`, `#memes`, `#healmates-bully-corner`, `#gambling`** — top-reacted lines, the top meme, a flag when something blows up. Reuses the existing roast vote-count logic in `discord_inputs.py`. *(🔒 needs DISC-01, the read layer extended.)*
- **📣 "Who's Popping Off."** Auto shoutouts: biggest climber, fresh personal-best parse, new streak record, first +20. Amrevenge topping DPS again? The Bar announces it. Rotating so it's never the same three names.
- **✍️ The Guestbook Wall.** Carve your name in the ship's timber — short notes and tags that persist. *(Bridged through Discord — see Defaults.)*
- **📌 Inside-jokes shrine.** Officer-seeded guild canon: the origin of "Skill Issues," the Brewzleeh debt lore, the great Healmates wipe. New crew read it and *get* the group.
- **🕯️ Ambient life.** Cast dolls seated at tables, leaning on the bar, campfire/lantern flicker, gentle ship sway — so the room always looks inhabited even at 4 AM.
- **🍻 Brewzleeh's brews** on tap behind the bar — a visual gag tying the Bar to the Casino next door.

## C. THE CASINO — Brewzleeh's domain

- **The Debt Plaque.** The ticking, glowing counter as the room's centerpiece, with its interest note and escalating flavor lines.
- **🎰 The Wheel of Debt** (the mini-game). Spin for a random roast, a *"you owe Brewzleeh 1,337g"* verdict, a random crew callout, or a title. Pure client-side, no stakes, endlessly re-spinnable — the idle hook that brings people back mid-week.
- **Bets & polls.** *"Who's carrying this week?" "Worst pull of the tier?" "Next transmog theme?"* Vote aboard, results next week — extends the proven roast-vote pattern. *(Bridged through Discord.)*
- Ties directly to **SCENE_SCENARIOS #12 (Undermine)**, where Brewzleeh runs his rigged table — the Casino is that scene, aboard.

## D. THE CREW — making the characters come alive

The dolls on Main Deck should visibly *know* what happened this week.

- **Real events drive real poses.** Top parser → victory pose. Most deaths → slumped/ghost. New +20 → triumphant. Biggest climb → fired-up. The rig already breathes; stats just pick the variant. (ANIM-01)
- **Status badges & auras.** A crown on the week's #1, a ghost over the Hold's top camper, a glow on a fresh record-holder, a coin-purse on whoever Brewzleeh fleeced.
- **Earned titles under their feet.** *"Averzian's Bane," "Serial Wiper," "In Debt to Brewzleeh," "Survived the Brig."* (ENG-02)
- **Crew reactions, together.** Boss kill → the whole deck cheers with class-color confetti. Raid wipe → a comedic collective faceplant. (ANIM-05 / X-07)
- **Click-to-emote.** Click any crewmate and they wave, flex, bow or faceplant. Zero backend, pure rig — the cheapest, highest-delight interaction aboard. (X-02)
- **Banter.** Hover/click two crewmates and they trade a line drawn from real data — the two trading #1 DPS get a rivalry line; healers commiserate about the Brig. (STORY-03)
- **The crew populates the ship.** The same 131 dolls staged as regulars: at the bar, gambling in the Casino, on watch in the Crow's Nest, doing time in the Brig.

---

## Tone guide

- **Roasty but affectionate.** We dunk because we're friends. Never mean to someone who didn't opt in — the Brig works because Healmates is in on it, and there's an opt-out.
- **WoW-native, lightly nautical.** Parses, keys, wipes, transmog — with ship dressing on top. Never a corporate SaaS voice.
- **Wiping is content.** Failure is celebrated. The Hold is funny. Debt is funny. Skill issues are the brand.
- **Punches sideways, not down.** Officers get roasted too.
- **Example copy:** *"Spin the Wheel of Debt," "Sign the Wall," "Throw a 🔥," "Report to the Brig," "Below Deck."*

---

## Locked defaults (per Zach)

1. **No new backend — interactions bridge through Discord.** React/vote/sign aboard → the bot writes it to Discord; Discord stays the single source of truth and the site stays static on GitHub Pages. Zero infra cost, zero maintenance.
2. **The Brig has an opt-out.** Anyone can leave the Bully Corner permanently; the list is honored everywhere.
3. **Public feed pulls the fun guild-public channels only:** `#guild-chat`, `#memes`, `#healmates-bully-corner`, `#gambling`. `#the-important-people` and anything private stay out.

## Feasibility

- **🟢 Free / static-safe (build now):** the ship reframe and deck nav, promoting the gags into rooms, all microcopy, Captain's Log recap, "who's popping off," click-to-emote, result-driven poses, badges/titles, the Wheel of Debt, boss-kill celebration, ambient life. Renders at build time or runs in-browser.
- **🔒 Needs the Discord read layer (DISC-01):** the Guild Pulse feed, meme/quote of the week, drama flags. Highest-leverage unlock; reuses existing code pointed at more channels.
- **🟠 Needs the Discord write bridge (default #1):** persisted reactions, the Guestbook Wall, polls/bets, comments. No DB — the bot posts on the crew's behalf.

---

## Build phases

**Phase 0 — Board the ship (zero backend, do first).**
Reframe the site as *The Skill Issue*: deck-list nav + anchored rooms, build the **Crow's Nest**, **Main Deck**, **Bar**, **Casino**, **Hold** shells; promote the gags into their rooms (debt plaque ticking in the Casino, tombstones + Hall of Flame in the Hold, roast pinned); roll nautical/WoW microcopy sitewide; ship the **Captain's Log** recap and **"Who's Popping Off."**
→ *This alone kills the "empty / no soul / no spot to hang out" problem with no backend at all.*

**Phase 1 — Wake the crew (free, high-delight).**
Click-to-emote, result-driven poses, badges/auras/titles, boss-kill celebration, and staging cast dolls throughout the ship's rooms.
→ *Kills "mannequins / no interaction."*

**Phase 2 — Open the Casino (free).**
The Wheel of Debt, crew banter, the inside-jokes shrine, the Galley.
→ *Idle fun that pulls people back mid-week.*

**Phase 3 — Connect the Pulse (the keystone).**
Extend the Discord read layer → live Guild Pulse in the Bar, meme/quote of the week, drama flags.
→ *Makes it feel like the guild is actually aboard.*

**Phase 4 — Two-way (Discord bridge).**
Persisted reactions, Guestbook Wall, polls/bets, comments — all written through the bot.
→ *Gives the crew ownership, the thing the read-only site lost.*

**Later:** the full painted ship cutaway nav, the Slop Chest customization editor (ARC-07/08), Engine Room deep stats.

---

## Remaining question for Zach

**Ship name** — going with **`The Skill Issue`** unless he says otherwise. Alternates: *S.S. Corpse Run*, *The Wipefarer*, *The Reserved Plot*.

*Cross-refs: WEBSITE_IDEAS (B-01/02/05, X-02/07/08/09), IDEAS_BACKLOG (DISC-01/02/03/04, STORY-01/03, ENG-01/02, ANIM-01/05, ARC-07/08, VOY-01/05), SCENE_SCENARIOS (#12 Undermine → the Casino).*

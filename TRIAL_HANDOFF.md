# Trial handoff — 3 characters in the approved scene style

For the front-end session's trial website. These are final images, ready
to display as-is. No paper-doll layers, no manifest changes needed — this
trial is single-image per character, which is the look Zach approved.

## The three finals

| Character | Path | Provenance |
|---|---|---|
| **Rakdisc** | `cast/_trial/rakdisc.png` | `cast/rakdisc/scene1_raidhall_w025.png` — Zach's #1, used AS-IS, not regenerated |
| **Floofwall** | `cast/_trial/floofwall.png` | `cast/floofwall/floofwall_tavern_w025.png` — the one Zach likes, used AS-IS |
| **Healyeah** | `cast/_trial/healyeah.png` | NEW — `healyeah_dragonflight_scene_w030_s70203.png` |

Originals are untouched; `cast/_trial/` holds copies under stable names so
the site can link them without depending on seed numbers.

Contact sheet of all three together: `cast/_trial/_trio.png`

An alternate Healyeah is at `cast/_trial/healyeah_alt.png` — see below.

## What changed for Healyeah

The previous Healyeah missed: he rendered as a feral quadruped dragon on
a plain gradient, with no scene and no armour.

Root cause: **"Dracthyr" is not a concept the model knows.** Prompting it
yields either a feral dragon or a human with wings bolted on — both of
which happened. The fix is to describe what a Dracthyr *looks like* in
words the model does know: "an anthropomorphic dragon man, bipedal,
draconic head with a long reptilian snout, standing on two clawed legs",
with `human face, human head, human skin` pushed hard into the negative.

Recipe otherwise unchanged from the approved one: `build_ipadapter_graph`,
IP-Adapter on his real Blizzard transmog render, clip-skip-2, tiled VAE,
detail pass. Weight is **0.30** rather than 0.25 — still inside the
approved family (`healyeah_dragonflight_v2_w030` already used 0.30), and
0.25 was too weak to hold the species.

Class fantasy leaned into: he is an **Augmentation Evoker**, which is the
**bronze** dragonflight — so bronze/gold armour, sand-and-time magic, and
an ornate dragon spire rather than a generic fantasy hall.

## Two honest notes before this goes in front of Zach

**1. Style cohesion is imperfect.** Rakdisc and Floofwall are flat
cel-shaded with bold ink outlines. The chosen Healyeah is more
painterly/rendered and more saturated. They read as the same family, but
he is visibly the odd one out.

`cast/_trial/healyeah_alt.png` is a flat-cel version generated to match
them more closely, and its armour is a better match for his real
transmog (crimson + gold + red gems, twin spell-flames). It was NOT
chosen because its face is armoured/masked with large horns, which risks
reading as a demon again — the exact complaint being fixed. **If Zach
cares more about style cohesion than species clarity, swap to the alt.**

**2. The sword is off-class.** Evokers do not wield greatswords; they
cast. The chosen image is visually the strongest and unmistakably a
dragon, but a purist will notice.

## What the site needs from this

Nothing beyond the three paths. They are ordinary PNGs at varying sizes;
`rakdisc.png` and `floofwall.png` are 832x1216, `healyeah.png` is larger
(the detail pass upscales). Scale to a common height on the page.

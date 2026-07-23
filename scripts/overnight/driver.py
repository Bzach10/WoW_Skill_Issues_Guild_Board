"""The self-driving overnight run: generate -> checkpoint -> log -> resume.

This is where the autonomy lives. It is a plain process, not an agent: it
holds the whole night's work as an explicit task list, does one task at a
time, writes each result to the checkpoint file the moment it lands, and
never lets one bad asset stop the run.

Ordering is deliberate. The roster characters people will actually look
at come first, so that if the night dies at 2am we lost library breadth
rather than the cast. Within a character, the base body comes first
because every gear layer is generated FROM it.

Resume is free: re-running skips anything already in the checkpoint. Kill
it and restart it as often as you like.

    python scripts/overnight/driver.py            # run the whole plan
    python scripts/overnight/driver.py --dry-run  # print the plan only
"""

import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compose import render as compose_render  # noqa: E402
from engine import (ComfyClient, Hung, collect_outputs, controlnet_graph,  # noqa: E402
                    load_state, log, log_resources, mark_done, mark_failed,
                    resources, save_state, stage_input, txt2img_graph, alert)
from layers import extract_layers, write_layers  # noqa: E402
from publish import publish, verify  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
BODIES = REPO / "cast" / "_bodies"
GEAR = REPO / "cast" / "_gear"

STYLE_TAIL = ("one piece anime style, cel shaded, clean bold lineart, "
              "full body single character head to feet, "
              "standing straight front view, "
              "flat plain light grey background, even flat lighting, no shadow")

BODY_NEG_BASE = ("cropped, cut off, out of frame, close-up, portrait, "
                 "long flowing hair, hair covering body, "
                 "elongated body, distorted anatomy, tiny head, "
                 "multiple characters, weapon, armor, robe, cloak, cape, "
                 "hood, background scenery, text, watermark, blurry, "
                 "extra limbs, dynamic pose, tilted, perspective, "
                 "underwear, lingerie, swimsuit, bikini, nude, topless")
GEAR_NEG = ("cropped, cut off, out of frame, close-up, nude, topless, "
            "underwear, lingerie, bikini, swimsuit, bare legs, leotard, "
            "multiple characters, background scenery, "
            "text, watermark, blurry, extra limbs, dynamic pose, tilted")

# Base bodies wear modest clothing on purpose. The base is only ever seen
# where a gear layer fails to cover it — and the first run proved that
# happens (a missing midsection turned a roster member into a figure in
# underwear). Tunic-and-leggings means the worst case is "plainly
# dressed" rather than "undressed", which is the right failure mode for a
# board showing real people's characters.
BODY_WEAR = ("wearing a plain modest fitted tunic and full-length leggings, "
             "simple undyed cloth, covered arms and legs, simple shoes")

# --- base bodies ---------------------------------------------------------
# SPECIES LEADS. The first attempt buried the race clause mid-prompt and
# every non-human came out as the same slim human woman — the model's
# prior simply outvoted it. Species now opens the prompt, is restated,
# and each race carries its own negative naming exactly what it is NOT.
RACES = {
    "nightborne_female": {
        "pos": "a tall slender nightborne elf woman, lavender purple skin, "
               "long pointed ears, glowing golden eyes, "
               "white hair in a tight neat bun, elegant sharp features",
        "neg": "human skin, round ears, fur, scales, muscular, male, man",
        "seed": 4242,
    },
    "pandaren_male": {
        "pos": "a huge burly anthropomorphic giant panda man, "
               "thick black and white fur covering his entire body, "
               "furry panda head with black eye patches and round black ears, "
               "black fur arms and legs, broad heavy build, big belly, "
               "black topknot, a male panda warrior, anthro panda",
        "neg": "human, human skin, bare skin, humanoid face, woman, female, "
               "feminine, slim, skinny, thin, breasts, long legs, elf",
        "seed": 8801,
    },
    "dracthyr_male": {
        "pos": "an anthropomorphic dragon man, dragonkin, "
               "bronze scaled skin covering the whole body, "
               "draconic head with a snout, short horns swept back, "
               "reptilian eyes, clawed hands, athletic male build, no hair",
        "neg": "human, human face, human skin, fur, woman, female, feminine, "
               "slim, breasts, elf, round ears",
        "seed": 3310,
    },
    "nightelf_female": {
        "pos": "a tall night elf woman, violet purple skin, "
               "very long pointed ears, silver hair in a tight braid, "
               "glowing silver eyes, athletic build",
        "neg": "human skin, round ears, fur, scales, male, man",
        "seed": 5150,
    },
    "human_male": {
        "pos": "an athletic human man, fair skin, short brown hair, "
               "square jaw, broad shoulders, masculine build",
        "neg": "woman, female, feminine, breasts, slim, elf, pointed ears, "
               "fur, scales",
        "seed": 6120,
    },
    "orc_male": {
        "pos": "a heavyset muscular orc man, green skin, "
               "small tusks jutting from the lower jaw, heavy brow, "
               "black topknot, thick arms, broad build",
        "neg": "human skin, woman, female, feminine, slim, skinny, elf, "
               "pointed ears, fur, scales",
        "seed": 7005,
    },
}

# --- gear archetypes: finite, reusable, NOT per-WoW-item ----------------
ARCHETYPES = {
    "cloth_robe_holy": "wearing a long flowing white and gold priest robe, "
                       "wide draping sleeves, layered cloth skirt to the "
                       "floor, gold trim, holy vestments, ornate embroidery",
    "cloth_robe_shadow": "wearing a long dark violet and black robe, "
                         "wide draping sleeves, layered skirt to the floor, "
                         "silver trim, shadowy vestments",
    "leather_scout": "wearing fitted brown leather armour, studded jerkin, "
                     "belted waist, leather bracers, knee-high boots",
    "mail_hunter": "wearing green and steel chainmail armour, mail shirt, "
                   "shoulder guards, belted waist, sturdy boots",
    "plate_warrior": "wearing heavy polished steel plate armour, "
                     "large pauldrons, breastplate, plated legs, "
                     "armoured boots, gold filigree",
    "plate_paladin": "wearing ornate silver and gold plate armour, "
                     "winged pauldrons, holy breastplate, plated legs, "
                     "radiant gold trim",
}

# Roster characters get composited and published; library entries are art
# only, ready to be mapped onto characters later.
ROSTER = {
    "rakdisc-proudmoore": ("nightborne_female", "cloth_robe_holy"),
    "floofwall-queldorei": ("pandaren_male", "leather_scout"),
    "healyeah-queldorei": ("dracthyr_male", "mail_hunter"),
}

# Roster first, then the rest of the library.
PRIORITY_RACES = ["nightborne_female", "pandaren_male", "dracthyr_male"]


def body_prompt(race_key):
    r = RACES[race_key]
    return f"{r['pos']}, {BODY_WEAR}, {STYLE_TAIL}"


def body_negative(race_key):
    return f"{RACES[race_key]['neg']}, {BODY_NEG_BASE}"


def gear_prompt(race_key, arch_key):
    """Species leads here too — ControlNet fixes the pose, not the species,
    so a gear render can still drift back to a generic human without it."""
    r = RACES[race_key]
    return f"{r['pos']}, {ARCHETYPES[arch_key]}, {STYLE_TAIL}"


def gear_negative(race_key):
    return f"{RACES[race_key]['neg']}, {GEAR_NEG}"


def throttle():
    """Back off when the box is genuinely under memory pressure."""
    r = resources()
    free = r.get("ram_free_mb")
    if free is not None and free < 800:
        log(f"RAM low ({free} MB) — pausing 90s to let it settle", "WARN")
        time.sleep(90)
    else:
        time.sleep(3)


def ensure_body(client, state, race_key):
    """Base body for a race/gender. Returns its path, or None on failure."""
    key = f"body:{race_key}"
    dest = BODIES / f"{race_key}.png"
    if key in state["done"] and dest.exists():
        return dest
    BODIES.mkdir(parents=True, exist_ok=True)
    graph = txt2img_graph(body_prompt(race_key), body_negative(race_key),
                          seed=RACES[race_key]["seed"],
                          prefix=f"overnight/body_{race_key}",
                          lora_strength=0.40)
    outputs = client.run(graph, label=key)
    paths = collect_outputs(outputs)
    if not paths:
        raise RuntimeError("no image returned")
    dest.write_bytes(paths[0].read_bytes())
    mark_done(state, key, dest)
    log(f"  body {race_key} -> {dest.name}")
    return dest


def ensure_gear(client, state, race_key, arch_key, body_path):
    """One gear archetype rendered onto one base body, split into layers."""
    key = f"gear:{race_key}:{arch_key}"
    out_dir = GEAR / race_key / arch_key
    if key in state["done"] and (out_dir / "chest.png").exists():
        return out_dir

    staged = stage_input(body_path, f"ov_body_{race_key}.png")
    graph = controlnet_graph(staged, gear_prompt(race_key, arch_key),
                             gear_negative(race_key),
                             seed=RACES[race_key]["seed"],
                             prefix=f"overnight/gear_{race_key}_{arch_key}",
                             strength=0.85, end_percent=0.80, lora_strength=0.40)
    outputs = client.run(graph, label=key)
    paths = collect_outputs(outputs)
    if not paths:
        raise RuntimeError("no image returned")

    raw = GEAR / race_key / f"_{arch_key}_raw.png"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(paths[0].read_bytes())

    written = write_layers(extract_layers(body_path, raw), out_dir)
    mark_done(state, key, out_dir)
    log(f"  gear {race_key}/{arch_key} -> {', '.join(sorted(written))}")
    return out_dir


def build_character(client, state, char_id, race_key, arch_key):
    """Assemble a roster character and publish it to the manifest."""
    key = f"char:{char_id}"
    body = ensure_body(client, state, race_key)
    gear_dir = ensure_gear(client, state, race_key, arch_key, body)

    char_dir = REPO / "cast" / char_id / "one_piece"
    char_dir.mkdir(parents=True, exist_ok=True)
    layers = extract_layers(body, GEAR / race_key / f"_{arch_key}_raw.png")
    write_layers(layers, char_dir)

    still, gif, slots = compose_render(char_dir, char_dir)
    entry, published = publish(char_id)
    ok = verify(entry, [p["slot"] for p in published])
    if not ok:
        raise RuntimeError("runtime verification failed")

    mark_done(state, key, still)
    log(f"  CHARACTER {char_id}: {len(slots)} layers, still={still.name}, "
        f"gif={gif.name}, runtime=PASS")
    return still, gif


def plan():
    """The night's whole task list, in the order it will be attempted."""
    tasks = []
    for char_id, (race, arch) in ROSTER.items():
        tasks.append(("character", char_id, race, arch))
    rest = PRIORITY_RACES + [r for r in RACES if r not in PRIORITY_RACES]
    for race in rest:
        for arch in ARCHETYPES:
            tasks.append(("gear", None, race, arch))
    return tasks


def bodies_only(argv):
    """Generate every base body, then STOP for inspection.

    This gate exists because of how the first run failed: the pandaren
    base body came out as a slim human woman, and we only found out after
    building twelve gear renders on top of it. A base body is the cheapest
    possible place to catch a species error and the most expensive place
    to miss one — everything downstream inherits it.
    """
    force = "--force" in argv
    state = load_state()
    client = ComfyClient()
    log("=" * 62)
    log(f"BASE BODY PASS — {len(RACES)} races (gate before any gear)")
    for race in list(PRIORITY_RACES) + [r for r in RACES if r not in PRIORITY_RACES]:
        if force:
            state["done"].pop(f"body:{race}", None)
            save_state(state)
        try:
            path = ensure_body(client, state, race)
            log(f"  {race:<20} -> {path}")
        except Exception as exc:
            mark_failed(state, f"body:{race}", exc)
            log(f"  {race:<20} FAILED: {exc}", "ERROR")
        throttle()
    log("BASE BODY PASS DONE — inspect cast/_bodies/ before running gear")
    log("=" * 62)
    return 0


def main(argv):
    if "--bodies-only" in argv:
        return bodies_only(argv)

    tasks = plan()
    if "--dry-run" in argv:
        for i, (kind, char, race, arch) in enumerate(tasks, 1):
            print(f"{i:3}. {kind:<10} {char or '-':<22} {race:<18} {arch}")
        print(f"\n{len(tasks)} tasks")
        return 0

    state = load_state()
    state.setdefault("started", time.time())
    save_state(state)

    client = ComfyClient()
    log("=" * 62)
    log(f"OVERNIGHT RUN START — {len(tasks)} tasks "
        f"({len(state['done'])} already checkpointed)")
    log_resources("start")

    ok = failed = skipped = 0
    for i, (kind, char_id, race, arch) in enumerate(tasks, 1):
        label = f"[{i}/{len(tasks)}] {kind} {char_id or race}/{arch}"
        key = f"char:{char_id}" if kind == "character" else f"gear:{race}:{arch}"
        if key in state["done"]:
            skipped += 1
            continue

        log(label)
        try:
            if kind == "character":
                build_character(client, state, char_id, race, arch)
            else:
                body = ensure_body(client, state, race)
                ensure_gear(client, state, race, arch, body)
            ok += 1
        except Hung:
            # The engine is down and its one relaunch did not take. Further
            # work would just fail in a loop and bury the log.
            alert(f"STOPPING at {label}: engine unrecoverable. "
                  f"{ok} done, {failed} failed, {len(tasks)-i} not attempted.")
            break
        except Exception as exc:
            failed += 1
            mark_failed(state, key, exc)
            log(f"  FAILED (continuing): {exc}", "ERROR")
            log(traceback.format_exc().strip().splitlines()[-1], "ERROR")

        if i % 5 == 0:
            log_resources(f"after {i}")
        throttle()

    log(f"RUN END — {ok} generated, {failed} failed, {skipped} already done")
    log_resources("end")
    log("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

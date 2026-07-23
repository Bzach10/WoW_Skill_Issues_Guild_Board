#!/usr/bin/env python3
"""BUDGET B FINAL: the 12 webpage backdrop scenes from SCENE_SCENARIOS.md.

Winning approach (Zach-approved): Nano Banana Pro, multi-image native
integration (not paste-on cutouts), correct 16:9 framing.

Per scene, two SEPARATE calls that share one environment:
  1. RAW scene — pure environment, no characters (for the Unreal
     animation background layer).
  2. BAKED scene — feed the raw scene image PLUS each featured
     character's locked profile.png reference, instruct the model to
     place them into THAT exact environment acting out the mini-story.
     This keeps the background pixel-identical between raw/baked so
     swapping is a clean layer, not a re-roll.

Live RunPod balance is checked before every call; hard-stops at $9
spent from Budget B's own baseline (tracked separately from Budget A).
"""
import base64
import io
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _run_full_roster import UA  # noqa: E402
from _runpod_balance import load_api_key, get_balance  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SCENES_DIR = REPO_ROOT / "cast" / "_scenes"
LOG_PATH = SCENES_DIR / "budget_b_final_log.json"
PREVIEWS_DIR = Path(
    r"C:\Users\zachf\OneDrive\Documents\WoW Server Stuff\Diven WoW Guild Board"
    r"\WoW_Skill_Issues_Guild_Board\previews"
)
POT_CAP = 9.0
MODEL_SLUG = "nano-banana-pro-edit"

CHARACTER_KEYS = {
    "Rakdisc": "rakdisc-proudmoore", "Enyò": "enyò-area-52", "Ohnomyais": "ohnomyais-area-52",
    "Tommybravoo": "tommybravoo-bleeding-hollow", "Jovala": "jovala-stormrage", "Kirrá": "kirrá-aggramar",
    "Rexxhavocc": "rexxhavocc-area-52", "Boondocka": "boondocka-hydraxis", "Ellebasi": "ellebasi-malganis",
    "Hellful": "hellful-lightnings-blade", "Impkiller": "impkiller-tichondrius", "Martylol": "martylol-illidan",
    "Rhansîck": "rhansìk-area-52", "Buchalter": "buchalter-area-52", "Kelova": "kelova-stormrage",
    "Shadoxii": "shadoxii-illidan", "Shadoxi": "shadoxi-illidan", "Aiime": "aiime-bleeding-hollow",
    "Healyeah": "healyeah-queldorei", "Arfas": "arfas-queldorei", "Healmates": "healmates-korgath",
    "Tinyx": "tinyx-bleeding-hollow", "Kegsmashroll": "kegsmashroll-stormrage", "Flogeron": "flogeron-area-52",
    "Yur": "yur-whisperwind", "Rakell": "rakell-proudmoore", "Onessarain": "onessarain-area-52",
    "Tommybravox": "tommybravox-bleeding-hollow", "Amrevenge": "amrevenge-stormrage",
    "Floofwall": "floofwall-queldorei", "Brewzleeh": "brewzleeh-tichondrius", "Maillo": "maillo-area-52",
    # Phyrthepali: no Blizzard render in the roster, no art exists — omitted from scene 8.
}

# (key, label, environment description [research-informed], featured names, mini-story action)
SCENES = [
    ("silvermoon_city", "Silvermoon City",
     "The elven capital Silvermoon City: soaring crimson-and-gold spires with sunburst finials, "
     "the royal Sunfury Spire palace floating in the distant skyline, the grand Court of the Sun "
     "plaza with its ornate central fountain, white-stone elven architecture with living plant "
     "accents, crimson-and-gold banners bearing sun and phoenix motifs, luminous bejeweled crystal "
     "shards drifting in the air, warm golden eternal-autumn light.",
     ["Rakdisc", "Enyò", "Ohnomyais"],
     "Rakdisc (a Nightborne disc priest) drags the crew through the Court of the Sun on a transmog "
     "run, holding up a crimson robe to the light to inspect it, while Enyò and Ohnomyais stand "
     "behind him faking enthusiasm for yet another nearly-identical shade of crimson."),

    ("stormwind_city", "Stormwind City",
     "Stormwind City at golden hour: blue-tiled rooftops, a towering stone cathedral with stained "
     "glass, canals reflecting warm sunset light, a stone Trade District bridge, banners fluttering, "
     "grand Alliance human architecture.",
     ["Tommybravoo", "Jovala", "Kirrá"],
     "Tommybravoo strikes an exaggerated hero pose on the Trade District bridge for a guild "
     "recruitment poster photo, Jovala struggles to hold an old-fashioned camera steady in front of "
     "him, while Kirrá sneaks up behind them both to scoop handfuls of coins out of the fountain."),

    ("orgrimmar", "Orgrimmar",
     "Orgrimmar, the Horde fortress-capital: brutal red iron walls and spiked fortifications, the "
     "Valley of Strength with war drums, massive gates, dramatic orange dusk sky, rugged orcish "
     "architecture.",
     ["Rexxhavocc", "Boondocka", "Ellebasi"],
     "Rexxhavocc squares up inside a brawler's ring in the Valley of Honor, fists raised, while "
     "Boondocka stands at ringside taking side-bets from onlookers, and Ellebasi calmly reads a "
     "combat training dummy's damage meter nearby and smugly declares themselves the real winner."),

    ("dark_portal", "The Dark Portal",
     "The Dark Portal: a huge ancient stone arch crackling with swirling fel-green energy at its "
     "center, set in the scorched red wasteland of the Blasted Lands, an ember-orange sky, cracked "
     "scorched earth, ominous silhouettes of a demonic horde gathering in the far background.",
     ["Hellful", "Impkiller", "Martylol"],
     "Impkiller punts a small stray imp through the air like a field goal toward the swirling green "
     "portal, Hellful cheering wildly at the distance, while Martylol holds up a phone filming it "
     "for the memes channel instead of noticing the demon horde silhouettes massing behind them."),

    ("dalaran", "Dalaran",
     "The violet mage city of Dalaran floating serenely above snowy streets under a starry night "
     "sky, glowing arcane-purple magic lights, spired wizard-tower architecture, an ornate arcane "
     "clocktower, a shimmering magical shield dome overhead.",
     ["Rhansîck", "Buchalter", "Kelova"],
     "Buchalter does frantic arcane chalk-math on a floating chalkboard trying to prove the guild "
     "bank gold is not actually missing, while Rhansîck and Kelova lean over the floating city's "
     "edge lobbing small illegal fireballs off the underbelly just to watch them fall into the "
     "clouds below."),

    ("icecrown_citadel", "Icecrown Citadel",
     "Icecrown Citadel: a jagged fortress of black saronite and ice spires rising from a frozen "
     "wasteland, the Lich King's frozen throne visible high above, eerie cobalt-green aurora "
     "borealis lighting the sky, cold blue moonlight over the frost.",
     ["Shadoxii", "Shadoxi", "Aiime"],
     "The Shadox twins pose for a 'menacing' photo on the icy steps below the frozen throne — one "
     "throwing up rock-horns confidently, the other mid-slip on the ice — while Aiime solemnly "
     "plants a small guild banner in a snowdrift that is already toppling over behind them."),

    ("elwynn_forest", "Elwynn Forest",
     "Elwynn Forest at golden hour: lush rolling green hills and autumn oaks, warm sunbeams through "
     "tall trees, the Northshire chapel in the distance, a stone bridge over Crystal Lake's stream, "
     "peaceful idyllic starter-zone lighting.",
     ["Healyeah", "Arfas"],
     "Healyeah (a Dracthyr) is mid-belly-flop off the Crystal Lake bridge into the water fishing rod "
     "in hand, while Arfas naps peacefully against a haystack nearby, both taking a nostalgic level-1 "
     "day instead of pushing keys."),

    ("mount_hyjal", "Mount Hyjal / World Tree",
     "Mount Hyjal at night: the colossal World Tree Nordrassil towering at epic scale, its massive "
     "glowing canopy lit by starlight, cascading waterfalls down verdant green slopes, magical "
     "golden-green light at the tree's ancient roots.",
     ["Healmates", "Tinyx"],
     "At the World Tree's roots, Healmates stands looking sheepish, visibly getting ribbed about a "
     "recent mid-fight death, while Tinyx bounces around them spamming glowing heart emotes trying "
     "to keep the peace. (Phyrthepali omitted — no source art available.)"),

    ("ironforge", "Ironforge",
     "The great dwarven halls of Ironforge: a molten forge chamber with rivers of glowing lava, "
     "massive brass and stone architecture, the Great Forge roaring with sparks flying, warm orange "
     "forge-light against dark stone, a Stonehearth festival banner.",
     ["Kegsmashroll", "Flogeron", "Yur"],
     "Kegsmashroll triumphantly slams an empty stein down mid-stein-slamming-contest, clearly "
     "winning by a mile, Flogeron passed out face-down under the table nearby, while Yur rides a "
     "runaway forge-cart loaded with ale kegs careening across the Great Forge platform behind them."),

    ("caverns_of_time", "Caverns of Time / Tanaris",
     "A golden desert canyon in Tanaris opening into the Caverns of Time: a swirling glowing bronze "
     "time portal set into sandstone cliffs, dramatic desert sunset, ancient bronze-dragon "
     "architecture, hourglass-sand motifs.",
     ["Rakell", "Onessarain", "Tommybravox"],
     "Rakell gestures animatedly, arguing with a robed Bronze Dragonflight timeway keeper for 'just "
     "one' timeline reset to undo the last wipe, while Onessarain and Tommybravox are both crouched "
     "reaching into the exact same ancient treasure chest, each visible in a faint duplicate "
     "timeline-echo of themselves looting it a moment apart."),

    ("ungoro_crater", "Un'Goro Crater",
     "Un'Goro Crater: a lush prehistoric jungle crater basin, towering waterfalls cascading down "
     "volcanic cliffs, a dramatic steaming active volcano in the background, ferns and prehistoric "
     "foliage, warm humid mist and light, ROAMING DINOSAURS prominent in the scene.",
     ["Amrevenge", "Floofwall"],
     "Amrevenge (a Beast Mastery hunter) plants their feet and grips a taming rope on a huge, "
     "snorting, mid-charge devilsaur, wrestling it to a stop, while Floofwall the pandaren "
     "brewmaster sits calmly cross-legged on the devilsaur's back brewing a pot of tea, utterly "
     "unbothered, betting it'll make the guild's best new tank."),

    ("undermine", "Undermine (Goblin Capital)",
     "Undermine, the neon goblin boomtown sprawling underground beneath Kezan: the Gallagio casino "
     "floor with brilliant colorful neon lights, gold coins and chips scattered on felt tables, "
     "slot machines glowing in the background, oil-slick chrome surfaces, cash-green and hot-pink "
     "cartel signage, hazy industrial smog-lit atmosphere, gaudy goblin excess everywhere.",
     ["Brewzleeh", "Maillo"],
     "Brewzleeh (pandaren monk) runs a rigged three-card-monte / coin-flip table on a crate under "
     "the Undermine neon, grinning wide and raking in a big pile of the guild's gold coins, while "
     "Maillo — visibly sweating, already deep in gambling debt — shoves one more coin stack across "
     "the crate insisting this next bet is a 'guaranteed winner'."),
]


def load_log():
    if LOG_PATH.exists():
        return json.loads(LOG_PATH.read_text(encoding="utf-8"))
    return {"raw_done": [], "baked_done": [], "failed": [], "spend_checkpoints": []}


def save_log(log):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(log, indent=2), encoding="utf-8")


def call_model(prompt, image_paths, aspect_ratio="16:9", attempts=2):
    images = []
    for p in image_paths:
        images.append(base64.b64encode(Path(p).read_bytes()).decode("ascii"))
    data_uris = [f"data:image/png;base64,{b64}" for b64 in images]
    payload = {
        "input": {
            "prompt": prompt,
            "images": data_uris,
            "resolution": "2K",
            "aspect_ratio": aspect_ratio,
        }
    }
    body = json.dumps(payload).encode("utf-8")
    api_key = load_api_key()
    last_err = None
    for _ in range(attempts):
        req = urllib.request.Request(
            f"https://api.runpod.ai/v2/{MODEL_SLUG}/runsync",
            data=body, method="POST",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=170) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            last_err = str(e)
            continue
        if result.get("status") == "COMPLETED":
            output = result.get("output", {})
            url = output.get("image_url") or output.get("result")
            cost = output.get("cost", 0.0)
            if url:
                return url, cost, result.get("id")
            last_err = f"no image url: {json.dumps(result)[:500]}"
        else:
            last_err = f"status={result.get('status')} body={json.dumps(result)[:500]}"
    raise RuntimeError(last_err)


def download(url, dest):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.read())


BLANK = None


def raw_scene_prompt(env_description, vibe_label):
    return (
        f"A wide 16:9 landscape environment illustration in clean bold-ink anime art style "
        f"(One Piece), of {vibe_label}: {env_description} Epic painterly environment art, "
        f"dramatic lighting, vibrant saturated colors, bold black linework, cel-shaded shonen "
        f"anime aesthetic. NO characters or people anywhere in the image — pure environment/"
        f"architecture/landscape art only. Leave the lower-middle third of the frame relatively "
        f"open and uncluttered, like an empty stage floor, so characters can be placed into the "
        f"scene afterward. Wide cinematic 16:9 composition, correct landscape aspect ratio."
    )


def baked_scene_prompt(vibe_label, mini_story, names):
    names_str = ", ".join(names)
    return (
        f"This first image is the exact environment to use: {vibe_label}. The remaining reference "
        f"images each show one specific character's exact appearance, gear, and art style to "
        f"preserve precisely — do not alter their design. Place these characters ({names_str}) "
        f"physically INTO the first image's exact environment, acting out this moment: {mini_story} "
        f"Integrate them fully and naturally: match the environment's perspective, scale, lighting "
        f"direction and color grade, give them real cast shadows and properly grounded feet/contact "
        f"with the ground or objects, and paint them in the exact same bold-ink anime linework and "
        f"flat cel-shading style as the environment, so the whole image reads as one single "
        f"illustration — never like a cutout pasted on top. Keep each character facing a natural, "
        f"forward-readable orientation (not mirrored or turned away) unless the action specifically "
        f"requires otherwise. Preserve the environment from the first image exactly; do not change "
        f"its architecture or composition. Wide cinematic 16:9 composition suitable for a website "
        f"header/section background, with breathing room for text/UI overlay."
    )


def main():
    baseline = get_balance()
    print(f"[budget-b-final] baseline balance ${baseline:.4f}  cap: stop at ${POT_CAP:.2f} spent", flush=True)

    log = load_log()

    for i, (key, label, env_desc, names, mini_story) in enumerate(SCENES):
        scene_dir = SCENES_DIR / key
        raw_path = scene_dir / "raw.png"
        baked_path = scene_dir / "baked.png"

        char_paths = []
        present_names = []
        for n in names:
            ck = CHARACTER_KEYS.get(n)
            if not ck:
                continue
            p = REPO_ROOT / "cast" / ck / "one_piece" / "profile.png"
            if p.exists():
                char_paths.append(p)
                present_names.append(n)

        def check_budget():
            balance = get_balance()
            spent = baseline - balance
            return spent, balance

        # --- RAW scene ---
        if key not in log["raw_done"]:
            spent, balance = check_budget()
            if spent >= POT_CAP:
                print(f"[stop] Budget B spent ${spent:.4f} >= ${POT_CAP:.2f} cap (before raw:{key}).", flush=True)
                break
            try:
                prompt = raw_scene_prompt(env_desc, label)
                # nano-banana-pro-edit requires at least one image; feed a blank neutral canvas.
                from PIL import Image
                placeholder = scene_dir / "_placeholder.png"
                scene_dir.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (1024, 576), (200, 200, 200)).save(placeholder)
                url, cost, req_id = call_model(prompt, [placeholder])
                download(url, raw_path)
                placeholder.unlink(missing_ok=True)
                log["raw_done"].append(key)
                spent2, balance2 = check_budget()
                log["spend_checkpoints"].append({"key": f"{key}_raw", "balance": balance2, "spent_from_baseline": round(spent2, 4)})
                save_log(log)
                print(f"[{i+1}/{len(SCENES)}] raw   {label}  ->  {raw_path}  spent=${spent2:.4f}/{POT_CAP:.2f}", flush=True)
            except Exception as e:
                log["failed"].append(f"{key}_raw")
                save_log(log)
                print(f"[{i+1}/{len(SCENES)}] FAIL raw {label} ({e})", flush=True)
                continue

        # --- BAKED scene ---
        if key not in log["baked_done"]:
            spent, balance = check_budget()
            if spent >= POT_CAP:
                print(f"[stop] Budget B spent ${spent:.4f} >= ${POT_CAP:.2f} cap (before baked:{key}).", flush=True)
                break
            try:
                prompt = baked_scene_prompt(label, mini_story, present_names)
                url, cost, req_id = call_model(prompt, [raw_path] + char_paths)
                download(url, baked_path)

                dest = PREVIEWS_DIR / f"scene_{key}_baked.png"
                dest.write_bytes(baked_path.read_bytes())

                log["baked_done"].append(key)
                spent2, balance2 = check_budget()
                log["spend_checkpoints"].append({"key": f"{key}_baked", "balance": balance2, "spent_from_baseline": round(spent2, 4)})
                save_log(log)
                cutouts = [f"cast/{CHARACTER_KEYS[n]}/one_piece/board.png" for n in present_names]
                print(f"[{i+1}/{len(SCENES)}] baked {label}  ->  {baked_path}  (preview: {dest})  "
                      f"characters={present_names}  cutouts={cutouts}  spent=${spent2:.4f}/{POT_CAP:.2f}", flush=True)
            except Exception as e:
                log["failed"].append(f"{key}_baked")
                save_log(log)
                print(f"[{i+1}/{len(SCENES)}] FAIL baked {label} ({e})", flush=True)

        time.sleep(0.2)

    final_balance = get_balance()
    print(f"\n[done] Budget B (final scenes) spend: ${baseline - final_balance:.4f} "
          f"(baseline ${baseline:.4f} -> ${final_balance:.4f})", flush=True)
    print(f"[done] raw={len(log['raw_done'])} baked={len(log['baked_done'])} failed={len(log['failed'])}", flush=True)


if __name__ == "__main__":
    main()

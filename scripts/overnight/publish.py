"""Write a character's layer set into cast_manifest.json (v2), then prove
the shipped runtime accepts it.

"It renders" is not a claim we make by eyeballing our own compositor —
our compositor is not the thing users see. So this imports the real
guild_board.paperdoll from the frontend worktree and runs assemble() on
the manifest we just wrote. If it does not come back mode="layered" with
every slot we published, this exits non-zero and says why.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "cast_manifest.json"
FRONTEND_PAPERDOLL = Path(r"C:\wt\fc\guild_board\paperdoll.py")

CANVAS = {"w": 832, "h": 1216}
SLOT_Z = {"cloak": 10, "body": 20, "legs": 30, "chest": 40, "arms": 50,
          "head": 60, "face": 61, "weapon_off": 70, "weapon_main": 71}


def build_layers(char_id, style="one_piece"):
    """Every contract slot that actually exists on disk, in z-order."""
    rel_dir = f"cast/{char_id}/{style}"
    layers = []
    for slot, z in sorted(SLOT_Z.items(), key=lambda kv: kv[1]):
        rel = f"{rel_dir}/{slot}.png"
        if (REPO / rel).exists():
            layers.append({"slot": slot, "src": rel,
                           "anchor": {"x": 0, "y": 0}, "z": z})
    return layers


def publish(char_id, style="one_piece"):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    char = manifest.get("characters", {}).get(char_id)
    if char is None:
        raise SystemExit(f"{char_id} not in cast_manifest.json")

    layers = build_layers(char_id, style)
    if not layers:
        raise SystemExit(f"no layer PNGs found for {char_id}")

    entry = char.setdefault("styles", {}).setdefault(style, {})
    entry["canvas"] = dict(CANVAS)
    entry["layers"] = layers
    entry["version"] = 2

    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    return entry, layers


def verify(entry, published_slots):
    """Run the REAL runtime over what we wrote."""
    if not FRONTEND_PAPERDOLL.exists():
        print(f"CANNOT VERIFY: {FRONTEND_PAPERDOLL} not found", file=sys.stderr)
        return False
    import importlib.util
    spec = importlib.util.spec_from_file_location("_fc_paperdoll",
                                                   FRONTEND_PAPERDOLL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    result = mod.assemble(entry)
    print(f"  runtime mode      : {result['mode']}")
    print(f"  runtime canvas    : {result['canvas']}")
    print(f"  runtime layers    : {len(result['layers'])}")
    for layer in result["layers"]:
        ox, oy = layer["origin_pct"]
        print(f"    z={layer['z']:>3} {layer['slot']:<12} "
              f"bone={layer['bone']:<12} origin=({ox:.1f}%, {oy:.1f}%)")

    if result["mode"] != "layered":
        print(f"FAIL: expected mode 'layered', got {result['mode']!r}",
              file=sys.stderr)
        return False
    got = {layer["slot"] for layer in result["layers"]}
    missing = set(published_slots) - got
    if missing:
        print(f"FAIL: runtime dropped slots {sorted(missing)}", file=sys.stderr)
        return False
    return True


def main(argv):
    char_id = argv[0] if argv else "rakdisc-proudmoore"
    entry, layers = publish(char_id)
    slots = [layer["slot"] for layer in layers]
    print(f"published {char_id}: {', '.join(slots)}")
    ok = verify(entry, slots)
    print("RUNTIME VERIFY: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

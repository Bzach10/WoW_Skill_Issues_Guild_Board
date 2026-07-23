#!/usr/bin/env python3
"""Audit existing cutouts for over-removal (missing weapons/limbs/effects).

For each character with a board.png, compares the character-area FRACTION
of the canvas in the final cutout against the character-area fraction in
their original Blizzard render (cropped the same way the generator crops
its input). Both are resolution-independent fractions, so this works
across images of different sizes.

This is a heuristic, not exact — a dynamic action pose can legitimately
occupy a different fraction of the frame than the static Blizzard render.
But a character that lost a weapon/limb/effect during cutout will show a
LARGE, consistent drop, not a small pose-driven wobble, so a generous
threshold (15% relative) still catches real losses without flagging
everyone.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _run_full_roster import prep_input  # reuses the exact same crop logic

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "cast_manifest.json"
RENDERS_DIR = REPO_ROOT / "cast" / "_renders_cache"
STYLE = "one_piece"


def char_area_fraction_from_render(entry):
    from PIL import Image
    import numpy as np
    render_path = RENDERS_DIR / f"{entry}.png"
    if not render_path.exists():
        return None
    cropped = prep_input(render_path)
    arr = np.array(cropped)
    nonwhite = (np.abs(arr.astype(int) - 255).sum(axis=2) > 30).sum()
    return nonwhite / (cropped.width * cropped.height)


def cutout_area_fraction(board_path):
    from PIL import Image
    import numpy as np
    if not Path(board_path).exists():
        return None
    im = Image.open(board_path)
    if im.mode not in ("RGBA", "LA", "PA"):
        return None
    alpha = np.array(im.getchannel("A"))
    opaque = (alpha > 128).sum()
    return opaque / alpha.size


def main():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    chars = manifest.get("characters", {})

    results = []
    for entry, node in sorted(chars.items()):
        if not isinstance(node, dict):
            continue
        styles = node.get("styles", {})
        style_node = styles.get(STYLE, {})
        board = style_node.get("board")
        if not board:
            continue
        board_path = REPO_ROOT / board if not Path(board).is_absolute() else Path(board)

        ref_frac = char_area_fraction_from_render(entry)
        cut_frac = cutout_area_fraction(board_path)
        if ref_frac is None or cut_frac is None:
            continue

        ratio = cut_frac / ref_frac if ref_frac > 0 else None
        flagged = bool(ratio is not None and ratio < 0.85)
        results.append({
            "entry": entry,
            "name": node.get("name"),
            "class": node.get("class"),
            "ref_frac": round(ref_frac, 4),
            "cut_frac": round(cut_frac, 4),
            "ratio": round(ratio, 3) if ratio is not None else None,
            "flagged": flagged,
        })

    flagged_list = [r for r in results if r["flagged"]]
    print(f"Audited {len(results)} characters with cutouts.")
    print(f"Flagged {len(flagged_list)} as likely missing content (>15% area loss vs original render):")
    for r in sorted(flagged_list, key=lambda x: x["ratio"]):
        print(f"  {r['entry']:35s} {r['class'] or '':14s} ratio={r['ratio']:.2f}  ref={r['ref_frac']:.3f} cut={r['cut_frac']:.3f}")

    out_path = REPO_ROOT / "cast" / "_rnd_img2img" / "cutout_audit.json"
    out_path.write_text(json.dumps({
        "audited": len(results),
        "flagged": [r["entry"] for r in flagged_list],
        "details": results,
    }, indent=2), encoding="utf-8")
    print(f"\nFull report: {out_path}")


if __name__ == "__main__":
    main()

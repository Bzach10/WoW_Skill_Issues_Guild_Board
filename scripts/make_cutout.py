"""Turn a generated character illustration into a transparent cut-out for
the website (cast/<name>/board.png, real alpha channel) — CPU only, never
touches the GPU. Uses rembg (U2Net), with the ONNX runtime session pinned
to CPUExecutionProvider explicitly (the installed onnxruntime package is
the CPU build anyway, so this is belt-and-suspenders, not the only guard).

Usage: python scripts/make_cutout.py <input.png> <character_name>
  -> writes cast/<character_name>/board.png (RGBA)

Import and call make_cutout(src, name) directly for programmatic use
(e.g. once approved character art is locked, run this as the last step).
"""
import os
import sys


def make_cutout(src_path, character_name, cast_root=None):
    """src_path: path to a generated (opaque) character PNG.
    character_name: used as the cast/<name>/ folder (lowercased, spaces->_).
    Returns the output path (cast/<name>/board.png).
    """
    from rembg import new_session, remove

    cast_root = cast_root or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cast")
    slug = character_name.strip().lower().replace(" ", "_")
    out_dir = os.path.join(cast_root, slug)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "board.png")

    with open(src_path, "rb") as f:
        input_bytes = f.read()

    # CPU only, no GPU/CUDA provider ever considered.
    session = new_session("u2net", providers=["CPUExecutionProvider"])
    output_bytes = remove(input_bytes, session=session)

    with open(out_path, "wb") as f:
        f.write(output_bytes)
    return out_path


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) < 2:
        print("Usage: python scripts/make_cutout.py <input.png> <character_name>")
        return 1
    src_path, character_name = argv[0], argv[1]
    out_path = make_cutout(src_path, character_name)
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

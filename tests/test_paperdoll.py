"""The paper-doll compositor: the layer/anchor contract, and the promise
that no manifest shape can produce a broken character."""

import pytest

from guild_board import paperdoll


def _png(tmp_path, name):
    from PIL import Image
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(path)
    return str(path).replace("\\", "/")


def layered(tmp_path, slots=("cloak", "body", "chest", "arms", "head", "weapon_main")):
    return {
        "canvas": {"w": 832, "h": 1216},
        "layers": [{"slot": slot, "src": _png(tmp_path, f"{slot}.png"),
                    "anchor": {"x": 0, "y": 0},
                    "pivot": {"x": 416, "y": 400},
                    "z": paperdoll.SLOT_Z[slot]}
                   for slot in slots],
    }


# ------------------------------------------------------------ assembly

def test_layers_assemble_in_the_contract_z_order(tmp_path):
    doll = paperdoll.assemble(layered(tmp_path))
    assert doll["mode"] == "layered"
    order = [layer["slot"] for layer in doll["layers"]]
    assert order == ["cloak", "body", "chest", "arms", "head", "weapon_main"]
    # and the z values really do ascend
    assert [layer["z"] for layer in doll["layers"]] == sorted(
        layer["z"] for layer in doll["layers"])


def test_the_documented_stack_order_holds(tmp_path):
    """background < cloak < body < legs < chest < arms < face/head < weapons"""
    z = paperdoll.SLOT_Z
    assert z["cloak"] < z["body"] < z["legs"] < z["chest"] < z["arms"]
    assert z["arms"] < z["head"] <= z["face"]
    assert z["face"] < z["weapon_off"] < z["weapon_main"]


def test_anchors_and_pivots_become_percentages(tmp_path):
    """Positions are emitted as percentages so a doll scales with its
    container instead of being pinned to authored pixels."""
    assets = layered(tmp_path, slots=("body",))
    assets["layers"][0]["anchor"] = {"x": 208, "y": 304}
    assets["layers"][0]["pivot"] = {"x": 416, "y": 608}
    doll = paperdoll.assemble(assets)
    layer = doll["layers"][0]
    assert layer["left_pct"] == pytest.approx(25.0)
    assert layer["top_pct"] == pytest.approx(25.0)
    assert layer["origin_pct"] == (pytest.approx(50.0), pytest.approx(50.0))


def test_every_layer_gets_a_bone(tmp_path):
    doll = paperdoll.assemble(layered(tmp_path))
    bones = {layer["slot"]: layer["bone"] for layer in doll["layers"]}
    assert bones["arms"] == "arms"
    assert bones["head"] == "head"
    assert bones["cloak"] == "cloak"
    assert bones["weapon_main"] == "weapon_main"
    assert bones["body"] == "torso"


def test_a_custom_canvas_is_respected(tmp_path):
    assets = layered(tmp_path, slots=("body",))
    assets["canvas"] = {"w": 400, "h": 400}
    assets["layers"][0]["anchor"] = {"x": 100, "y": 100}
    doll = paperdoll.assemble(assets)
    assert doll["canvas"] == {"w": 400, "h": 400}
    assert doll["layers"][0]["left_pct"] == pytest.approx(25.0)


# ------------------------------------------------------------ fail-open

def test_a_missing_layer_file_is_dropped_not_rendered(tmp_path):
    assets = layered(tmp_path, slots=("body", "chest"))
    assets["layers"][1]["src"] = "cast/nope/missing.png"
    doll = paperdoll.assemble(assets)
    assert [layer["slot"] for layer in doll["layers"]] == ["body"]


def test_no_layers_falls_back_to_the_flat_cutout(tmp_path):
    flat = _png(tmp_path, "board.png")
    doll = paperdoll.assemble({"board": flat})
    assert doll["mode"] == "flat"
    assert doll["layers"][0]["slot"] == "composite"
    assert doll["layers"][0]["bone"] == "torso"


def test_all_layers_missing_falls_back_to_the_flat_cutout(tmp_path):
    flat = _png(tmp_path, "board.png")
    assets = layered(tmp_path, slots=("body",))
    assets["layers"][0]["src"] = "gone.png"
    assets["board"] = flat
    doll = paperdoll.assemble(assets)
    assert doll["mode"] == "flat"


def test_nothing_usable_reports_none(tmp_path):
    doll = paperdoll.assemble({"layers": [{"slot": "body", "src": "gone.png"}]})
    assert doll["mode"] == "none"
    assert doll["layers"] == []


def test_layer_without_a_pivot_gets_the_contract_default(tmp_path):
    assets = {"layers": [{"slot": "arms", "src": _png(tmp_path, "arms.png")}]}
    doll = paperdoll.assemble(assets)
    fx, fy = paperdoll.DEFAULT_PIVOT["arms"]
    assert doll["layers"][0]["origin_pct"] == (pytest.approx(fx * 100),
                                               pytest.approx(fy * 100))


def test_an_unknown_slot_still_renders(tmp_path):
    """A slot the contract has not defined yet must not vanish."""
    assets = {"layers": [{"slot": "tabard", "src": _png(tmp_path, "tabard.png")}]}
    doll = paperdoll.assemble(assets)
    assert doll["mode"] == "layered"
    assert doll["layers"][0]["slot"] == "tabard"
    assert doll["layers"][0]["bone"] == "torso"


@pytest.mark.parametrize("broken", [
    None,
    {},
    "not a dict",
    {"layers": "not a list"},
    {"layers": [None, 42, "nope"]},
    {"layers": [{"slot": "body"}]},                     # no src
    {"canvas": {"w": 0, "h": 0}, "layers": []},
    {"canvas": "nope", "layers": []},
])
def test_no_manifest_shape_can_break_assembly(broken):
    doll = paperdoll.assemble(broken)
    assert doll["mode"] in ("layered", "flat", "none")
    assert isinstance(doll["layers"], list)
    assert doll["canvas"]["w"] > 0 and doll["canvas"]["h"] > 0


def test_garbage_anchor_and_z_values_do_not_raise(tmp_path):
    assets = {"layers": [{
        "slot": "chest", "src": _png(tmp_path, "chest.png"),
        "anchor": {"x": "left", "y": None}, "pivot": "middle", "z": "top",
    }]}
    doll = paperdoll.assemble(assets)
    layer = doll["layers"][0]
    assert layer["left_pct"] == 0.0
    assert layer["z"] == paperdoll.SLOT_Z["chest"]


def test_contract_summary_matches_the_implementation():
    """The doc and the code must not drift apart."""
    summary = paperdoll.contract_summary()
    assert "composite" not in summary["slot_z_order"]
    assert summary["canvas"] == paperdoll.DEFAULT_CANVAS
    for slot in summary["slot_z_order"]:
        assert slot in paperdoll.SLOT_Z and slot in paperdoll.SLOT_BONE

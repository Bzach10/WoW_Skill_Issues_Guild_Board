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
    """cloak < body < legs < chest < arms < head < face < headgear < weapons"""
    z = paperdoll.SLOT_Z
    assert z["cloak"] < z["body"] < z["legs"] < z["chest"] < z["arms"]
    assert z["arms"] < z["head"] < z["face"]
    assert z["face"] < z["headgear"] < z["weapon_off"] < z["weapon_main"]


def test_headgear_renders_above_the_face():
    """THE ART-TEAM BLOCKER: face sat at the top of the head stack, so a
    mitre, helm or hood was occluded by it. Headgear must be above."""
    assert paperdoll.SLOT_Z["headgear"] > paperdoll.SLOT_Z["face"]
    assert paperdoll.SLOT_Z["headgear"] > paperdoll.SLOT_Z["head"]


def test_headgear_rides_the_head_bone(tmp_path):
    """A mitre has to nod with the head, not float independently."""
    assert paperdoll.SLOT_BONE["headgear"] == paperdoll.SLOT_BONE["head"]


def test_a_full_head_stack_composites_in_the_right_order(tmp_path):
    doll = paperdoll.assemble(layered(tmp_path,
        slots=("body", "head", "face", "headgear")))
    order = [layer["slot"] for layer in doll["layers"]]
    assert order == ["body", "head", "face", "headgear"]


# ------------------------------------------------------ prop proportions

def test_a_prop_with_a_declared_size_keeps_its_own_region(tmp_path):
    """Props are authored square; without a size they are stretched to
    the 832x1216 body frame and a mitre comes out tall and thin."""
    assets = {"canvas": {"w": 832, "h": 1216}, "layers": [{
        "slot": "headgear", "src": _png(tmp_path, "headgear.png"),
        "anchor": {"x": 208, "y": 122}, "size": {"w": 416, "h": 416},
        "pivot": {"x": 416, "y": 365}, "z": 65}]}
    layer = paperdoll.assemble(assets)["layers"][0]
    assert layer["width_pct"] == pytest.approx(50.0)     # 416/832
    assert layer["height_pct"] == pytest.approx(34.2105, rel=1e-3)  # 416/1216
    assert layer["is_prop"] is True


def test_a_sized_props_pivot_is_rebased_into_its_own_box(tmp_path):
    """transform-origin is relative to the element, not the canvas — a
    prop must not rotate about a point outside itself."""
    assets = {"canvas": {"w": 832, "h": 1216}, "layers": [{
        "slot": "headgear", "src": _png(tmp_path, "headgear.png"),
        "anchor": {"x": 208, "y": 122}, "size": {"w": 416, "h": 416},
        "pivot": {"x": 416, "y": 330}, "z": 65}]}
    layer = paperdoll.assemble(assets)["layers"][0]
    # pivot sits at (416-208)/416 = 50% across, (330-122)/416 = 50% down
    assert layer["origin_pct"][0] == pytest.approx(50.0)
    assert layer["origin_pct"][1] == pytest.approx(50.0)
    assert 0 <= layer["origin_pct"][0] <= 100
    assert 0 <= layer["origin_pct"][1] <= 100


def test_a_square_prop_region_is_actually_square_on_the_canvas(tmp_path):
    """50% of 832 and 34.21% of 1216 are both 416px — the rendered box is
    square even though the percentages differ."""
    assets = {"canvas": {"w": 832, "h": 1216}, "layers": [{
        "slot": "weapon_main", "src": _png(tmp_path, "weapon_main.png"),
        "anchor": {"x": 0, "y": 0}, "size": {"w": 416, "h": 416}, "z": 71}]}
    layer = paperdoll.assemble(assets)["layers"][0]
    assert layer["width_pct"] / 100 * 832 == pytest.approx(416)
    assert layer["height_pct"] / 100 * 1216 == pytest.approx(416)


def test_body_layers_stay_full_canvas_by_default(tmp_path):
    """The existing pilot art declares no size and must be unaffected."""
    layer = paperdoll.assemble(layered(tmp_path, slots=("body",)))["layers"][0]
    assert layer["width_pct"] is None and layer["height_pct"] is None
    assert layer["is_prop"] is False


def test_a_prop_without_a_size_still_renders(tmp_path):
    """Degrade, don't drop — it just falls back to full-canvas."""
    assets = {"layers": [{"slot": "headgear",
                          "src": _png(tmp_path, "headgear.png")}]}
    layer = paperdoll.assemble(assets)["layers"][0]
    assert layer["slot"] == "headgear"
    assert layer["width_pct"] is None


@pytest.mark.parametrize("size", [
    None, {}, "big", {"w": "wide"}, {"w": 0, "h": 0}, {"w": -5, "h": -5},
])
def test_a_garbage_size_falls_back_to_full_canvas(size, tmp_path):
    assets = {"layers": [{"slot": "headgear",
                          "src": _png(tmp_path, "headgear.png"), "size": size}]}
    layer = paperdoll.assemble(assets)["layers"][0]
    assert layer["width_pct"] is None and layer["height_pct"] is None


def test_anchors_and_pivots_become_percentages(tmp_path):
    """Positions are emitted as percentages so a doll scales with its
    container instead of being pinned to authored pixels.

    The pivot is authored in CANVAS pixels but transform-origin is
    relative to the element, so it is rebased by the anchor. Here the
    layer sits at (208, 304) and the pivot is at canvas (416, 608), which
    is (416-208)/832 = 25% across the layer's own box, not 50% across the
    canvas. Before the rebase, any layer with a non-zero anchor rotated
    about the wrong point.
    """
    assets = layered(tmp_path, slots=("body",))
    assets["layers"][0]["anchor"] = {"x": 208, "y": 304}
    assets["layers"][0]["pivot"] = {"x": 416, "y": 608}
    doll = paperdoll.assemble(assets)
    layer = doll["layers"][0]
    assert layer["left_pct"] == pytest.approx(25.0)
    assert layer["top_pct"] == pytest.approx(25.0)
    assert layer["origin_pct"] == (pytest.approx(25.0), pytest.approx(25.0))


def test_a_zero_anchor_pivot_is_unchanged(tmp_path):
    """The common case — full-canvas art anchored at the origin — keeps
    the plain canvas-relative pivot."""
    assets = layered(tmp_path, slots=("body",))
    assets["layers"][0]["anchor"] = {"x": 0, "y": 0}
    assets["layers"][0]["pivot"] = {"x": 416, "y": 608}
    layer = paperdoll.assemble(assets)["layers"][0]
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
    # the published order really is the implemented order
    assert summary["slot_z_order"] == sorted(
        summary["slot_z_order"], key=lambda s: paperdoll.SLOT_Z[s])
    assert summary["prop_slots"] == sorted(paperdoll.PROP_SLOTS)
    assert "size{w,h}" in summary["layer_fields"]


def test_the_published_headgear_box_really_contains_the_head():
    """The recommended square must sit above the face in z AND actually
    cover the region the pilot face layers occupy (x 293-571, y 68-264)."""
    box = paperdoll.contract_summary()["headgear_box"]
    assert box["w"] == box["h"], "the headgear region must be square"
    assert box["x"] <= 293 and box["x"] + box["w"] >= 571
    assert box["y"] <= 68 and box["y"] + box["h"] >= 264


def test_a_square_declared_size_stays_square_in_rendered_pixels():
    """50% of 832 and 34.21% of 1216 are both 416px."""
    box = paperdoll.contract_summary()["headgear_box"]
    canvas = paperdoll.DEFAULT_CANVAS
    w_px = box["w"] / canvas["w"] * canvas["w"]
    h_px = box["h"] / canvas["h"] * canvas["h"]
    assert w_px == pytest.approx(h_px)

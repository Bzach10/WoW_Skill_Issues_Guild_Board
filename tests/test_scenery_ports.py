"""The voyage's ports (VOY-07): the 12 monthly scenes as a route."""

from datetime import datetime

from guild_board import scenery


def test_ports_are_always_twelve_in_month_order():
    ports = scenery.ports()
    assert len(ports) == 12
    assert [p["month"] for p in ports] == list(range(1, 13))


def test_exactly_one_current_port_and_it_is_this_month():
    ports = scenery.ports()
    current = [p for p in ports if p["current"]]
    assert len(current) == 1
    assert current[0]["month"] == datetime.now().month


def test_ready_ports_carry_a_backdrop_unready_ones_do_not():
    for p in scenery.ports():
        if p["ready"]:
            assert p["backdrop"]
        else:
            assert p["backdrop"] is None


def test_a_month_with_no_scene_is_an_uncharted_port_not_a_gap():
    # An empty rotation still yields 12 ports, each uncharted.
    ports = scenery.ports(cfg={"scenery": {"rotation": {}}})
    assert len(ports) == 12
    assert all(not p["ready"] for p in ports)
    assert all(p["title"] == "Uncharted" for p in ports)

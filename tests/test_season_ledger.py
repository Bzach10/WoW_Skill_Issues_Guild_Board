"""The season ledger: append-only, idempotent, honest about what it
doesn't know — and a freeze that is written exactly once.

These pin the four properties the whole design rests on, because every one
of them is unrecoverable if it breaks: a ledger that double-appends is
ambiguous forever, a ledger keyed on a bare name credits the wrong Beroben
forever, a `false` where the evidence was missing is a lie forever, and a
freeze that can be rewritten is not a freeze.
"""

import json
import os

import pytest

from guild_board import season_ledger as sl

# ---------------------------------------------------------------------------
# fixtures — a small delivered bundle, shaped exactly like web_data_public
# ---------------------------------------------------------------------------

def competition(slug="season-mn-1", characters=None):
    return {
        "season": {"slug": slug, "name": "Midnight Season 1"},
        "based_on": "2026-08-11T16:14:32+00:00",
        "character_count": 3,
        "ranked_count": len(characters or []),
        "characters": characters if characters is not None else [
            {"key": "amrevenge-stormrage", "name": "Amrevenge", "realm": "Stormrage",
             "rank": 1, "score": 3943.9, "delta_week": 26.2,
             "ranks": {"region_overall": 12430}},
            {"key": "beroben-emerald-dream", "name": "Beroben", "realm": "Emerald Dream",
             "rank": 2, "score": 3100.0, "delta_week": 199.8, "ranks": {}},
            {"key": "beroben-queldorei", "name": "Beroben", "realm": "Quel'dorei",
             "rank": 3, "score": 2900.0, "delta_week": 199.8, "ranks": {}},
        ],
        "unranked": [{"key": "azell-bleeding-hollow", "name": "Azell"}],
    }


def weekly_board(week="2026-08-04"):
    return {
        "keyed_against_roster": True,
        "streaks_week": week,
        "streaks_by_key": {"amrevenge-stormrage": 3, "beroben-emerald-dream": 1},
        "attendance": {"amrevenge-stormrage": ["2026-07-28", "2026-08-04"],
                       "beroben-emerald-dream": ["2026-08-04"]},
        "attendance_coverage": {"weeks_scanned": ["2026-07-28", "2026-08-04"],
                                "weeks_logged": ["2026-07-21", "2026-07-28",
                                                 "2026-08-04"],
                                "weeks_unknown": ["2026-07-21"]},
    }


def records(based_on="2026-08-11T16:19:00+00:00"):
    return {"based_on": based_on, "generated_at": "2026-08-11T16:20:00+00:00",
            "standing": {"realm": 35, "region": 1604, "world": 5119},
            "headline_records": [{"id": "highest_timed_key", "value": 21}]}


def islands(slug="season-mn-1"):
    return {"season_slug": slug, "generated_at": "2026-08-11T16:20:00+00:00",
            "dungeons": {"islands": [{"id": "skyreach", "status": "conquered"}]}}


# ---------------------------------------------------------------------------
# the week boundary a row is keyed on
# ---------------------------------------------------------------------------

def test_the_row_records_the_completed_week_not_the_live_one():
    # Wednesday 2026-08-12: the week in progress started Tuesday 08-11, so
    # the week with a result to record is the one before it.
    assert sl.week_to_record("2026-08-12T11:30:00+00:00") == "2026-08-04"


def test_a_run_just_before_the_tuesday_reset_still_owes_last_week():
    # 14:00 UTC Tuesday is still inside the old raid week (the reset is at
    # 15:00), so the completed week is the one before that.
    assert sl.week_to_record("2026-08-18T14:00:00+00:00") == "2026-08-04"
    assert sl.week_to_record("2026-08-18T15:00:00+00:00") == "2026-08-11"


def test_the_seasons_closing_week_is_the_one_that_ends_on_the_flip():
    from guild_board import season as season_mod
    assert sl.season_closing_week(season_mod.SEASON_MN_1) == "2026-08-11"
    assert sl.week_belongs_to_season("2026-08-11", "season-mn-1")
    assert not sl.week_belongs_to_season("2026-08-11", "season-mn-2")
    assert sl.week_belongs_to_season("2026-08-18", "season-mn-2")


# ---------------------------------------------------------------------------
# idempotency — the property every workflow relies on
# ---------------------------------------------------------------------------

def test_reappending_the_same_week_writes_nothing(tmp_path):
    root = str(tmp_path)
    first = sl.append_for_run(root=root, competition=competition(),
                              weekly_board=weekly_board(),
                              week_label="2026-08-04")
    assert first["appended"] == 3
    again = sl.append_for_run(root=root, competition=competition(),
                              weekly_board=weekly_board(),
                              week_label="2026-08-04")
    assert again["appended"] == 0
    path = sl.ledger_path("season-mn-1", root)
    assert len(sl.read_rows(path)) == 3


def test_a_new_week_appends_and_leaves_the_old_lines_untouched(tmp_path):
    root = str(tmp_path)
    path = sl.ledger_path("season-mn-1", root)
    sl.append_for_run(root=root, competition=competition(),
                      weekly_board=weekly_board(), week_label="2026-08-04")
    before = open(path, encoding="utf-8").read()
    sl.append_for_run(root=root, competition=competition(),
                      weekly_board=weekly_board(), week_label="2026-08-11")
    after = open(path, encoding="utf-8").read()
    assert after.startswith(before)          # append-only, byte for byte
    assert len(sl.read_rows(path)) == 6


def test_a_repost_after_a_partial_write_fills_only_the_gap(tmp_path):
    root = str(tmp_path)
    path = sl.ledger_path("season-mn-1", root)
    one = competition(characters=competition()["characters"][:1])
    sl.append_rows(sl.rows_for_week(one, None, week_label="2026-08-04"), path)
    added = sl.append_rows(
        sl.rows_for_week(competition(), None, week_label="2026-08-04"), path)
    assert added == 2
    assert len(sl.read_rows(path)) == 3


# ---------------------------------------------------------------------------
# the key gate — two Berobens are two people, forever
# ---------------------------------------------------------------------------

def test_two_characters_sharing_a_name_never_collapse_to_one_row(tmp_path):
    rows = sl.rows_for_week(competition(), weekly_board(), week_label="2026-08-04")
    keys = [row["character_key"] for row in rows]
    assert keys.count("beroben-emerald-dream") == 1
    assert keys.count("beroben-queldorei") == 1
    assert len(set(keys)) == len(keys)


def test_a_bare_display_name_is_not_a_key_this_file_will_carry():
    assert not sl.valid_character_key("beroben")
    assert not sl.valid_character_key("Amrevenge-Stormrage")     # not folded
    assert not sl.valid_character_key("../../etc/passwd")
    assert not sl.valid_character_key("amrevenge-stormrage\n{}")
    assert not sl.valid_character_key("amrevenge stormrage")
    assert not sl.valid_character_key("a" * 65 + "-x")
    assert not sl.valid_character_key(None)
    assert sl.valid_character_key("amrevenge-stormrage")
    assert sl.valid_character_key("enyò-area-52")                 # unicode name
    assert sl.valid_character_key("kel'thuzad-bleeding-hollow")   # apostrophe


def test_an_unusable_key_is_dropped_not_repaired(tmp_path):
    bad = competition(characters=[
        {"key": "beroben", "rank": 1, "score": 10.0},
        {"key": "amrevenge-stormrage", "rank": 2, "score": 5.0},
    ])
    rows = sl.rows_for_week(bad, None, week_label="2026-08-04")
    assert [r["character_key"] for r in rows] == ["amrevenge-stormrage"]


def test_unranked_characters_get_no_row():
    rows = sl.rows_for_week(competition(), None, week_label="2026-08-04")
    assert "azell-bleeding-hollow" not in {r["character_key"] for r in rows}


# ---------------------------------------------------------------------------
# honest nulls — absence of evidence is never `false`
# ---------------------------------------------------------------------------

def test_attendance_is_true_false_or_null_on_the_evidence():
    rows = {r["character_key"]: r
            for r in sl.rows_for_week(competition(), weekly_board(),
                                      week_label="2026-08-04")}
    assert rows["amrevenge-stormrage"]["attended"] is True
    # The sweep read 2026-08-04 and this character was not in it: a real no.
    assert rows["beroben-queldorei"]["attended"] is False


def test_a_week_the_sweep_could_not_read_is_null_never_false():
    rows = {r["character_key"]: r
            for r in sl.rows_for_week(competition(), weekly_board(),
                                      week_label="2026-07-21")}
    # 2026-07-21 is logged but unscanned — nobody knows who was there.
    assert rows["beroben-queldorei"]["attended"] is None


def test_without_a_roster_nothing_is_keyed_so_nothing_is_claimed():
    unkeyed = dict(weekly_board(), keyed_against_roster=False)
    rows = sl.rows_for_week(competition(), unkeyed, week_label="2026-08-04")
    assert all(row["attended"] is None for row in rows)
    assert all(row["streak"] is None for row in rows)


def test_a_streak_only_attaches_to_the_week_it_was_measured_in():
    same = sl.rows_for_week(competition(), weekly_board("2026-08-04"),
                            week_label="2026-08-04")
    assert same[0]["streak"] == 3
    other = sl.rows_for_week(competition(), weekly_board("2026-08-11"),
                             week_label="2026-08-04")
    assert all(row["streak"] is None for row in other)


# ---------------------------------------------------------------------------
# the shape and the size on disk
# ---------------------------------------------------------------------------

def test_a_row_carries_exactly_the_agreed_fields(tmp_path):
    row = sl.rows_for_week(competition(), weekly_board(),
                           week_label="2026-08-04")[0]
    assert list(row) == list(sl.ROW_FIELDS)
    assert row["season_slug"] == "season-mn-1"
    assert row["week_label"] == "2026-08-04"
    assert row["rank"] == 1 and row["score"] == 3943.9 and row["delta"] == 26.2


def test_a_line_stays_compact(tmp_path):
    line = sl._encode(sl.rows_for_week(competition(), weekly_board(),
                                       week_label="2026-08-04")[0])
    # ~130 bytes is the number the whole size budget was quoted from; a
    # regression here is a regression in "under 1 MB a year, forever".
    assert len(line.encode("utf-8")) < 200


def test_the_file_is_one_json_object_per_line(tmp_path):
    root = str(tmp_path)
    sl.append_for_run(root=root, competition=competition(),
                      weekly_board=weekly_board(), week_label="2026-08-04")
    raw = open(sl.ledger_path("season-mn-1", root), encoding="utf-8").read()
    assert raw.endswith("\n")
    for line in raw.splitlines():
        assert json.loads(line)["season_slug"] == "season-mn-1"


# ---------------------------------------------------------------------------
# the flip: a week is never filed under the wrong season
# ---------------------------------------------------------------------------

def test_a_rebaked_bundle_may_not_file_the_old_seasons_week(tmp_path):
    # The two hours after a flip: the bundle already says season-mn-2 while
    # the week being recorded still belongs to season-mn-1.
    result = sl.append_for_run(root=str(tmp_path),
                               competition=competition("season-mn-2"),
                               weekly_board=weekly_board(),
                               week_label="2026-08-11")
    assert result["appended"] == 0
    assert result["reason"] == "week outside season"
    assert not os.path.exists(sl.ledger_path("season-mn-2", str(tmp_path)))


def test_the_previous_season_is_read_out_of_the_ledger_itself(tmp_path):
    root = str(tmp_path)
    assert sl.previous_season_slug(root) is None
    sl.append_for_run(root=root, competition=competition(),
                      weekly_board=weekly_board(), week_label="2026-08-04")
    assert sl.previous_season_slug(root) == "season-mn-1"


def test_the_flip_freezes_the_old_season_once_and_then_stops(tmp_path, monkeypatch):
    root = str(tmp_path)
    sl.append_for_run(root=root, competition=competition(),
                      weekly_board=weekly_board(), week_label="2026-08-04")
    _write_bundle(tmp_path)
    flipped = sl.maybe_freeze_on_flip(root=root, now="2026-08-18T15:00:00+00:00",
                                      allow_git=False)
    assert flipped["frozen"] is True
    assert flipped["season_slug"] == "season-mn-1"
    # Every run after that finds the freeze and does nothing at all.
    again = sl.maybe_freeze_on_flip(root=root, now="2026-08-19T11:30:00+00:00",
                                    allow_git=False)
    assert again["frozen"] is False and again["reason"] == "already frozen"


def test_a_failed_freeze_is_retried_not_forgotten(tmp_path):
    # The trap this avoids: the flip-day run finds no sources of the right
    # vintage, the new season's first rows land, and a "has the season
    # changed since last time?" test then answers no forever — leaving the
    # old season unfrozen and nobody to notice.
    root = str(tmp_path)
    sl.append_for_run(root=root, competition=competition(),
                      weekly_board=weekly_board(), week_label="2026-08-04")
    _write_bundle(tmp_path, slug="season-mn-2",
                  records_based_on="2026-08-25T16:19:00+00:00")
    failed = sl.maybe_freeze_on_flip(root=root, now="2026-08-18T15:00:00+00:00",
                                     allow_git=False)
    assert failed["frozen"] is False and failed["reason"] == "no clean source"
    # The new season is now the one being written to...
    sl.append_for_run(root=root, competition=competition("season-mn-2"),
                      weekly_board=weekly_board(), week_label="2026-08-18")
    assert sl.previous_season_slug(root) == "season-mn-2"
    # ...and the old one is STILL pending, and still freezes when a source
    # of the right vintage turns up.
    _write_bundle(tmp_path)
    healed = sl.maybe_freeze_on_flip(root=root, now="2026-08-25T11:30:00+00:00",
                                     allow_git=False)
    assert healed["frozen"] is True and healed["season_slug"] == "season-mn-1"


def test_no_flip_means_no_freeze(tmp_path):
    root = str(tmp_path)
    sl.append_for_run(root=root, competition=competition(),
                      weekly_board=weekly_board(), week_label="2026-08-04")
    _write_bundle(tmp_path)
    result = sl.maybe_freeze_on_flip(root=root, now="2026-08-17T11:30:00+00:00",
                                     allow_git=False)
    assert result["frozen"] is False and result["reason"] == "no flip"
    assert not os.path.exists(sl.freeze_dir("season-mn-1", root))


# ---------------------------------------------------------------------------
# the freeze — written once, from the right season's bytes
# ---------------------------------------------------------------------------

def _write_bundle(tmp_path, slug="season-mn-1", records_based_on=None):
    bundle = tmp_path / sl.BUNDLE_DIR
    bundle.mkdir(exist_ok=True)
    payloads = {sl.COMPETITION_FILE: competition(slug),
                sl.RECORDS_FILE: records(records_based_on or "2026-08-11T16:19:00+00:00"),
                sl.ISLANDS_FILE: islands(slug)}
    for name, payload in payloads.items():
        (bundle / name).write_text(json.dumps(payload), encoding="utf-8")
    return bundle


def test_a_freeze_writes_the_three_files_once(tmp_path):
    root = str(tmp_path)
    _write_bundle(tmp_path)
    result = sl.freeze_season("season-mn-1", root=root)
    for name in sl.FREEZE_FILES:
        path = os.path.join(sl.freeze_dir("season-mn-1", root), name)
        assert os.path.exists(path)
        payload = json.load(open(path, encoding="utf-8"))
        assert payload["season"]["slug"] == "season-mn-1"
        assert payload["final"] is True
    standings = json.load(open(result["written"][0], encoding="utf-8"))
    assert [c["rank"] for c in standings["characters"]] == [1, 2, 3]
    assert standings["guild_standing"]["world"] == 5119
    assert standings["closing_week"] == "2026-08-11"


def test_the_guard_refuses_a_second_freeze(tmp_path):
    root = str(tmp_path)
    _write_bundle(tmp_path)
    sl.freeze_season("season-mn-1", root=root)
    first = open(os.path.join(sl.freeze_dir("season-mn-1", root),
                              "final_standings.json"), encoding="utf-8").read()
    with pytest.raises(FileExistsError):
        sl.freeze_season("season-mn-1", root=root)
    after = open(os.path.join(sl.freeze_dir("season-mn-1", root),
                              "final_standings.json"), encoding="utf-8").read()
    assert after == first        # the refusal did not touch a byte


def test_the_guard_refuses_a_partial_overwrite_too(tmp_path):
    root = str(tmp_path)
    _write_bundle(tmp_path)
    base = tmp_path / "data" / "seasons" / "season-mn-1"
    base.mkdir(parents=True)
    (base / "records.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError):
        sl.freeze_season("season-mn-1", root=root)
    assert not (base / "final_standings.json").exists()


def test_a_freeze_refuses_the_wrong_seasons_numbers(tmp_path):
    # The failure this guard exists for: the flip has happened, the bundle
    # has been rebaked against S2, and something tries to write those
    # numbers into S1's grave.
    root = str(tmp_path)
    _write_bundle(tmp_path, slug="season-mn-2",
                  records_based_on="2026-08-25T16:19:00+00:00")
    with pytest.raises(ValueError) as exc:
        sl.freeze_season("season-mn-1", root=root)
    assert "wrong vintage" in str(exc.value)
    assert not os.path.exists(sl.freeze_dir("season-mn-1", root))


def test_a_freeze_refuses_records_it_cannot_date(tmp_path):
    root = str(tmp_path)
    _write_bundle(tmp_path)
    bundle = tmp_path / sl.BUNDLE_DIR
    bundle.joinpath(sl.RECORDS_FILE).write_text(
        json.dumps({"standing": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        sl.freeze_season("season-mn-1", root=root)


def test_the_freeze_writes_the_seasons_closing_week_into_the_ledger(tmp_path):
    # The last week of a season closes exactly at the flip, so no scheduled
    # run is ever holding both that week AND a bundle of the old season's
    # vintage. The freeze is, so the freeze writes it.
    root = str(tmp_path)
    _write_bundle(tmp_path)
    result = sl.freeze_season("season-mn-1", root=root)
    assert result["closing_week"]["week_label"] == "2026-08-11"
    assert result["closing_week"]["appended"] == 3
    weeks = {row["week_label"] for row in
             sl.read_rows(sl.ledger_path("season-mn-1", root))}
    assert weeks == {"2026-08-11"}


# ---------------------------------------------------------------------------
# the backfill — marked as reconstruction, and never invented
# ---------------------------------------------------------------------------

def test_backfilled_rows_are_marked_as_reconstructions(tmp_path):
    rows = sl.rows_for_week(competition(), None, week_label="2026-08-04",
                            backfilled=True)
    assert all(row["backfilled"] is True for row in rows)
    live = sl.rows_for_week(competition(), None, week_label="2026-08-04")
    assert all("backfilled" not in row for row in live)


def test_a_backfill_row_never_overwrites_a_live_one(tmp_path):
    root = str(tmp_path)
    path = sl.ledger_path("season-mn-1", root)
    sl.append_rows(sl.rows_for_week(competition(), weekly_board(),
                                    week_label="2026-08-04"), path)
    added = sl.append_rows(sl.rows_for_week(competition(), None,
                                            week_label="2026-08-04",
                                            backfilled=True), path)
    assert added == 0
    assert all("backfilled" not in row for row in sl.read_rows(path))


def test_the_backfill_skips_a_week_with_no_snapshot_after_it(tmp_path, monkeypatch):
    # Two bakes, three weeks apart: 07-24 (the first view after week 07-14
    # closed) and 08-12 (the first view after week 08-04 closed). Weeks
    # 07-21 and 07-28 closed with no bake in the week that followed, and
    # the history in front of us cannot say what they finished on — so
    # they get no rows at all rather than a stale stand-in.
    history = [("sha_new", "2026-08-12T11:30:00+00:00"),
               ("sha_old", "2026-07-24T23:47:00+00:00")]
    blobs = {
        "sha_new": dict(competition(), based_on="2026-08-12T11:30:00+00:00"),
        "sha_old": dict(competition(), based_on="2026-07-24T23:47:00+00:00"),
    }
    monkeypatch.setattr(sl, "competition_history",
                        lambda root=".", limit=200, rev="HEAD": history)
    monkeypatch.setattr(sl, "git_show_json",
                        lambda rev, path, root=".": blobs.get(rev))
    plan = sl.plan_backfill(root=str(tmp_path), now="2026-08-16T00:00:00+00:00")
    assert [(entry["week_label"], entry["sha"]) for entry in plan] == [
        ("2026-07-14", "sha_old"), ("2026-08-04", "sha_new")]
    assert {"2026-07-21", "2026-07-28"}.isdisjoint(
        {entry["week_label"] for entry in plan})


def test_the_backfill_stops_at_the_last_completed_week(tmp_path, monkeypatch):
    history = [("sha", "2026-08-19T11:30:00+00:00")]
    monkeypatch.setattr(sl, "competition_history",
                        lambda root=".", limit=200, rev="HEAD": history)
    monkeypatch.setattr(
        sl, "git_show_json",
        lambda rev, path, root=".": dict(competition(),
                                         based_on="2026-08-19T11:30:00+00:00"))
    # Asked on 08-16, a bake from 08-19 describes a week that has not
    # finished yet from the caller's point of view.
    assert sl.plan_backfill(root=str(tmp_path),
                            now="2026-08-16T00:00:00+00:00") == []

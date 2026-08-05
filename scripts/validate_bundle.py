"""Validate a built web-data bundle for cross-layer consistency.

Why this exists
---------------
On 2026-07-23 a partial refresh updated competition.json while the digest
layers (records_leaderboard, recap_ribbon) kept week-old numbers -- and every
file claimed the same based_on, so nothing looked wrong. The downstream
redesign's contract build caught it a day later. This gate makes that class
of bundle impossible to ship from here.

The bundle deliberately mixes two cadences:

  weekly  recap_ribbon, records_leaderboard   (from board_state -- the
          story-of-the-week and the weekly ladder with streaks)
  daily   competition                          (from competition_cache --
          the living Raider.io pull)

Cross-cadence disagreement in scores is EXPECTED mid-week and is not an
error. What IS an error:

  parity     a standalone layer file that differs from the copy embedded in
             site_data.json (a partial write/copy -- the 2026-07-23 failure)
  internal   a layer that disagrees with itself (counts vs rows, ranks not
             contiguous, rankings naming characters that don't exist)
  weekly     the weekly layers disagreeing with each other (recap's biggest
             climber vs the ladder's own delta_week column)
  stamps     a layer whose based_on does not match its actual source's
             timestamp (the lie that hid the 2026-07-23 split-brain)

Like test_no_credentials_in_output.py this runs two ways on purpose:

    pytest tests/test_validate_bundle.py      # in CI
    python scripts/validate_bundle.py [DIR]   # as a build gate in the
                                              # daily-refresh workflow

Exit code 0 when nothing is wrong, 1 on any ERROR. Warnings alone pass.
Console output is ASCII-safe (character names carry accents; CI logs and
Windows consoles must both survive them).
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The standalone per-layer files build_site_data.py writes next to
# site_data.json. Every one must exist and byte-match its embedded copy.
LAYERS = ("recap_ribbon", "records_leaderboard", "weekly_board",
          "guild_achievements", "island_completion", "transmog_changes",
          "guild_pulse", "competition", "parses")

# Layers younger than some bundles on disk. Their ABSENCE is a warning (a
# bundle built before the layer existed is old, not split-brained); their
# PRESENCE is held to the same parity rule as every other layer.
YOUNG_LAYERS = frozenset({"weekly_board"})

SCORE_TOLERANCE = 0.05  # scores are one-decimal floats; anything past
                        # rounding noise is real drift


def _say(msg):
    print(msg.encode("ascii", "backslashreplace").decode("ascii"))


class Report:
    """Collects findings so one bad layer doesn't hide the rest."""

    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, section, message):
        self.errors.append((section, message))

    def warn(self, section, message):
        self.warnings.append((section, message))

    def dump(self):
        for kind, findings in (("ERROR", self.errors), ("WARN", self.warnings)):
            for section, message in findings:
                _say(f"{kind} [{section}] {message}")


def load_bundle(bundle_dir):
    """Load site_data.json + every standalone layer file. Missing or
    unparseable files are reported by the caller via KeyError/None."""
    bundle = {}
    for name in LAYERS + ("site_data",):
        path = os.path.join(bundle_dir, f"{name}.json")
        try:
            with open(path, encoding="utf-8") as f:
                obj = json.load(f)
            # samples carry a top-level "_sample": true marker the embedded
            # copies do not; it is a fixture label, never data, so it is
            # invisible to the parity check.
            if isinstance(obj, dict):
                obj.pop("_sample", None)
            bundle[name] = obj
        except FileNotFoundError:
            bundle[name] = None
        except json.JSONDecodeError as e:
            bundle[name] = None
            bundle.setdefault("_parse_errors", {})[name] = str(e)
    return bundle


def check_presence_and_parity(bundle, report):
    """Every layer file exists, parses, and equals its site_data embed.

    The 2026-07-23 failure was exactly a bundle whose members came from
    different runs. site_data.json embeds every layer, so equality between
    the standalone file and the embed proves the whole set left one build.
    """
    site = bundle.get("site_data")
    if site is None:
        report.error("presence", "site_data.json missing or unparseable")
        return
    for name in LAYERS:
        layer = bundle.get(name)
        if layer is None:
            detail = (bundle.get("_parse_errors") or {}).get(name, "missing")
            if name in YOUNG_LAYERS and detail == "missing":
                report.warn("presence",
                            f"{name}.json: missing -- this bundle predates the "
                            "layer; rebuild with scripts/build_site_data.py to "
                            "add it. Consumers treat it as absent, not empty.")
                continue
            report.error("presence", f"{name}.json: {detail}")
            continue
        if name not in site:
            report.error("parity", f"site_data.json has no '{name}' block")
        elif layer != site[name]:
            report.error(
                "parity",
                f"{name}.json differs from the copy inside site_data.json -- "
                "the bundle mixes two builds; regenerate with "
                "scripts/build_site_data.py")


def check_competition_internal(bundle, report):
    """The daily layer agrees with itself: counts, ranks, and rankings all
    describe the same set of characters."""
    comp = bundle.get("competition")
    if not comp or not comp.get("available"):
        return  # honest empty state -- nothing to cross-check
    # `characters` is EVERYONE browsable: ranked rows first (rank 1..N),
    # then the deliberate unscored bucket (rank None). `unranked` is the
    # summary list of that bucket; `rankings.overall` ladders the ranked.
    characters = comp.get("characters") or []
    unranked = comp.get("unranked") or []
    ranked_rows = [c for c in characters if c.get("rank") is not None]
    if comp.get("character_count") != len(characters):
        report.error("competition", "character_count {} != characters rows {}".format(comp.get("character_count"), len(characters)))
    if comp.get("ranked_count") != len(ranked_rows):
        report.error("competition", "ranked_count {} != ranked characters {}".format(comp.get("ranked_count"), len(ranked_rows)))
    if comp.get("unranked_count") != len(unranked):
        report.error("competition", "unranked_count {} != unranked rows {}".format(comp.get("unranked_count"), len(unranked)))
    by_key = {c.get("key"): c for c in characters}
    for u in unranked:
        c = by_key.get(u.get("key"))
        if c is None:
            report.error("competition", "unranked names unknown key {}".format(u.get("key")))
        elif c.get("rank") is not None:
            report.error("competition", "unranked key {} carries a rank in characters".format(u.get("key")))
    # Departed ledger (additive): a character is a member or departed, never
    # both; the count must describe the rows; every row must say when the
    # absence was first observed.
    departed = comp.get("departed") or []
    for d in departed:
        if d.get("key") in by_key:
            report.error("competition",
                         "departed key {} still listed in characters".format(d.get("key")))
        if not d.get("departed_at"):
            report.error("competition",
                         "departed key {} carries no departed_at stamp".format(d.get("key")))
    if comp.get("departed_count") is not None and comp.get("departed_count") != len(departed):
        report.error("competition", "departed_count {} != departed rows {}".format(
            comp.get("departed_count"), len(departed)))
    overall = (comp.get("rankings") or {}).get("overall") or []
    if len(overall) != len(ranked_rows):
        report.error("competition", f"rankings.overall has {len(overall)} rows, expected {len(ranked_rows)} ranked")
    for i, entry in enumerate(overall):
        if entry.get("rank") != i + 1:
            report.error("competition",
                         "rankings.overall ranks not contiguous at row %s" % (i + 1))
            break
    for entry in overall:
        c = by_key.get(entry.get("key"))
        if c is None:
            report.error("competition", "rankings.overall names unknown key {}".format(entry.get("key")))
        elif abs((c.get("score") or 0) - (entry.get("score") or 0)) > SCORE_TOLERANCE:
            report.error("competition", "score drift for {}: rankings {} vs characters {}".format(entry.get("key"), entry.get("score"), c.get("score")))


def check_weekly_coherence(bundle, report):
    """The two weekly layers tell one story: recap's beats agree with the
    ladder and headline records they digest."""
    recap = bundle.get("recap_ribbon") or {}
    records = bundle.get("records_leaderboard") or {}
    ladder = records.get("ladder") or []
    headline = {r.get("id"): r for r in records.get("headline_records") or []}
    beat_to_headline = {"biggest_key": "highest_timed_key",
                        "best_dps_parse": "best_dps_parse",
                        "best_hps_parse": "best_hps_parse"}

    if records.get("ladder_size") != len(ladder):
        report.error("weekly", "ladder_size {} != ladder rows {}".format(records.get("ladder_size"), len(ladder)))

    for beat in recap.get("beats") or []:
        kind = beat.get("kind")
        if kind in beat_to_headline:
            rec = headline.get(beat_to_headline[kind])
            if rec is None:
                report.error("weekly", f"recap beat {kind} has no matching headline record")
            elif rec.get("holder") != beat.get("subject") or rec.get("value") != beat.get("value"):
                report.error("weekly", f"recap beat {kind} disagrees with headline_records")
        elif kind == "biggest_climber":
            if ladder:
                top = max(ladder, key=lambda r: r.get("delta_week") or 0)
                if (top.get("name") != beat.get("subject")
                        or abs((top.get("delta_week") or 0) - (beat.get("value") or 0)) > SCORE_TOLERANCE):
                    report.error(
                        "weekly",
                        "recap biggest_climber ({} {:+g}) disagrees with the ladder's "
                        "own delta_week column ({} {:+g})".format(beat.get("subject"), beat.get("value") or 0,
                           top.get("name"), top.get("delta_week") or 0))


def check_stamps(bundle, report):
    """based_on stamps tell the truth about cadence.

    The weekly layers must share one stamp (they leave one board_state).
    The daily layer carries its own pull time plus week_baseline_from; its
    baseline must be the same weekly stamp. A daily stamp OLDER than the
    weekly one means the daily refresh is not actually running -- warn.
    """
    recap = bundle.get("recap_ribbon") or {}
    records = bundle.get("records_leaderboard") or {}
    week = bundle.get("weekly_board") or {}
    comp = bundle.get("competition") or {}

    weekly = {recap.get("based_on"), records.get("based_on"),
              week.get("based_on")}
    if len(weekly) > 1:
        report.error("stamps", f"weekly layers carry different based_on stamps: {sorted(str(s) for s in weekly)}")
    weekly_stamp = next(iter(weekly), None)

    if comp.get("available"):
        baseline = comp.get("week_baseline_from")
        if weekly_stamp and baseline and baseline != weekly_stamp:
            report.error(
                "stamps",
                f"competition.week_baseline_from ({baseline}) != weekly layers' based_on "
                f"({weekly_stamp}) -- delta_week is measured against a different snapshot "
                "than the ladder shows")
        daily = comp.get("based_on")
        if daily and weekly_stamp and daily < weekly_stamp:
            report.warn(
                "stamps",
                f"competition based_on ({daily}) predates the weekly snapshot ({weekly_stamp}) -- "
                "is the daily refresh actually running?")


# The consumer's own window. data/build_contract.py::verify_source_vintage in
# the redesign repo refuses any delivery whose meta.sources span more than
# this. Duplicated here ON PURPOSE so the producer fails first, loudly, at the
# workflow that made the bad bundle -- instead of the consumer failing later,
# quietly, in a place nobody is watching.
CONSUMER_VINTAGE_WINDOW_SECONDS = 30 * 60


def _iso(ts):
    from datetime import datetime
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def check_bundle_coherence(bundle, report):
    """The bundle is ONE MOMENT, or it is not shippable.

    The 2026-07-28 incident. build_site_data.py stamps generated_at = now on
    site_data / island_completion / records_leaderboard / parses -- the
    REBUILD clock -- while competition.json carries based_on from
    competition_cache.json, which only moves when refresh_competition.py
    runs. FIVE workflows rebuild this bundle; only two of them refresh
    competition first. The other three therefore committed bundles whose
    stamps spanned hours, and every one of those was silently UNINGESTIBLE:
    the consumer's vintage guard refused each delivery, the site froze on a
    two-day-old raid number, and nothing in this repo said a word about it.

    Nothing here looks wrong file-by-file -- that is exactly why it needs a
    check. The rule is the consumer's own: every source stamp within 30
    minutes of every other. A bundle that fails this must not be committed
    and must not be delivered.

    THE FIX WHEN THIS FIRES is at the producer, never here: refresh the
    laggard layer before rebuilding the bundle (for competition that is
    `python scripts/refresh_competition.py`, public API, no credentials).
    Widening this window would only move the lie downstream.
    """
    site = bundle.get("site_data")
    if not isinstance(site, dict):
        return  # presence check already reported it

    comp = bundle.get("competition") or {}
    stamps = {
        "site_data.generated_at": site.get("generated_at"),
        "competition.based_on": comp.get("based_on") if comp.get("available") else None,
        "island_completion.generated_at": (bundle.get("island_completion") or {}).get("generated_at"),
        "records_leaderboard.generated_at": (bundle.get("records_leaderboard") or {}).get("generated_at"),
        "parses.generated_at": (bundle.get("parses") or {}).get("generated_at"),
    }
    parsed = {k: _iso(v) for k, v in stamps.items() if v}
    if len(parsed) < 2:
        return

    newest_k = max(parsed, key=lambda k: parsed[k])
    oldest_k = min(parsed, key=lambda k: parsed[k])
    spread = parsed[newest_k] - parsed[oldest_k]
    if spread.total_seconds() > CONSUMER_VINTAGE_WINDOW_SECONDS:
        report.error(
            "coherence",
            f"bundle spans {spread} -- {oldest_k} ({stamps[oldest_k]}) is that much "
            f"older than {newest_k} ({stamps[newest_k]}). The consumer's 30-minute "
            f"vintage guard will REFUSE this delivery and the site will freeze on "
            f"whatever it already had. Refresh '{oldest_k.split('.')[0]}' before "
            "rebuilding the bundle (competition: python scripts/refresh_competition.py).")


def check_raid_frame(bundle, report):
    """The raid's per-boss frame must not contradict its own aggregate.

    island_completion.raid carries BOTH an aggregate (bosses_killed,
    killed_by_difficulty) and a per-boss islands[] list. When the per-boss
    detail comes from Blizzard guild achievements those name only the kills
    that earned a Guild Run achievement -- three of them at the time of
    writing -- while the aggregate says nine bosses are down on Heroic. A
    consumer that renders the islands list would then show 3/9 next to a
    "5/9 M" headline. Warning, not error: the redesign's contract derives
    per-boss state from the aggregate plus attestations and is unaffected,
    so this must not block a bundle -- but no other consumer should discover
    it the hard way.
    """
    raid = ((bundle.get("island_completion") or {}).get("raid")) or {}
    islands = raid.get("islands") or []
    if not islands:
        return
    conquered = sum(1 for b in islands if b.get("status") == "conquered")
    killed = raid.get("bosses_killed")
    if isinstance(killed, int) and killed and conquered < killed:
        report.warn(
            "raid_frame",
            f"raid.islands marks {conquered} boss(es) conquered but bosses_killed "
            f"= {killed} (detail_source={raid.get('detail_source')}). The named-kill "
            "source knows fewer kills than the aggregate; a consumer reading the "
            "islands list will under-report progress.")


def validate_bundle(bundle_dir):
    """Run every check; returns a Report."""
    report = Report()
    bundle = load_bundle(bundle_dir)
    check_presence_and_parity(bundle, report)
    check_competition_internal(bundle, report)
    check_weekly_coherence(bundle, report)
    check_stamps(bundle, report)
    check_bundle_coherence(bundle, report)
    check_raid_frame(bundle, report)
    return report


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    bundle_dir = args[0] if args else os.path.join(ROOT, "web_data")
    report = validate_bundle(bundle_dir)
    report.dump()
    if report.errors:
        _say(f"BUNDLE REFUSED: {len(report.errors)} error(s) in {bundle_dir}")
        return 1
    _say(f"bundle ok: {bundle_dir} ({len(report.warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())

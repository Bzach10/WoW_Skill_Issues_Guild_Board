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
LAYERS = ("recap_ribbon", "records_leaderboard", "guild_achievements",
          "island_completion", "transmog_changes", "guild_pulse",
          "competition")

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
        report.error("competition", "character_count %s != characters rows %s"
                     % (comp.get("character_count"), len(characters)))
    if comp.get("ranked_count") != len(ranked_rows):
        report.error("competition", "ranked_count %s != ranked characters %s"
                     % (comp.get("ranked_count"), len(ranked_rows)))
    if comp.get("unranked_count") != len(unranked):
        report.error("competition", "unranked_count %s != unranked rows %s"
                     % (comp.get("unranked_count"), len(unranked)))
    by_key = {c.get("key"): c for c in characters}
    for u in unranked:
        c = by_key.get(u.get("key"))
        if c is None:
            report.error("competition", "unranked names unknown key %s" % u.get("key"))
        elif c.get("rank") is not None:
            report.error("competition", "unranked key %s carries a rank in characters"
                         % u.get("key"))
    overall = (comp.get("rankings") or {}).get("overall") or []
    if len(overall) != len(ranked_rows):
        report.error("competition", "rankings.overall has %s rows, expected %s ranked"
                     % (len(overall), len(ranked_rows)))
    for i, entry in enumerate(overall):
        if entry.get("rank") != i + 1:
            report.error("competition",
                         "rankings.overall ranks not contiguous at row %s" % (i + 1))
            break
    for entry in overall:
        c = by_key.get(entry.get("key"))
        if c is None:
            report.error("competition", "rankings.overall names unknown key %s"
                         % entry.get("key"))
        elif abs((c.get("score") or 0) - (entry.get("score") or 0)) > SCORE_TOLERANCE:
            report.error("competition", "score drift for %s: rankings %s vs characters %s"
                         % (entry.get("key"), entry.get("score"), c.get("score")))


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
        report.error("weekly", "ladder_size %s != ladder rows %s"
                     % (records.get("ladder_size"), len(ladder)))

    for beat in recap.get("beats") or []:
        kind = beat.get("kind")
        if kind in beat_to_headline:
            rec = headline.get(beat_to_headline[kind])
            if rec is None:
                report.error("weekly", "recap beat %s has no matching headline record" % kind)
            elif rec.get("holder") != beat.get("subject") or rec.get("value") != beat.get("value"):
                report.error("weekly", "recap beat %s disagrees with headline_records" % kind)
        elif kind == "biggest_climber":
            if ladder:
                top = max(ladder, key=lambda r: r.get("delta_week") or 0)
                if (top.get("name") != beat.get("subject")
                        or abs((top.get("delta_week") or 0) - (beat.get("value") or 0)) > SCORE_TOLERANCE):
                    report.error(
                        "weekly",
                        "recap biggest_climber (%s %+g) disagrees with the ladder's "
                        "own delta_week column (%s %+g)"
                        % (beat.get("subject"), beat.get("value") or 0,
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
    comp = bundle.get("competition") or {}

    weekly = {recap.get("based_on"), records.get("based_on")}
    if len(weekly) > 1:
        report.error("stamps", "weekly layers carry different based_on stamps: %s"
                     % sorted(str(s) for s in weekly))
    weekly_stamp = next(iter(weekly), None)

    if comp.get("available"):
        baseline = comp.get("week_baseline_from")
        if weekly_stamp and baseline and baseline != weekly_stamp:
            report.error(
                "stamps",
                "competition.week_baseline_from (%s) != weekly layers' based_on "
                "(%s) -- delta_week is measured against a different snapshot "
                "than the ladder shows" % (baseline, weekly_stamp))
        daily = comp.get("based_on")
        if daily and weekly_stamp and daily < weekly_stamp:
            report.warn(
                "stamps",
                "competition based_on (%s) predates the weekly snapshot (%s) -- "
                "is the daily refresh actually running?" % (daily, weekly_stamp))


def validate_bundle(bundle_dir):
    """Run every check; returns a Report."""
    report = Report()
    bundle = load_bundle(bundle_dir)
    check_presence_and_parity(bundle, report)
    check_competition_internal(bundle, report)
    check_weekly_coherence(bundle, report)
    check_stamps(bundle, report)
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

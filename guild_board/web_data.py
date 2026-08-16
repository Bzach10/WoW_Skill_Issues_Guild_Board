"""Website data layers — the JSON the front-end reads for the Voyage Map,
islands, leaderboard, achievements and weekly recap.

Every function here is PURE: it takes already-loaded dicts (board_state,
cast_manifest, live-fetched M+ bests, guild achievements) and returns a
JSON-serialisable dict. Nothing here does network I/O — the driver script
(scripts/build_site_data.py) loads the inputs and writes the output, so
the shapes can be unit-tested offline with fixtures.

The contract the front-end consumes is documented in WEB_DATA_CONTRACT.md;
`SCHEMA_VERSION` below is the single source of truth for it and every
emitted envelope carries it. Bump it on any breaking shape change.

Five layers, each independently emittable so the front-end can lazy-load:

  build_recap_ribbon        story-of-the-week beats (week-over-week diff)
  build_records_leaderboard sortable season records/ladder
  build_guild_achievements  Midnight progress (credential-gated — degrades)
  build_island_completion   per-island conquered/timed status
  build_transmog_changes    before/after transmog diff
  build_parses              per-character WCL parse averages (credential-
                            gated — degrades; keyed name-realm, never bare)

build_site_data() assembles all five into one envelope.
"""

from datetime import datetime, timezone

from guild_board import season as season_mod
from guild_board.config import index_roster_by_name, resolve_character_key

SCHEMA_VERSION = 1


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _rekey_by_character(mapping, index):
    """Re-key a bare-name map onto character keys.

    Returns (keyed, unresolved). `unresolved` carries one row per name that
    could not become a key — {"name", "reason"} with reason "ambiguous" or
    "unknown" — because a name the pipeline cannot resolve is a SEAM a
    surface prints, not a row it quietly deletes and not a row it pays to a
    guess. Ambiguity is real here: the roster holds two Berobens.

    With no index at all there is nothing to resolve AGAINST, so nothing is
    reported: calling every name "unknown" would claim the roster was
    consulted and rejected them. `keyed_against_roster` carries that state.
    """
    if not index:
        return {}, []
    keyed, unresolved = {}, []
    for name, value in (mapping or {}).items():
        key, reason = resolve_character_key(name, index)
        if key:
            keyed[key] = value
        else:
            unresolved.append({"name": name, "reason": reason})
    return keyed, sorted(unresolved, key=lambda row: row["name"])


def _title(name):
    """board_state stores M+ names lowercased; records store them
    title-cased. Present a consistent display name without destroying the
    raw key the front-end may need for lookups."""
    return (name or "").strip().title()


# ---------------------------------------------------------------------------
# 1. Weekly recap ribbon
# ---------------------------------------------------------------------------

def build_recap_ribbon(board_state, transmog_changes=None, max_beats=6):
    """Auto-generate the "story of the week" from the week-over-week diff
    already captured in board_state.

    board_state carries a `baseline` snapshot (last week's standing,
    season_scores and records). Diffing current against it is the whole
    signal — no new data source needed. Each beat is a self-contained
    headline the ribbon can render in order; `emphasis` ("record" > "big"
    > "normal") lets the UI weight them.

    transmog_changes: the dict from build_transmog_changes (optional). When
    present, a "look changed" beat is added if anyone re-transmogged.
    """
    beats = []
    current = board_state or {}
    baseline = current.get("baseline") or {}
    records = current.get("records") or {}
    base_records = baseline.get("records") or {}

    # --- Records. `new` is set by the pipeline when a record was beaten
    # this week; fall back to a value comparison against baseline so a
    # missing flag never hides a genuine new record.
    key = records.get("highest_timed_key") or {}
    base_key = base_records.get("highest_timed_key") or {}
    if key.get("level"):
        beat_new = key.get("new") or key.get("level", 0) > base_key.get("level", 0)
        beats.append({
            "kind": "biggest_key",
            "headline": f"+{key['level']} {key.get('dungeon', '')}".strip(),
            "detail": f"{_title(key.get('name'))} timed the guild's biggest key"
                      + (f" as {key['spec']}" if key.get("spec") else ""),
            "subject": _title(key.get("name")),
            "value": key.get("level"),
            "emphasis": "record" if beat_new else "big",
            "is_new": bool(beat_new),
        })

    for rec_key, label, unit in (
            ("best_dps_parse", "top DPS parse", "%"),
            ("best_hps_parse", "top HPS parse", "%")):
        rec = records.get(rec_key) or {}
        base = base_records.get(rec_key) or {}
        if rec.get("parse"):
            is_new = rec.get("new") or rec.get("parse", 0) > base.get("parse", 0)
            beats.append({
                "kind": rec_key,
                "headline": f"{rec['parse']}{unit} on {rec.get('boss', '')}".strip(),
                "detail": f"{_title(rec.get('name'))} set the guild's {label}"
                          + (f" ({rec['spec']} {rec.get('cls', '')})".replace(" )", ")")
                             if rec.get("spec") else ""),
                "subject": _title(rec.get("name")),
                "value": rec.get("parse"),
                "emphasis": "record" if is_new else "normal",
                "is_new": bool(is_new),
            })

    # --- Biggest climber this week (season score delta vs baseline).
    scores = current.get("season_scores") or {}
    base_scores = baseline.get("season_scores") or {}
    climber, best_delta = None, 0.0
    for name, score in scores.items():
        delta = round(score - base_scores.get(name, score), 1)
        if delta > best_delta:
            best_delta, climber = delta, name
    if climber and best_delta > 0:
        beats.append({
            "kind": "biggest_climber",
            "headline": f"+{best_delta} score",
            "detail": f"{_title(climber)} climbed the most this week",
            "subject": _title(climber),
            "value": best_delta,
            "emphasis": "big" if best_delta >= 50 else "normal",
            "is_new": False,
        })

    # --- New faces on the ladder this week.
    newcomers = [n for n in scores if n not in base_scores]
    if newcomers:
        beats.append({
            "kind": "new_on_ladder",
            "headline": f"{len(newcomers)} new on the ladder"
                        if len(newcomers) > 1 else f"{_title(newcomers[0])} joined the ladder",
            "detail": ", ".join(_title(n) for n in newcomers[:5])
                      + (" …" if len(newcomers) > 5 else ""),
            "subject": _title(newcomers[0]),
            "value": len(newcomers),
            "emphasis": "normal",
            "is_new": True,
        })

    # --- Guild standing movement (lower world rank = better).
    standing = current.get("standing") or {}
    base_standing = baseline.get("standing") or {}
    if standing.get("world") and base_standing.get("world"):
        moved = base_standing["world"] - standing["world"]
        if moved:
            direction = "climbed" if moved > 0 else "slipped"
            beats.append({
                "kind": "standing_move",
                "headline": f"World #{standing['world']:,}",
                "detail": f"The guild {direction} {abs(moved):,} world ranks",
                "subject": "Skill Issues",
                "value": moved,
                "emphasis": "normal",
                "is_new": False,
            })

    # --- Transmog activity (optional, from layer 5).
    changed = (transmog_changes or {}).get("changed") or []
    if changed:
        beats.append({
            "kind": "transmog",
            "headline": f"{len(changed)} new look{'s' if len(changed) > 1 else ''}",
            "detail": ", ".join(c.get("name", c.get("slug", "")) for c in changed[:5])
                      + (" …" if len(changed) > 5 else "") + " changed their transmog",
            "subject": changed[0].get("name", changed[0].get("slug")),
            "value": len(changed),
            "emphasis": "normal",
            "is_new": True,
        })

    # Records first, then by how notable, then a stable order.
    order = {"record": 0, "big": 1, "normal": 2}
    beats.sort(key=lambda b: order.get(b["emphasis"], 3))

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "week_of": current.get("streaks_week"),
        "based_on": current.get("last_updated"),
        "beats": beats[:max_beats],
        "beat_count": len(beats),
    }


# ---------------------------------------------------------------------------
# 2. Records leaderboard
# ---------------------------------------------------------------------------

def build_records_leaderboard(board_state, limit=None):
    """Sortable season dataset: the headline records plus the full M+ score
    ladder with each member's week-over-week delta and current streak.

    The front-end sorts client-side, so every row carries all sort keys
    (score, delta, streak) rather than being pre-sorted into one order.
    Rows arrive score-descending as a sensible default.
    """
    current = board_state or {}
    scores = current.get("season_scores") or {}
    base_scores = (current.get("baseline") or {}).get("season_scores") or {}
    streaks = current.get("streaks") or {}

    ladder = []
    for rank, (name, score) in enumerate(
            sorted(scores.items(), key=lambda kv: kv[1], reverse=True), start=1):
        ladder.append({
            "rank": rank,
            "name": _title(name),
            "key": name,
            "score": score,
            "delta_week": round(score - base_scores.get(name, score), 1),
            "streak_weeks": streaks.get(name, 0),
            "is_new": name not in base_scores,
        })
    if limit:
        ladder = ladder[:limit]

    records = current.get("records") or {}
    headline = []
    key = records.get("highest_timed_key") or {}
    if key.get("level"):
        headline.append({
            "id": "highest_timed_key", "label": "Biggest Timed Key",
            "holder": _title(key.get("name")),
            "value": key.get("level"), "unit": "key_level",
            "context": key.get("dungeon"), "spec": key.get("spec"),
            "is_new": bool(key.get("new")),
        })
    for rec_id, label in (("best_dps_parse", "Best DPS Parse"),
                          ("best_hps_parse", "Best HPS Parse")):
        rec = records.get(rec_id) or {}
        if rec.get("parse"):
            headline.append({
                "id": rec_id, "label": label,
                "holder": _title(rec.get("name")),
                "value": rec.get("parse"), "unit": "percentile",
                "context": rec.get("boss"),
                "spec": (f"{rec.get('spec', '')} {rec.get('cls', '')}").strip(),
                "is_new": bool(rec.get("new")),
            })

    # The rank tiles on the Discord board have always carried an arrow: the
    # standing ALONE is only half of what it shows. Carry the week the arrow
    # is measured against so a consumer can print the same movement instead
    # of re-deriving it (or, as the paper did, dropping it).
    previous = (current.get("baseline") or {}).get("standing") or {}
    standing = current.get("standing") or {}
    delta = {}
    for scope in ("realm", "region", "world"):
        now, was = standing.get(scope), previous.get(scope)
        if isinstance(now, int) and isinstance(was, int) and was:
            delta[scope] = was - now      # positive = climbed

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "based_on": current.get("last_updated"),
        "standing": current.get("standing"),
        "previous_standing": previous or None,
        "standing_delta": delta or None,
        "headline_records": headline,
        "ladder": ladder,
        "ladder_size": len(ladder),
        "sortable_by": ["score", "delta_week", "streak_weeks", "rank"],
    }


# ---------------------------------------------------------------------------
# 2b. The weekly board's own week — the numbers that used to die with the run
# ---------------------------------------------------------------------------

def build_weekly_board(board_state=None, roster=None):
    """The WEEK the Discord board posts, as a data layer.

    Kills, pulls, wipes, deaths, this week's timed keys, this week's raid and
    Mythic+ parse pools, the most-improved pairs and the roast. These are
    Warcraft-Logs facts that the board rendered straight into a PNG and never
    published; `guild_board.state.build_week_block` now persists them into
    board_state.json and this turns that into the delivered layer.

    Degrades to `available: false` with an empty, documented shape rather
    than inventing a zero — a week nobody could read the logs for is a gap in
    the measurement, not a week in which nobody died.

    roster: the roster cache's name-realm entries. Warcraft Logs names have
    no realm, so `streaks` and `deaths` have always been keyed on a BARE
    NAME — and this roster holds two characters called Beroben, i.e. two
    people sharing one key. With a roster in hand this emits the same facts
    keyed on the character key (`attendance`, `streaks_by_key`,
    `deaths_by_key`) plus the names that could not be resolved. The bare-name
    maps stay exactly as they were: they are what the live consumer reads
    today, and breaking them here would take the site down before the
    consumer has switched over.
    """
    week = (board_state or {}).get("week") or {}
    have = any(k in week for k in ("kills", "pulls", "deaths_total",
                                   "keys", "parses", "mplus_parses"))

    index = index_roster_by_name(roster)
    attendance_block = (board_state or {}).get("attendance") or {}
    attendance, attendance_unresolved = _rekey_by_character(
        attendance_block.get("weeks"), index)
    streaks_by_key, streaks_unresolved = _rekey_by_character(
        (board_state or {}).get("streaks"), index)
    deaths_by_key, deaths_unresolved = _rekey_by_character(
        week.get("deaths"), index)
    scanned = list(attendance_block.get("scanned") or [])
    logged = list(attendance_block.get("all") or [])

    out = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "available": bool(have),
        "based_on": (board_state or {}).get("last_updated"),
        "week_label": week.get("label"),
        "week_start": week.get("start"),
        "week_end": week.get("end"),
        "zone": week.get("zone"),
        "difficulty": week.get("difficulty"),
        "kills": week.get("kills"),
        "pulls": week.get("pulls"),
        "wipes": week.get("wipes"),
        "deaths_total": week.get("deaths_total"),
        "deaths": week.get("deaths") or {},
        "repair_estimate": week.get("repair_estimate"),
        "keys": week.get("keys") or [],
        "parses": week.get("parses") or {},
        "mplus_parses": week.get("mplus_parses") or {},
        "improvement": week.get("improvement") or {},
        "roast": week.get("roast"),
        "streaks": (board_state or {}).get("streaks") or {},
        "streaks_week": (board_state or {}).get("streaks_week"),
        "streaks_started": (board_state or {}).get("streaks_started"),
        # --- keyed on the CHARACTER KEY (name-realm), never a bare name.
        # `attendance` is the season's raid weeks per character: the sweep
        # that feeds Most Improved has always known who was in which week and
        # the pipeline threw it away after reducing it to a streak integer.
        "attendance": attendance,
        "attendance_coverage": {
            "weeks_scanned": scanned,
            "weeks_logged": logged,
            # Weeks the guild logged but whose report details the sweep did
            # not read. A streak cannot be counted through one of these, and
            # a consumer must not read an absence in them as "did not raid".
            "weeks_unknown": sorted(set(logged) - set(scanned)),
            "characters": len(attendance),
            "source_names": len(attendance_block.get("weeks") or {}),
        },
        "attendance_unresolved": attendance_unresolved,
        "streaks_by_key": streaks_by_key,
        "streaks_unresolved": streaks_unresolved,
        "deaths_by_key": deaths_by_key,
        "deaths_unresolved": deaths_unresolved,
        # False means no roster reached this builder, so every *_by_key map
        # above is empty BECAUSE IT COULD NOT BE BUILT — not because nobody
        # raided. A consumer must branch on this before rendering a zero.
        "keyed_against_roster": bool(index),
        "roster_size": len(index),
    }
    out["status"] = ("ok" if have else
                     "pending: the weekly board has not posted a week yet")
    return out


# ---------------------------------------------------------------------------
# 3. Guild achievements (Midnight progress)  — credential-gated
# ---------------------------------------------------------------------------

def build_guild_achievements(achievements=None, season=None):
    """Trophy-hall data from Blizzard's guild achievements API.

    achievements: the raw payload from
    /data/wow/guild/{realm}/{name}/achievements, or None. That endpoint
    needs BLIZZARD_CLIENT_ID/SECRET, which are not present in every
    environment — so this degrades to a stable, documented empty shape with
    `available: false` rather than inventing trophies. The front-end can
    build the whole trophy hall against this shape and it fills in the
    moment a credentialed refresh runs.
    """
    if not achievements:
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _now_iso(),
            "available": False,
            "status": "pending_credentials",
            "source": "/data/wow/guild/{realm}/{name}/achievements",
            # Member-facing copy: name the script, never the credential
            # env vars — the sweep in test_no_credentials_in_output.py
            # fails the build on credential names in shipped output.
            "detail": "No guild-achievements data yet — the credentialed "
                      "Action (scripts/refresh_blizzard_profiles.py) has "
                      "not run. Blizzard's guild API fills this layer.",
            "total_points": 0,
            "trophies": [],
        }

    total = achievements.get("total_quantity") or achievements.get("total_points")
    trophies = []
    for entry in achievements.get("achievements") or []:
        ach = entry.get("achievement") or {}
        completed_ms = entry.get("completed_timestamp")
        trophies.append({
            "id": ach.get("id"),
            "name": ach.get("name"),
            "completed_at": _ms_to_iso(completed_ms),
            "criteria": _achievement_criteria(entry.get("criteria")),
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "available": True,
        "status": "ok",
        "source": "/data/wow/guild/{realm}/{name}/achievements",
        "total_points": total or 0,
        "trophy_count": len(trophies),
        "trophies": trophies,
    }


def _ms_to_iso(ms):
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _achievement_criteria(criteria):
    """Flatten Blizzard's nested criteria into is_completed + child count —
    enough for a trophy card without dragging the whole tree to the client."""
    if not criteria:
        return None
    return {
        "is_completed": bool(criteria.get("is_completed")),
        "child_count": len(criteria.get("child_criteria") or []),
    }


# ---------------------------------------------------------------------------
# 4. Island completion
# ---------------------------------------------------------------------------

def extract_raid_boss_kills(achievements, season=None):
    """Map a season's raid bosses to their earliest kill date, from the
    guild-achievements payload.

    Blizzard names boss-kill achievements after the boss ("Ahead of the
    Curve: <boss>", "<boss>", etc.), so a boss is confirmed killed when its
    display name appears in any completed achievement title. Returns
    {boss_name: first_kill_iso_or_None}. Only bosses actually found are
    included — an empty result means the payload had no matching titles,
    which the caller treats as "fall back to the inferred count".
    """
    season = season or season_mod.CURRENT_SEASON
    kills = {}
    entries = (achievements or {}).get("achievements") or []
    for boss in season["raid"]["bosses"]:
        name = boss["name"]
        earliest = None
        for entry in entries:
            title = ((entry.get("achievement") or {}).get("name") or "")
            if name.lower() in title.lower():
                iso = _ms_to_iso(entry.get("completed_timestamp"))
                if iso and (earliest is None or iso < earliest):
                    earliest = iso
                elif earliest is None:
                    earliest = iso or earliest
        if earliest is not None or _boss_title_present(name, entries):
            kills[name] = earliest
    return kills


def _boss_title_present(boss_name, entries):
    return any(boss_name.lower() in ((e.get("achievement") or {}).get("name") or "").lower()
               for e in entries)


def build_island_completion(dungeon_bests=None, raid_progression=None,
                            board_records=None, season=None,
                            confirmed_boss_kills=None):
    """Per-island conquered/timed status for the Voyage Map.

    dungeon_bests: {dungeon_name: {"level": int, "timed": bool,
                    "by": str}} — the roster's best run per current-season
                    dungeon (from Raider.io mythic_plus_best_runs; the
                    pipeline already fetches these). Missing dungeon = no
                    run yet.
    raid_progression: Raider.io guild raid_progression block, e.g.
                    {"tier-mn-1": {"summary": "3/9 M",
                     "mythic_bosses_killed": 3, ...}}.
    board_records: board_state["records"], used to attribute specific
                    raid-boss records to their island where we have them.
    confirmed_boss_kills: {boss_name: first_kill_iso_or_None} from the
                    guild-achievements API (see extract_raid_boss_kills).
                    When present, these are AUTHORITATIVE per-boss kills —
                    every listed boss is kill_confirmed with a first_kill_at,
                    detail_source becomes "guild_achievements", and the
                    pull-order inference is only used to fill gaps.

    A dungeon island is "conquered" when someone timed it, "attempted" when
    run but not timed, "locked" when untouched. Raid bosses are confirmed
    from guild achievements when available, and otherwise inferred from the
    tier's aggregate kill count by pull order (flagged as such).
    """
    season = season or season_mod.CURRENT_SEASON
    dungeon_bests = dungeon_bests or {}
    raid_progression = raid_progression or {}
    board_records = board_records or {}
    confirmed_boss_kills = confirmed_boss_kills or {}

    islands = []
    conquered = 0
    for dg in season["dungeons"]:
        best = dungeon_bests.get(dg["name"]) or {}
        timed = bool(best.get("timed"))
        if timed:
            conquered += 1
        islands.append({
            "id": dg["slug"],
            "name": dg["name"],
            "kind": "dungeon",
            "challenge_mode_id": dg["challenge_mode_id"],
            "status": "conquered" if timed else ("attempted" if best.get("level") else "locked"),
            "best_level": best.get("level"),
            "timed": timed,
            "held_by": best.get("by"),
        })

    raid = season["raid"]
    prog = raid_progression.get(raid["slug"]) or {}
    mythic_killed = prog.get("mythic_bosses_killed") or 0
    heroic_killed = prog.get("heroic_bosses_killed") or 0
    normal_killed = prog.get("normal_bosses_killed") or 0
    highest_killed = max(mythic_killed, heroic_killed, normal_killed)

    # Which specific bosses we can name as beaten, from board records.
    record_bosses = {
        (board_records.get(k) or {}).get("boss")
        for k in ("best_dps_parse", "best_hps_parse")
    }
    record_bosses.discard(None)

    # Guild achievements, when present, are the authoritative per-boss source.
    have_achievements = bool(confirmed_boss_kills)
    detail_source = "guild_achievements" if have_achievements else "raid_progression_count"

    boss_islands = []
    for boss in raid["bosses"]:
        name = boss["name"]
        # Confirmed if guild achievements name the kill, or we hold a record
        # for that specific boss. The record path is only as trustworthy as
        # the record's own provenance - Amrevenge's 97 on Fallen-King
        # Salhadaar (board_records.best_dps_parse) was [unknown] until
        # 2026-07-23, when Zach confirmed it real (owner-confirmed + WCL);
        # see docs/DATA_INTEGRITY.md #4.1/#6. Salhadaar's kill_confirmed
        # here rests on that record and is sound now that it's verified.
        # A record whose own provenance is still unverified would make this
        # a weaker signal than "confirmed" implies - see DATA_INTEGRITY.md
        # #2 leak path 5 (kill_confirmed conflates two confidence levels;
        # the DB-layer fix is DATABASE_DESIGN.md #7.3's kill_state, not yet
        # landed).
        confirmed = name in confirmed_boss_kills or name in record_bosses
        # Inference (pull order vs kill count) only fills gaps, and only when
        # we don't have the authoritative achievement list.
        by_order = (not have_achievements) and boss["order"] <= highest_killed
        boss_islands.append({
            "id": boss["slug"],
            "name": name,
            "kind": "raid_boss",
            "order": boss["order"],
            "status": "conquered" if (confirmed or by_order) else "locked",
            "kill_confirmed": confirmed,
            "inferred_from_progress": by_order and not confirmed,
            "first_kill_at": confirmed_boss_kills.get(name),
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "season_slug": season["slug"],
        "season_name": season["name"],
        "dungeons": {
            "islands": islands,
            "conquered": conquered,
            "total": len(islands),
        },
        "raid": {
            "slug": raid["slug"],
            "display_name": raid.get("display_name"),
            "summary": prog.get("summary"),
            # bosses_killed is the highest count across difficulties — a boss
            # dead on any difficulty counts as "conquered" for the island.
            # The per-difficulty counts are exposed so the UI can label it
            # ("5 down, 3 of them on Mythic") instead of guessing.
            "bosses_killed": highest_killed,
            "killed_by_difficulty": {
                "normal": normal_killed, "heroic": heroic_killed,
                "mythic": mythic_killed,
            },
            "total_bosses": len(raid["bosses"]),
            "islands": boss_islands,
            # Provenance: "guild_achievements" = authoritative per-boss kills
            # with first_kill_at dates; "raid_progression_count" = per-boss
            # status inferred from the aggregate kill count by pull order.
            "detail_source": detail_source,
        },
    }


# ---------------------------------------------------------------------------
# 5. Transmog "what changed this week"
# ---------------------------------------------------------------------------

def build_transmog_changes(manifest, snapshot=None):
    """Before/after transmog diff for the "what changed this week" feature.

    manifest: cast_manifest dict.
    snapshot: {slug: fingerprint} from the previous run (e.g. last week's),
              or None on the very first run.

    Returns the changed/new characters AND a fresh `snapshot` the caller
    should persist for next week's comparison — same baseline pattern
    board_state already uses. On the first run (no snapshot) nothing is
    reported as changed; every character seeds the baseline instead, so the
    ribbon does not falsely announce that the whole cast re-transmogged.
    """
    manifest = manifest or {}
    characters = manifest.get("characters") or {}
    snapshot = snapshot or {}

    changed, new = [], []
    fresh_snapshot = {}
    for slug, char in characters.items():
        fp = char.get("transmog_fingerprint") or ""
        fresh_snapshot[slug] = fp
        prior = snapshot.get(slug)
        if prior is None:
            if snapshot:  # baseline exists but this char is new to it
                new.append({"slug": slug, "name": char.get("name", slug)})
            continue
        if prior != fp:
            changed.append({
                "slug": slug,
                "name": char.get("name", slug),
                "class": char.get("class"),
                "spec": char.get("spec"),
                "render_url": char.get("render_url"),
                "before_fingerprint": prior,
                "after_fingerprint": fp,
            })

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "is_first_run": not snapshot,
        "changed": changed,
        "changed_count": len(changed),
        "new_characters": new,
        "snapshot": fresh_snapshot,
    }


# ---------------------------------------------------------------------------
# 6. Guild pulse — the living Discord feed
# ---------------------------------------------------------------------------

def build_guild_pulse(pulse_items=None, max_items=60):
    """The hangout's heartbeat: a living feed of guild-public Discord
    highlights (chat, memes, banter, notable reactions).

    pulse_items: the flat list from discord_inputs.fetch_guild_pulse (already
    privacy-filtered — allowlisted channels only, opt-outs and blocklist
    applied, display names only, no user ids), or None. None degrades to a
    stable empty shape with available:false so the feed component builds now
    and fills when the credentialed Discord refresh runs.

    Everything here is pass-through packaging: no NEW data is derived, so a
    message can never appear in the feed unless the fetch layer let it
    through its privacy filters.
    """
    if not pulse_items:
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _now_iso(),
            "available": False,
            "status": "pending_discord_refresh",
            "source": "read-only Discord bot, allowlisted guild-public channels",
            "items": [],
            "item_count": 0,
            "by_kind": {},
        }

    items = pulse_items[:max_items]
    by_kind = {}
    for it in items:
        by_kind[it.get("kind", "chat")] = by_kind.get(it.get("kind", "chat"), 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "available": True,
        "status": "ok",
        "source": "read-only Discord bot, allowlisted guild-public channels",
        "items": items,
        "item_count": len(items),
        "by_kind": by_kind,
        # Discord CDN media urls can be signed/expiring, so the feed is meant
        # to be re-fetched regularly rather than cached long-term client-side.
        "media_note": "Discord CDN urls may expire; refresh the feed rather "
                      "than hotlinking indefinitely.",
    }


# ---------------------------------------------------------------------------
# 7. Per-character parses — current-tier WCL best-performance averages
# ---------------------------------------------------------------------------

# WCL difficulty ids -> the names config.yml's parses.difficulty_scale uses.
_DIFFICULTY_NAMES = {5: "mythic", 4: "heroic", 3: "normal", 1: "lfr"}
_DIFFICULTY_IDS = {name: did for did, name in _DIFFICULTY_NAMES.items()}


def _scale_factors(difficulty_scale):
    """config.yml's name-keyed factors as clean floats, defaulting to 1.0.

    Forgiving on purpose — this file is officer-edited YAML. A missing or
    non-numeric factor becomes the identity rather than blowing up the
    build; negatives clamp to 0 (= excluded, same as an explicit 0)."""
    factors = {}
    for name in ("mythic", "heroic", "normal", "lfr"):
        raw = (difficulty_scale or {}).get(name, 1.0)
        try:
            factors[name] = max(0.0, float(raw))
        except (TypeError, ValueError):
            factors[name] = 1.0
    return factors


def sweep_difficulties(difficulty_scale, candidates=(5, 4, 3)):
    """The WCL difficulty ids the parse sweep should walk, given config.yml's
    parses.difficulty_scale: a factor of 0 excludes that difficulty from the
    fetch as well as the build, so one knob controls both policy and API
    spend. Order (highest first) is preserved."""
    factors = _scale_factors(difficulty_scale)
    return tuple(d for d in candidates
                 if factors.get(_DIFFICULTY_NAMES.get(d, ""), 1.0) > 0)


def _scale_zone_characters(characters, factors, default_tier):
    """One zone's raw character map -> the scaled, headline-carrying map the
    layer ships. Shared by the main tier and every extra zone (bonus raids
    like Sporefall), so all zones obey identical rules:

    * The sweep fetches EVERY enabled difficulty per character (the site
      shows mythic and heroic side by side), nested under by_difficulty.
      A pre-rework cache entry is flat (one difficulty at top level); it
      is normalized into the same nest so one code path serves both until
      the next credentialed refresh rewrites the cache.
    * The difficulty discount: raw stays raw, rankings read the scaled
      value. Percentiles live on 0-100, so the scaled value is capped
      there (a factor > 1 can reward mythic but never mint a 101). A
      factor of 0 EXCLUDES the difficulty: its sub-entry is dropped ("no
      logs yet" on the site, never a 0.0% row) and sweep_difficulties()
      stops the fetch querying it. The raw cache keeps everything, so
      re-enabling later is loss-free.
    * Headline = the difficulty with the best SCALED value (the whole
      point of the factors: a heroic 95 at x0.8 loses to a mythic 80).
      Raw + scaled + difficulty stay one coherent triple from the same
      winning sub-entry.
    """
    out = {}
    for key, entry in (characters or {}).items():
        bd = entry.get("by_difficulty")
        if not bd:
            legacy_name = _DIFFICULTY_NAMES.get(entry.get("difficulty"), "")
            sub = {k: entry[k] for k in
                   ("best_perf_avg", "median_perf_avg", "by_role") if k in entry}
            bd = {legacy_name: sub} if legacy_name and sub else {}

        scaled_bd = {}
        for diff_name, sub in bd.items():
            factor = factors.get(diff_name, 1.0)
            raw = (sub or {}).get("best_perf_avg")
            if factor <= 0 or raw is None:
                continue
            s = dict(sub)
            s["scaled_perf_avg"] = round(min(raw * factor, 100.0), 1)
            s["difficulty_scale"] = factor
            scaled_bd[diff_name] = s
        if not scaled_bd:
            continue

        best_name, best_sub = max(scaled_bd.items(),
                                  key=lambda kv: kv[1]["scaled_perf_avg"])
        e = {
            "name": entry.get("name") or "",
            "key": key,
            "class": entry.get("class") or "",
            "best_perf_avg": best_sub["best_perf_avg"],
            "scaled_perf_avg": best_sub["scaled_perf_avg"],
            "difficulty": _DIFFICULTY_IDS.get(best_name),
            "difficulty_scale": best_sub["difficulty_scale"],
            "by_role": best_sub.get("by_role") or {},
            "by_difficulty": scaled_bd,
            # Every entry names the tier it was measured in, so a row copied
            # out of this file stays self-describing across season boundaries.
            "tier": entry.get("tier") or default_tier,
            "sourced_at": entry.get("sourced_at"),
        }
        if best_sub.get("median_perf_avg") is not None:
            e["median_perf_avg"] = best_sub["median_perf_avg"]
        out[key] = e
    return out


def build_parses(parses_fetched=None, season=None, difficulty_scale=None):
    """Per-character current-tier Warcraft Logs parse data — the axis the
    Four Emperors ranking, standings parse columns and the newspaper's raid
    sections read.

    parses_fetched: the dict from parses_cache.json (written by
    scripts/refresh_parses.py in the credentialed Action), or None. Warcraft
    Logs credentials exist only in CI, so locally this degrades to a stable
    empty shape with available:false — the front-end can build every parse
    surface against it and it fills the moment the credentialed refresh runs.

    difficulty_scale: config.yml's parses.difficulty_scale ({"mythic": 1.0,
    "heroic": 0.8, ...}), or None for no scaling. Each character keeps their
    RAW best_perf_avg and gains scaled_perf_avg = raw x the factor for the
    difficulty their parses came from (capped at 100). Rankings consume the
    scaled value; displays can show the raw one. Applied here at build time
    — never at fetch time — so retuning a factor in config.yml only needs a
    bundle rebuild, not a re-pull, and the cache stays raw truth.

    Characters are keyed by the FULL name-realm key ("amrevenge-stormrage",
    exact Unicode). Never bare names: board_state's bare-name season_scores
    keying is a documented data-destroying bug for same-named characters on
    different realms, and this layer must not repeat it.
    """
    season = season or season_mod.CURRENT_SEASON
    fetched = parses_fetched or {}
    characters = fetched.get("characters") or {}
    factors = _scale_factors(difficulty_scale)

    if not characters:
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _now_iso(),
            "available": False,
            "status": "pending_credentials",
            "source": "Warcraft Logs character zoneRankings",
            "detail": "No parse cache yet — the credentialed Action "
                      "(scripts/refresh_parses.py) has not run. Raider.io "
                      "does not expose parse percentiles, so this layer "
                      "fills only from Warcraft Logs.",
            "season": {"slug": season["slug"], "name": season["name"]},
            "tier": None,
            "sourced_at": None,
            "characters": {},
            "character_count": 0,
            "extra_zones": {},
            "zones_swept": [],
        }

    tier = fetched.get("tier") or {}
    out_chars = _scale_zone_characters(characters, factors, tier)

    # Bonus raids swept alongside the tier (season.py extra_raids — e.g.
    # Sporefall/Rotmire). Same scaling, own block: these must never bleed
    # into the main characters map, because the Emperor Index and every
    # main-layer sort are current-tier stats.
    extra_out = {}
    for slug, zone in (fetched.get("extra_zones") or {}).items():
        zone_tier = {"zone_id": (zone or {}).get("zone_id"),
                     "name": (zone or {}).get("name")}
        zchars = _scale_zone_characters((zone or {}).get("characters"),
                                        factors, zone_tier)
        extra_out[slug] = {
            "zone_id": zone_tier["zone_id"],
            "name": zone_tier["name"],
            "characters": zchars,
            "character_count": len(zchars),
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "available": True,
        "status": "ok",
        "source": "Warcraft Logs character zoneRankings",
        "season": {"slug": season["slug"], "name": season["name"]},
        "tier": tier,
        "sourced_at": fetched.get("last_updated"),
        # Provenance: the factors this build applied (config.yml ->
        # parses.difficulty_scale), so a reader can tell a tuned bundle
        # from an unscaled one without diffing configs.
        "difficulty_scale": factors,
        "characters": out_chars,
        "character_count": len(out_chars),
        # Bonus raids (season.py extra_raids), each its own character map —
        # e.g. extra_zones.sporefall for the Rotmire newspaper section.
        # Never merged into `characters`: the Emperor Index is tier-only.
        "extra_zones": extra_out,
        # Which WCL zones the sweep actually covered (run provenance, from
        # the refresh script) — a raid missing downstream is diagnosable
        # from the data itself.
        "zones_swept": fetched.get("zones_swept") or [],
    }


# ---------------------------------------------------------------------------
# Assembler
# ---------------------------------------------------------------------------

def build_site_data(board_state=None, manifest=None, dungeon_bests=None,
                    raid_progression=None, guild_achievements=None,
                    transmog_snapshot=None, pulse_items=None,
                    competition_fetched=None, parses_fetched=None,
                    difficulty_scale=None, guild=None, season=None,
                    roster=None):
    """Assemble every layer into one envelope for the front-end.

    Any input may be omitted; the corresponding layer degrades to its
    documented empty/pending shape rather than raising, so a partial data
    refresh still produces a valid site_data.json.

    roster: the roster cache entries (name-realm). Only the weekly board uses
    it, and only to turn Warcraft Logs' bare names into character keys —
    omitting it leaves the keyed maps empty and says so, it never invents.
    """
    from guild_board.competition import build_competition
    season = season or season_mod.CURRENT_SEASON
    transmog = build_transmog_changes(manifest, snapshot=transmog_snapshot)
    # Guild achievements feed BOTH layer 3 (trophy hall) and layer 4 (the
    # authoritative per-boss raid kills), so extract the boss kills once here.
    confirmed_boss_kills = extract_raid_boss_kills(guild_achievements, season=season)
    # Parses feed their own layer AND the competition characters' parse
    # field (the Emperor Index's second axis), so build the envelope once.
    parses = build_parses(parses_fetched, season=season,
                          difficulty_scale=difficulty_scale)
    site = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "guild": guild or {"name": "Skill Issues",
                           "realm": "bleeding-hollow", "region": "us"},
        "season": {"slug": season["slug"], "name": season["name"]},
        "recap_ribbon": build_recap_ribbon(board_state, transmog_changes=transmog),
        "records_leaderboard": build_records_leaderboard(board_state),
        "weekly_board": build_weekly_board(board_state, roster=roster),
        "guild_achievements": build_guild_achievements(guild_achievements, season=season),
        "island_completion": build_island_completion(
            dungeon_bests, raid_progression,
            (board_state or {}).get("records"), season=season,
            confirmed_boss_kills=confirmed_boss_kills),
        "transmog_changes": transmog,
        "guild_pulse": build_guild_pulse(pulse_items),
        "competition": build_competition(competition_fetched, board_state,
                                         season=season, wcl_parses=parses),
        "parses": parses,
    }
    site["parity"] = build_parity_map(site)
    return site


# Every field the weekly Discord guild board posts, mapped to where the
# website serves it. This is the data-backed DATA PARITY FLOOR: the site must
# show all of it, plus more. `state` is one of:
#   live      real data flowing now
#   partial   some data now, fuller with credentials (parses)
#   pending   structurally present but needs a credentialed refresh to fill
# The front-end can iterate this to guarantee no section renders dead.
_PARITY_SPEC = [
    ("guild_announcement", "records_leaderboard/guild_pulse", "Discord announcement channel (needs Discord bot access)"),
    ("guild_standing", "records_leaderboard.standing", None),
    ("overall_realm_rank", "records_leaderboard.standing", None),
    ("rank_movement", "records_leaderboard.standing_delta", "the arrow beside each rank tile"),
    ("mplus_weekly_keys", "weekly_board.keys / competition.key_records", None),
    ("mplus_season_scores", "competition.rankings", None),
    ("mplus_season_parses", "competition.characters[].best_runs", None),
    ("top_dps_parses", "weekly_board.parses.dps / competition.parses.leaders", "full weekly list needs Warcraft Logs enrichment"),
    ("top_healing_parses", "weekly_board.parses.hps / competition.parses.leaders", "full weekly list needs WCL creds"),
    ("top_tank_parses", "weekly_board.parses.tanks / competition.parses", "needs WCL creds"),
    ("mplus_weekly_parses", "weekly_board.mplus_parses", "needs WCL creds"),
    ("wipes_and_repair", "weekly_board.wipes / .repair_estimate", "needs WCL creds"),
    ("weekly_raid_boss_ranks", "island_completion.raid", "WCL realm/region ranks need WCL creds"),
    ("raid_progression", "island_completion.raid", None),
    ("most_deaths", "weekly_board.deaths", "needs WCL creds"),
    ("most_improved", "weekly_board.improvement / competition.movement", None),
    ("iron_attendance", "weekly_board.attendance / .streaks_by_key",
     "season raid weeks per character key; the bare-name .streaks map is kept "
     "alongside for consumers that have not switched"),
    ("roast_of_the_week", "weekly_board.roast", "the officer's roast, carried from the weekly run"),
    ("guild_achievements", "guild_achievements", "needs BLIZZARD creds"),
]


def build_parity_map(site):
    """Report, per Discord-board field, where the site serves it and whether
    it's live/partial/pending — so nothing renders as a dead section."""
    comp = site.get("competition") or {}
    standing = (site.get("records_leaderboard") or {}).get("standing")
    raid = (site.get("island_completion") or {}).get("raid") or {}
    ach = site.get("guild_achievements") or {}
    parses = comp.get("parses") or {}
    week = site.get("weekly_board") or {}
    rl = site.get("records_leaderboard") or {}

    def _state(field):
        if field == "guild_standing" or field == "overall_realm_rank":
            return "live" if standing else "pending"
        if field == "rank_movement":
            return "live" if rl.get("standing_delta") else "pending"
        if field == "mplus_weekly_keys":
            if week.get("keys"):
                return "live"
            return "partial" if comp.get("available") else "pending"
        if field in ("mplus_season_scores", "mplus_season_parses"):
            return "live" if comp.get("available") else "pending"
        if field == "most_improved":
            if (week.get("improvement") or {}):
                return "live"
            return "partial" if comp.get("available") else "pending"
        if field == "raid_progression":
            return "live" if raid.get("total_bosses") else "pending"
        if field in ("top_dps_parses", "top_healing_parses", "top_tank_parses"):
            role = {"top_dps_parses": "dps", "top_healing_parses": "hps",
                    "top_tank_parses": "tanks"}[field]
            if (week.get("parses") or {}).get(role):
                return "live"
            if parses.get("available") == "full":
                return "live"
            return "partial" if parses.get("leaders") else "pending"
        if field == "mplus_weekly_parses":
            return "live" if (week.get("mplus_parses") or {}) else "pending"
        if field == "wipes_and_repair":
            return "live" if week.get("wipes") is not None else "pending"
        if field == "most_deaths":
            return "live" if (week.get("deaths") or {}) else "pending"
        if field == "iron_attendance":
            if week.get("attendance"):
                return "live"
            # Streaks without the season attendance behind them are one
            # integer per bare name: real, but not the keyed ingestion the
            # ledger needs.
            return "partial" if (week.get("streaks") or {}) else "pending"
        if field == "roast_of_the_week":
            return "live" if (week.get("roast") or {}).get("roast") else "pending"
        if field == "guild_achievements":
            return "live" if ach.get("available") else "pending"
        if field == "weekly_raid_boss_ranks":
            return "pending"
        if field == "guild_announcement":
            return "pending"
        return "pending"

    fields = []
    for field, where, note in _PARITY_SPEC:
        fields.append({"field": field, "served_by": where,
                       "state": _state(field), "note": note})
    live = sum(1 for f in fields if f["state"] == "live")
    return {
        "schema_version": SCHEMA_VERSION,
        "summary": {"live": live,
                    "partial": sum(1 for f in fields if f["state"] == "partial"),
                    "pending": sum(1 for f in fields if f["state"] == "pending"),
                    "total": len(fields)},
        "fields": fields,
    }

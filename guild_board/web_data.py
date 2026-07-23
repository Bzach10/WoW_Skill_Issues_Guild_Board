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

build_site_data() assembles all five into one envelope.
"""

from datetime import datetime, timezone

from guild_board import season as season_mod

SCHEMA_VERSION = 1


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


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

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "based_on": current.get("last_updated"),
        "standing": current.get("standing"),
        "headline_records": headline,
        "ladder": ladder,
        "ladder_size": len(ladder),
        "sortable_by": ["score", "delta_week", "streak_weeks", "rank"],
    }


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
            "detail": "Blizzard guild-achievements API returned no data — "
                      "run scripts/refresh_blizzard_profiles.py with "
                      "BLIZZARD_CLIENT_ID/SECRET set, then rebuild.",
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
# Assembler
# ---------------------------------------------------------------------------

def build_site_data(board_state=None, manifest=None, dungeon_bests=None,
                    raid_progression=None, guild_achievements=None,
                    transmog_snapshot=None, pulse_items=None,
                    competition_fetched=None, guild=None, season=None):
    """Assemble every layer into one envelope for the front-end.

    Any input may be omitted; the corresponding layer degrades to its
    documented empty/pending shape rather than raising, so a partial data
    refresh still produces a valid site_data.json.
    """
    from guild_board.competition import build_competition
    season = season or season_mod.CURRENT_SEASON
    transmog = build_transmog_changes(manifest, snapshot=transmog_snapshot)
    # Guild achievements feed BOTH layer 3 (trophy hall) and layer 4 (the
    # authoritative per-boss raid kills), so extract the boss kills once here.
    confirmed_boss_kills = extract_raid_boss_kills(guild_achievements, season=season)
    site = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "guild": guild or {"name": "Skill Issues",
                           "realm": "bleeding-hollow", "region": "us"},
        "season": {"slug": season["slug"], "name": season["name"]},
        "recap_ribbon": build_recap_ribbon(board_state, transmog_changes=transmog),
        "records_leaderboard": build_records_leaderboard(board_state),
        "guild_achievements": build_guild_achievements(guild_achievements, season=season),
        "island_completion": build_island_completion(
            dungeon_bests, raid_progression,
            (board_state or {}).get("records"), season=season,
            confirmed_boss_kills=confirmed_boss_kills),
        "transmog_changes": transmog,
        "guild_pulse": build_guild_pulse(pulse_items),
        "competition": build_competition(competition_fetched, board_state, season=season),
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
    ("guild_announcement", "records_leaderboard/guild_pulse", "Discord announcement channel (needs DISCORD_BOT_TOKEN)"),
    ("guild_standing", "records_leaderboard.standing", None),
    ("overall_realm_rank", "records_leaderboard.standing", None),
    ("mplus_weekly_keys", "competition.key_records", None),
    ("mplus_season_scores", "competition.rankings", None),
    ("mplus_season_parses", "competition.characters[].best_runs", None),
    ("top_dps_parses", "competition.parses.leaders", "full weekly list needs WCL_CLIENT_ID/SECRET"),
    ("top_healing_parses", "competition.parses.leaders", "full weekly list needs WCL creds"),
    ("top_tank_parses", "competition.parses", "needs WCL creds"),
    ("weekly_raid_boss_ranks", "island_completion.raid", "WCL realm/region ranks need WCL creds"),
    ("raid_progression", "island_completion.raid", None),
    ("most_deaths", "competition (pending)", "needs WCL creds"),
    ("most_improved", "competition.movement", None),
    ("roast_of_the_week", "guild_pulse (pending)", "needs DISCORD_BOT_TOKEN"),
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

    def _state(field):
        if field == "guild_standing" or field == "overall_realm_rank":
            return "live" if standing else "pending"
        if field in ("mplus_weekly_keys", "mplus_season_scores",
                     "mplus_season_parses", "most_improved"):
            return "live" if comp.get("available") else "pending"
        if field == "raid_progression":
            return "live" if raid.get("total_bosses") else "pending"
        if field in ("top_dps_parses", "top_healing_parses", "top_tank_parses"):
            return "partial" if parses.get("leaders") else "pending"
        if field == "guild_achievements":
            return "live" if ach.get("available") else "pending"
        if field == "weekly_raid_boss_ranks" or field == "most_deaths":
            return "pending"
        if field in ("roast_of_the_week", "guild_announcement"):
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

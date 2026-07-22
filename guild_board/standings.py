"""The Standings — the guild's competition data, at or above board parity.

The weekly Discord board posts: top DPS/HPS/all-role parses, weekly timed
keys, season M+ scores, best season runs, most-improved, weekly boss
ranks, records, awards (attendance / biggest climb) and the realm/region/
world standing. This assembles the same fields for the website — from
`board_state.json` (season scores, records, streaks, standing) and the
real `voyage_data.json` (guild raid progression + guild-best dungeon keys,
no-auth Raider.io) — and reads the pipeline's `web_stats.json` for the
WCL-derived parse ladders when a data refresh has produced it.

Nothing here is hand-kept; a daily refresh carries straight through.
"""

import logging

from .showcase import slugify

logger = logging.getLogger(__name__)


def _title(name):
    return (name or "").strip().replace("-", " ").title()


def _season_ladder(board_state):
    scores = (board_state or {}).get("season_scores") or {}
    baseline = ((board_state or {}).get("baseline") or {}).get("season_scores") or {}
    streaks = (board_state or {}).get("streaks") or {}
    rows = []
    for name, score in sorted(scores.items(), key=lambda kv: -kv[1]):
        prev = baseline.get(name)
        rows.append({
            "name": _title(name), "slug": name, "score": score,
            "delta": round(score - prev, 1) if prev is not None else None,
            "streak": streaks.get(name),
        })
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


def _dungeon_keys(voyage_data):
    """The guild's best timed key per dungeon — real, from Raider.io."""
    dungeons = (voyage_data or {}).get("dungeons") or {}
    out = []
    for dungeon, run in dungeons.items():
        if not run:
            continue
        out.append({
            "dungeon": dungeon,
            "level": run.get("level"),
            "holder": run.get("name"),
            "realm": _title(run.get("realm")),
            "score": run.get("score"),
            "time": _fmt_time(run.get("clear_time_ms")),
        })
    out.sort(key=lambda d: (-(d.get("level") or 0), -(d.get("score") or 0)))
    return out


def _fmt_time(ms):
    if not ms:
        return None
    total = int(ms // 1000)
    return f"{total // 60}:{total % 60:02d}"


def _raid(voyage_data, cfg=None):
    """Guild raid progression for the active tier — bosses by difficulty."""
    rp = (voyage_data or {}).get("raid_progression") or {}
    if not rp:
        return None
    # the tier with the most kills is the one we're actually on
    def killed(v):
        return (v or {}).get("mythic_bosses_killed", 0) * 100 + \
               (v or {}).get("heroic_bosses_killed", 0)
    slug, prog = max(rp.items(), key=lambda kv: killed(kv[1]))
    total = prog.get("total_bosses") or 0
    return {
        "slug": slug,
        "summary": prog.get("summary"),
        "total": total,
        "normal": prog.get("normal_bosses_killed", 0),
        "heroic": prog.get("heroic_bosses_killed", 0),
        "mythic": prog.get("mythic_bosses_killed", 0),
        "bosses": (voyage_data or {}).get("bosses") or {},
    }


def _roster_names(roster):
    """The set of real character names, from roster_cache's `name-realm`
    keys. Returns None when no roster was supplied, which disables the
    membership check entirely (callers that cannot supply one keep the
    old behaviour)."""
    if not roster:
        return None
    names = set()
    for entry in roster:
        if not isinstance(entry, str):
            entry = (entry or {}).get("name") or ""
        # `name-realm` — realm slugs carry the hyphens, names do not
        name = entry.split("-")[0].strip().lower()
        if name:
            names.add(name)
    return names or None


def _parses(board_state, web_stats, roster=None):
    """Top parse ladders. Full top-5 come from the pipeline's web_stats
    (WCL) when present; otherwise the season's record holder anchors each,
    so the field is never blank.

    A parse holder who is not in the roster is **logged, never dropped.**

    An earlier revision of this function silently suppressed such rows, on
    the theory that an off-roster name must be fabricated. That was wrong
    and it cost a real person their record: Phyrthepali is a real Holy
    Paladin in Skill Issues on Bleeding Hollow with a genuine 96 on
    Imperator Averzian (Warcraft Logs, 2026-07-19, 166,925.6 HPS), and he
    is simply **missing from `competition.json`'s roster pull.** Absence
    from a derived roster is evidence that the roster is incomplete, not
    that the person does not exist — and suppressing the row turns a
    fixable data gap into a member's achievement quietly disappearing off
    the front page, which is the worse failure.

    So: surface the mismatch to whoever runs the build, and render the row.
    """
    records = (board_state or {}).get("records") or {}
    ws = web_stats or {}
    known = _roster_names(roster)

    def check(name):
        """Log an off-roster parse holder. Never changes what is rendered."""
        if known is None or not name:
            return
        if str(name).split("-")[0].strip().lower() not in known:
            logger.warning(
                "Parse holder %r is not in the roster cache — the roster pull "
                "is probably stale or incomplete. Rendering the row anyway; "
                "refresh the roster rather than dropping the record.", name)

    def ladder(key, record_key, label):
        rows = ws.get(key) or []
        if rows:
            for r in rows[:5]:
                check(r.get("name"))
            return {"rows": rows[:5], "source": "wcl", "label": label}
        rec = records.get(record_key) or {}
        if rec.get("parse"):
            check(rec.get("name"))
            return {"rows": [{
                "name": _title(rec.get("name")), "value": rec["parse"],
                "detail": " · ".join(b for b in (rec.get("boss"), rec.get("spec")) if b),
            }], "source": "record", "label": label}
        # Nothing to show. Say why, if the pipeline told us — an unexplained
        # em-dash reads as "the site is broken" when the truth is usually
        # "Warcraft Logs credentials are unset" or "no tank parse recorded
        # yet this season". Both are fixable; neither is visible as a dash.
        return {"rows": [], "source": None, "label": label,
                "unavailable_reason": ws.get("reason") or
                ("No season record for this role yet." if records
                 else "No parse data has reached the site yet.")}

    return {
        "dps": ladder("top_dps", "best_dps_parse", "Top DPS parses"),
        "hps": ladder("top_hps", "best_hps_parse", "Top healing parses"),
        "tanks": ladder("top_tanks", None, "Top tank parses"),
    }


def parallel_ladders(season_ladder):
    """Four boards so the light isn't only on the top five parsers — the
    elite, the climbers, the ever-present, and the new blood. Between them
    they rank a big slice of the roster, not just the podium."""
    scored = [r for r in season_ladder if r.get("score") is not None]
    risers = sorted((r for r in scored if r.get("delta") and r["delta"] > 0),
                    key=lambda r: -r["delta"])[:5]
    attendance = sorted((r for r in scored if (r.get("streak") or 0) >= 2),
                        key=lambda r: (-(r["streak"]), r["rank"]))[:5]
    # "New blood" = the lowest scored who are still on the board — the
    # opposite end from Top Bounty, so a different five get their name up.
    rookies = list(reversed(sorted(scored, key=lambda r: r["score"])[:5]))
    return [
        {"key": "bounty", "icon": "💰", "title": "Top Bounty",
         "note": "highest Mythic+ scores", "unit": "score",
         "rows": scored[:5]},
        {"key": "riser", "icon": "📈", "title": "Biggest Risers",
         "note": "climbed most this week", "unit": "delta",
         "rows": risers},
        {"key": "iron", "icon": "⚓", "title": "Iron Attendance",
         "note": "most weeks on deck", "unit": "streak",
         "rows": attendance},
        {"key": "rookie", "icon": "🌊", "title": "New Blood",
         "note": "earning their stripes", "unit": "score",
         "rows": rookies},
    ]


def build(board_state, voyage_data=None, web_stats=None, cfg=None, roster=None):
    bs = board_state or {}
    ladder = _season_ladder(bs)
    climbers = [r for r in ladder if r["delta"]]
    biggest_climb = max(climbers, key=lambda r: r["delta"], default=None)
    iron = max((r for r in ladder if r["streak"]),
               key=lambda r: r["streak"], default=None)
    records = bs.get("records") or {}
    return {
        "standing": bs.get("standing") or {},
        "season_ladder": ladder,
        "season_count": len(ladder),
        "dungeon_keys": _dungeon_keys(voyage_data),
        "raid": _raid(voyage_data, cfg),
        "parses": _parses(bs, web_stats, roster),
        "records": records,
        "biggest_climb": biggest_climb,
        "iron_attendance": iron,
        "ladders": parallel_ladders(ladder),
        "has_web_stats": bool(web_stats),
    }

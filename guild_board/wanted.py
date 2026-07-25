"""The Wanted Board — the guild's leaderboard as One Piece bounty posters.

Every crewmate is a WANTED poster and their BOUNTY is their Mythic+ score:
the competition number that founded the guild, shown plainly. The original
board was a top-5, so the five biggest bounties get hero framing and the
whole crew ranks below.

Pure function of `board_state.json` + the crew, so a daily data refresh
just re-runs it — no hand-maintained numbers anywhere.
"""

from pathlib import Path

from .showcase import slugify

# The art pipeline bakes a finished 900×1350 WebP bounty poster per slug
# (gold "MOST WANTED" for the top 5, standard, or "BOUNTY UNCONFIRMED" for
# the scoreless). When present we ship the baked bill instead of the live
# CSS card — it's the version Zach approved. Bundled at bounty/<slug>.webp.
BOUNTY_DIR = Path("bounty")


def baked_poster(slug):
    """The bundled path to a slug's baked poster, or None if not baked."""
    if slug and (BOUNTY_DIR / f"{slug}.webp").exists():
        return f"bounty/{slug}.webp"
    return None


# A bounty poster reads better with a round, weighty figure. The real M+
# score is the truth we show; the "berry" figure is that score scaled into
# bounty-sized numerals so the poster lands like a real wanted bill.
BERRY_PER_POINT = 100_000


def _slug(name):
    return slugify(name or "")


def _record_titles(records):
    """slug -> [title, ...] for the crew who hold a season record."""
    out = {}

    def add(slug, title):
        if slug:
            out.setdefault(slug, []).append(title)

    key = records.get("highest_timed_key") or {}
    if key.get("level"):
        add(_slug(key.get("name")), f"Deepest Key +{key['level']}")
    dps = records.get("best_dps_parse") or {}
    if dps.get("parse"):
        add(_slug(dps.get("name")), f"Sharpest Parse · {dps['parse']}")
    hps = records.get("best_hps_parse") or {}
    if hps.get("parse"):
        add(_slug(hps.get("name")), f"Kept Us Alive · {hps['parse']}")
    return out


def board(crew, board_state, cfg=None):
    """The whole wanted board: ranked entries, the top-5, and the headline
    competition numbers, all derived from board_state."""
    bs = board_state or {}
    scores = bs.get("season_scores") or {}
    baseline = (bs.get("baseline") or {}).get("season_scores") or {}
    streaks = bs.get("streaks") or {}
    records = bs.get("records") or {}
    titles = _record_titles(records)

    entries = []
    for m in crew or []:
        if m.get("parked"):
            # Unresolved members (page exists, membership unconfirmed) do
            # not get a bounty and do not count toward the crew.
            continue
        slug = m.get("slug")
        # board_state data is keyed by bare name; only an unambiguous
        # name may match it (two crewmates share a name — see crew.py).
        state_key = m.get("legacy_slug", slug)
        score = m.get("score")
        if score is None and state_key:
            score = scores.get(state_key)
        prev = baseline.get(state_key) if state_key else None
        delta = (round(score - prev, 1)
                 if (score is not None and prev is not None) else None)
        art = m.get("art") or {}
        src = art.get("src") if isinstance(art, dict) else None
        entries.append({
            "slug": slug,
            "name": m.get("name"),
            "role": m.get("role"),
            "role_label": m.get("role_label"),
            "cls": m.get("cls"),
            "spec": m.get("spec"),
            "score": score,
            "bounty": int(round(score * BERRY_PER_POINT)) if score is not None else None,
            "delta": delta,
            "streak": streaks.get(state_key) if state_key else None,
            "art": src,
            "pending": not src,
            "titles": titles.get(slug, []),
            "baked": baked_poster(slug),
        })

    scored = sorted((e for e in entries if e["score"] is not None),
                    key=lambda e: -e["score"])
    unscored = sorted((e for e in entries if e["score"] is None),
                      key=lambda e: (e["name"] or "").lower())
    for i, e in enumerate(scored):
        e["rank"] = i + 1
    for e in unscored:
        e["rank"] = None

    climbers = [e for e in scored if e["delta"]]
    biggest_climb = max(climbers, key=lambda e: e["delta"], default=None)
    longest_streak = max((e for e in scored if e["streak"]),
                         key=lambda e: e["streak"], default=None)

    return {
        "entries": scored + unscored,
        "top5": scored[:5],
        "rest": scored[5:] + unscored,
        "ranked_count": len(scored),
        "total_count": len(scored) + len(unscored),
        "biggest_climb": biggest_climb,
        "longest_streak": longest_streak,
        "records": records,
        "berry_per_point": BERRY_PER_POINT,
    }

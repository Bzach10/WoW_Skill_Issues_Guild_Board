#!/usr/bin/env python3
"""Render the public crew board (layout: crew_deck) from the real data
already on disk — no network, no credentials, no CI required.

    python scripts/render_crew_board.py [--out site/index.html]

Reads: config.yml, theme.yml, board_state.json, roster_cache.json, and
(when the art workstream has produced them) blizzard_profile_cache.json
and cast/<slug>/*.png.

Every input is optional. Anything missing degrades to a labelled
placeholder rather than failing the render — a board that is partly
stubbed is still a board.
"""

import argparse
import json
import logging
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import jinja2  # noqa: E402

from guild_board import crew as crew_mod  # noqa: E402
from guild_board import links as links_mod  # noqa: E402
from guild_board import profiles as profiles_mod  # noqa: E402
from guild_board import theme as theme_mod  # noqa: E402
from guild_board import html_board  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("render_crew_board")

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "guild_board" / "templates"

# Every family the three themes can ask for, in one request.
FONT_CSS_URL = (
    "https://fonts.googleapis.com/css2"
    "?family=Cinzel+Decorative:wght@400;700;900"
    "&family=Inter:wght@400;600;700;900"
    "&family=JetBrains+Mono:wght@400;700"
    "&display=swap"
)


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        logger.info("%s unavailable (%s); continuing without it.", path, exc)
        return default


def _load_cfg(path="config.yml"):
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("config.yml unreadable (%s); using defaults.", exc)
        return {}


def _embers(seed=7, n=22):
    rng = random.Random(seed)
    return [{
        "left": round(rng.uniform(0, 100), 2),
        "dx": rng.randint(-90, 90),
        "size": rng.choice([2, 3, 3, 4, 5]),
        "dur": round(rng.uniform(11, 26), 1),
        "delay": round(rng.uniform(0, 18), 1),
    } for _ in range(n)]


def _ladder(season_scores, roster, region, crew=None, top_n=12):
    """The real season M+ ladder, with a Raider.io profile link per player
    when the roster cache tells us their realm.

    `data-tags` feeds the shared interactive layer's role classifier. We
    emit a player's REAL spec/class only — never a guess — so a row we
    cannot classify simply carries no tag.
    """
    tags_by_slug = {}
    for member in (crew or []):
        if member.get("role") != "unknown":
            tags_by_slug[member["slug"]] = " ".join(
                x for x in (member.get("spec"), member.get("cls"),
                            member.get("role")) if x).lower()
    # Per-player realms via the shared resolver: the guild is cross-realm,
    # so a link built from the guild realm alone is wrong for most people.
    on_deck = {m["slug"] for m in (crew or [])}
    index = links_mod.realm_index(roster)
    rows = sorted(season_scores.items(), key=lambda kv: -kv[1])[:top_n]
    out = []
    for i, (slug, score) in enumerate(rows, start=1):
        # Link to the profile page we own when this player is on the deck;
        # otherwise fall back to their external profile.
        url = (profiles_mod.profile_href(slug) if slug in on_deck
               else links_mod.character_url(slug, index, region=region,
                                            site="raiderio"))
        out.append({"rank": i, "name": slug.title(), "score": score, "url": url,
                    "tags": tags_by_slug.get(slug, "")})
    return out


def _island_record_html(island):
    """Per-island data, rendered honestly: a real record, or 'no record yet'."""
    data = island.get("data")
    if not data:
        return '<span class="norec">No record yet — the crew hasn\'t claimed this one.</span>'
    if island["kind"] == "raid_boss":
        label = "Best DPS parse" if data.get("role") == "dps" else "Best HPS parse"
        spec = " ".join(x for x in (data.get("spec"), data.get("cls")) if x)
        return (f'{label}: <b>{data.get("parse")}</b> — {data.get("name")}'
                f'{f" ({spec})" if spec else ""}')
    spec = data.get("spec")
    suffix = f" ({spec})" if spec else ""
    return (f'Best timed key: <b>+{data.get("level")}</b> — '
            f'{data.get("name")}{suffix}')


def build_context(cfg, theme, board_state, roster, profiles=None,
                  manifest=None, style=None):
    season_scores = (board_state or {}).get("season_scores") or {}
    standing = (board_state or {}).get("standing") or None
    guild_cfg = cfg.get("guild") or {}
    region = (guild_cfg.get("region") or "us").lower()

    manifest = crew_mod.load_manifest() if manifest is None else manifest
    style = crew_mod.resolve_style(manifest, theme, override=style)

    crew = crew_mod.build_crew(cfg, theme, season_scores=season_scores,
                               profiles=profiles, manifest=manifest,
                               style=style)
    counts = crew_mod.role_counts(crew)

    scenes = crew_mod.resolve_scenes(theme)
    islands, current, voyage_real = crew_mod.load_islands(cfg, board_state)
    for island in islands:
        island["record_html"] = _island_record_html(island)
        island["scene"] = crew_mod.scene_for_island(island, scenes)
    current = current or (islands[0]["id"] if islands else None)
    current_island = next((i for i in islands if i["id"] == current), None)

    week_index = datetime.now(timezone.utc).isocalendar()[1]
    debt_raw = html_board._debt_card(theme, week_index)
    debt = None
    if debt_raw:
        debt = {
            "title": debt_raw["title"],
            "owed": f'{debt_raw["amount"]:,}',
            "note": debt_raw["interest_note"] or debt_raw["climbing_note"],
            "lines": debt_raw["lines"],
            "flavor": debt_raw["flavor"],
        }

    roast_cfg = (cfg.get("sections") or {}).get("roast_of_the_week") or {}
    roast = None
    if roast_cfg.get("enabled", True) and roast_cfg.get("roast"):
        roast = {"roast": roast_cfg["roast"],
                 "winner": roast_cfg.get("winner", "Anonymous"),
                 "target": roast_cfg.get("target") or ""}

    updated = (board_state or {}).get("last_updated") or ""
    if updated:
        try:
            updated = datetime.fromisoformat(updated).strftime("%b %d, %Y")
        except ValueError:
            pass

    stubbed = []
    with_art = [m for m in crew if m["art_is_real"]]
    if not manifest:
        stubbed.append("crew art (no cast_manifest.json yet — silhouette slots)")
    elif not with_art:
        stubbed.append("crew art (manifest present, but no usable cut-outs on disk yet)")
    elif len(with_art) < len(crew):
        stubbed.append(f"crew art for {len(crew) - len(with_art)} of {len(crew)} "
                       f"(the rest are rendered)")
    borrowed = [m["name"] for m in crew if m.get("style_is_fallback")]
    if borrowed:
        stubbed.append(f"style {style!r} missing for {', '.join(borrowed)} "
                       f"(showing their other style)")
    if not voyage_real:
        stubbed.append("voyage islands (sample chain — guild_board.voyage not on this branch)")
    if not any(i.get("data") for i in islands):
        stubbed.append("per-island records (only the raid bosses in board_state.json resolve offline)")

    return {
        "guild_name": guild_cfg.get("name") or "Skill Issues",
        "realm_label": f"{(guild_cfg.get('realm_slug') or '').replace('-', ' ').title()} · {region.upper()}",
        "gag_subtitle": (theme.get("motd_quips") or ["Git Gud."])[week_index % len(theme.get("motd_quips") or [1])],
        "credits": theme.get("credits") or "",
        "standing": standing,
        "updated": updated,
        "themes": crew_mod.resolve_themes(theme),
        "default_theme": crew_mod.default_theme_key(theme),
        "role_tint": crew_mod.ROLE_TINT,
        "font_css_url": FONT_CSS_URL,
        "embers": _embers(),
        "crew": crew,
        "counts": counts,
        "profile_href": {m["slug"]: profiles_mod.profile_href(m["slug"]) for m in crew},
        "active_style": style,
        "styles_available": manifest.get("styles_available") or [],
        "scenes": scenes,
        "opening_scene": (current_island["scene"] if current_island
                          else crew_mod.scene_for_island(None, scenes)),
        "islands": islands,
        "current_island": current,
        "current_island_name": current_island["name"] if current_island else "",
        "current_island_flavor": current_island.get("flavor", "") if current_island else "",
        "current_island_record": (current_island["record_html"] if current_island
                                  else '<span class="norec">No island selected.</span>'),
        "ladder": _ladder(season_scores, roster, region, crew=crew),
        "roast": roast,
        "debt": debt,
        "archive": [],   # week archive links are injected by CI's publish step
        "stub_note": ("Still stubbed: " + "; ".join(stubbed)) if stubbed else "",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="crew_board.html")
    ap.add_argument("--config", default="config.yml")
    ap.add_argument("--manifest", default=None,
                    help="Path to a cast_manifest.json (defaults to the one "
                         "in the working directory).")
    ap.add_argument("--style", default=None,
                    help="Preview a specific cast style instead of the "
                         "manifest's active_style (e.g. --style one_piece).")
    args = ap.parse_args()

    cfg = _load_cfg(args.config)
    theme = theme_mod.load_theme(theme_mod.THEME_FILE)
    board_state = _load_json("board_state.json", {})
    roster = (_load_json("roster_cache.json", {}) or {}).get("members") or []

    manifest = (crew_mod.load_manifest(args.manifest)
                if args.manifest else crew_mod.load_manifest())
    ctx = build_context(cfg, theme, board_state, roster,
                        manifest=manifest, style=args.style)

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=True,
    )
    html = env.get_template("web/crew_deck.html.j2").render(**ctx)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    # One permalink page per crew member. These are the real destination
    # for a player's name — the durable fix for links that used to point
    # at a guessed realm and open a blank page.
    profile_ctxs = profiles_mod.build_all(ctx["crew"], board_state, cfg, roster)
    profile_dir = out.parent / profiles_mod.PROFILE_DIR
    profile_dir.mkdir(parents=True, exist_ok=True)
    for pctx in profile_ctxs:
        page = env.get_template("web/pages/profile.html.j2").render(
            p=pctx, **{k: v for k, v in ctx.items() if k != "p"})
        (profile_dir / f"{pctx['slug']}.html").write_text(page, encoding="utf-8")
    logger.info("Wrote %d profile pages to %s/", len(profile_ctxs), profile_dir)
    logger.info("Wrote %s (%d crew, %d islands, %d ladder rows, style=%s, "
                "%d with real art)",
                out, len(ctx["crew"]), len(ctx["islands"]), len(ctx["ladder"]),
                ctx["active_style"] or "none",
                sum(1 for m in ctx["crew"] if m["art_is_real"]))
    if ctx["stub_note"]:
        logger.info(ctx["stub_note"])


if __name__ == "__main__":
    main()

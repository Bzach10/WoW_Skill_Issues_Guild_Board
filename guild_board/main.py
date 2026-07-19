import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import requests

from guild_board.config import load_config, require_env, resolve_roster, save_roster_cache
from guild_board.discord import post_to_discord
from guild_board.discord_inputs import fetch_latest_announcement, fetch_top_roast
from guild_board.filters import apply_roster_filters, make_name_filter
from guild_board.board_image import generate_board_animation, generate_board_image
from guild_board.formatters import build_embed, build_image_embed
from guild_board.images import generate_progress_image
from guild_board.raiderio import collect_mplus, collect_mplus_season_parses, collect_mplus_season_scores
from guild_board.state import advance_streaks, load_board_state, save_board_state, update_records
from guild_board.wcl import (
    DIFFICULTY_MAP,
    IMPROVEMENT_DIFFICULTIES,
    MPLUS_DIFFICULTY,
    clear_report_cache,
    collect_improvement_history,
    merge_improvement,
    collect_parses_only,
    collect_raid_stats,
    compute_improvement,
    detect_zone,
    fetch_guild_reports,
    fetch_guild_standing,
    fill_missing_parses,
    fetch_realm_rank_leaders,
    get_wcl_token,
    try_difficulties,
)

logger = logging.getLogger(__name__)


def _load_weekly_state(path="weekly_state.json"):
    """Load volatile weekly state (roast, roster overrides) if it exists."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _merge_state(cfg, state):
    """Merge weekly_state.json values into config."""
    if not state:
        return cfg
    roast = state.get("roast_of_the_week")
    if roast:
        cfg.setdefault("sections", {}).setdefault("roast_of_the_week", {}).update(roast)
        cfg.setdefault("roast_of_the_week", {}).update(roast)

    overrides = state.get("roster_overrides", {})
    if overrides:
        filters = cfg.setdefault("filters", {})
        include = set(filters.get("always_include", []))
        exclude = set(filters.get("always_exclude", []))
        include.update(overrides.get("always_include", []))
        exclude.update(overrides.get("always_exclude", []))
        filters["always_include"] = sorted(include)
        filters["always_exclude"] = sorted(exclude)
    return cfg


def _setup_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _apply_discord_inputs(cfg, start_ms):
    """Pull the voted roast and officer announcement from Discord channels.

    Everything fails open: a missing token, unset channel id, or API error
    just leaves the config/weekly_state values in place.
    """
    inputs_cfg = cfg.get("discord_inputs") or {}
    if not inputs_cfg.get("enabled", False):
        return

    bot_token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not bot_token:
        logger.warning("discord_inputs is enabled but DISCORD_BOT_TOKEN is not set; skipping.")
        return

    sections = cfg.setdefault("sections", {})

    roast_channels = inputs_cfg.get("roast_channel_ids") or inputs_cfg.get("roast_channel_id") or []
    if isinstance(roast_channels, (str, int)):
        roast_channels = [roast_channels]
    roast_channels = [str(c).strip() for c in roast_channels if str(c).strip()]
    manual = (sections.get("roast_of_the_week") or {}).get("manual_override")
    if roast_channels and not manual:
        try:
            top = fetch_top_roast(
                bot_token, roast_channels, start_ms,
                vote_emoji=inputs_cfg.get("vote_emoji", "\U0001F525"),
                min_votes=int(inputs_cfg.get("min_votes", 1)),
            )
            if top:
                logger.info("Roast voted from Discord: %s vote(s), by %s", top["votes"], top["winner"])
                update = {"roast": top["roast"], "winner": top["winner"], "target": top["target"]}
                sections.setdefault("roast_of_the_week", {}).update(update)
                cfg.setdefault("roast_of_the_week", {}).update(update)
            else:
                logger.info("No qualifying roast submissions in Discord this week.")
        except requests.RequestException as exc:
            logger.warning("Roast channel read failed: %s", exc)

    ann_channel = str(inputs_cfg.get("announcement_channel_id") or "").strip()
    if ann_channel:
        try:
            ann = fetch_latest_announcement(bot_token, ann_channel)
            if ann:
                logger.info("Announcement pulled from Discord (by %s)", ann["author"])
                sections.setdefault("announcement", {})["text"] = ann["text"]
            else:
                logger.info("No announcement message found in the Discord channel; using config text.")
        except requests.RequestException as exc:
            logger.warning("Announcement channel read failed: %s", exc)


def _collect_improvement(token, cfg, reports, stats, zone_id, roster_keep, end_ms):
    """Season-long Most Improved data plus season-best parse candidates.

    Returns (improvement, season_bests) where season_bests holds the
    highest parse per role seen anywhere in the season sweep — the Guild
    Records candidates, free of extra API calls."""
    sections = cfg.get("sections", {})
    imp_dps_cfg = sections.get("most_improved_dps", {})
    imp_heal_cfg = sections.get("most_improved_healers", {})
    if not stats or not (imp_dps_cfg.get("enabled", False) or imp_heal_cfg.get("enabled", False)):
        return None, None
    if zone_id is None:
        zone_id, _ = detect_zone(cfg, reports)
    try:
        keep = roster_keep or make_name_filter(token, cfg)
        min_days = int(imp_dps_cfg.get("min_days", imp_heal_cfg.get("min_days", 14)))
        per_diff_dps, per_diff_hps = [], []
        season_bests = {"dps": None, "hps": None}
        for diff in IMPROVEMENT_DIFFICULTIES:
            history = collect_improvement_history(token, cfg, zone_id, diff, end_ms)
            for role, bucket in (("dps", per_diff_dps), ("hps", per_diff_hps)):
                ranked = compute_improvement(history[role], min_span_days=min_days)
                for entry in ranked:
                    entry["difficulty"] = diff
                bucket.append(ranked)
                for name, samples in history[role].items():
                    if not keep(name):
                        continue
                    top = max(samples, key=lambda s: s.get("parse") or 0)
                    best = season_bests[role]
                    if best is None or (top.get("parse") or 0) > best["parse"]:
                        season_bests[role] = {
                            "name": name,
                            "parse": top.get("parse") or 0,
                            "boss": top.get("boss") or "",
                            "spec": top.get("spec") or "",
                            "cls": top.get("cls") or "",
                            "difficulty": diff,
                        }
        improvement = {}
        if imp_dps_cfg.get("enabled", False):
            ranked = [e for e in merge_improvement(*per_diff_dps) if keep(e["name"])]
            improvement["dps"] = ranked[:int(imp_dps_cfg.get("top_n", 5))]
        if imp_heal_cfg.get("enabled", False):
            ranked = [e for e in merge_improvement(*per_diff_hps) if keep(e["name"])]
            improvement["hps"] = ranked[:int(imp_heal_cfg.get("top_n", 5))]
        logger.info("Most Improved: %s DPS, %s healer(s)",
                    len(improvement.get("dps") or []),
                    len(improvement.get("hps") or []))
        return improvement, season_bests
    except (RuntimeError, requests.RequestException) as exc:
        logger.warning("Most Improved lookup failed; skipping the section: %s", exc)
        return None, None


def _collect_weekly_mplus(token, cfg, reports, roster_keep):
    """This week's M+ dungeon parses, or None when disabled/unavailable."""
    sections = cfg.get("sections", {})
    if not sections.get("mplus_weekly_parses", {}).get("enabled", True):
        return None
    try:
        mdps, mhps = collect_parses_only(token, cfg, reports, MPLUS_DIFFICULTY)
        if roster_keep:
            mdps = {n: v for n, v in mdps.items() if roster_keep(n)}
            mhps = {n: v for n, v in mhps.items() if roster_keep(n)}
        if mdps or mhps:
            logger.info("Weekly M+ parses: %s DPS, %s HPS", len(mdps), len(mhps))
        else:
            logger.info("No M+ dungeon logs found this week (players must upload M+ runs to WCL).")
        # Keep the dict even when empty so the board shows the section
        # title with a "no logs" placeholder instead of hiding it.
        return {"dps": mdps, "hps": mhps}
    except (RuntimeError, requests.RequestException) as exc:
        logger.warning("Weekly M+ parse lookup failed: %s", exc)
        return None


def build_board(cfg, start_dt=None, end_dt=None, preview=False, dry_run=False):
    """Collect data and build the Discord embed (and optionally post it)."""
    if start_dt is None or end_dt is None:
        lookback_days = int(cfg.get("lookback_days", 7))
        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(days=lookback_days)

    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    clear_report_cache()
    _apply_discord_inputs(cfg, start_ms)

    stats = None
    standing = None
    leaders = None
    zone_id = None
    zone_name = None
    no_logs = False
    token = None
    roster_keep = None

    sections = cfg.get("sections", {})
    mplus_cfg = sections.get("mplus") or cfg.get("mplus", {})
    mplus_season_scores_cfg = sections.get("mplus_season_scores") or {}
    mplus_season_parses_cfg = sections.get("mplus_season_parses") or sections.get("mplus_season_runs") or {}
    raid_enabled = cfg.get("raid", {}).get("enabled", True)

    mplus_enabled = mplus_cfg.get("enabled", False)
    mplus_auto_fetch = mplus_cfg.get("auto_fetch_roster", False)
    season_scores_auto_fetch = mplus_season_scores_cfg.get("auto_fetch_roster", False)
    season_parses_auto_fetch = mplus_season_parses_cfg.get("auto_fetch_roster", False)

    needs_token = (
        raid_enabled
        or (mplus_enabled and mplus_auto_fetch)
        or (mplus_season_scores_cfg.get("enabled", False) and season_scores_auto_fetch)
        or (mplus_season_parses_cfg.get("enabled", False) and season_parses_auto_fetch)
    )

    if needs_token:
        client_id = require_env("WCL_CLIENT_ID")
        client_secret = require_env("WCL_CLIENT_SECRET")
        token = get_wcl_token(client_id, client_secret)

    if raid_enabled:
        reports = fetch_guild_reports(token, cfg, start_ms, end_ms)

        if not reports:
            logger.info("No Warcraft Logs reports found in the lookback window.")
            no_logs = True
        else:
            logger.info("Found %s report(s) this week.", len(reports))

            sections = cfg.get("sections", {})
            raid_cfg = sections.get("top_dps") if sections else cfg.get("raid", {})
            use_fallback = raid_cfg.get("difficulty_fallback", True)

            if use_fallback:
                logger.info("Using difficulty fallback (mythic -> heroic -> normal)")
                stats, difficulty_used = try_difficulties(collect_raid_stats, cfg, token, reports)
                if stats:
                    logger.info("Using %s data", difficulty_used)
                    logger.info("Stats: %s DPS, %s HPS, %s kills, %s pulls",
                                len(stats.get("best_dps", {})),
                                len(stats.get("best_hps", {})),
                                stats.get("kills"),
                                stats.get("pulls"))
                else:
                    logger.info("No data found for any difficulty")
            else:
                logger.info("Using configured difficulty only")
                stats = collect_raid_stats(token, cfg, reports)
                if stats:
                    logger.info("Stats: %s DPS, %s HPS, %s kills, %s pulls",
                                len(stats.get("best_dps", {})),
                                len(stats.get("best_hps", {})),
                                stats.get("kills"),
                                stats.get("pulls"))
                else:
                    logger.info("No data found")

            if stats:
                # Filter pugs out FIRST, then backfill a metric the filter
                # emptied (e.g. all mythic healers were non-members) from a
                # lower difficulty — with the same filter applied.
                roster_keep = make_name_filter(token, cfg)
                stats = apply_roster_filters(token, cfg, stats, keep=roster_keep)
                stats = fill_missing_parses(token, cfg, reports, stats, keep=roster_keep)
                logger.info("After roster filters: %s DPS, %s HPS",
                            len(stats.get("best_dps", {})),
                            len(stats.get("best_hps", {})))
            else:
                logger.info("Stats is None, skipping roster filters")

            if (cfg.get("rankings") or {}).get("enabled", True):
                zone_id, zone_name = detect_zone(cfg, reports)
                if zone_id:
                    try:
                        standing = fetch_guild_standing(token, cfg, zone_id)
                        if standing:
                            logger.info("Guild standing retrieved: %s", standing)
                    except (RuntimeError, requests.RequestException) as exc:
                        logger.warning("Guild standing lookup failed: %s", exc)

                    if stats and stats.get("participants"):
                        if use_fallback:
                            logger.info("Using difficulty fallback for realm rank leaders")
                            leaders, diff_used = try_difficulties(
                                lambda token, cfg, reports, difficulty: fetch_realm_rank_leaders(
                                    token, cfg, stats["participants"], zone_id, difficulty
                                ),
                                cfg, token, reports
                            )
                            if leaders:
                                logger.info("Using %s data for realm rank leaders", diff_used)
                        else:
                            try:
                                leaders = fetch_realm_rank_leaders(
                                    token, cfg, stats["participants"], zone_id, stats["difficulty"]
                                )
                            except (RuntimeError, requests.RequestException) as exc:
                                logger.warning("Realm rank leaders lookup failed: %s", exc)
                else:
                    logger.info("Could not detect raid zone; skipping rankings section.")

            # Standing memory: WCL's lookup flakes sometimes — show last
            # week's rank labeled as such rather than dropping the tiles.
            if not standing or not any(standing.get(k) for k in ("realm", "region", "world")):
                prev_standing = (load_board_state().get("standing") or {})
                if prev_standing:
                    standing = {**prev_standing, "stale": True}
                    logger.info("Standing lookup empty; showing last week's ranks.")

    improvement = None
    season_parse_bests = None
    if raid_enabled:
        improvement, season_parse_bests = _collect_improvement(
            token, cfg, reports, stats, zone_id, roster_keep, end_ms)
    mplus_weekly = None
    if raid_enabled and not no_logs and token:
        mplus_weekly = _collect_weekly_mplus(token, cfg, reports, roster_keep)

    mplus_results = None
    mplus_season_scores = None
    mplus_season_parses = None

    if mplus_enabled:
        mplus_results = collect_mplus(cfg, token)

    sections = cfg.get("sections", {})
    mplus_season_scores_cfg = sections.get("mplus_season_scores", {})
    mplus_season_parses_cfg = sections.get("mplus_season_parses", {})

    if mplus_season_scores_cfg.get("enabled", False):
        mplus_season_scores = collect_mplus_season_scores(cfg, token)

    season_key_record = None
    if mplus_season_parses_cfg.get("enabled", False):
        mplus_season_parses, season_key_record = collect_mplus_season_parses(cfg, token)

    sections = cfg.get("sections", {})
    layout = (cfg.get("display") or {}).get("layout", "two_column")

    image_path = None
    previous = load_board_state()

    # Streaks: who was active in any weekly dataset this week
    active_names = set()
    if stats:
        active_names |= set(stats.get("best_dps") or {})
        active_names |= set(stats.get("best_hps") or {})
    for run in (mplus_results or []):
        active_names.add(run[2])
    if mplus_weekly:
        active_names |= set(mplus_weekly.get("dps") or {})
        active_names |= set(mplus_weekly.get("hps") or {})
    streaks = advance_streaks(previous.get("streaks"), active_names)

    # Season record book: weekly data plus the full-season sweeps, so
    # records reflect the entire season rather than weeks since launch
    records = update_records(previous.get("records"), stats, mplus_results,
                             season_parses=season_parse_bests,
                             season_key=season_key_record)

    if layout == "image_board":
        try:
            display_cfg = cfg.get("display") or {}
            board_args = (cfg, stats, standing, leaders, zone_name,
                          mplus_results, mplus_season_scores, mplus_season_parses,
                          start_dt, end_dt, no_logs)
            board_kwargs = dict(improvement=improvement, mplus_weekly=mplus_weekly,
                                previous=previous, streaks=streaks, records=records)
            if display_cfg.get("animate", False):
                image_path = generate_board_animation(
                    *board_args, output_path="board.gif",
                    frames=int(display_cfg.get("animate_frames", 10)), **board_kwargs)
            if not image_path:
                image_path = generate_board_image(
                    *board_args, output_path="board.png", **board_kwargs)
        except Exception as exc:
            logger.warning("Board image generation failed; falling back to text embed: %s", exc)
            # two_column is unreadable in Discord; fall back to plain fields.
            cfg.setdefault("display", {})["layout"] = "single_column"

    if image_path:
        embed = build_image_embed(cfg, stats, start_dt, end_dt,
                                  image_url=f"attachment://{os.path.basename(image_path)}")
    else:
        progress_image_url = None
        progress_cfg = sections.get("progress_image", {})
        if progress_cfg.get("enabled", True):
            image_path = "progress.png"
            try:
                generate_progress_image(cfg, stats, standing, zone_name, start_dt, end_dt, image_path)
                progress_image_url = "attachment://progress.png"
            except Exception as exc:
                logger.warning("Failed to generate image: %s", exc)
                image_path = None

        embed = build_embed(cfg, stats, standing, leaders, zone_name,
                            mplus_results, mplus_season_scores, mplus_season_parses,
                            start_dt, end_dt, no_logs,
                            progress_image_url=progress_image_url)

    if preview:
        return embed, image_path

    if not dry_run:
        webhook_url = require_env("DISCORD_WEBHOOK_URL")
        post_to_discord(webhook_url, embed, image_path=image_path, cfg=cfg)
        logger.info("Board posted to Discord.")
        try:
            save_board_state(standing, mplus_season_scores, streaks=streaks, records=records)
        except OSError as exc:
            logger.warning("Could not save board state: %s", exc)

    return embed, image_path


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="WoW Guild Weekly Board")
    parser.add_argument("--preview", action="store_true", help="Render preview to preview.html and exit without posting")
    parser.add_argument("--dry-run", action="store_true", help="Collect data and print embed but do not post")
    parser.add_argument("--date", help="End date for the board (YYYY-MM-DD)")
    parser.add_argument("--lookback", type=int, default=None, help="Override lookback days")
    parser.add_argument("--difficulty", help="Override raid difficulty (normal/heroic/mythic)")
    parser.add_argument("--roast", help="Override roast of the week")
    parser.add_argument("--roast-winner", help="Override roast winner")
    parser.add_argument("--roast-target", help="Override roast target")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args(argv)

    level = logging.DEBUG if args.verbose else logging.INFO
    _setup_logging(level)

    cfg = load_config()
    state = _load_weekly_state()
    cfg = _merge_state(cfg, state)

    if args.difficulty:
        cfg.setdefault("raid", {})["difficulty"] = args.difficulty
        if cfg.get("sections"):
            for key in ("top_dps", "top_healing"):
                cfg["sections"].setdefault(key, {})["difficulty"] = args.difficulty

    if args.lookback is not None:
        cfg["lookback_days"] = args.lookback

    if args.roast:
        roast = {
            "roast": args.roast,
            "winner": args.roast_winner or "Anonymous",
            "target": args.roast_target or "",
            # A manually entered roast beats the Discord vote
            "manual_override": True,
        }
        cfg.setdefault("sections", {}).setdefault("roast_of_the_week", {}).update(roast)
        cfg.setdefault("roast_of_the_week", {}).update(roast)

    if args.date:
        end_dt = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=int(cfg.get("lookback_days", 7)))

    embed, image_path = build_board(cfg, start_dt=start_dt, end_dt=end_dt, preview=args.preview, dry_run=args.dry_run)

    if args.preview:
        _write_preview(embed, image_path)
        return

    if args.dry_run:
        import json as _json
        print(_json.dumps(embed, indent=2))


def _write_preview(embed, image_path):
    """Write a local preview HTML file for the board."""
    html = _embed_to_html(embed, image_path)
    with open("preview.html", "w", encoding="utf-8") as f:
        f.write(html)
    logger.info("Preview written to preview.html")


def _embed_to_html(embed, image_path):
    """Convert a Discord embed to a basic HTML preview."""
    title = embed.get("title", "")
    description = embed.get("description", "")
    color = embed.get("color", 0xC69B6D)
    color_hex = f"#{color:06x}"
    fields = embed.get("fields", [])
    footer = embed.get("footer", {}).get("text", "")
    image_url = embed.get("image", {}).get("url", "")

    field_html = ""
    for field in fields:
        name = field.get("name", "")
        value = field.get("value", "").replace("\n", "<br>")
        field_html += f"<div class='field'><h3>{name}</h3><p>{value}</p></div>\n"

    if image_url.startswith("attachment://") and image_path:
        image_url = image_path
    img_tag = f"<img src='{image_url}' alt='board' />" if image_url else ""
    if image_path and not image_url:
        img_tag = f"<img src='{image_path}' alt='board' />"

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Guild Board Preview</title>
<style>
body {{ background: #1e1e22; color: #eee; font-family: Arial, sans-serif; padding: 20px; }}
.card {{ background: #2a2a30; border-left: 5px solid {color_hex}; padding: 20px; max-width: 800px; margin: auto; border-radius: 8px; }}
h1 {{ color: {color_hex}; margin: 0 0 10px; }}
.field {{ margin-bottom: 12px; border-bottom: 1px solid #444; padding-bottom: 8px; }}
.field h3 {{ margin: 0 0 4px; color: #fff; font-size: 14px; }}
.field p {{ margin: 0; color: #ddd; font-size: 13px; }}
.footer {{ color: #999; font-size: 12px; margin-top: 16px; }}
img {{ max-width: 100%; margin-top: 12px; border-radius: 8px; }}
a {{ color: #6cb5ff; text-decoration: none; }}
</style>
</head>
<body>
<div class="card">
<h1>{title}</h1>
<p>{description}</p>
{img_tag}
{field_html}
<div class="footer">{footer}</div>
</div>
</body>
</html>
"""


if __name__ == "__main__":
    main()

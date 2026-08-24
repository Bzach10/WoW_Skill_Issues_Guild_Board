import logging
from datetime import datetime, timezone

from guild_board.links import site_url
from guild_board.raiderio import raiderio_profile_url, raiderio_run_url
from guild_board.wcl import DIFFICULTY_MAP, wcl_character_url, wcl_guild_url, wcl_report_url

logger = logging.getLogger(__name__)

MEDALS = ["\U0001F947", "\U0001F948", "\U0001F949", "\U0001F536", "\U0001F537"]


def plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def masthead(cfg):
    """What the post calls itself.

    THE PAPER IS THE POST: when the attachments are photographs of the
    site's newspaper, the post carries the paper's real masthead. Every
    other path renders this repo's own board instead, and a title that
    claimed to be the paper over a different image would be the one
    dishonest line in the post.
    """
    return ("The Weekly Wipe"
            if str((cfg or {}).get("renderer", "")).lower() == "paper"
            else "Weekly Board")


def week_label(cfg):
    """'Raid week' for a normal 7-day window, 'Last N days' otherwise."""
    lookback = int(cfg.get("lookback_days", 7))
    return "Raid week" if lookback == 7 else f"Last {lookback} days"


def fmt_amount(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return f"{n:.0f}"


def medal(i):
    return MEDALS[i] if i < len(MEDALS) else f"**{i + 1}.**"


def _markdown_link(text, url):
    if not url:
        return text
    return f"[{text}]({url})"


def _player_url(name, cfg, realm_slug=None):
    region = cfg["guild"]["region"]
    realm = realm_slug or cfg["guild"]["realm_slug"]
    return wcl_character_url(name, realm, region)


def rank_lines_parses(best_parses, top_n, unit, cfg):
    ranked = sorted(best_parses.items(), key=lambda kv: kv[1]["parse"], reverse=True)[:top_n]
    lines = []
    for i, (name, info) in enumerate(ranked):
        player_link = _markdown_link(name, _player_url(name, cfg))
        parse_link = _markdown_link(
            f"{info['parse']:.0f}%",
            wcl_report_url(info["report_code"]) if info.get("report_code") else None,
        )
        boss = info.get("boss", "Unknown boss")
        lines.append(
            f"{medal(i)} {player_link} ({info['spec']}) — {parse_link} "
            f"on {boss} ({fmt_amount(info['amount'])} {unit})"
        )
    return "\n".join(lines) if lines else "_No data this week_"


def rank_lines_deaths(deaths, top_n):
    ranked = sorted(deaths.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    lines = []
    for i, (name, count) in enumerate(ranked):
        lines.append(f"{medal(i)} **{name}** — {count} deaths")
    return "\n".join(lines) if lines else "_Nobody died. Suspicious._"


def rank_lines_leaders(leaders, top_n, cfg):
    lines = []
    for i, entry in enumerate(leaders[:top_n]):
        region = cfg["guild"]["region"]
        realm = cfg["guild"]["realm_slug"]
        name = entry["name"]
        player_link = _markdown_link(name, wcl_character_url(name, realm, region))
        region_txt = ""
        if entry.get("region_rank"):
            region_txt = f" · Region #{entry['region_rank']:,}"
        avg_txt = ""
        if isinstance(entry.get("best_avg"), (int, float)):
            avg_txt = f" · {entry['best_avg']:.1f} best avg"
        boss = entry.get("boss")
        boss_txt = f" on {boss}" if boss else ""
        lines.append(
            f"{medal(i)} {player_link} ({entry['spec']}) — "
            f"Realm **#{entry['realm_rank']:,}**{boss_txt}{region_txt}{avg_txt}"
        )
    return "\n".join(lines) if lines else "_No ranked players found yet_"


def guild_standing_value(standing, zone_name, cfg):
    parts = []
    guild_url = wcl_guild_url(cfg["guild"]["name"], cfg["guild"]["realm_slug"], cfg["guild"]["region"])
    if standing.get("realm"):
        parts.append(_markdown_link(f"Realm #{standing['realm']:,}", guild_url))
    if standing.get("region"):
        parts.append(_markdown_link(f"Region #{standing['region']:,}", guild_url))
    if standing.get("world"):
        parts.append(_markdown_link(f"World #{standing['world']:,}", guild_url))
    if not parts:
        return None
    zone_txt = f" — {zone_name}" if zone_name else ""
    return " · ".join(parts) + f"\n_Progress ranking{zone_txt}_"


def rank_lines_mplus(results, top_n, cfg):
    lines = []
    for i, item in enumerate(results[:top_n]):
        if len(item) == 4:
            level, dungeon, name, timed = item
            spec = ""
        else:
            level, dungeon, name, spec, timed = item
        tag = "timed" if timed else "over time"
        spec_txt = f" ({spec})" if spec else ""
        region = cfg["guild"]["region"]
        realm = cfg["guild"]["realm_slug"]
        player_link = _markdown_link(name, raiderio_profile_url(name, realm, region))
        dungeon_link = _markdown_link(dungeon, raiderio_run_url(name, realm, region, dungeon))
        lines.append(f"{medal(i)} {player_link}{spec_txt} — +{level} {dungeon_link} ({tag})")
    return "\n".join(lines) if lines else "_No keys recorded this week_"


# ---------------------------------------------------------------------------
# Section formatter functions
# ---------------------------------------------------------------------------

def format_section_header(cfg, section_name, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    sections = cfg.get("sections", {})
    section_cfg = sections.get(section_name, {})

    if not section_cfg.get("enabled", True):
        return None

    title = section_cfg.get("title") or section_name.replace("_header", "").title()
    icon = section_cfg.get("icon", "")
    return {
        "name": f"────────── {icon} {title} {icon} ──────────",
        "value": "\u200b",
        "inline": False,
    }


def format_announcement(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    """Format the guild announcement field (always appears at the top)."""
    sections = cfg.get("sections", {})
    ann_cfg = sections.get("announcement", {})

    if not ann_cfg.get("enabled", True):
        return None

    title = ann_cfg.get("title", "\U0001F4E2 Guild Announcement")
    text = ann_cfg.get("text", "Welcome to the weekly board!")

    if not text:
        return None

    return {"name": title, "value": text, "inline": False}


def format_no_logs_notice(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    if not no_logs:
        return None

    sections = cfg.get("sections", {})
    notice_cfg = sections.get("no_logs_notice", {})

    if not notice_cfg.get("enabled", True):
        return None

    message = notice_cfg.get("message", "No raid logs found for the last {lookback_days} days.")
    lookback_days = cfg.get("lookback_days", 7)
    formatted_message = message.format(lookback_days=lookback_days)

    return {
        "name": "\u26A0\uFE0F No Logs This Week",
        "value": formatted_message,
        "inline": False,
    }


def format_guild_standing(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    sections = cfg.get("sections", {})
    standing_cfg = sections.get("guild_standing", {})

    if not standing_cfg.get("enabled", True):
        return None

    if standing:
        value = guild_standing_value(standing, zone_name, cfg)
        if value:
            return {"name": "\U0001F30D Guild Standing", "value": value, "inline": False}

    return None


def format_overall_realm_rank(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    """Format the overall guild realm rank field under Guild Achievements."""
    sections = cfg.get("sections", {})
    rank_cfg = sections.get("overall_realm_rank", {})

    if not rank_cfg.get("enabled", True):
        return None

    if not standing:
        return None

    value = guild_standing_value(standing, zone_name, cfg)
    if value:
        return {"name": "\U0001F30D Overall Realm Rank", "value": value, "inline": False}
    return None


def format_top_dps(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    sections = cfg.get("sections", {})
    dps_cfg = sections.get("top_dps", {})

    if not dps_cfg.get("enabled", True):
        return None

    if stats is not None:
        top_n = int(cfg.get("top_n", 5))
        return {
            "name": "\u2694\uFE0F Top DPS Parses",
            "value": rank_lines_parses(stats["best_dps"], top_n, "DPS", cfg),
            "inline": False,
        }

    return None


def format_top_healing(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    sections = cfg.get("sections", {})
    healing_cfg = sections.get("top_healing", {})

    if not healing_cfg.get("enabled", True):
        return None

    if stats is not None:
        top_n = int(cfg.get("top_n", 5))
        return {
            "name": "\U0001F489 Top Healing Parses",
            "value": rank_lines_parses(stats["best_hps"], top_n, "HPS", cfg),
            "inline": False,
        }

    return None


def format_realm_rank_leaders(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    sections = cfg.get("sections", {})
    leaders_cfg = sections.get("realm_rank_leaders", {})

    if not leaders_cfg.get("enabled", True):
        return None

    if leaders:
        top_n = int(cfg.get("top_n", 5))
        return {
            "name": "\u2B50 Weekly Raid Boss Ranks",
            "value": rank_lines_leaders(leaders, top_n, cfg),
            "inline": False,
        }

    return None


def format_most_deaths(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    sections = cfg.get("sections", {})
    deaths_cfg = sections.get("most_deaths", {})

    if not deaths_cfg.get("enabled", True):
        return None

    if stats is not None:
        top_n = int(cfg.get("top_n", 5))
        return {
            "name": "\U0001F480 Graveyard Camper Award (Most Deaths)",
            "value": rank_lines_deaths(stats["deaths"], top_n),
            "inline": False,
        }

    return None


def format_roast_of_the_week(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    sections = cfg.get("sections", {})
    roast_cfg = sections.get("roast_of_the_week", {})

    if not roast_cfg.get("enabled", True):
        return None

    if not roast_cfg:
        roast_cfg = cfg.get("roast_of_the_week", {})

    if not roast_cfg:
        return None

    if roast_cfg.get("roast"):
        winner = roast_cfg.get("winner", "Anonymous")
        target = roast_cfg.get("target", "")
        target_txt = f" (aimed at {target})" if target else ""
        return {
            "name": "\U0001F525 Roast of the Week",
            "value": f"\u201C{roast_cfg['roast']}\u201D\n\u2014 **{winner}**{target_txt}",
            "inline": False,
        }
    else:
        return {
            "name": "\U0001F525 Roast of the Week",
            "value": "_No roast submitted. Healers live to see another week._",
            "inline": False,
        }


def format_mplus(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    sections = cfg.get("sections", {})
    mplus_cfg = sections.get("mplus_last_week") if sections else {}
    if not mplus_cfg:
        mplus_cfg = sections.get("mplus", {})
    if not mplus_cfg:
        mplus_cfg = cfg.get("mplus", {})

    if not mplus_cfg.get("enabled", True):
        return None

    if mplus_results is not None:
        top_n = int(cfg.get("top_n", 5))
        return {
            "name": "\U0001F5DD\uFE0F Last Week M+ Runs",
            "value": rank_lines_mplus(mplus_results, top_n, cfg),
            "inline": False,
        }

    return None


def format_mplus_season_scores(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    sections = cfg.get("sections", {})
    mplus_cfg = sections.get("mplus_season_scores", {})

    if not mplus_cfg.get("enabled", True):
        return None

    if mplus_season_scores is not None:
        top_n = int(cfg.get("top_n", 5))
        lines = []
        for i, (score, name, spec) in enumerate(mplus_season_scores[:top_n]):
            spec_txt = f" ({spec})" if spec else ""
            region = cfg["guild"]["region"]
            realm = cfg["guild"]["realm_slug"]
            player_link = _markdown_link(name, raiderio_profile_url(name, realm, region))
            lines.append(f"{medal(i)} {player_link}{spec_txt} — {score:.0f} score")
        value = "\n".join(lines) if lines else "_No season scores found_"
        return {
            "name": "\U0001F3C6 Season-Long M+ Scores",
            "value": value,
            "inline": False,
        }

    return None


def format_mplus_season_parses(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs):
    sections = cfg.get("sections", {})
    mplus_cfg = sections.get("mplus_season_runs") if sections else {}
    if not mplus_cfg:
        mplus_cfg = sections.get("mplus_season_parses", {})

    if not mplus_cfg.get("enabled", True):
        return None

    if mplus_season_parses is not None:
        top_n = int(cfg.get("top_n", 5))
        lines = []
        use_wcl = mplus_cfg.get("use_wcl_parses", True)
        region = cfg["guild"]["region"]
        realm = cfg["guild"]["realm_slug"]
        for i, item in enumerate(mplus_season_parses[:top_n]):
            if len(item) == 5:
                value, dungeon, name, spec, is_wcl = item
            else:
                value, dungeon, name, spec = item
                is_wcl = use_wcl
            spec_txt = f" ({spec})" if spec else ""
            player_link = _markdown_link(name, raiderio_profile_url(name, realm, region))
            dungeon_link = _markdown_link(dungeon, raiderio_run_url(name, realm, region, dungeon))
            if is_wcl:
                lines.append(f"{medal(i)} {player_link}{spec_txt} — {value:.0f}% on {dungeon_link}")
            else:
                lines.append(f"{medal(i)} {player_link}{spec_txt} — {value:.0f} score on {dungeon_link}")
        value = "\n".join(lines) if lines else "_No season runs found_"
        return {
            "name": "\U0001F525 Top Season Mythic+ Runs",
            "value": value,
            "inline": False,
        }

    return None


SECTION_FORMATTERS = {
    "announcement": format_announcement,
    "no_logs_notice": format_no_logs_notice,
    "guild_achievement_header": lambda *args, **kwargs: format_section_header(args[0], "guild_achievement_header", *args[1:]),
    "guild_standing": format_guild_standing,
    "overall_realm_rank": format_overall_realm_rank,
    "mplus_header": lambda *args, **kwargs: format_section_header(args[0], "mplus_header", *args[1:]),
    "mplus": format_mplus,
    "mplus_last_week": format_mplus,
    "mplus_season_scores": format_mplus_season_scores,
    "mplus_season_parses": format_mplus_season_parses,
    "mplus_season_runs": format_mplus_season_parses,
    "raid_header": lambda *args, **kwargs: format_section_header(args[0], "raid_header", *args[1:]),
    "top_dps": format_top_dps,
    "top_healing": format_top_healing,
    "realm_rank_leaders": format_realm_rank_leaders,
    "most_deaths": format_most_deaths,
    "roast_of_the_week": format_roast_of_the_week,
}


def build_embed(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, start_dt, end_dt, no_logs=False, progress_image_url=None):
    guild_name = cfg["guild"]["name"]
    difficulty = str(cfg["raid"]["difficulty"]).title()
    date_range = f"{start_dt.strftime('%b %d')} – {end_dt.strftime('%b %d, %Y')}"

    sections = cfg.get("sections", {})

    section_items = list(sections.items()) if sections else []
    if not section_items:
        # No sections configured: use a sensible default board
        default_order = ("guild_standing", "top_dps", "top_healing",
                         "realm_rank_leaders", "most_deaths",
                         "roast_of_the_week", "mplus")
        section_items = [(name, {"order": i}) for i, name in enumerate(default_order)]

    layout = cfg.get("display", {}).get("layout", "single_column")
    if layout == "two_column":
        # Discord reflows inline fields unpredictably; this layout is retired.
        logger.info("Layout 'two_column' is deprecated; rendering single_column.")

    fields = []
    sorted_sections = sorted(section_items, key=lambda x: x[1].get("order", 999))
    for section_name, _section_cfg in sorted_sections:
        formatter = SECTION_FORMATTERS.get(section_name)
        if not formatter:
            continue
        try:
            field = formatter(cfg, stats, standing, leaders, zone_name,
                              mplus_results, mplus_season_scores, mplus_season_parses, no_logs)
        except Exception as exc:
            logger.warning("Error formatting section '%s': %s", section_name, exc)
            continue
        if field:
            field["inline"] = False
            fields.append(field)

    footer_bits = []
    if stats is not None:
        footer_bits.append(f"{plural(stats['kills'], 'kill')} / {plural(stats['pulls'], 'pull')} this week")
    footer_bits.append("Drop your healer roasts in the thread for next week \U0001F525")

    embed = {
        "title": f"\u2693 {guild_name} — {masthead(cfg)} — {difficulty}",
        "description": f"{week_label(cfg)}: **{date_range}**",
        "color": 0xC69B6D,
        "fields": fields,
        "footer": {"text": " | ".join(footer_bits)},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if progress_image_url:
        embed["image"] = {"url": progress_image_url}

    return embed


def tldr_lines(stats, standing=None):
    """Three phone-readable callout lines for the embed text, so the top of
    the board lands even before anyone zooms into the image."""
    lines = []
    if stats:
        for pool_key, icon, label in (("best_dps", "\U0001F5E1️", "Top DPS"),
                                      ("best_hps", "\U0001F49A", "Top heals"),
                                      ("best_tanks", "\U0001F6E1️", "Top tank")):
            pool = stats.get(pool_key) or {}
            if pool:
                name, info = max(pool.items(), key=lambda kv: kv[1].get("parse") or 0)
                parse = info.get("parse") or 0
                boss = info.get("boss") or ""
                bit = f"{icon} {label}: **{name}** {parse:.0f}%"
                lines.append(bit + (f" on {boss}" if boss else ""))
    if standing and standing.get("realm"):
        suffix = " (last wk)" if standing.get("stale") else ""
        lines.append(f"\U0001F3F0 Realm rank **#{standing['realm']:,}**{suffix}")
    return lines


def build_image_embed(cfg, stats, start_dt, end_dt, image_url="attachment://board.png",
                      tldr=None):
    """Minimal embed for image-board mode: title, announcement, the board image.

    All stats live in the rendered image; the embed carries what an image
    can't — the title, the officer announcement, phone-readable TL;DR
    callouts, and the footer CTA.
    """
    guild_name = cfg["guild"]["name"]
    difficulty = str(cfg["raid"]["difficulty"]).title()
    if stats is not None:
        # Reflect the difficulty the data actually came from (fallback may downgrade)
        names = {num: name.title() for name, num in DIFFICULTY_MAP.items()}
        difficulty = names.get(stats.get("difficulty"), difficulty)
    date_range = f"{start_dt.strftime('%b %d')} – {end_dt.strftime('%b %d, %Y')}"

    desc_lines = []
    ann_cfg = cfg.get("sections", {}).get("announcement", {})
    if ann_cfg.get("enabled", True) and ann_cfg.get("text"):
        desc_lines.append(f"\U0001F4E2 {ann_cfg['text']}")
    desc_lines.append(f"{week_label(cfg)}: **{date_range}**")
    if tldr:
        desc_lines.append("")
        desc_lines.extend(tldr)

    footer_bits = []
    if stats is not None:
        footer_bits.append(f"{plural(stats['kills'], 'kill')} / {plural(stats['pulls'], 'pull')} this week")
    footer_bits.append("Drop your healer roasts in the thread for next week \U0001F525")

    embed = {
        "title": f"\u2693 {guild_name} — {masthead(cfg)} — {difficulty}",
        "description": "\n".join(desc_lines),
        "color": 0xC69B6D,
        "image": {"url": image_url},
        "footer": {"text": " | ".join(footer_bits)},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    # The embed TITLE links to the ship site — the most obvious click
    # target Discord offers an embed (link buttons on channel webhooks
    # get silently dropped when Discord rejects them).
    ship = site_url(cfg)
    if ship:
        embed["url"] = ship
    return embed

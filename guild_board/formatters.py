import logging
from datetime import datetime, timezone

from guild_board.raiderio import raiderio_profile_url, raiderio_run_url
from guild_board.wcl import DIFFICULTY_MAP, wcl_character_url, wcl_guild_url, wcl_report_url

logger = logging.getLogger(__name__)

MEDALS = ["\U0001F947", "\U0001F948", "\U0001F949", "\U0001F536", "\U0001F537"]


def plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


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

    if not standing_cfg and cfg.get("rankings", {}).get("enabled", True):
        standing_cfg = cfg.get("rankings", {})

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

    if not dps_cfg and cfg.get("raid", {}).get("enabled", True):
        dps_cfg = cfg.get("raid", {})

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

    if not healing_cfg and cfg.get("raid", {}).get("enabled", True):
        healing_cfg = cfg.get("raid", {})

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

    if not leaders_cfg and cfg.get("rankings", {}).get("enabled", True):
        leaders_cfg = cfg.get("rankings", {})

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


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def _section_group(section_name):
    if section_name == "announcement":
        return "announcement"
    if section_name in {"guild_achievement_header", "guild_standing", "overall_realm_rank", "roast_of_the_week"}:
        return "guild_achievement"
    if section_name in {"mplus_header", "mplus", "mplus_last_week", "mplus_season_scores", "mplus_season_parses", "mplus_season_runs"}:
        return "mplus"
    if section_name in {"raid_header", "top_dps", "top_healing", "realm_rank_leaders", "most_deaths", "no_logs_notice"}:
        return "raid"
    return "other"


def _build_two_column_fields(cfg, raw_fields):
    """Arrange announcement, two side-by-side columns (Raid/M+), and guild achievements below."""
    sections = cfg.get("sections", {})

    groups = {"announcement": [], "raid": [], "mplus": [], "guild_achievement": [], "other": []}
    for section_name, field in raw_fields:
        group = _section_group(section_name)
        if group in groups:
            groups[group].append((section_name, field))
        else:
            groups["other"].append((section_name, field))

    fields = []

    # Announcement first, full width
    for _, f in groups["announcement"]:
        f["inline"] = False
        fields.append(f)

    # Build two inline columns. Drop header placeholders (empty values).
    raid = [(n, f) for n, f in groups["raid"] if f["value"] != "\u200b"]
    mplus = [(n, f) for n, f in groups["mplus"] if f["value"] != "\u200b"]

    COLUMN_TITLES = {
        "top_dps": "\u2694\uFE0F Top DPS",
        "top_healing": "\U0001F489 Top Heals",
        "realm_rank_leaders": "\u2B50 Weekly Raid Boss Ranks",
        "most_deaths": "\U0001F480 Most Deaths",
        "no_logs_notice": "\u26A0\uFE0F No Logs",
        "mplus": "\U0001F5DD\uFE0F Last Week",
        "mplus_last_week": "\U0001F5DD\uFE0F Last Week",
        "mplus_season_scores": "\U0001F3C6 Season Scores",
        "mplus_season_parses": "\U0001F525 Season Runs",
        "mplus_season_runs": "\U0001F525 Season Runs",
    }

    def _column_value(col_fields):
        parts = []
        for name, f in col_fields:
            title = COLUMN_TITLES.get(name, f["name"])
            parts.append(f"**{title}**\n{f['value']}")
        value = "\n\n".join(parts)
        if len(value) > 1024:
            value = value[:1021] + "..."
        return value

    raid_cfg = sections.get("raid_header", {})
    mplus_cfg = sections.get("mplus_header", {})
    raid_title = raid_cfg.get("title", "Raid")
    mplus_title = mplus_cfg.get("title", "Mythic Plus")
    raid_icon = raid_cfg.get("icon", "")
    mplus_icon = mplus_cfg.get("icon", "")

    if raid or mplus:
        raid_value = _column_value(raid) if raid else "_No raid data this week_"
        mplus_value = _column_value(mplus) if mplus else "_No M+ data this week_"
        fields.append({"name": f"{raid_icon} {raid_title}".strip(), "value": raid_value, "inline": True})
        fields.append({"name": f"{mplus_icon} {mplus_title}".strip(), "value": mplus_value, "inline": True})

    # Guild achievements: full-width header, then body fields
    ga_header = next((f for _, f in groups["guild_achievement"] if f["value"] == "\u200b"), None)
    ga_body = [f for _, f in groups["guild_achievement"] if f["value"] != "\u200b"]
    if ga_header:
        ga_header["inline"] = False
        fields.append(ga_header)
    for f in ga_body:
        f["inline"] = False
        fields.append(f)

    # Any other full-width fields
    for _, f in groups["other"]:
        f["inline"] = False
        fields.append(f)

    return fields


def build_embed(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, start_dt, end_dt, no_logs=False, progress_image_url=None):
    guild_name = cfg["guild"]["name"]
    difficulty = str(cfg["raid"]["difficulty"]).title()
    date_range = f"{start_dt.strftime('%b %d')} – {end_dt.strftime('%b %d, %Y')}"

    sections = cfg.get("sections", {})

    fields = []
    section_items = list(sections.items()) if sections else []

    if not section_items:
        # Legacy behavior
        if standing:
            value = guild_standing_value(standing, zone_name, cfg)
            if value:
                fields.append({"name": "\U0001F30D Guild Standing", "value": value, "inline": False})

        if stats is not None:
            top_n = int(cfg.get("top_n", 5))
            fields.append({
                "name": "\u2694\uFE0F Top DPS Parses",
                "value": rank_lines_parses(stats["best_dps"], top_n, "DPS", cfg),
                "inline": False,
            })
            fields.append({
                "name": "\U0001F489 Top Healing Parses",
                "value": rank_lines_parses(stats["best_hps"], top_n, "HPS", cfg),
                "inline": False,
            })

        if leaders:
            top_n = int(cfg.get("top_n", 5))
            fields.append({
                "name": "\u2B50 Realm Rank Leaders (Tier All Stars)",
                "value": rank_lines_leaders(leaders, top_n, cfg),
                "inline": False,
            })

        if stats is not None:
            top_n = int(cfg.get("top_n", 5))
            fields.append({
                "name": "\U0001F480 Graveyard Camper Award (Most Deaths)",
                "value": rank_lines_deaths(stats["deaths"], top_n),
                "inline": False,
            })

        roast = cfg.get("roast_of_the_week") or {}
        if roast.get("roast"):
            winner = roast.get("winner", "Anonymous")
            target = roast.get("target", "")
            target_txt = f" (aimed at {target})" if target else ""
            fields.append({
                "name": "\U0001F525 Roast of the Week",
                "value": f"\u201C{roast['roast']}\u201D\n\u2014 **{winner}**{target_txt}",
                "inline": False,
            })
        else:
            fields.append({
                "name": "\U0001F525 Roast of the Week",
                "value": "_No roast submitted. Healers live to see another week._",
                "inline": False,
            })

        if mplus_results is not None:
            top_n = int(cfg.get("top_n", 5))
            fields.append({
                "name": "\U0001F5DD\uFE0F Highest M+ Keys This Week",
                "value": rank_lines_mplus(mplus_results, top_n, cfg),
                "inline": False,
            })
    else:
        sorted_sections = sorted(section_items, key=lambda x: x[1].get("order", 999))
        raw_fields = []

        for section_name, section_cfg in sorted_sections:
            formatter = SECTION_FORMATTERS.get(section_name)
            if formatter:
                try:
                    field = formatter(cfg, stats, standing, leaders, zone_name, mplus_results, mplus_season_scores, mplus_season_parses, no_logs)
                    if field:
                        raw_fields.append((section_name, field))
                except Exception as exc:
                    logger.warning("Error formatting section '%s': %s", section_name, exc)
                    continue

        layout = cfg.get("display", {}).get("layout", "two_column")
        if layout == "two_column":
            fields = _build_two_column_fields(cfg, raw_fields)
        else:
            fields = [field for _, field in raw_fields]

    footer_bits = []
    if stats is not None:
        footer_bits.append(f"{plural(stats['kills'], 'kill')} / {plural(stats['pulls'], 'pull')} this week")
    footer_bits.append("Drop your healer roasts in the thread for next week \U0001F525")

    embed = {
        "title": f"\U0001F3C6 {guild_name} Weekly Board — {difficulty}",
        "description": f"{week_label(cfg)}: **{date_range}**",
        "color": 0xC69B6D,
        "fields": fields,
        "footer": {"text": " | ".join(footer_bits)},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if progress_image_url:
        embed["image"] = {"url": progress_image_url}

    return embed


def build_image_embed(cfg, stats, start_dt, end_dt, image_url="attachment://board.png"):
    """Minimal embed for image-board mode: title, announcement, the board image.

    All stats live in the rendered image; the embed only carries what an
    image can't — the title, the officer announcement, and the footer CTA.
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

    footer_bits = []
    if stats is not None:
        footer_bits.append(f"{plural(stats['kills'], 'kill')} / {plural(stats['pulls'], 'pull')} this week")
    footer_bits.append("Drop your healer roasts in the thread for next week \U0001F525")

    return {
        "title": f"\U0001F3C6 {guild_name} Weekly Board — {difficulty}",
        "description": "\n".join(desc_lines),
        "color": 0xC69B6D,
        "image": {"url": image_url},
        "footer": {"text": " | ".join(footer_bits)},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

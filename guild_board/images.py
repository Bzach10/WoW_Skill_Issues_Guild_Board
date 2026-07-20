import logging

from PIL import Image, ImageDraw, ImageFont


logger = logging.getLogger(__name__)


def _load_font(size):
    """Try to load a nice font, fall back to Pillow default."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def generate_progress_image(cfg, stats, standing, zone_name, start_dt, end_dt, output_path="progress.png"):
    """Generate a static PNG progress card and save it."""
    # Tall enough for the mini leaderboards drawn at y=320 (3 rows ≈ 70px).
    width, height = 900, 420
    bg = (18, 18, 22)
    accent = (230, 180, 70)
    text = (220, 220, 220)
    muted = (150, 150, 150)

    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    title_font = _load_font(34)
    subtitle_font = _load_font(22)
    label_font = _load_font(16)
    value_font = _load_font(26)
    small_font = _load_font(14)

    guild_name = cfg["guild"]["name"]
    difficulty = str(cfg.get("raid", {}).get("difficulty", "mythic")).title()
    zone = zone_name or "Current Raid"
    date_range = f"{start_dt.strftime('%b %d')} – {end_dt.strftime('%b %d, %Y')}"

    # Title
    draw.text((40, 30), guild_name, font=title_font, fill=accent)
    draw.text((40, 78), f"{difficulty} {zone}", font=subtitle_font, fill=text)
    draw.text((40, 110), date_range, font=label_font, fill=muted)

    kills = stats.get("kills", 0) if stats else 0
    pulls = stats.get("pulls", 0) if stats else 0
    deaths = stats.get("deaths", {}) if stats else {}
    total_deaths = sum(deaths.values()) if deaths else 0

    stats_data = [
        ("Kills", str(kills)),
        ("Pulls", str(pulls)),
        ("Deaths", str(total_deaths)),
    ]

    if standing:
        if standing.get("world"):
            stats_data.append(("World", f"#{standing['world']:,}"))
        if standing.get("region"):
            stats_data.append(("Region", f"#{standing['region']:,}"))
        if standing.get("realm"):
            stats_data.append(("Realm", f"#{standing['realm']:,}"))

    x = 40
    y = 160
    for label, value in stats_data[:5]:
        draw.text((x, y), label, font=label_font, fill=muted)
        draw.text((x, y + 28), value, font=value_font, fill=text)
        x += 170

    # Progress bar
    bar_x, bar_y, bar_w, bar_h = 40, 260, 820, 32
    draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=8, outline=muted, width=2)
    if pulls > 0:
        fill_w = int(bar_w * (kills / max(pulls, 1)))
        if fill_w > 0:
            draw.rounded_rectangle([bar_x, bar_y, bar_x + fill_w, bar_y + bar_h], radius=8, fill=accent)
        pct = kills / max(pulls, 1) * 100
        label = f"{kills} / {pulls} kills ({pct:.1f}%)"
    else:
        label = "No pulls this week"

    bbox = draw.textbbox((0, 0), label, font=label_font)
    text_w = bbox[2] - bbox[0]
    draw.text((bar_x + (bar_w - text_w) // 2, bar_y + 6), label, font=label_font, fill=bg if pulls and kills else text)

    # Mini leaderboards if stats available
    if stats:
        _draw_mini_leaderboards(draw, stats, 40, 320, 820, small_font, cfg)

    img.save(output_path, "PNG")
    logger.info("Generated static image at %s", output_path)
    return output_path


def _draw_mini_leaderboards(draw, stats, x, y, total_width, font, cfg):
    """Draw small DPS/HPS/Deaths leaderboards on the progress card."""
    column_width = total_width // 3
    sections = [
        ("Top DPS", stats.get("best_dps", {}), "parse"),
        ("Top HPS", stats.get("best_hps", {}), "parse"),
        ("Most Deaths", stats.get("deaths", {}), "count"),
    ]

    for idx, (title, data, sort_key) in enumerate(sections):
        cx = x + idx * column_width
        draw.text((cx, y), title, font=font, fill=(230, 180, 70))

        if sort_key == "count":
            items = sorted(data.items(), key=lambda kv: kv[1], reverse=True)[:3]
            lines = [f"{i+1}. {n} — {c}" for i, (n, c) in enumerate(items)]
        else:
            items = sorted(data.items(), key=lambda kv: kv[1]["parse"], reverse=True)[:3]
            lines = [f"{i+1}. {n} — {info['parse']:.0f}%" for i, (n, info) in enumerate(items)]

        for i, line in enumerate(lines):
            draw.text((cx, y + 18 + i * 16), line, font=font, fill=(220, 220, 220))

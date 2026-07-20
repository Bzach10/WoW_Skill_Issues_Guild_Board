"""Guild-editable board theme.

Everything about how the board LOOKS — colors, background art, fonts,
which header/footer module frames it, and every gag line — lives in
theme.yml at the repo root. This module owns the defaults (the shipped
Stone & Torchlight design, verbatim) and deep-merges the guild's
theme.yml over them, so a missing or partial file can never break a
render: any key you don't set keeps its default.

Guild-made template modules can live in board_templates/headers/ and
board_templates/footers/ at the repo root; they're found before the
built-ins, so a guild can also OVERRIDE a built-in by shadowing its
filename. See CUSTOMIZING.md for the walkthrough.
"""

import copy
import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

THEME_FILE = "theme.yml"

# Search order for header/footer/board templates: the guild's own modules
# first, then the built-ins that ship with the package.
GUILD_TEMPLATE_DIR = Path("board_templates")
PACKAGE_TEMPLATE_DIR = Path(__file__).parent / "templates"

# Known band heights per built-in module — the GIF encoder freezes the
# middle of the board and only animates the bands, so it needs to know
# where each module ends. Custom modules can declare theirs in theme.yml
# (board.header_height / board.footer_height).
HEADER_HEIGHTS = {"stone_torchlight": 300, "banner": 190}
FOOTER_HEIGHTS = {"graveyard": 430, "simple": 150}
FOOTER_EXTRA = 52 + 40   # MOTD strip + credits bar, shared by every footer

DEFAULT_THEME = {
    "board": {
        "header": "stone_torchlight",   # file in templates/headers/<name>.html.j2
        "footer": "graveyard",          # file in templates/footers/<name>.html.j2
        "width": 3000,
        "header_height": None,          # only needed for custom modules
        "footer_height": None,
        # Wanted-poster column dressing (empty strings hide the lines)
        "poster_eyebrow": "★ WANTED ★",
        "poster_reward": "DEAD OR ALIVE · REWARD: GLORY",
        # Which LAYOUT the public website uses — a file in templates/web/.
        # Ships with: poster (the WANTED-poster grid), chronicle (editorial
        # feature spread), ember_terminal (arcane console log), codex
        # (illuminated single-column scroll). A guild can add its own in
        # board_templates/web/. An unknown name falls back to poster.
        "web_layout": "poster",
    },
    "colors": {
        "background": "#111217",
        "panel": "#1e212b",
        "hairline": "#353b48",
        "accent": "#e6b446",
        "text": "#f2f3f7",
        "muted": "#b3b9c5",
        "faint": "#7f8591",
        "red": "#e5484d",
        "green": "#4cdc56",
    },
    "fonts": {
        "display": "Cinzel",        # big carved titles (any Google Font name)
        "display_weights": "700;900",  # weights the display font actually ships
        "body": "Inter",            # all the data text
        "mono": "JetBrains Mono",   # console/ledger numerals (ember_terminal)
    },
    "backgrounds": {
        "header": "assets/wall_header.png",
        "middle": "assets/theme_art.png",
        "middle_tint": 0.87,    # 0 = art at full strength, 1 = solid color
        "footer": "assets/wall_footer.png",
        "poster": None,         # parchment image behind each WANTED column
    },
    "header": {
        "sign_text": "GIT GUD",
        "sign_subtext": "MGMT IS NOT RESPONSIBLE",
        "wipes_label": "WIPES THIS WEEK",
        "wipes_sub": "deaths: {deaths} · personal best: still zero",
        "repair_label": "SEASON REPAIR BILL (EST.)",
        "repair_sub": "donations welcome · thoughts & prayers accepted",
        "counter_label": "“GO AGANE” COUNTER",
        "counter_sub": "morale: unaffected · copium: stable",
        "debuffs_label": "ACTIVE RAID DEBUFFS",
        # stack: a number/string, or "deaths" to show the week's death total
        "debuffs": [
            {"icon": "inv_misc_questionmark", "kind": "bad", "label": "Skill Issue", "stack": "40"},
            {"icon": "spell_fire_fire", "kind": "bad", "label": "Standing in Fire", "stack": "6w"},
            {"icon": "inv_misc_bone_humanskull_01", "kind": "bad", "label": "Graveyard Timeshare", "stack": "deaths"},
            {"icon": "spell_nature_sleep", "kind": "good", "label": "Coping", "stack": "∞"},
            {"icon": "spell_holy_layonhands", "kind": "good", "label": "Healer Diff", "stack": "1"},
        ],
    },
    "footer": {
        "debt": {
            "enabled": True,
            "title": "Brewzleeh's Gambling Debt",
            "principal": 137000,        # gold owed at week 0
            "weekly_rate_pct": 9.99,    # compounds every week, obviously
            "interest_note": "interest: 9.99% weekly · collateral: his monk",
            "climbing_note": "and climbing",
            "lines": [
                "Binds on !roll",
                "Deathroll Ledger|Unique",
                "+15 Gambling Addiction",
                "-100% Gold Retention Aura",
                "Equip: Doubles down on a 2% win chance.",
                "Equip: Cannot leave while ahead. Has never been ahead.",
                "Use: Borrows from GBank tab 3. Again. (No Cooldown)",
            ],
            "flavor": "“Just one more roll.” — Brewzleeh, at 4 AM",
            "requires": "Requires: An intervention",
        },
        "graveyard": {
            "title": "GRAVEYARD CAMPERS MEMORIAL",
            "caption": "Plots assigned by deaths-per-pull. The campfire is load-bearing.",
            "reserved": "HEALMATES",
            "reserved_note": "6 consecutive weeks in the fire",
        },
        "item_title": "GUILD ITEM OF THE MONTH",
        "item_empty": "New item arriving soon™",
    },
    "motd_quips": [
        "MORE DOTS. MORE DOTS. … OK STOP DOTS.",
        "That's a 50 DKP MINUS.",
        "Healmates has now stood in the fire for 6 consecutive weeks — a new guild record.",
        "Key depleted? That is a you problem.",
        "At least Leeroy had a plan.",
        "Raid times: Tue/Thu, 8 PM to whenever Rakdisc stops blaming people.",
        "Repair bills are self-inflicted and therefore not reimbursable.",
    ],
    "credits": "“Git Gud.” — ancient guild proverb",
    "awards": {
        "enabled": True,
        "per_week": 2,      # how many rotating awards appear each board
        "top_n": 3,
    },
}


def _deep_merge(base, override):
    """Recursive dict merge; override wins, lists replace wholesale."""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_theme(path=THEME_FILE):
    """The shipped design, with the guild's theme.yml merged over it.

    Fails open: a missing, empty, or unparseable file just means the
    default theme — the board always renders.
    """
    theme = copy.deepcopy(DEFAULT_THEME)
    try:
        with open(path, "r", encoding="utf-8") as f:
            user = yaml.safe_load(f)
        if isinstance(user, dict):
            theme = _deep_merge(theme, user)
            logger.info("Loaded guild theme from %s", path)
    except FileNotFoundError:
        pass
    except yaml.YAMLError as exc:
        logger.warning("theme.yml has a syntax error (%s); using the default theme.", exc)
    return theme


def _resolve_module(kind, name, default):
    """Return the template path (relative to the loader roots) for a
    header/footer module, falling back to the default when the named
    module doesn't exist anywhere."""
    rel = f"{kind}/{name}.html.j2"
    for root in (GUILD_TEMPLATE_DIR, PACKAGE_TEMPLATE_DIR):
        if (root / kind / f"{name}.html.j2").exists():
            return rel, name
    logger.warning("Theme names %s module '%s' but no %s exists; using '%s'.",
                   kind[:-1], name, rel, default)
    return f"{kind}/{default}.html.j2", default


def resolve_templates(theme):
    """Map the theme's header/footer names to real template paths and
    band heights (used by the GIF encoder's frozen-middle scheme)."""
    board = theme.get("board", {})
    header_rel, header_name = _resolve_module(
        "headers", board.get("header") or "stone_torchlight", "stone_torchlight")
    footer_rel, footer_name = _resolve_module(
        "footers", board.get("footer") or "graveyard", "graveyard")
    web_rel, _ = _resolve_module(
        "web", board.get("web_layout") or "poster", "poster")
    header_h = board.get("header_height") or HEADER_HEIGHTS.get(header_name, 300)
    footer_h = (board.get("footer_height") or FOOTER_HEIGHTS.get(footer_name, 430))
    return {
        "header_template": header_rel,
        "footer_template": footer_rel,
        "web_layout_template": web_rel,
        "header_h": int(header_h),
        "footer_h": int(footer_h),
        "footer_total": int(footer_h) + FOOTER_EXTRA,
    }


def template_loader_paths():
    """Loader search path: guild modules first, then the built-ins."""
    paths = []
    if GUILD_TEMPLATE_DIR.is_dir():
        paths.append(str(GUILD_TEMPLATE_DIR))
    paths.append(str(PACKAGE_TEMPLATE_DIR))
    return paths


def font_css_url(theme):
    fonts = theme.get("fonts", {})
    display = (fonts.get("display") or "Cinzel").replace(" ", "+")
    body = (fonts.get("body") or "Inter").replace(" ", "+")
    # Google Fonts rejects requests for weights a family doesn't ship
    # (e.g. Rye only has 400), so the display axis is theme-declared.
    # Absent key -> shipped default axes; explicit "" -> plain family.
    weights = str(fonts.get("display_weights",
                            DEFAULT_THEME["fonts"]["display_weights"]) or "").strip()
    display_spec = f"{display}:wght@{weights}" if weights else display
    # The mono family is only used by console-style layouts; an empty
    # value simply drops it and those layouts fall back to the system
    # monospace stack.
    mono = (fonts.get("mono", DEFAULT_THEME["fonts"]["mono"]) or "").strip()
    mono_spec = (f"&family={mono.replace(' ', '+')}:wght@400;700"
                 if mono else "")
    return ("https://fonts.googleapis.com/css2?"
            f"family={display_spec}&"
            f"family={body}:wght@400;500;600;700;800"
            f"{mono_spec}&display=swap")


def hex_to_rgb(value, fallback=(17, 18, 23)):
    value = (value or "").strip().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    try:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return fallback

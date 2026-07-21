"""The Voyage Map: the season's dungeons + raid as islands on a pirate route.

Island roster is built from data the pipeline already treats as real:
  - Dungeon islands: guild_board.raiderio.DUNGEON_NAME_FIXES (the actual
    season's M+ pool, already used to fix up Raider.io's dungeon names).
  - Raid islands: the boss names already recorded as real records in
    board_state.json (best_dps_parse.boss / best_hps_parse.boss), extended
    with the two other bosses in this tier per the confirmed art-director
    pass (THEME_JOURNAL.md's "Imperial Bounty" / Voidspire Sanctum concept).

Nothing here invents roster members or fake stats — landing on an island
pulls real data (Raider.io's public API for dungeons, board_state.json's
existing records for raid bosses) or shows "no record yet" honestly.

Public API, for anything else (e.g. a front-end UI) that wants to consume
this without reading the implementation:

  build_islands() -> list[dict]
      Ordered island chain, dungeons then raid bosses. Each dict:
        {"id": str,       # stable slug, e.g. "grim-batol"
         "name": str,      # real display name, e.g. "Grim Batol"
         "kind": str,      # "dungeon" | "raid_boss"
         "flavor": str}    # one-line island concept text
      Does NOT include a "data" key — callers attach that themselves via
      the two fetch_* functions below (see scripts/render_voyage_map.py
      for the reference wiring).

  current_island_id(cfg) -> str
      Which island id the crew ship is docked at. Reads cfg["voyage"]
      ["current_island"] (falls back to the first dungeon's id if unset
      or unrecognized) — cfg is the normal guild_board.config.load_config()
      dict, same one every other module in this package takes.

  fetch_dungeon_island_data(cfg, dungeon_display_name) -> dict | None
      {"name": str, "level": int, "spec": str} for the roster's best timed
      run in that dungeon this week (live Raider.io call, no credentials
      needed), or None if nobody has one yet.

  fetch_raid_island_data(board_state, boss_name) -> dict | None
      {"name": str, "parse": float, "spec": str, "cls": str, "role": str}
      pulled from board_state["records"] (best_dps_parse/best_hps_parse),
      or None if the current record isn't for that specific boss.
      board_state is the plain dict loaded from board_state.json.
"""

from guild_board.raiderio import DUNGEON_NAME_FIXES

# The real current raid tier's boss roster (order = kill order within the
# tier; not independently confirmed by a live WCL zone query since that
# needs a WCL token, but Averzian/Salhadaar are directly present as real
# record-holders in board_state.json, and all four are consistently the
# tier's bosses across every real/derived data point in this repo).
RAID_BOSSES = [
    "Imperator Averzian",
    "Fallen-King Salhadaar",
    "Chimaerus",
    "Vorasius",
]

# One-line "island" concept per dungeon, riffing on each zone's actual
# in-game flavor — these are real WoW zones, so the flavor text describes
# what's really there, just framed as a stop on the crew's voyage.
DUNGEON_FLAVOR = {
    "Ara-Kara, City of Echoes": "A wind-carved arakkoa ruin that answers every shout with one of its own — the crew swears the echoes started repeating THEIR jokes.",
    "City of Threads": "A buried nerubian silk-city below the surface world — bring a torch, bring a blade, and never bring an appetite for spiders.",
    "The Dawnbreaker": "A ghost ship of the reborn, sailing forever on borrowed time — the one island that was already a boat before the crew got here.",
    "The Stonevault": "An earthen dwarven vault sealed against something that got back out anyway.",
    "Mists of Tirna Scithe": "A fae dreamwood where the paths rearrange themselves out of spite.",
    "The Necrotic Wake": "A plague-dock crawling with things that used to have a pulse and a shift schedule.",
    "Siege of Boralus": "An actual pirate harbor under siege — finally, an island the crew feels at home robbing.",
    "Grim Batol": "A dragon-scarred mountain fortress, all iron and old grudges.",
    "Waycrest Manor": "A gothic manor where the furniture has opinions and the hosts won't take a hint.",
    "Operation: Mechagon - Workshop": "A gnomish scrap-metropolis running on spite, sparks, and warranty voids.",
}

RAID_FLAVOR = {
    "Imperator Averzian": "The fallen empire's first gate — an Imperator who never got the memo that the throne isn't his anymore.",
    "Fallen-King Salhadaar": "A dead king still giving orders nobody left alive should be following.",
    "Chimaerus": "The Undreamt God — something that was never supposed to wake up, let alone hold court.",
    "Vorasius": "The throne room itself, and whatever's left wearing the crown.",
}


def build_islands():
    """Return the ordered island chain: dungeons first, then the raid tier.

    Each island: {id, name, kind, flavor}. Real names only — no invented
    content beyond the one-line flavor text.
    """
    islands = []
    for name in DUNGEON_NAME_FIXES:
        islands.append({
            "id": _slugify(name),
            "name": DUNGEON_NAME_FIXES[name],
            "kind": "dungeon",
            "flavor": DUNGEON_FLAVOR.get(name, ""),
        })
    for name in RAID_BOSSES:
        islands.append({
            "id": _slugify(name),
            "name": name,
            "kind": "raid_boss",
            "flavor": RAID_FLAVOR.get(name, ""),
        })
    return islands


def _slugify(name):
    return "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")


def current_island_id(cfg):
    """Which island the crew ship is docked at — officer-editable in
    config.yml (voyage.current_island), defaulting to the first dungeon.
    """
    voyage_cfg = (cfg or {}).get("voyage", {})
    islands = build_islands()
    configured = voyage_cfg.get("current_island")
    if configured:
        ids = {isl["id"] for isl in islands}
        if configured in ids:
            return configured
    return islands[0]["id"] if islands else None


def fetch_dungeon_island_data(cfg, dungeon_display_name):
    """Real guild-best timed run for one dungeon this week, via Raider.io's
    public API (no credentials needed) — same endpoint/roster the existing
    weekly M+ section already uses, just filtered to one dungeon.

    Returns {"name": str, "level": int, "spec": str} or None if nobody in
    the roster has a timed run there this week.
    """
    import requests

    from guild_board.config import clean_spec_name, load_roster_cache, split_name_realm

    region = ((cfg or {}).get("guild") or {}).get("region", "us")
    roster, _ = load_roster_cache(cfg)
    best = None
    for entry in roster:
        if "-" not in entry:
            continue
        name, realm = split_name_realm(entry)
        try:
            resp = requests.get(
                "https://raider.io/api/v1/characters/profile",
                params={"region": region, "realm": realm, "name": name,
                        "fields": "mythic_plus_weekly_highest_level_runs"},
                timeout=30,
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
        except requests.RequestException:
            continue

        runs = data.get("mythic_plus_weekly_highest_level_runs") or []
        for run in runs:
            dungeon = (run.get("dungeon") or "").strip()
            if dungeon != dungeon_display_name.split(" - ")[0].split(",")[0].strip() \
               and dungeon != dungeon_display_name:
                continue
            if (run.get("num_keystone_upgrades", 0) or 0) <= 0:
                continue
            level = run.get("mythic_level", 0)
            if best is None or level > best["level"]:
                spec = clean_spec_name(run.get("spec"), data.get("class", ""))
                best = {"name": data.get("name", name), "level": level, "spec": spec}
    return best


def fetch_raid_island_data(board_state, boss_name):
    """Real record for one raid boss, pulled straight from the records
    already in board_state.json (best_dps_parse / best_hps_parse) — no
    new fetch, since this data is already collected by the weekly board.

    Returns {"name", "parse", "spec", "cls", "role"} or None if the
    current record isn't for this specific boss.
    """
    records = (board_state or {}).get("records", {})
    for role, key in (("dps", "best_dps_parse"), ("hps", "best_hps_parse")):
        record = records.get(key) or {}
        if (record.get("boss") or "").strip() == boss_name:
            return {
                "name": record.get("name"),
                "parse": record.get("parse"),
                "spec": record.get("spec"),
                "cls": record.get("cls"),
                "role": role,
            }
    return None

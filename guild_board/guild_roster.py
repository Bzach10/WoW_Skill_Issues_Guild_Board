"""Guild roster resolution across every authority we can reach.

Why this module exists
----------------------
Until now the roster's only live source was Warcraft Logs
(`wcl.fetch_guild_member_roster`, cached into `roster_cache.json`). That is
the wrong kind of source, and the failure it produces is silent.

**WCL's guild member list is a by-product of log uploads, not a guild
roster.** A character appears there because a report tagged to the guild
was parsed and their name was in it. A real, currently-raiding member who
has not surfaced in a parsed report — or whose WCL character record is not
linked to the guild — is simply absent, and nothing anywhere says so.

That is exactly how Phyrthepali went missing. He is a real Holy Paladin in
Skill Issues on Bleeding Hollow, the guild's own realm, with a 96 parse on
Imperator Averzian. He is present in Raider.io's guild roster at rank 99.
He was absent from `roster_cache.json`, therefore absent from
`competition.json`, therefore absent from the website — and the only reason
anyone noticed is that Zach happened to spot it.

Reconciling the two authorities on 2026-07-22 found he was **one of 15**,
not a one-off:

    raider.io guild roster   117 members
    wcl-derived cache        135 members
    union                    150 members
    competition.json         132 members  (88% of the union)

So the roster total was never a count. It was a floor.

The rules this module follows
-----------------------------
1. **Union, never intersect.** A member confirmed by *any* authority is a
   member. Sources disagree constantly — WCL retains people who have left,
   Raider.io lags on people who just joined — and the union is the only
   combination that cannot silently delete a real person.
2. **Disagreement is output, not a log line.** Every name that one source
   has and another lacks lands in a reconciliation report on disk, with the
   source that vouched for it. A roster gap has to be *visible* to get
   fixed; `logger.warning` scrolls past.
3. **`name-realm` is the identity.** Never the bare name. This roster
   really does contain two distinct characters called Beroben (Emerald
   Dream and Quel'dorei) and two called Violence that differ only in which
   vowel carries the diacritic (Viôlence / Violënce, both Bleeding Hollow).
4. **Fail loud, fail open.** A source that errors is recorded as
   `unreachable` and contributes nothing; it never empties the roster and
   never silently looks like an empty guild.

Note on Blizzard: Blizzard's `/data/wow/guild/{realm}/{guild}/roster`
endpoint is the true authority, and **no code in this project has ever
called it** — `blizzard.py` implements per-character profile lookups only.
Wiring it in is the right next step and needs `BLIZZARD_CLIENT_ID` /
`BLIZZARD_CLIENT_SECRET`; `fetch_blizzard_guild_roster` below is the seam
for it. Until then Raider.io's guild roster is the closest reachable stand-in
(Raider.io crawls Blizzard), and it is treated as a source, never as truth.
"""

import json
import logging
import os
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

RAIDERIO_GUILD_URL = "https://raider.io/api/v1/guilds/profile"

# Report path. Deliberately not under data/ — this is a build artifact that
# should be read by a human after every run, not consumed by the pipeline.
RECONCILIATION_PATH = "roster_reconciliation.json"


def member_key(name, realm_slug):
    """The one identity function. `name-realm`, lowercased, accents kept.

    Accents are **kept**: folding them collapses Viôlence and Violënce,
    who are two different people on the same realm.
    """
    return f"{(name or '').strip().lower()}-{(realm_slug or '').strip().lower()}"


def _guild_slug(name):
    """Blizzard's guild slug: lowercased, spaces to hyphens.

    "Skill Issues" -> "skill-issues".
    """
    return (name or "").strip().lower().replace("'", "").replace(" ", "-")


def _realm_slug(realm):
    """Raider.io gives display realms ("Lightning's Blade"); slugs are what
    every key and URL in this project uses."""
    return (realm or "").strip().lower().replace("'", "").replace(" ", "-")


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def fetch_raiderio_guild_roster(cfg, timeout=30):
    """Raider.io's guild roster -> {key: {...}}. Raises on transport error.

    Raider.io crawls Blizzard, so unlike WCL this is an actual guild roster:
    it includes members who have never appeared in a log.
    """
    guild = (cfg or {}).get("guild") or {}
    resp = requests.get(RAIDERIO_GUILD_URL, timeout=timeout, params={
        "region": guild.get("region", "us"),
        "realm": guild.get("realm_slug", ""),
        "name": guild.get("name", ""),
        "fields": "members",
    })
    resp.raise_for_status()
    payload = resp.json()

    members = {}
    for entry in payload.get("members") or []:
        char = entry.get("character") or {}
        name = char.get("name")
        if not name:
            continue
        slug = _realm_slug(char.get("realm"))
        members[member_key(name, slug)] = {
            "name": name,
            "realm_slug": slug,
            "realm": char.get("realm"),
            "rank": entry.get("rank"),
            "class": char.get("class"),
            "spec": char.get("active_spec_name"),
            "role": (char.get("active_spec_role") or "").lower() or None,
        }
    return members


BLIZZARD_OAUTH_URL = "https://oauth.battle.net/token"
BLIZZARD_API_HOST = "https://{region}.api.blizzard.com"


def fetch_blizzard_access_token(cfg, timeout=30):
    """OAuth client-credentials -> a bearer token, or None if unconfigured.

    Returns None (not an exception) when the credentials are absent, because
    "nobody has set these up yet" is the project's normal state and should
    read as an unavailable source rather than a crash. Anything else — bad
    credentials, a 5xx, a transport error — raises, because that is a
    genuine failure and a roster that silently falls back to a stale source
    is exactly how fifteen members went missing in the first place.
    """
    client_id = os.environ.get("BLIZZARD_CLIENT_ID")
    client_secret = os.environ.get("BLIZZARD_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None

    region = ((cfg or {}).get("guild") or {}).get("region", "us")
    resp = requests.post(
        BLIZZARD_OAUTH_URL,
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        timeout=timeout,
    )
    resp.raise_for_status()
    token = (resp.json() or {}).get("access_token")
    if not token:
        raise RuntimeError(
            "Blizzard OAuth returned 200 with no access_token; refusing to "
            "continue with an unauthenticated roster call."
        )
    logger.info("Blizzard OAuth: token acquired for region %s.", region)
    return token


def fetch_blizzard_guild_roster(cfg, token=None, timeout=30):
    """Blizzard's `/data/wow/guild/{realm}/{guild}/roster` -> {key: {...}}.

    **This is the authoritative roster.** Every other source in this module
    is a stand-in for it. Warcraft Logs knows who has appeared in an
    uploaded report; Raider.io knows who it last crawled; Blizzard knows who
    is in the guild. Only the third is the question being asked.

    Returns None when credentials are unset — the resolver records that as
    `unavailable`, a stated gap rather than a silent zero. It never invents
    a roster and never falls back quietly.

    Identity: the key is `name-realm` with the **exact Unicode name
    preserved**, because Viôlence and Violënce are two different people on
    one realm and folding accents merges them. Blizzard's own stable
    character `id` is carried through as `blizzard_id` so downstream code
    can key on it once every source can supply one.

    UNVERIFIED AGAINST THE LIVE API. Written 2026-07-22 in an environment
    with no network egress and no credentials, so it has never made a real
    request. The request shape follows Blizzard's documented profile API
    (client-credentials OAuth, `namespace=profile-{region}`). Treat the
    first live run as the test: it will either return members or raise.
    """
    guild = (cfg or {}).get("guild") or {}
    region = guild.get("region", "us")
    realm_slug = guild.get("realm_slug", "")
    guild_slug = guild.get("name_slug") or _guild_slug(guild.get("name", ""))

    if not realm_slug or not guild_slug:
        logger.warning(
            "Blizzard guild roster: cfg.guild is missing realm_slug or name "
            "(realm=%r guild=%r). Not guessing — reporting unavailable.",
            realm_slug, guild_slug)
        return None

    token = token or fetch_blizzard_access_token(cfg, timeout=timeout)
    if not token:
        logger.info(
            "Blizzard guild roster: BLIZZARD_CLIENT_ID / "
            "BLIZZARD_CLIENT_SECRET are unset, so the authoritative roster "
            "cannot be fetched. Falling back to the reachable sources and "
            "recording this one as unavailable.")
        return None

    url = "{host}/data/wow/guild/{realm}/{guild}/roster".format(
        host=BLIZZARD_API_HOST.format(region=region),
        realm=realm_slug, guild=guild_slug)
    resp = requests.get(
        url, timeout=timeout,
        headers={"Authorization": "Bearer %s" % token},
        params={"namespace": "profile-%s" % region, "locale": "en_US"},
    )
    resp.raise_for_status()
    payload = resp.json() or {}

    members = {}
    for entry in payload.get("members") or []:
        char = entry.get("character") or {}
        name = char.get("name")
        realm = (char.get("realm") or {})
        slug = realm.get("slug") or _realm_slug(realm.get("name"))
        if not name or not slug:
            # Never skip silently: a member the authority returned and we
            # could not key is a roster gap, and roster gaps fail loud.
            logger.warning(
                "Blizzard guild roster: member with name=%r realm=%r could "
                "not be keyed and was NOT counted. This is a gap, not a "
                "no-op.", name, slug)
            continue
        members[member_key(name, slug)] = {
            "name": name,                       # exact, Unicode preserved
            "realm_slug": slug,
            "realm": realm.get("name"),
            "rank": entry.get("rank"),
            "class": ((char.get("playable_class") or {}).get("name")),
            "spec": None,                       # not in the roster payload
            "role": None,                       # derived downstream from spec
            "blizzard_id": char.get("id"),      # stable identity, when present
            "level": char.get("level"),
        }
    logger.info("Blizzard guild roster: %d members (the authority).",
                len(members))
    return members


SUPPLEMENT_PATHS = ("data/roster_supplement.json", "roster_supplement.json")


def load_supplement(path=None):
    """Members confirmed real by a human or a live API, absent from the pull.

    The lowest-tech source and the highest-trust one: every entry carries
    re-checkable `evidence`. Loaded by default so that when *every* network
    source is unreachable, the members we already know the pull misses do
    not disappear again. Entries without evidence are skipped and named.
    """
    candidates = [path] if path else SUPPLEMENT_PATHS
    for candidate in candidates:
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        rows = []
        for entry in data.get("characters") or []:
            if not entry.get("evidence"):
                logger.warning("roster_supplement entry %r has no `evidence`; "
                               "skipping it.", entry.get("key") or entry)
                continue
            rows.append(entry)
        return rows
    return []


def wcl_roster_entries(roster_list):
    """The existing `name-realm` string list (roster_cache.json / WCL) as
    the same dict shape, so every source can be merged uniformly."""
    members = {}
    for entry in roster_list or []:
        if not isinstance(entry, str) or "-" not in entry:
            continue
        name, realm = entry.split("-", 1)
        members[member_key(name, realm)] = {
            "name": name, "realm_slug": realm, "realm": None,
            "rank": None, "class": None, "spec": None, "role": None,
        }
    return members


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

# Sources that only ever list *part* of the roster. They contribute members
# but must not count towards agreement: the supplement exists precisely to
# hold members the other sources lack, so including it would mark every
# single member "disputed" and make the signal useless.
PARTIAL_SOURCES = ("supplement",)


def merge_sources(sources, partial=PARTIAL_SOURCES):
    """sources: {source_name: {key: info} | None}. None = unreachable.

    Returns (members, report). `members` is the UNION keyed by name-realm,
    each carrying `sources` (who vouched for them) and the richest field
    values seen. Nobody is ever dropped for appearing in only one source.
    """
    members = {}
    reachable = [n for n, m in sources.items()
                 if m is not None and n not in partial]

    for source_name in sorted(sources):
        found = sources[source_name]
        if found is None:
            continue
        for key, info in found.items():
            row = members.setdefault(key, {"key": key, "sources": []})
            row["sources"].append(source_name)
            for field, value in info.items():
                # First non-empty value wins; sources are merged, not
                # overwritten, so a thin source never blanks a rich one.
                if value not in (None, "") and not row.get(field):
                    row[field] = value

    for row in members.values():
        row["sources"] = sorted(set(row["sources"]))
        # Present in some full-roster sources but not all -> needs a human.
        # A member vouched for ONLY by a partial source is disputed too:
        # that is exactly the Phyrthepali case.
        full_backing = [s for s in row["sources"] if s not in partial]
        row["disputed"] = len(full_backing) < len(reachable)

    report = build_report(sources, members, partial)
    return members, report


def build_report(sources, members, partial=PARTIAL_SOURCES):
    """The disagreement, written down. This is the point of the module."""
    reachable = {n: m for n, m in sources.items()
                 if m is not None and n not in partial}
    unreachable = sorted(n for n, m in sources.items()
                         if m is None and n not in partial)

    only_in = {}
    missing_from = {}
    for source_name, found in reachable.items():
        others = set()
        for other_name, other in reachable.items():
            if other_name != source_name:
                others |= set(other)
        only_in[source_name] = sorted(set(found) - others)
        missing_from[source_name] = sorted(
            k for k in members if k not in found)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {n: len(m) for n, m in reachable.items()},
        "unreachable_sources": unreachable,
        "roster_total": len(members),
        "agreed_by_all_reachable_sources": sum(
            1 for r in members.values() if not r["disputed"]),
        # Every member some source has and another lacks. Each of these is
        # either a real member one source is missing, or a departed member
        # another is retaining. Both need a human; neither gets deleted.
        "disputed_members": sorted(
            ({"key": r["key"], "name": r.get("name"),
              "realm_slug": r.get("realm_slug"), "rank": r.get("rank"),
              "confirmed_by": r["sources"]}
             for r in members.values() if r["disputed"]),
            key=lambda r: r["key"]),
        "only_in_source": only_in,
        "missing_from_source": missing_from,
    }


def write_report(report, path=RECONCILIATION_PATH):
    """Fail-open: a report we couldn't write must not break a build."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
    except OSError as exc:
        logger.warning("Could not write %s: %s", path, exc)
        return False
    return True


def resolve(cfg, wcl_roster=None, supplement=None, raiderio_fetch=None,
            blizzard_fetch=None, report_path=RECONCILIATION_PATH):
    """The roster, from every authority available, unioned.

    Returns (members, report). Injectable fetchers so this is testable
    without a network.
    """
    raiderio_fetch = raiderio_fetch or fetch_raiderio_guild_roster
    blizzard_fetch = blizzard_fetch or fetch_blizzard_guild_roster

    sources = {}

    try:
        sources["raiderio"] = raiderio_fetch(cfg)
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Raider.io guild roster unreachable (%s); it will be "
                       "recorded as a gap, not treated as an empty guild.", exc)
        sources["raiderio"] = None

    try:
        sources["blizzard"] = blizzard_fetch(cfg)
    except Exception as exc:  # noqa: BLE001 - a seam; never fatal
        logger.warning("Blizzard guild roster unreachable (%s).", exc)
        sources["blizzard"] = None

    sources["wcl_cache"] = wcl_roster_entries(wcl_roster) if wcl_roster else None

    # Default to the on-disk supplement. Passing supplement=[] disables it.
    if supplement is None:
        supplement = load_supplement()

    if supplement:
        # Human-confirmed members with evidence. Lowest-tech source, highest
        # trust: someone looked at a real page and wrote down what they saw.
        sources["supplement"] = {
            member_key(m.get("name"), m.get("realm_slug")): {
                "name": m.get("name"), "realm_slug": m.get("realm_slug"),
                "realm": m.get("realm"), "class": m.get("class"),
                "spec": m.get("spec"), "role": m.get("role"),
            } for m in supplement if m.get("name") and m.get("realm_slug")
        }

    members, report = merge_sources(sources)

    if report["disputed_members"]:
        logger.warning(
            "Roster reconciliation: %s of %s members are confirmed by only "
            "some sources. They are all KEPT. See %s for who and why.",
            len(report["disputed_members"]), report["roster_total"], report_path)
    if report["unreachable_sources"]:
        logger.warning("Roster sources unreachable this run: %s. The roster "
                       "total below is a FLOOR, not a count.",
                       ", ".join(report["unreachable_sources"]))

    write_report(report, report_path)
    return members, report


def detect_name_collisions(members):
    """Characters that share a bare name — where name-keying loses data.

    This is not hypothetical and it is not only a display bug.
    `board_state.json.season_scores` is keyed by bare character name, so
    the two Berobens share one slot: it holds 1907.8 (the Quel'dorei
    Protection Paladin) and the Emerald Dream Mage's 2307.3 is simply
    **gone** — overwritten, not merged. Every bare-name key in this repo
    silently destroys one of the two.

    Returns {bare_name: [keys...]} for every name held by more than one
    character. Callers should surface it, loudly.
    """
    by_name = {}
    for key, row in (members or {}).items():
        name = (row.get("name") or key.rsplit("-", 1)[0]).strip().lower()
        by_name.setdefault(name, []).append(key)
    return {n: sorted(k) for n, k in by_name.items() if len(k) > 1}


def warn_about_collisions(members, logger_=None):
    """Log every bare-name collision at WARNING. Returns the collisions."""
    log = logger_ or logger
    collisions = detect_name_collisions(members)
    for name, keys in sorted(collisions.items()):
        log.warning(
            "Name collision: %s distinct characters are named %r (%s). Any "
            "data keyed by bare name — season_scores, streaks, profile links "
            "— holds only ONE of them and silently discards the rest.",
            len(keys), name, ", ".join(keys))
    return collisions


def roster_keys(members):
    """Just the `name-realm` keys, sorted — the shape the rest of the
    pipeline already consumes."""
    return sorted(members)

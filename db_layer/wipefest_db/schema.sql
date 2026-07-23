-- S.S. Wipe Fest — data layer, Phase 1 schema
-- Built to docs/DATABASE_DESIGN.md §3 (surrogate-key model).
--
-- PRIMARY KEY MODEL (settled; do not relitigate — see docs/DECISIONS.md):
--   The primary key is a project-owned surrogate `character.character_id`.
--   Blizzard's numeric character id is NEVER a key. It is stored as an
--   observed, fallible attribute on character_identity.blizzard_id, because
--   Blizzard staff confirmed (2020-09-28) it collides across realms/regions
--   and CHANGES on realm transfer. Making it the PK would re-introduce the
--   Beroben collision. [verified]
--
-- Names are stored EXACT (NFC Unicode). Accent-folding lives only in
-- character_identity.name_folded, which is SEARCH/DISPLAY only and is NEVER
-- a join or uniqueness key. Viôlence and Violënce are two rows, forever.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- 3.5  Provenance & coverage — the fail-loud spine (created first: FKs target it)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fetch_run (
  run_id            INTEGER PRIMARY KEY,
  source            TEXT NOT NULL,          -- blizzard | raiderio | warcraftlogs | manual | legacy_json
  endpoint          TEXT NOT NULL,
  started_at        TEXT NOT NULL,          -- ISO8601 UTC
  finished_at       TEXT,
  outcome           TEXT NOT NULL,          -- 'success' | 'partial' | 'failed'
  targets_attempted INTEGER,
  targets_succeeded INTEGER,
  http_429_count    INTEGER DEFAULT 0,
  error_summary     TEXT,
  raw_capture_path  TEXT,
  CHECK (outcome IN ('success','partial','failed'))
);

CREATE TABLE IF NOT EXISTS fetch_attempt (
  attempt_id   INTEGER PRIMARY KEY,
  run_id       INTEGER NOT NULL REFERENCES fetch_run(run_id),
  character_id INTEGER REFERENCES character(character_id),
  target_key   TEXT,                        -- for targets with no surrogate yet
  http_status  INTEGER,
  outcome      TEXT NOT NULL,               -- 'ok' | 'not_found' | 'error' | 'skipped_304'
  error        TEXT,
  CHECK (outcome IN ('ok','not_found','error','skipped_304'))
);
CREATE INDEX IF NOT EXISTS ix_fetch_attempt_run ON fetch_attempt(run_id);

-- ---------------------------------------------------------------------------
-- 3.1  Identity layer — the surrogate. Anything mutable is banned from here.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS character (
  character_id      INTEGER PRIMARY KEY,    -- OURS. Never from Blizzard.
  first_observed_at TEXT NOT NULL,          -- ISO8601 UTC
  player_id         INTEGER,                -- deferred seam (0.1/3.1a). Always NULL in phase one.
  merged_into       INTEGER REFERENCES character(character_id),  -- NULL = live
  merged_at         TEXT,
  merged_reason     TEXT
  -- NB: player_id REFERENCES player(player_id) is intentionally omitted:
  --     no player table exists in phase one. The column is the reserved seam.
);

CREATE TABLE IF NOT EXISTS character_identity (   -- observations of who a surrogate appeared as
  identity_id    INTEGER PRIMARY KEY,
  character_id   INTEGER NOT NULL REFERENCES character(character_id),
  region         TEXT NOT NULL,             -- 'us'
  realm_slug     TEXT NOT NULL,             -- 'bleeding-hollow' (the CHARACTER's realm)
  name           TEXT NOT NULL,             -- EXACT Unicode. 'Violence(accented)'. Never folded.
  name_folded    TEXT NOT NULL,             -- accent-folded, SEARCH & DISPLAY ONLY. Never a key.
  blizzard_id    INTEGER,                   -- observed, NOT a key. May change. May collide.
  observed_from  TEXT NOT NULL,
  observed_to    TEXT,                      -- NULL = current
  source         TEXT NOT NULL,
  run_id         INTEGER NOT NULL REFERENCES fetch_run(run_id)
);
-- The one invariant that matters: at any moment, one (region, realm, EXACT name)
-- maps to exactly one surrogate. Index is on `name`, not `name_folded`.
CREATE UNIQUE INDEX IF NOT EXISTS ux_identity_current
  ON character_identity(region, realm_slug, name) WHERE observed_to IS NULL;
CREATE INDEX IF NOT EXISTS ix_identity_char    ON character_identity(character_id);
CREATE INDEX IF NOT EXISTS ix_identity_folded  ON character_identity(region, realm_slug, name_folded);
CREATE INDEX IF NOT EXISTS ix_identity_blizzid ON character_identity(blizzard_id);

CREATE TABLE IF NOT EXISTS identity_link_candidate (  -- proposed renames/transfers. NEVER auto-applied.
  candidate_id     INTEGER PRIMARY KEY,
  from_character   INTEGER NOT NULL REFERENCES character(character_id),
  to_character     INTEGER NOT NULL REFERENCES character(character_id),
  confidence       TEXT NOT NULL,           -- 'high' | 'medium' | 'low'
  evidence_json    TEXT NOT NULL,
  proposed_at      TEXT NOT NULL,
  status           TEXT NOT NULL DEFAULT 'pending',
  decided_by       TEXT,
  decided_at       TEXT,
  decided_note     TEXT,
  CHECK (confidence IN ('high','medium','low')),
  CHECK (status IN ('pending','accepted','rejected'))
);

-- ---------------------------------------------------------------------------
-- 3.2  Membership as intervals — never delete a member
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS guild (
  guild_id     INTEGER PRIMARY KEY,
  region       TEXT NOT NULL,
  realm_slug   TEXT NOT NULL,               -- the GUILD's realm: 'bleeding-hollow'
  name_slug    TEXT NOT NULL,               -- 'skill-issues'
  display_name TEXT NOT NULL,               -- 'Skill Issues'
  UNIQUE (region, realm_slug, name_slug)
);

CREATE TABLE IF NOT EXISTS membership_interval (
  interval_id     INTEGER PRIMARY KEY,
  character_id    INTEGER NOT NULL REFERENCES character(character_id),
  guild_id        INTEGER NOT NULL REFERENCES guild(guild_id),
  observed_from   TEXT NOT NULL,            -- first run that SAW them ("seen since", not "member since")
  observed_to     TEXT,                     -- NULL = currently a member
  rank            INTEGER,                  -- Blizzard guild rank, 0 = GM
  first_run_id    INTEGER NOT NULL REFERENCES fetch_run(run_id),
  last_run_id     INTEGER NOT NULL REFERENCES fetch_run(run_id),
  closed_run_id   INTEGER REFERENCES fetch_run(run_id),
  closed_reason   TEXT                      -- 'absent_from_complete_roster_pull' | 'manual'
);
CREATE INDEX IF NOT EXISTS ix_membership_char  ON membership_interval(character_id);
CREATE INDEX IF NOT EXISTS ix_membership_open  ON membership_interval(guild_id) WHERE observed_to IS NULL;

-- ---------------------------------------------------------------------------
-- 3.3  Facts — append-only observations. NEVER UPDATE, NEVER DELETE.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mplus_score_observation (
  obs_id       INTEGER PRIMARY KEY,
  character_id INTEGER NOT NULL REFERENCES character(character_id),
  season       TEXT NOT NULL,
  role         TEXT NOT NULL,               -- 'all' | 'dps' | 'healer' | 'tank'
  score        REAL NOT NULL,
  source       TEXT NOT NULL,
  observed_at  TEXT NOT NULL,               -- when the fact was TRUE (as-of)
  ingested_at  TEXT NOT NULL,               -- when WE recorded it
  run_id       INTEGER NOT NULL REFERENCES fetch_run(run_id),
  source_url   TEXT
);
CREATE INDEX IF NOT EXISTS ix_mplus_score_latest
  ON mplus_score_observation(character_id, season, role, source, observed_at DESC);

CREATE TABLE IF NOT EXISTS mplus_run_observation (
  obs_id       INTEGER PRIMARY KEY,
  character_id INTEGER NOT NULL REFERENCES character(character_id),
  season       TEXT,
  dungeon_id   INTEGER,
  dungeon_name TEXT,
  key_level    INTEGER,
  timed        INTEGER,
  upgrades     INTEGER,
  score        REAL,
  clear_ms     INTEGER,
  par_ms       INTEGER,
  completed_at TEXT,
  run_ref      TEXT,
  source       TEXT NOT NULL,
  observed_at  TEXT NOT NULL,
  ingested_at  TEXT NOT NULL,
  run_id       INTEGER NOT NULL REFERENCES fetch_run(run_id),
  source_url   TEXT
);
CREATE INDEX IF NOT EXISTS ix_mplus_run_char ON mplus_run_observation(character_id, season);
CREATE INDEX IF NOT EXISTS ix_mplus_run_ref  ON mplus_run_observation(run_ref);

CREATE TABLE IF NOT EXISTS raid_kill_observation (
  obs_id        INTEGER PRIMARY KEY,
  character_id  INTEGER NOT NULL REFERENCES character(character_id),
  instance      TEXT,
  difficulty    TEXT,
  encounter_id  INTEGER,
  killed        INTEGER,
  first_kill_at TEXT,
  report_code   TEXT,
  fight_id      INTEGER,
  source        TEXT NOT NULL,
  observed_at   TEXT NOT NULL,
  ingested_at   TEXT NOT NULL,
  run_id        INTEGER NOT NULL REFERENCES fetch_run(run_id),
  source_url    TEXT
);
CREATE INDEX IF NOT EXISTS ix_raidkill_char ON raid_kill_observation(character_id, encounter_id, difficulty);

CREATE TABLE IF NOT EXISTS parse_observation (
  obs_id        INTEGER PRIMARY KEY,
  character_id  INTEGER NOT NULL REFERENCES character(character_id),
  encounter_id  INTEGER,
  difficulty    TEXT,
  metric        TEXT,
  percentile    REAL,
  amount        REAL,
  report_code   TEXT,
  fight_id      INTEGER,
  keystone_level INTEGER,
  source        TEXT NOT NULL,
  observed_at   TEXT NOT NULL,
  ingested_at   TEXT NOT NULL,
  run_id        INTEGER NOT NULL REFERENCES fetch_run(run_id),
  source_url    TEXT
);
CREATE INDEX IF NOT EXISTS ix_parse_char ON parse_observation(character_id, encounter_id, difficulty, metric);

CREATE TABLE IF NOT EXISTS character_profile_observation (
  obs_id             INTEGER PRIMARY KEY,
  character_id       INTEGER NOT NULL REFERENCES character(character_id),
  class              TEXT,
  race               TEXT,
  spec               TEXT,
  level              INTEGER,
  faction            TEXT,
  achievement_points INTEGER,
  render_url         TEXT,
  transmog_fingerprint TEXT,
  source             TEXT NOT NULL,
  observed_at        TEXT NOT NULL,
  ingested_at        TEXT NOT NULL,
  run_id             INTEGER NOT NULL REFERENCES fetch_run(run_id),
  source_url         TEXT
);
CREATE INDEX IF NOT EXISTS ix_profile_char ON character_profile_observation(character_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS guild_progress_observation (
  obs_id        INTEGER PRIMARY KEY,
  character_id  INTEGER REFERENCES character(character_id),  -- nullable: guild-level fact
  guild_id      INTEGER REFERENCES guild(guild_id),
  instance      TEXT,
  difficulty    TEXT,
  bosses_killed INTEGER,
  bosses_total  INTEGER,
  world_rank    INTEGER,
  region_rank   INTEGER,
  realm_rank    INTEGER,
  source        TEXT NOT NULL,
  observed_at   TEXT NOT NULL,
  ingested_at   TEXT NOT NULL,
  run_id        INTEGER NOT NULL REFERENCES fetch_run(run_id),
  source_url    TEXT
);

-- ---------------------------------------------------------------------------
-- 3.4  Source precedence, as data (seeded from config, never hardcoded)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS field_authority (
  field          TEXT NOT NULL,
  source         TEXT NOT NULL,
  rank           INTEGER NOT NULL,          -- 1 = highest authority
  max_age_hours  INTEGER,
  tolerance      REAL,
  PRIMARY KEY (field, source)
);

-- ---------------------------------------------------------------------------
-- 3.6  Views — the site build reads views only (precedence is a read-time concern)
-- ---------------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_current_identity AS
  SELECT character_id, region, realm_slug, name, name_folded, blizzard_id, observed_from, source
  FROM character_identity
  WHERE observed_to IS NULL;

CREATE VIEW IF NOT EXISTS v_current_roster AS
  SELECT ci.character_id, ci.region, ci.realm_slug, ci.name, ci.name_folded,
         g.display_name AS guild, mi.rank, mi.observed_from AS seen_since
  FROM membership_interval mi
  JOIN guild g               ON g.guild_id = mi.guild_id
  JOIN v_current_identity ci ON ci.character_id = mi.character_id
  WHERE mi.observed_to IS NULL;

CREATE VIEW IF NOT EXISTS v_mplus_score_resolved AS
WITH latest_per_source AS (
  SELECT character_id, season, role, source, score, observed_at, source_url,
         ROW_NUMBER() OVER (PARTITION BY character_id, season, role, source
                            ORDER BY observed_at DESC, obs_id DESC) AS rn
  FROM mplus_score_observation
),
ranked AS (
  SELECT lps.character_id, lps.season, lps.role, lps.source, lps.score,
         lps.observed_at, lps.source_url, fa.rank AS authority_rank, fa.tolerance
  FROM latest_per_source lps
  JOIN field_authority fa ON fa.field = 'mplus_score' AND fa.source = lps.source
  WHERE lps.rn = 1
    AND (fa.max_age_hours IS NULL
         OR (julianday('now') - julianday(lps.observed_at)) * 24.0 <= fa.max_age_hours)
),
spread AS (
  SELECT character_id, season, role,
         MAX(score) - MIN(score) AS score_spread, MIN(tolerance) AS tol
  FROM ranked GROUP BY character_id, season, role
),
winner AS (
  SELECT r.*,
         ROW_NUMBER() OVER (PARTITION BY r.character_id, r.season, r.role
                            ORDER BY r.authority_rank ASC, r.observed_at DESC) AS wn
  FROM ranked r
)
SELECT w.character_id, w.season, w.role,
       w.source AS winning_source, w.score, w.observed_at, w.source_url,
       CASE WHEN s.score_spread > COALESCE(s.tol, 0) THEN 1 ELSE 0 END AS has_conflict
FROM winner w
JOIN spread s ON s.character_id = w.character_id AND s.season = w.season AND s.role = w.role
WHERE w.wn = 1;

CREATE VIEW IF NOT EXISTS v_source_disagreement AS
WITH latest_per_source AS (
  SELECT character_id, season, role, source, score,
         ROW_NUMBER() OVER (PARTITION BY character_id, season, role, source
                            ORDER BY observed_at DESC, obs_id DESC) AS rn
  FROM mplus_score_observation
)
SELECT character_id, season, role, COUNT(*) AS source_count,
       MIN(score) AS min_score, MAX(score) AS max_score, MAX(score) - MIN(score) AS spread
FROM latest_per_source WHERE rn = 1
GROUP BY character_id, season, role
HAVING COUNT(*) > 1 AND (MAX(score) - MIN(score)) > 0;

CREATE VIEW IF NOT EXISTS v_coverage_report AS
  SELECT source,
         MAX(CASE WHEN outcome = 'success' THEN finished_at END) AS last_success_at,
         COUNT(*)                                             AS total_runs,
         SUM(CASE WHEN outcome = 'failed'  THEN 1 ELSE 0 END) AS failed_runs,
         SUM(CASE WHEN outcome = 'partial' THEN 1 ELSE 0 END) AS partial_runs
  FROM fetch_run GROUP BY source;

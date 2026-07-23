"""Load the source-precedence config and seed the field_authority table.

The precedence table is DATA, not code (docs/DATABASE_DESIGN.md §3.4): changing
which source wins is a config edit + rebuild, never a re-ingestion. This loader
is the only writer of field_authority, and it fully replaces the table so the
config file is the single source of truth. field_authority holds CONFIG, not
observations, so replacing it does not violate the append-only fact rule.

Canonical config is JSON (stdlib-only, so it loads under host pytest without a
pip install). If PyYAML happens to be present a .yml/.yaml file is also accepted.
"""
from __future__ import annotations

import json
import os

_DEFAULT_CONFIG = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config", "source_precedence.json"
)


def load_config(path: str = _DEFAULT_CONFIG) -> dict:
    if path.endswith((".yml", ".yaml")):
        try:
            import yaml  # optional
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "YAML config requested but PyYAML is not installed; use the .json config"
            ) from exc
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def seed_field_authority(conn, path: str = _DEFAULT_CONFIG) -> int:
    cfg = load_config(path)
    rows = cfg["fields"]
    # Validate before writing: no duplicate (field, source); rank is a positive int.
    seen = set()
    for r in rows:
        key = (r["field"], r["source"])
        if key in seen:
            raise ValueError(f"duplicate precedence entry for {key}")
        if not isinstance(r["rank"], int) or r["rank"] < 1:
            raise ValueError(f"rank must be a positive int for {key}, got {r['rank']!r}")
        seen.add(key)
    conn.execute("DELETE FROM field_authority")  # config replace, not a fact mutation
    conn.executemany(
        """INSERT INTO field_authority(field, source, rank, max_age_hours, tolerance)
           VALUES (:field, :source, :rank, :max_age_hours, :tolerance)""",
        [
            {
                "field": r["field"], "source": r["source"], "rank": r["rank"],
                "max_age_hours": r.get("max_age_hours"), "tolerance": r.get("tolerance"),
            }
            for r in rows
        ],
    )
    conn.commit()
    return len(rows)

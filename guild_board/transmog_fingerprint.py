"""A cheap, deterministic "did their look change" signal for the weekly
diff step. Blizzard's render URL encodes an internal render id that
changes whenever the character's equipped appearance changes — so
hashing the URL is a reliable proxy for "the transmog changed" without
downloading and diffing the actual image every week.
"""

import hashlib
import json


def compute_transmog_fingerprint(profile):
    """profile: one blizzard_profile_cache.json character entry.

    Falls back to hashing the whole profile dict if transmog_render_url
    is missing, so a character with an incomplete profile still gets a
    stable (if less precise) fingerprint rather than crashing the diff.
    """
    url = (profile or {}).get("transmog_render_url")
    if url:
        basis = url
    else:
        basis = json.dumps(profile or {}, sort_keys=True)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()

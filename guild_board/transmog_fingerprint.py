"""A cheap, deterministic "does this character's art need regenerating"
signal for the weekly diff step.

Despite the module name this is a fingerprint over every input that feeds
generation, not just the transmog:

  - transmog_render_url — the IP-Adapter likeness reference. Blizzard's
    render URL embeds an internal render id that changes whenever the
    equipped appearance changes, so hashing the URL detects a transmog
    change without downloading and diffing the image every week.
  - race / class / gender / active_spec — cast_art.build_prompt() puts all
    four into the positive prompt (and gender into the negative), so a
    change to any of them means the prompt, and therefore the art, is stale.

Hashing only the URL (the original behaviour) missed that second group: a
character who respecced kept their old art indefinitely, because the render
URL had not moved. Hashing the *whole* profile dict — the old no-URL
fallback — had the opposite failure, keying on incidental fields so that
unrelated profile churn burned GPU time on needless regeneration.
"""

import hashlib
import json

# The exact fields generation depends on. Anything not listed here must not
# move the fingerprint; anything build_prompt() or the IP-Adapter reference
# starts consuming must be added here.
ART_INPUT_FIELDS = (
    "transmog_render_url",
    "race",
    "class",
    "gender",
    "active_spec",
)


def compute_transmog_fingerprint(profile):
    """profile: one blizzard_profile_cache.json character entry (or a
    cast_manifest.json character entry — see the `spec` note below).

    Returns a stable sha256 hex digest over ART_INPUT_FIELDS. Missing
    fields are hashed as empty strings rather than omitted, so a profile
    that later gains a render URL fingerprints differently from one that
    never had it — which is exactly a case we want to regenerate on.
    """
    profile = profile or {}
    basis = {field: (profile.get(field) or "") for field in ART_INPUT_FIELDS}
    # The raw Blizzard profile calls it "active_spec"; cast_manifest stores
    # it as "spec". Accept either so a manifest entry and the profile it was
    # built from fingerprint identically.
    if not basis["active_spec"]:
        basis["active_spec"] = profile.get("spec") or ""
    payload = json.dumps(basis, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

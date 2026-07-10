import logging

logger = logging.getLogger(__name__)

# Two fights in different reports are the same pull if they match on
# encounter, difficulty, and outcome, start within 60s of each other
# (allows for clock drift between loggers' PCs), and have durations
# within 15s of each other (separates rapid re-pulls of the same boss).
FIGHT_START_TOLERANCE_MS = 60_000
FIGHT_DURATION_TOLERANCE_MS = 15_000


class FightDeduper:
    """Recognizes the same boss pull appearing in multiple uploaded reports."""

    def __init__(self):
        self._seen = []

    def check_and_add(self, encounter_id, difficulty, kill, abs_start_ms, duration_ms):
        """Return True if this pull was already counted; otherwise record it."""
        for (enc, diff, was_kill, start, duration) in self._seen:
            if (
                enc == encounter_id
                and diff == difficulty
                and was_kill == kill
                and abs(start - abs_start_ms) <= FIGHT_START_TOLERANCE_MS
                and abs(duration - duration_ms) <= FIGHT_DURATION_TOLERANCE_MS
            ):
                return True
        self._seen.append((encounter_id, difficulty, kill, abs_start_ms, duration_ms))
        return False


def report_sort_key(report, preferred_uploader):
    """Process the designated primary logger's reports first, then longest
    reports first, so the most complete log is the source of truth and
    fragments dedupe against it."""
    owner = ((report.get("owner") or {}).get("name") or "").strip().lower()
    is_preferred = bool(preferred_uploader) and owner == preferred_uploader
    duration = (report.get("endTime") or 0) - (report.get("startTime") or 0)
    return (0 if is_preferred else 1, -duration)

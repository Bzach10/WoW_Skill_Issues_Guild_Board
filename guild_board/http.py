"""Shared HTTP session + rate limiting for the third-party APIs.

Two problems this solves, both measured against Raider.io with the real
135-member roster:

1. Every collector called ``requests.get`` at module level, so each request
   opened a fresh TCP+TLS connection. Reusing one pooled session cut a
   20-character pass from 12.5s to 7.0s — 1.78x, and 84s to 47s over the
   full roster.

2. Pacing was a hardcoded ``time.sleep(0.3)`` after each request. That is a
   floor on latency, not a real rate limit: it does not account for request
   time, and it cannot be shared across threads if anything is ever
   parallelised. ``RateLimiter`` is a token bucket over wall-clock time, so
   the aggregate rate is what is actually capped.

Raider.io publishes a limit of 300 requests/minute (5/s). DEFAULT_RATE
leaves deliberate headroom below that — being throttled costs far more than
the seconds saved by crowding the ceiling.
"""

import threading
import time

import requests

# Raider.io allows 5 req/s. 3/s keeps clear headroom for retries and for
# anything else on the same IP (a dev running the board locally while the
# scheduled job fires, for instance).
DEFAULT_RATE = 3.0

# Matches the worker count the pool is sized for; see get_session().
DEFAULT_POOL_SIZE = 8


class RateLimiter:
    """Token bucket enforcing an aggregate requests-per-second ceiling.

    Thread-safe: the reservation is made under a lock and the sleep happens
    outside it, so N threads sharing one limiter self-schedule into
    non-overlapping slots instead of all sleeping the same interval and
    then firing simultaneously.
    """

    def __init__(self, per_second=DEFAULT_RATE):
        if per_second <= 0:
            raise ValueError("per_second must be positive")
        self.interval = 1.0 / per_second
        self._lock = threading.Lock()
        self._next_slot = time.monotonic()

    def acquire(self):
        """Block until this caller's slot is due."""
        with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next_slot - now)
            # max(now, ...) stops an idle period from banking credit and
            # releasing a burst that exceeds the ceiling.
            self._next_slot = max(now, self._next_slot) + self.interval
        if wait:
            time.sleep(wait)


_session = None
_session_lock = threading.Lock()


def get_session(pool_size=DEFAULT_POOL_SIZE):
    """Return the process-wide pooled session, creating it on first use."""
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                session = requests.Session()
                adapter = requests.adapters.HTTPAdapter(
                    pool_connections=pool_size, pool_maxsize=pool_size)
                session.mount("https://", adapter)
                session.mount("http://", adapter)
                _session = session
    return _session


def reset_session():
    """Drop the pooled session. For tests, and for long-lived processes that
    want to force fresh connections."""
    global _session
    with _session_lock:
        if _session is not None:
            _session.close()
        _session = None

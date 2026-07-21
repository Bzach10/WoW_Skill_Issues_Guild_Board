"""Offline tests for guild_board.http (pooled session + rate limiter).

No network. The limiter is tested against a fake clock so the suite stays
fast and deterministic — sleeping for real would make these the slowest
tests in the project for no added confidence.
"""

import threading

import pytest

from guild_board import http


@pytest.fixture(autouse=True)
def _reset():
    http.reset_session()
    yield
    http.reset_session()


class FakeClock:
    """Stands in for time.monotonic/time.sleep so elapsed time is exact."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(http.time, "monotonic", fake.monotonic)
    monkeypatch.setattr(http.time, "sleep", fake.sleep)
    return fake


# --- session pooling

def test_get_session_returns_the_same_session():
    assert http.get_session() is http.get_session()


def test_get_session_mounts_a_pooled_adapter():
    session = http.get_session(pool_size=8)
    adapter = session.get_adapter("https://raider.io/api/v1/characters/profile")
    assert adapter._pool_maxsize == 8


def test_reset_session_forces_a_new_one():
    first = http.get_session()
    http.reset_session()
    assert http.get_session() is not first


def test_get_session_is_thread_safe():
    """Concurrent first-use must not create competing sessions."""
    seen = []
    barrier = threading.Barrier(8)

    def grab():
        barrier.wait()
        seen.append(http.get_session())

    threads = [threading.Thread(target=grab) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len({id(s) for s in seen}) == 1


# --- rate limiting

def test_first_acquire_does_not_sleep(clock):
    http.RateLimiter(per_second=5).acquire()
    assert clock.sleeps == []


def test_acquire_paces_subsequent_calls(clock):
    limiter = http.RateLimiter(per_second=5)  # one slot every 0.2s
    for _ in range(4):
        limiter.acquire()
    assert clock.sleeps == pytest.approx([0.2, 0.2, 0.2])


def test_limiter_does_not_bank_credit_while_idle(clock):
    """An idle gap must not release a burst that exceeds the ceiling — the
    reason _next_slot is clamped forward to `now`."""
    limiter = http.RateLimiter(per_second=5)
    limiter.acquire()
    clock.now += 60.0  # a long idle period
    limiter.acquire()
    limiter.acquire()
    # The call after the gap is free; the one after it still waits a full slot.
    assert clock.sleeps == pytest.approx([0.2])


def test_aggregate_rate_holds_across_threads():
    """The ceiling is on aggregate throughput, so N threads sharing one
    limiter must not each get their own allowance. Uses the real clock
    because the point is cross-thread behaviour."""
    limiter = http.RateLimiter(per_second=50)  # 0.02s slots, 20 calls = ~0.38s
    import time as real_time
    start = real_time.monotonic()
    threads = [threading.Thread(target=limiter.acquire) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = real_time.monotonic() - start
    # 20 calls at 50/s cannot legitimately finish faster than 19 intervals.
    assert elapsed >= 19 * 0.02 * 0.8


def test_rate_must_be_positive():
    with pytest.raises(ValueError):
        http.RateLimiter(per_second=0)
    with pytest.raises(ValueError):
        http.RateLimiter(per_second=-1)


def test_default_rate_stays_under_raiderio_published_limit():
    """Raider.io documents 300/min = 5/s. Crossing it risks a throttle that
    costs far more than the seconds saved."""
    assert http.DEFAULT_RATE <= 5.0

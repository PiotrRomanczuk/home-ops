"""gmail_ratelimit.py — thread-safe AIMD pacing for the Gmail per-minute quota."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable


class RateLimiter:
    """Thread-safe, self-tuning pacing under the per-minute Gmail quota.

    The real per-project limit can sit below the documented 15 000 units/min,
    so this is AIMD: a quota error halves the rate and pauses everyone for a
    few seconds; every success nudges the rate back up towards the ceiling.
    """

    def __init__(self, units_per_sec: float, sleep: Callable[[float], None] = time.sleep,
                 floor: float = 10.0, pause: float = 5.0):
        self.rate, self._max, self._floor, self._pause = units_per_sec, units_per_sec, floor, pause
        self._sleep, self._next, self._last_cut = sleep, 0.0, -1e9
        self._lock = threading.Lock()

    def take(self, units: int) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + units / self.rate
        if start > now:
            self._sleep(start - now)

    def penalize(self) -> None:
        with self._lock:
            now = time.monotonic()
            if now - self._last_cut > self._pause:  # one cut per burst of parallel errors
                self.rate = max(self._floor, self.rate / 2)
                self._last_cut = now
                self._next = max(self._next, now + self._pause)

    def reward(self) -> None:
        with self._lock:
            self.rate = min(self._max, self.rate + 0.05)

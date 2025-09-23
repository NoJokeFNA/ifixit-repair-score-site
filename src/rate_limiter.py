import threading
import time
from time import perf_counter
from typing import Optional


class _RateLimiter:
    """Token-bucket rate limiter for controlling API request rate."""

    def __init__(self, rate_per_sec: int, burst: Optional[int] = None) -> None:
        self.rate: float = max(1, rate_per_sec)
        self.capacity: float = burst if burst is not None else self.rate
        self._tokens: float = self.capacity
        self._last: float = perf_counter()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        wait_time = 0.0
        with self._lock:
            now = perf_counter()
            elapsed = now - self._last
            self._last = now
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            if self._tokens < 1.0:
                wait_time = (1.0 - self._tokens) / self.rate
            else:
                self._tokens -= 1.0
                return
        if wait_time > 0.0:
            time.sleep(wait_time)
        with self._lock:
            now = perf_counter()
            elapsed = now - self._last
            self._last = now
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            self._tokens -= 1.0

import math
import threading
import time


class _RateLimiter:
    """Thread-safe request budget with shared cooldown and recovery after throttling."""

    def __init__(self, rate_per_sec: float, burst: float = 1, *, clock=None, sleep=None) -> None:
        if not math.isfinite(rate_per_sec) or rate_per_sec <= 0:
            raise ValueError("API rate must be a positive finite number")
        if not math.isfinite(burst) or burst < 1:
            raise ValueError("API burst must be at least one request")
        self.maximum = float(rate_per_sec)
        self.recovery_ceiling = self.maximum
        self.rate = self.maximum
        self.capacity = float(burst)
        self._tokens = self.capacity
        self._clock = clock or time.perf_counter
        self._sleep = sleep or time.sleep
        self._last = self._clock()
        self._blocked_until = self._last
        self._successes = 0
        self._requests = 0
        self._throttles = 0
        self._lock = threading.Lock()

    def _refill(self, now):
        self._tokens = min(self.capacity, self._tokens + max(0, now - self._last) * self.rate)
        self._last = now

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = self._clock()
                if now < self._blocked_until:
                    delay = self._blocked_until - now
                else:
                    self._refill(now)
                    if self._tokens >= 1:
                        self._tokens -= 1
                        self._requests += 1
                        return
                    delay = (1 - self._tokens) / self.rate
            self._sleep(delay)

    def throttle(self, seconds: float) -> None:
        with self._lock:
            now = self._clock()
            if now >= self._blocked_until:
                previous_rate = self.rate
                self.rate = max(min(1.0, self.maximum), previous_rate / 2)
                self.recovery_ceiling = min(self.recovery_ceiling, max(self.rate, previous_rate * 0.75))
            self._blocked_until = max(self._blocked_until, now + seconds)
            self._last = self._blocked_until
            self._tokens = 0
            self._successes = 0
            self._throttles += 1

    def on_success(self) -> None:
        with self._lock:
            if self.rate >= self.recovery_ceiling:
                return
            self._successes += 1
            if self._successes >= 32:
                self._refill(max(self._clock(), self._last))
                self.rate = min(self.recovery_ceiling, self.rate * 1.25)
                self._successes = 0

    def stats(self) -> dict:
        with self._lock:
            return {
                "requests": self._requests,
                "rate_limit": self.maximum,
                "current_rate": self.rate,
                "recovery_ceiling": self.recovery_ceiling,
                "throttles": self._throttles,
            }

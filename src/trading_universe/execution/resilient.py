"""Rate limiting, retries and a circuit breaker so exchange failures degrade gracefully."""

from __future__ import annotations

import time
from collections.abc import Callable

from .broker import Broker, BrokerError, Fill, OrderRequest, TransientBrokerError


class TokenBucket:
    def __init__(self, rate_per_s: float, burst: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.rate, self.capacity, self._clock = rate_per_s, float(burst), clock
        self._tokens, self._last = float(burst), clock()

    def try_acquire(self) -> bool:
        now = self._clock()
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
        self._last = now
        if self._tokens >= 1:
            self._tokens -= 1
            return True
        return False


class ExecutionUnavailable(Exception):
    """Raised instead of placing an order when the executor is throttled or the breaker is open."""


class ResilientExecutor:
    def __init__(
        self,
        broker: Broker,
        limiter: TokenBucket | None = None,
        max_retries: int = 3,
        backoff_s: float = 0.5,
        breaker_threshold: int = 5,
        breaker_cooldown_s: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.broker = broker
        self.limiter = limiter or TokenBucket(rate_per_s=2.0, burst=5, clock=clock)
        self.max_retries, self.backoff_s = max_retries, backoff_s
        self.breaker_threshold, self.breaker_cooldown_s = breaker_threshold, breaker_cooldown_s
        self._sleep, self._clock = sleep, clock
        self._consecutive_failures = 0
        self._open_until = 0.0

    @property
    def breaker_open(self) -> bool:
        return self._clock() < self._open_until

    def submit(self, order: OrderRequest, urgent: bool = False) -> Fill:
        """Place an order. `urgent` (risk-reducing exits such as stop-losses) bypasses the
        rate limiter and circuit breaker, since failing to exit is worse than one extra call."""
        if not urgent:
            if self.breaker_open:
                raise ExecutionUnavailable("circuit breaker open")
            if not self.limiter.try_acquire():
                raise ExecutionUnavailable("rate limited")
        for attempt in range(self.max_retries + 1):
            try:
                fill = self.broker.place_order(order)
                self._consecutive_failures = 0
                return fill
            except TransientBrokerError:
                self._record_failure()
                if attempt == self.max_retries or (self.breaker_open and not urgent):
                    raise ExecutionUnavailable(f"order {order.client_order_id} failed after retries")
                self._sleep(self.backoff_s * 2**attempt)
            except BrokerError:
                self._record_failure()
                raise
        raise AssertionError("unreachable")

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.breaker_threshold:
            self._open_until = self._clock() + self.breaker_cooldown_s
            self._consecutive_failures = 0

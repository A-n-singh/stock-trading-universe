from __future__ import annotations

import pytest

from conftest import FakeClock
from trading_universe.execution.broker import BrokerError, OrderRequest, PaperBroker, TransientBrokerError
from trading_universe.execution.resilient import ExecutionUnavailable, ResilientExecutor, TokenBucket
from trading_universe.models import Action


class FlakyBroker(PaperBroker):
    def __init__(self, failures: int, **kw):
        super().__init__(**kw)
        self.failures, self.calls = failures, 0

    def place_order(self, order):
        self.calls += 1
        if self.failures > 0:
            self.failures -= 1
            raise TransientBrokerError("429")
        return super().place_order(order)


def order(i: str = "o1") -> OrderRequest:
    return OrderRequest(i, "BTCUSDT", Action.BUY, 10, 100)


def executor(broker, clock=None, **kw):
    clock = clock or FakeClock()
    return ResilientExecutor(broker, limiter=TokenBucket(100, 100, clock=clock), sleep=lambda s: None, clock=clock, **kw)


def test_retries_transient_errors():
    b = FlakyBroker(failures=2)
    fill = executor(b).submit(order())
    assert fill.quantity == 10 and b.calls == 3


def test_gives_up_gracefully_after_retries():
    b = FlakyBroker(failures=10)
    with pytest.raises(ExecutionUnavailable):
        executor(b, max_retries=2).submit(order())
    assert b.positions() == {}


def test_permanent_error_not_retried():
    b = PaperBroker(starting_cash=10)
    with pytest.raises(BrokerError):
        executor(b).submit(order())


def test_duplicate_client_order_id_fills_once():
    b = PaperBroker(slippage_bps=0, fee_bps=0)
    ex = executor(b)
    ex.submit(order("same"))
    ex.submit(order("same"))
    assert b.positions() == {"BTCUSDT": 10}


def test_rate_limiter_throttles_instead_of_spamming():
    clock = FakeClock()
    ex = ResilientExecutor(PaperBroker(), limiter=TokenBucket(1, 2, clock=clock), clock=clock)
    ex.submit(order("a"))
    ex.submit(order("b"))
    with pytest.raises(ExecutionUnavailable, match="rate limited"):
        ex.submit(order("c"))
    clock.t += 1.0
    ex.submit(order("c"))


def test_circuit_breaker_opens_and_urgent_exits_bypass_it():
    clock = FakeClock()
    b = FlakyBroker(failures=3)
    ex = executor(b, clock=clock, max_retries=0, breaker_threshold=3, breaker_cooldown_s=60)
    for i in range(3):
        with pytest.raises(ExecutionUnavailable):
            ex.submit(order(f"x{i}"))
    assert ex.breaker_open
    with pytest.raises(ExecutionUnavailable, match="circuit breaker"):
        ex.submit(order("y"))
    assert ex.submit(order("exit"), urgent=True).quantity == 10
    clock.t += 61
    assert not ex.breaker_open


def test_paper_broker_applies_slippage_and_fees():
    b = PaperBroker(starting_cash=10_000, slippage_bps=10, fee_bps=10)
    fill = b.place_order(order())
    assert fill.price == pytest.approx(100.1)
    assert b.cash() == pytest.approx(10_000 - 1001 - 1.001)

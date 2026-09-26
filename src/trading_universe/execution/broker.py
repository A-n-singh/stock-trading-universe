"""Broker interface and an in-memory paper broker (Phase 1: real data, fake money)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from ..models import Action, utcnow


class BrokerError(Exception):
    """Permanent failure: do not retry (e.g. order rejected)."""


class TransientBrokerError(BrokerError):
    """Temporary failure: throttled, timeout, 5xx. Safe to retry with the same client_order_id."""


@dataclass(frozen=True)
class OrderRequest:
    client_order_id: str
    symbol: str
    side: Action
    quantity: float
    price_hint: float


@dataclass(frozen=True)
class Fill:
    client_order_id: str
    symbol: str
    side: Action
    quantity: float
    price: float
    fee: float
    filled_at: datetime


class Broker(Protocol):
    def place_order(self, order: OrderRequest) -> Fill: ...
    def cash(self) -> float: ...
    def positions(self) -> dict[str, float]: ...


@dataclass
class PaperBroker:
    starting_cash: float = 100_000.0
    slippage_bps: float = 5.0
    fee_bps: float = 3.0
    _cash: float = field(init=False)
    _positions: dict[str, float] = field(init=False, default_factory=dict)
    _fills: dict[str, Fill] = field(init=False, default_factory=dict)
    _marks: dict[str, float] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self._cash = self.starting_cash

    def mark(self, symbol: str, price: float) -> None:
        self._marks[symbol] = price

    def place_order(self, order: OrderRequest) -> Fill:
        if order.client_order_id in self._fills:  # idempotent: a retried order never fills twice
            return self._fills[order.client_order_id]
        if order.quantity <= 0 or order.price_hint <= 0:
            raise BrokerError("invalid order")
        slip = self.slippage_bps / 10_000
        price = order.price_hint * (1 + slip if order.side == Action.BUY else 1 - slip)
        notional = price * order.quantity
        fee = notional * self.fee_bps / 10_000
        signed = order.quantity if order.side == Action.BUY else -order.quantity
        if order.side == Action.BUY and notional + fee > self._cash + 1e-9:
            raise BrokerError("insufficient funds")
        self._cash -= signed * price + fee
        new_qty = self._positions.get(order.symbol, 0.0) + signed
        if abs(new_qty) < 1e-12:
            self._positions.pop(order.symbol, None)
        else:
            self._positions[order.symbol] = new_qty
        self._marks[order.symbol] = price
        fill = Fill(order.client_order_id, order.symbol, order.side, order.quantity, price, fee, utcnow())
        self._fills[order.client_order_id] = fill
        return fill

    def cash(self) -> float:
        return self._cash

    def positions(self) -> dict[str, float]:
        return dict(self._positions)

    def state(self) -> dict:
        """Cash, positions and last prices, so paper trading survives restarts."""
        return {"cash": self._cash, "positions": self._positions, "marks": self._marks}

    def restore(self, state: dict) -> None:
        self._cash = float(state["cash"])
        self._positions = {k: float(v) for k, v in state.get("positions", {}).items()}
        self._marks = {k: float(v) for k, v in state.get("marks", {}).items()}

    def equity(self) -> float:
        return self._cash + sum(q * self._marks.get(s, 0.0) for s, q in self._positions.items())

"""The Trading Agent: the fast loop running in parallel to the research hierarchy.

It never researches. Each tick it reads the Orchestrator's per-symbol snapshots, runs the
News / Technical / Risk AND-gate, places orders through a resilient executor and logs
everything needed to close the mistake loop.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol

from ..config import AgentConfig
from ..execution.broker import BrokerError, OrderRequest
from ..execution.resilient import ExecutionUnavailable, ResilientExecutor
from ..models import Action, AssetClass, Candle, Direction, GateVote, Snapshot, TradeDecision
from ..trade_log import TradeLog, TradeRecord
from .news import news_vote
from .risk import PortfolioState, risk_vote
from .technical import technical_vote
from .watch import WatchList
from ..training.features import decision_context

log = logging.getLogger(__name__)


class MarketData(Protocol):
    def candles(self, symbol: str) -> Sequence[Candle]: ...


@dataclass(frozen=True)
class TickEvent:
    symbol: str
    kind: str  # skipped | watching | expired | rejected | opened | closed | degraded
    detail: str = ""


@dataclass
class TickReport:
    at: datetime
    events: list[TickEvent] = field(default_factory=list)

    def add(self, symbol: str, kind: str, detail: str = "") -> None:
        self.events.append(TickEvent(symbol, kind, detail))
        log.info("%s %s %s", symbol, kind, detail)

    def of(self, kind: str) -> list[TickEvent]:
        return [e for e in self.events if e.kind == kind]


class TradingAgent:
    def __init__(self, cfg: AgentConfig, executor: ResilientExecutor, trade_log: TradeLog, decision_model: object | None = None) -> None:
        if not cfg.paper_trading:
            log.warning("paper_trading is disabled: orders will reach a live broker")
        self.cfg = cfg
        self.executor = executor
        self.trade_log = trade_log
        self.watch = WatchList(cfg)
        # Optional trained decision model (TDD): a fourth check that must also agree.
        self.decision_model = decision_model

    # ---- helpers -------------------------------------------------------

    def _is_fresh(self, snap: Snapshot, now: datetime) -> bool:
        limit = self.cfg.max_snapshot_age_crypto_s if snap.asset_class == AssetClass.CRYPTO else self.cfg.max_snapshot_age_s
        age = snap.age_seconds(now)
        return 0 <= age <= limit

    def _portfolio(self, market: MarketData) -> PortfolioState:
        broker = self.executor.broker
        positions = broker.positions()
        equity = broker.cash()
        short_exposure = long_exposure = 0.0
        for sym, qty in positions.items():
            candles = market.candles(sym)
            if candles:
                equity += qty * candles[-1].close
                if qty < 0:
                    short_exposure += -qty * candles[-1].close
                else:
                    long_exposure += qty * candles[-1].close
        return PortfolioState(equity=equity, cash=broker.cash(), open_positions=positions,
                              short_exposure=short_exposure, long_exposure=long_exposure)

    # ---- main loop -----------------------------------------------------

    def tick(self, snapshots: Mapping[str, Snapshot], market: MarketData, now: datetime, allow_entries: bool = True) -> TickReport:
        """`allow_entries=False` (paused from the Agents page): open trades and stop-losses are still
        managed, but no new trades are looked for."""
        report = TickReport(at=now)
        self._manage_open_trades(snapshots, market, now, report)
        for entry in self.watch.expire(now):
            report.add(entry.symbol, "expired", f"{entry.event_type} hypothesis aged out")
        if not allow_entries:
            return report
        for symbol in sorted(set(snapshots) | {e.symbol for e in self.watch}):
            self._evaluate(symbol, snapshots.get(symbol), market, now, report)
        return report

    def _evaluate(self, symbol: str, snap: Snapshot | None, market: MarketData, now: datetime, report: TickReport) -> None:
        # Freshness safety valve: never act on stale or missing data, never fall back to research.
        if snap is None or not self._is_fresh(snap, now):
            report.add(symbol, "skipped", "snapshot missing or stale")
            return
        if snap.confidence < self.cfg.min_snapshot_confidence:
            report.add(symbol, "skipped", f"snapshot confidence {snap.confidence:.2f} too low")
            return

        news = news_vote(snap, self.cfg)
        watched = self.watch.get(symbol)
        if not news.approve:
            if watched is None:
                report.add(symbol, "skipped", news.reason)
                return
            if watched.action != _bias_action(snap.direction_bias):
                self.watch.resolve(symbol)
                report.add(symbol, "expired", "snapshot bias flipped against watched hypothesis")
                return
            # Recheck the held hypothesis without needing a fresh news trigger.
            news = GateVote("news", True, action=watched.action, reason=f"watched {watched.event_type} hypothesis")

        candles = market.candles(symbol)
        if not candles:
            report.add(symbol, "skipped", "no price data")
            return
        tc = self.cfg.technical
        closed = _closed(candles, now, self.cfg.candle_interval_s)
        technical = technical_vote(closed, news.action, tc.trend_window, tc.breakout_window, tc.triggers)
        if not technical.approve:
            self.watch.add(snap, news.action, now)
            report.add(symbol, "watching", technical.reason)
            return

        context = decision_context(snap, closed, symbol)
        votes: tuple[GateVote, ...] = (news, technical)
        if self.decision_model is not None:
            model = model_vote(self.decision_model, context, news.action, self.cfg.model_min_confidence)
            votes += (model,)
            if not model.approve:
                self.watch.add(snap, news.action, now)
                report.add(symbol, "watching", f"model: {model.reason}")
                return

        price = candles[-1].close
        risk = risk_vote(snap, news.action, price, self._portfolio(market), self.cfg.risk)
        if not risk.approve:
            self.watch.resolve(symbol)
            report.add(symbol, "rejected", risk.reason)
            return

        decision = TradeDecision(
            symbol=symbol,
            action=news.action,
            quantity=risk.details["quantity"],
            entry_price=price,
            stop_price=risk.details["stop"],
            risk_amount=risk.details["risk_amount"],
            votes=(*votes, risk),
            snapshot=snap,
            decided_at=now,
        )
        assert decision.approved  # AND-gate: all three legs agreed
        order_id = f"{symbol}:{snap.snapshot_id or snap.as_of.isoformat()}:{decision.action.value}"
        try:
            fill = self.executor.submit(OrderRequest(order_id, symbol, decision.action, decision.quantity, price))
        except ExecutionUnavailable as e:
            report.add(symbol, "degraded", str(e))  # keep the watch entry; retry next tick
            self.watch.add(snap, decision.action, now)
            return
        except BrokerError as e:
            self.watch.resolve(symbol)
            report.add(symbol, "rejected", f"broker: {e}")
            return
        self.watch.resolve(symbol)
        self.trade_log.record_open(order_id, decision, fill.price, fill.fee, context=context)
        report.add(symbol, "opened", f"{decision.action.value} {decision.quantity} @ {fill.price:.2f}")

    def _manage_open_trades(self, snapshots: Mapping[str, Snapshot], market: MarketData, now: datetime, report: TickReport) -> None:
        for rec in self.trade_log.open_trades():
            candles = market.candles(rec.symbol)
            if not candles:
                continue
            last = candles[-1]
            is_long = rec.action == Action.BUY.value
            stop_hit = last.low <= rec.stop_price if is_long else last.high >= rec.stop_price
            snap = snapshots.get(rec.symbol)
            reversed_ = (
                snap is not None
                and self._is_fresh(snap, now)
                and snap.confidence >= self.cfg.min_snapshot_confidence
                and snap.direction_bias == (Direction.BEARISH if is_long else Direction.BULLISH)
            )
            if stop_hit:
                # Assume the stop fills at the stop price, or worse if the bar gapped through it.
                exit_px = min(rec.stop_price, last.open) if is_long else max(rec.stop_price, last.open)
                self._close(rec, exit_px, now, "stop_loss", report)
            elif reversed_:
                self._close(rec, last.close, now, "snapshot_reversal", report)

    def _close(self, rec: TradeRecord, price: float, now: datetime, reason: str, report: TickReport) -> None:
        side = Action.SELL if rec.action == Action.BUY.value else Action.BUY
        try:
            fill = self.executor.submit(OrderRequest(f"{rec.trade_id}:exit", rec.symbol, side, rec.quantity, price), urgent=True)
        except (ExecutionUnavailable, BrokerError) as e:
            report.add(rec.symbol, "degraded", f"exit failed ({reason}): {e}")
            return
        closed = self.trade_log.record_close(rec.trade_id, fill.price, now, reason, fill.fee)
        report.add(rec.symbol, "closed", f"{reason} pnl ₹{closed.pnl:.2f}")


def model_vote(model: object, context: dict, action: Action, min_confidence: float) -> GateVote:
    from ..training.schema import GATE_QUESTIONS, Output, TrainingExample

    question = GATE_QUESTIONS["trade"]
    out = model.decide(TrainingExample(context, question, Output("hold", 0.5)))  # type: ignore[attr-defined]
    agree = out.answer == action.value and out.confidence >= min_confidence
    reason = f"{getattr(model, 'model_id', 'model')} says {out.answer} ({out.confidence:.2f})"
    return GateVote("model", agree, action=action if agree else Action.HOLD, reason=reason,
                    details={"answer": out.answer, "confidence": out.confidence})


def _closed(candles: Sequence[Candle], now: datetime, interval_s: float | None) -> Sequence[Candle]:
    """Only finished candles, so live entry signals match the backtest (which sees closes only).
    The still-forming candle is kept for prices and stop-losses, just not for entry patterns."""
    if not interval_s:
        return candles
    def end(c: Candle) -> datetime:
        ts = c.ts if c.ts.tzinfo else c.ts.replace(tzinfo=timezone.utc)
        return ts + timedelta(seconds=interval_s)
    return [c for c in candles if end(c) <= now]


def _bias_action(d: Direction) -> Action:
    return {Direction.BULLISH: Action.BUY, Direction.BEARISH: Action.SELL}.get(d, Action.HOLD)

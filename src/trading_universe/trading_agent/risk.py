"""Risk leg of the AND-gate: position sizing and the ₹200–300 per-trade risk budget."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..config import RISK_BUDGET_MAX_INR, RiskConfig
from ..models import Action, AssetClass, GateVote, Snapshot


@dataclass(frozen=True)
class PortfolioState:
    equity: float
    cash: float
    open_positions: dict[str, float]  # symbol -> signed quantity


def size_position(
    entry: float, stop: float, cfg: RiskConfig, equity: float, cash: float, fractional: bool
) -> tuple[float, float]:
    """Return (quantity, risk_amount) so a stop-out never loses more than the risk budget."""
    per_unit_risk = abs(entry - stop)
    if entry <= 0 or per_unit_risk <= 0:
        return 0.0, 0.0
    qty = cfg.risk_per_trade / per_unit_risk
    qty = min(qty, cfg.max_position_fraction * equity / entry, cash / entry)
    qty = math.floor(qty * 1e6) / 1e6 if fractional else float(math.floor(qty))
    return qty, qty * per_unit_risk


def risk_vote(snapshot: Snapshot, action: Action, price: float, portfolio: PortfolioState, cfg: RiskConfig) -> GateVote:
    if action not in (Action.BUY, Action.SELL):
        return GateVote("risk", False, reason="no trade to size")
    if action == Action.SELL and not cfg.allow_short:
        return GateVote("risk", False, reason="short selling disabled")
    blocking = sorted(set(snapshot.risk_flags) & cfg.blocking_risk_flags)
    if blocking:
        return GateVote("risk", False, reason=f"blocking risk flags: {', '.join(blocking)}")
    if snapshot.symbol in portfolio.open_positions:
        return GateVote("risk", False, reason="position already open")
    if len(portfolio.open_positions) >= cfg.max_open_positions:
        return GateVote("risk", False, reason="max open positions reached")

    stop = price * (1 - cfg.stop_loss_pct) if action == Action.BUY else price * (1 + cfg.stop_loss_pct)
    qty, risk_amount = size_position(
        price, stop, cfg, portfolio.equity, portfolio.cash, fractional=snapshot.asset_class == AssetClass.CRYPTO
    )
    if qty <= 0:
        return GateVote("risk", False, reason="position size rounds to zero under risk budget / caps")
    # Hard guard: the budget is non-negotiable at execution time.
    if risk_amount > RISK_BUDGET_MAX_INR + 1e-9:
        return GateVote("risk", False, reason=f"risk ₹{risk_amount:.2f} exceeds budget")
    return GateVote(
        "risk",
        True,
        action=action,
        reason=f"qty {qty} risking ₹{risk_amount:.2f}",
        details={"quantity": qty, "stop": stop, "risk_amount": risk_amount, "entry": price},
    )

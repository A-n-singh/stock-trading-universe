"""Runtime configuration. Defaults are conservative and paper-trading only."""

from __future__ import annotations

from dataclasses import dataclass, field

# BRD constraint: fixed ₹200–300 per-trade risk budget, non-negotiable at execution time.
RISK_BUDGET_MIN_INR = 200.0
RISK_BUDGET_MAX_INR = 300.0


@dataclass
class RiskConfig:
    risk_per_trade: float = 250.0  # ₹ lost if the stop is hit; must stay within [200, 300]
    stop_loss_pct: float = 0.02  # stop placed this far from entry
    max_position_fraction: float = 0.20  # never put more than this share of equity in one trade
    max_open_positions: int = 5
    # Price of one unit of the quote currency in ₹: 1.0 for ₹-quoted stocks, the USDT rate (about 88)
    # for Binance USDT pairs. The ₹ risk budget is converted with it before sizing.
    quote_to_inr: float = 1.0
    allow_short: bool = False
    blocking_risk_flags: frozenset[str] = frozenset(
        {
            "halted", "circuit_limit", "illiquid", "earnings_blackout", "delisting",
            # crypto-specific
            "exchange_outage", "withdrawals_paused", "depeg", "hack", "rug_pull",
            # roadmap step 1: market mood filter. Set by the research loop when Bitcoin is below its
            # 200-day average; blocks new buys in a falling market.
            "market_downtrend",
        }
    )

    def __post_init__(self) -> None:
        if not RISK_BUDGET_MIN_INR <= self.risk_per_trade <= RISK_BUDGET_MAX_INR:
            raise ValueError(
                f"risk_per_trade must be within ₹{RISK_BUDGET_MIN_INR:.0f}–₹{RISK_BUDGET_MAX_INR:.0f}, "
                f"got ₹{self.risk_per_trade}"
            )
        if not 0 < self.stop_loss_pct < 1:
            raise ValueError("stop_loss_pct must be between 0 and 1")
        if self.quote_to_inr <= 0:
            raise ValueError("quote_to_inr must be positive")
        if not 0 < self.max_position_fraction <= 1:
            raise ValueError("max_position_fraction must be in (0, 1]")


@dataclass
class TechnicalConfig:
    """Price-rule settings. Tune them with `trading_universe.backtest.optimize` instead of guessing."""

    trend_window: int = 20
    breakout_window: int = 10
    triggers: frozenset[str] = frozenset({"engulfing", "wick", "breakout"})

    def __post_init__(self) -> None:
        if self.trend_window < 2 or self.breakout_window < 1:
            raise ValueError("windows too small")
        unknown = set(self.triggers) - {"engulfing", "wick", "breakout"}
        if unknown or not self.triggers:
            raise ValueError(f"triggers must be a non-empty subset of engulfing/wick/breakout, got {sorted(self.triggers)}")


@dataclass
class AgentConfig:
    # Freshness safety valve: older snapshots are skipped, never acted on.
    max_snapshot_age_s: float = 15 * 60
    max_snapshot_age_crypto_s: float = 5 * 60
    min_snapshot_confidence: float = 0.6
    min_news_confidence: float = 0.5
    min_news_magnitude: float = 0.3
    # Watch-state aging; placeholders until Phase 1 paper-trading data calibrates them.
    default_watch_window_s: float = 2 * 60 * 60
    watch_windows_s: dict[tuple[str, str], float] = field(default_factory=dict)  # (sector, event_type)
    risk: RiskConfig = field(default_factory=RiskConfig)
    technical: TechnicalConfig = field(default_factory=TechnicalConfig)
    paper_trading: bool = True
    # Candle length in seconds (86400 for daily). When set, entry patterns use finished candles only.
    candle_interval_s: float | None = None
    # Minimum confidence for the optional decision-model check.
    model_min_confidence: float = 0.6

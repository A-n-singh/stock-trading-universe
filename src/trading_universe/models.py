"""Core data types shared by the research loop and the Trading Agent."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Direction(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class Action(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class AssetClass(str, Enum):
    CRYPTO = "crypto"  # the system is crypto only


@dataclass(frozen=True)
class NewsSignal:
    """Multi-dimensional sentiment score produced by the research loop (SDD §News)."""

    direction: Direction
    magnitude: float  # 0..1, how big a deal the news is
    confidence: float  # 0..1, how reliable / corroborated the source is
    event_type: str = "general"  # e.g. earnings, regulatory, social
    actionable: bool = False  # upstream research flagged it as tradeable
    headline: str = ""


@dataclass(frozen=True)
class Snapshot:
    """Orchestrator's consolidated per-symbol view; the only input the Trading Agent reads."""

    symbol: str
    direction_bias: Direction
    confidence: float
    as_of: datetime
    asset_class: AssetClass = AssetClass.CRYPTO
    sector: str = "unknown"
    risk_flags: tuple[str, ...] = ()
    news: NewsSignal | None = None
    rationale: str = ""
    snapshot_id: str = ""

    def age_seconds(self, now: datetime) -> float:
        return (now - self.as_of).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["as_of"] = self.as_of.isoformat()
        d["direction_bias"] = self.direction_bias.value
        d["asset_class"] = self.asset_class.value
        if self.news is not None:
            d["news"]["direction"] = self.news.direction.value
        return d


@dataclass(frozen=True)
class Candle:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(frozen=True)
class GateVote:
    """One leg of the AND-gate (news, technical or risk)."""

    name: str
    approve: bool
    action: Action = Action.HOLD
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TradeDecision:
    symbol: str
    action: Action
    quantity: float
    entry_price: float
    stop_price: float
    risk_amount: float
    votes: tuple[GateVote, ...]
    snapshot: Snapshot
    decided_at: datetime

    @property
    def approved(self) -> bool:
        return self.action != Action.HOLD and all(v.approve for v in self.votes)

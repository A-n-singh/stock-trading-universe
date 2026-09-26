"""News leg of the AND-gate. Execution-only: it reads the snapshot, never researches."""

from __future__ import annotations

from ..config import AgentConfig
from ..models import Action, Direction, GateVote, Snapshot


def news_vote(snapshot: Snapshot, cfg: AgentConfig) -> GateVote:
    news = snapshot.news
    if news is None:
        return GateVote("news", False, reason="no news signal on snapshot")
    if not news.actionable:
        return GateVote("news", False, reason="upstream research did not flag news as actionable")
    if news.direction == Direction.NEUTRAL:
        return GateVote("news", False, reason="neutral news")
    if news.direction != snapshot.direction_bias:
        return GateVote("news", False, reason="news direction disagrees with snapshot bias")
    if news.confidence < cfg.min_news_confidence:
        return GateVote("news", False, reason=f"news confidence {news.confidence:.2f} below minimum")
    if news.magnitude < cfg.min_news_magnitude:
        return GateVote("news", False, reason=f"news magnitude {news.magnitude:.2f} below minimum")
    action = Action.BUY if news.direction == Direction.BULLISH else Action.SELL
    return GateVote(
        "news",
        True,
        action=action,
        reason=f"{news.event_type} news {news.direction.value}",
        details={"event_type": news.event_type, "magnitude": news.magnitude, "confidence": news.confidence},
    )

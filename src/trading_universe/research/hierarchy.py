"""The slow research loop (SDD): Orchestrator -> Domain Managers -> Team Leads -> Workers -> Cluster Agents.

One `Orchestrator.run_cycle()`:
  1. News & Sentiment manager routes each fresh news item to a team lead (vector match, rule-based
     escalation), the lead hands a batch to a disposable worker, the worker scores it.
  2. Price & Technical manager reads each coin's trend and momentum.
  3. Risk & Portfolio manager raises risk flags (hacks, delistings, volatility, falling market).
  4. One cluster agent per coin combines all three with the coin's memory into a Snapshot.
  5. The Orchestrator publishes the snapshots for the Trading Agent.
"""

from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from ..market import CandleFeed
from ..memory.shared import Kind, SharedMemory
from ..memory.vectors import HashEmbedder
from ..models import AssetClass, Direction, NewsSignal, Snapshot
from ..news.models import SECTORS, NewsItem
from ..news.store import MARKET, NewsStore
from .sentiment import LEAD_BY_NAME, LEADS, KeywordScorer, LeadProfile, ScoredNews, lead_for
from .snapshots import SnapshotStore
from .team_leads import TeamLeadRouter

log = logging.getLogger(__name__)


@dataclass
class ResearchConfig:
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT")
    news_window_h: float = 48
    news_half_life_h: float = 8
    market_news_weight: float = 0.5  # macro / regulatory news without a coin applies to all coins at half weight
    min_news_score: float = 0.15
    max_new_scores_per_cycle: int = 80  # cost guard for the LLM
    market_symbol: str = "BTCUSDT"  # roadmap step 1: market mood filter
    market_ma_days: int = 200
    market_filter: bool = True


# ------------------------------------------------------------------------ score cache


class ScoreCache:
    """Scores already paid for, so each (news item, coin) is scored once."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._d: dict[str, dict] = {}
        if path and path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self._d[rec["key"]] = rec

    @staticmethod
    def key(item: NewsItem, symbol: str) -> str:
        return f"{item.item_id}:{symbol}"

    def get(self, item: NewsItem, symbol: str) -> ScoredNews | None:
        rec = self._d.get(self.key(item, symbol))
        if rec is None:
            return None
        return ScoredNews(item, symbol, Direction(rec["direction"]), rec["magnitude"], rec["confidence"], rec["actionable"],
                          rec["reason"], rec["lead"], rec["scorer"])

    def put(self, s: ScoredNews) -> None:
        rec = {"key": self.key(s.item, s.symbol), "direction": s.direction.value, "magnitude": s.magnitude, "confidence": s.confidence,
               "actionable": s.actionable, "reason": s.reason, "lead": s.lead, "scorer": s.scorer}
        self._d[rec["key"]] = rec
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(json.dumps(rec) + "\n")


# ----------------------------------------------------------------------------- workers


@dataclass
class Worker:
    """Disposable: spun up for one batch, briefed only with its lead's profile, then discarded."""

    lead: LeadProfile
    scorer: object

    def run(self, jobs: list[tuple[NewsItem, str]]) -> list[ScoredNews]:
        return [self.scorer.score(item, symbol, self.lead) for item, symbol in jobs]  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------- managers


class NewsManager:
    domain = "news"

    def __init__(self, scorer: object, cache: ScoreCache, cfg: ResearchConfig, memory: SharedMemory | None = None) -> None:
        self.scorer, self.cache, self.cfg = scorer, cache, cfg
        emb = HashEmbedder()
        self._pending: NewsItem | None = None
        self.router = TeamLeadRouter(
            embed=lambda t: emb.embed([t])[0],
            # Below the similarity threshold, the escalation decides. The rule-based classifier maps the
            # item to an existing lead, so no lead is spawned without a real judgement call.
            escalate=lambda task, names: lead_for(self._pending).name if self._pending else None,
            threshold=0.55,
            memory=memory,
            approve_spawn=lambda domain, name: False,  # new leads need a domain-manager decision (open question in the SDD)
        )
        now = datetime.now(timezone.utc)
        for lead in LEADS:
            self.router.add_lead(lead.name, self.domain, [lead.description], now)
        self.workers_spawned = 0

    def run(self, items: list[NewsItem], now: datetime) -> list[ScoredNews]:
        horizon = now - timedelta(hours=self.cfg.news_window_h)
        tracked = set(self.cfg.symbols)
        jobs_by_lead: dict[str, list[tuple[NewsItem, str]]] = defaultdict(list)
        scored: list[ScoredNews] = []
        budget = self.cfg.max_new_scores_per_cycle
        for item in sorted(items, key=lambda i: i.published, reverse=True):
            if not horizon <= item.published <= now:
                continue
            targets = [s for s in item.symbols if s in tracked]
            if not item.symbols and item.event_type in ("macro", "regulatory", "etf"):
                targets = [MARKET]
            for sym in targets:
                cached = self.cache.get(item, sym)
                if cached is not None:
                    scored.append(cached)
                    continue
                if budget <= 0:
                    continue
                budget -= 1
                self._pending = item
                routed = self.router.route(f"{item.event_type}: {item.title}", self.domain, now)
                self._pending = None
                lead = LEAD_BY_NAME.get(routed.lead.name, LEAD_BY_NAME["general"]) if routed else lead_for(item)
                jobs_by_lead[lead.name].append((item, sym))
        for lead_name, jobs in jobs_by_lead.items():
            worker = Worker(LEAD_BY_NAME[lead_name], self.scorer)
            self.workers_spawned += 1
            for s in worker.run(jobs):
                self.cache.put(s)
                scored.append(s)
        self.router.sweep_dormant(now)
        return scored


@dataclass(frozen=True)
class PriceView:
    bias: Direction
    confidence: float
    last_close: float
    sma50: float
    sma200: float
    vol20: float  # daily volatility, last 20 days
    vol180: float
    reason: str


class PriceManager:
    def run(self, frame: pd.DataFrame) -> PriceView | None:
        if frame is None or len(frame) < 60:
            return None
        c = frame["close"]
        rets = c.pct_change().dropna()
        sma50 = c.rolling(50).mean().iloc[-1]
        sma200 = c.rolling(200).mean().iloc[-1] if len(c) >= 200 else float("nan")
        last = c.iloc[-1]
        mom20 = last / c.iloc[-21] - 1
        votes = [last > sma50, (last > sma200) if not math.isnan(sma200) else last > sma50, mom20 > 0]
        up = sum(votes)
        bias = Direction.BULLISH if up >= 2 else Direction.BEARISH
        confidence = 0.4 + 0.15 * abs(up - 1.5) * 2  # 0.55 when 2 of 3 agree, 0.85 when all 3 do
        reason = (f"close {last:,.4g} vs 50d avg {sma50:,.4g}"
                  + (f", 200d avg {sma200:,.4g}" if not math.isnan(sma200) else "") + f", 20d momentum {mom20:+.1%}")
        return PriceView(bias, round(min(confidence, 0.85), 3), float(last), float(sma50), float(sma200),
                         float(rets.tail(20).std()), float(rets.tail(180).std()), reason)


class RiskManager:
    def __init__(self, cfg: ResearchConfig) -> None:
        self.cfg = cfg

    def market_downtrend(self, market_frame: pd.DataFrame | None) -> bool:
        if not self.cfg.market_filter or market_frame is None or len(market_frame) < self.cfg.market_ma_days:
            return False
        c = market_frame["close"]
        return bool(c.iloc[-1] < c.rolling(self.cfg.market_ma_days).mean().iloc[-1])

    def flags(self, symbol: str, news: list[ScoredNews], price: PriceView | None, downtrend: bool, now: datetime) -> tuple[str, ...]:
        out = []
        recent = [s for s in news if s.symbol == symbol and now - s.item.published <= timedelta(hours=24)]
        if any(s.item.event_type == "hack" and s.direction == Direction.BEARISH and s.actionable and s.magnitude >= 0.5 for s in recent):
            out.append("hack")
        if any(s.item.event_type == "delisting" and s.item.kind == "announcement" for s in recent):
            out.append("delisting")
        if price and price.vol180 > 0 and price.vol20 > 2 * price.vol180:
            out.append("high_volatility")
        if price is None:
            out.append("no_price_data")
        if downtrend:
            out.append("market_downtrend")
        return tuple(out)


# ------------------------------------------------------------------------ cluster agent


@dataclass
class ClusterAgent:
    """Persistent per-coin agent: combines the managers' views and the coin's memory into one snapshot."""

    symbol: str
    cfg: ResearchConfig
    memory: SharedMemory | None = None

    def news_signal(self, news: list[ScoredNews], now: datetime) -> tuple[NewsSignal | None, float, ScoredNews | None]:
        total, confs, top, top_w = 0.0, [], None, 0.0
        for s in news:
            if s.symbol not in (self.symbol, MARKET) or s.direction == Direction.NEUTRAL:
                continue
            age_h = max(0.0, (now - s.item.published).total_seconds() / 3600)
            w = s.magnitude * s.confidence * 0.5 ** (age_h / self.cfg.news_half_life_h)
            if s.symbol == MARKET:
                w *= self.cfg.market_news_weight
            total += w if s.direction == Direction.BULLISH else -w
            confs.append((w, s.confidence))
            if w > top_w:
                top, top_w = s, w
        if top is None:
            return None, 0.0, None
        direction = Direction.BULLISH if total > 0 else Direction.BEARISH if total < 0 else Direction.NEUTRAL
        agreeing = [s for s in news if s.direction == direction and s.symbol in (self.symbol, MARKET)]
        conf = sum(w * c for w, c in confs) / max(sum(w for w, _ in confs), 1e-9)
        actionable = abs(total) >= self.cfg.min_news_score and any(s.actionable for s in agreeing)
        magnitude = max((s.magnitude for s in agreeing), default=0.0)
        lead_item = top if top.direction == direction else (agreeing[0] if agreeing else top)
        signal = NewsSignal(direction, round(magnitude, 3), round(conf, 3), lead_item.item.event_type, actionable, lead_item.item.title[:200])
        return signal, total, lead_item

    def run(self, news: list[ScoredNews], price: PriceView | None, flags: tuple[str, ...], now: datetime) -> Snapshot:
        signal, score, top = self.news_signal(news, now)
        if signal and signal.actionable:
            bias = signal.direction
            agree = price is not None and price.bias == bias
            confidence = (0.5 * signal.confidence + 0.5 * price.confidence + 0.1) if agree else signal.confidence * 0.7
        elif price is not None:
            bias, confidence = price.bias, price.confidence * 0.8
        else:
            bias, confidence = Direction.NEUTRAL, 0.0
        parts = []
        if signal:
            parts.append(f"News {signal.direction.value} (score {score:+.2f}{', actionable' if signal.actionable else ''}): "
                         f"{signal.headline}" + (f" — {top.reason}" if top else ""))
        else:
            parts.append("No recent news.")
        if price:
            parts.append(f"Price {price.bias.value}: {price.reason}.")
        if flags:
            parts.append("Risk flags: " + ", ".join(flags) + ".")
        if self.memory is not None:
            view = self.memory.asset_view(self.symbol, now)
            lessons = self.memory.recall(signal.headline if signal else self.symbol, kind=Kind.PATTERN, as_of=now, top_k=1)
            notes = view.notes[:1] + [l.text for l in lessons if l.score > 0.3]
            if notes:
                parts.append("Memory: " + " | ".join(notes))
        return Snapshot(
            symbol=self.symbol,
            direction_bias=bias,
            confidence=round(min(max(confidence, 0.0), 0.95), 3),
            as_of=now,
            asset_class=AssetClass.CRYPTO,
            sector=SECTORS.get(self.symbol, "unknown"),
            risk_flags=flags,
            news=signal,
            rationale=" ".join(parts),
            snapshot_id=f"{self.symbol}:{now:%Y%m%dT%H%M%S}",
        )


# ------------------------------------------------------------------------- orchestrator


@dataclass
class CycleReport:
    at: datetime
    news_collected: int = 0
    news_errors: dict[str, str] = field(default_factory=dict)
    scored: int = 0
    workers: int = 0
    snapshots: list[Snapshot] = field(default_factory=list)
    market_downtrend: bool = False


class Orchestrator:
    def __init__(
        self,
        cfg: ResearchConfig,
        news_store: NewsStore,
        snapshots: SnapshotStore,
        feed: CandleFeed,
        scorer: object | None = None,
        memory: SharedMemory | None = None,
        cache: ScoreCache | None = None,
        sources: list | None = None,
    ) -> None:
        self.cfg = cfg
        self.news_store, self.snapshots, self.feed, self.memory = news_store, snapshots, feed, memory
        self.sources = sources
        self.news = NewsManager(scorer or KeywordScorer(), cache or ScoreCache(None), cfg, memory)
        self.price = PriceManager()
        self.risk = RiskManager(cfg)
        self.clusters = {s: ClusterAgent(s, cfg, memory) for s in cfg.symbols}

    def run_cycle(self, now: datetime | None = None, collect_news: bool = True) -> CycleReport:
        now = now or datetime.now(timezone.utc)
        report = CycleReport(at=now)
        if collect_news and self.sources:
            from ..news.store import collect

            res = collect(self.sources, self.news_store, self.memory.events if self.memory else None)
            report.news_collected, report.news_errors = len(res.new_items), res.errors
        items = self.news_store.items(since=now - timedelta(hours=self.cfg.news_window_h), until=now)
        before = self.news.workers_spawned
        scored = self.news.run(items, now)
        report.scored, report.workers = len(scored), self.news.workers_spawned - before

        def frame(sym: str) -> pd.DataFrame | None:
            try:
                df = self.feed.frame(sym)
            except Exception as e:
                log.warning("no candles for %s: %s", sym, e)
                return None
            return df[df.index <= pd.Timestamp(now).tz_convert(None)] if df.index.tz is None else df[df.index <= now]

        report.market_downtrend = self.risk.market_downtrend(frame(self.cfg.market_symbol))
        for sym, agent in self.clusters.items():
            f = frame(sym)
            pv = self.price.run(f) if f is not None else None
            flags = self.risk.flags(sym, scored, pv, report.market_downtrend, now)
            report.snapshots.append(agent.run(scored, pv, flags, now))
        self.snapshots.publish(report.snapshots)
        return report

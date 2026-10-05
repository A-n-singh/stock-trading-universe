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
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from ..market import CandleFeed
from ..memory.shared import Kind, SharedMemory
from ..memory.vectors import HashEmbedder
from ..models import AssetClass, Direction, NewsSignal, Snapshot
from ..news.models import SECTORS, NewsItem
from ..news.store import MARKET, NewsStore
from ..brain import Brain, Signal, close_series
from ..control import Board, Controls, QuestionLog
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


def _strength(m: float) -> str:
    return "strong" if m >= 0.6 else "medium" if m >= 0.35 else "weak"


def _coin(sym: str) -> str:
    return "ALL" if sym == MARKET else sym.removesuffix("USDT")


ROUTE_SYSTEM = (
    "You route crypto news to the expert desk best suited to judge it. The desks:\n{desks}\n"
    "Answer desk = one desk name exactly as listed. Answer desk = new only if the headline belongs to a recurring "
    "topic that none of the desks covers well; then give new_desk_name (1-3 words) and new_desk_keywords "
    "(5-10 lowercase words describing the topic). reason: one short sentence."
)
ROUTE_SCHEMA = {
    "type": "object",
    "properties": {"desk": {"type": "string"}, "new_desk_name": {"type": "string"},
                   "new_desk_keywords": {"type": "string"}, "reason": {"type": "string"}},
    "required": ["desk", "reason"],
}


class NewsManager:
    domain = "news"
    UNSURE = (0.3, 0.5)  # confidence band where a desk asks the owner (trading needs 0.5)
    MAX_OPEN_QUESTIONS = 10
    MAX_NEW_QUESTIONS = 3  # per cycle, so the owner isn't flooded

    MAX_ESCALATIONS = 20  # language-model routing calls per cycle

    def __init__(self, scorer: object, cache: ScoreCache, cfg: ResearchConfig, memory: SharedMemory | None = None,
                 embedder: object | None = None, llm: object | None = None) -> None:
        self.scorer, self.cache, self.cfg = scorer, cache, cfg
        self.llm = llm
        emb = embedder or HashEmbedder()
        if embedder is not None:
            try:
                emb.embed([lead.description for lead in LEADS])  # one call up front: is the service usable?
            except Exception as e:
                log.warning("embedding service unavailable (%s); using word matching to route news", e)
                emb = HashEmbedder()
        self.embedder_name = getattr(emb, "name", f"hash{getattr(emb, 'dim', 256)}")
        self._escalations = 0
        self.proposals: dict[str, dict] = {}  # new desks the language model suggested, waiting to be asked
        self._pending: NewsItem | None = None
        self.router = TeamLeadRouter(
            embed=lambda t: emb.embed([t])[0],
            # Below the similarity threshold, the escalation decides. The rule-based classifier maps the
            # item to an existing lead, so no lead is spawned without a real judgement call.
            escalate=self._escalate,
            threshold=0.55,
            memory=memory,
            # New desks are only created by the owner, from the Agents page (the manager asks).
            approve_spawn=lambda domain, name: False,
        )
        now = datetime.now(timezone.utc)
        for lead in LEADS:
            self.router.add_lead(lead.name, self.domain, [lead.description], now)
        self.leads: dict[str, LeadProfile] = dict(LEAD_BY_NAME)
        self.workers_spawned = 0
        self.controls = Controls()
        self.board = Board()
        self.questions = QuestionLog()
        self.unmatched: list[tuple[datetime, str]] = []  # news no desk fits well (went to "general")

    # ---- routing: below the similarity threshold, a judgement call (SDD) -------------------

    def _escalate(self, task: str, names: list[str]) -> str | None:
        """Which existing team lead a hard-to-place headline belongs to. The language model decides when
        one is set (and may suggest a new team lead); otherwise the rule-based event classifier does."""
        item = self._pending
        rule = lead_for(item).name if item is not None else None
        if self.llm is None or item is None or self._escalations >= self.MAX_ESCALATIONS:
            return rule
        self._escalations += 1
        desks = "\n".join(f"- {n}: {self.leads[n].description}" for n in names if n in self.leads)
        try:
            out = self.llm.complete_json(ROUTE_SYSTEM.format(desks=desks), f"Headline: {item.title}\nSummary: {item.summary[:400]}",
                                         ROUTE_SCHEMA)
        except Exception as e:  # unavailable, refused, bad answer: the rules decide
            log.info("routing call failed (%s); rule-based routing", e)
            return rule
        desk = str(out.get("desk", "")).strip().lower()
        if desk in self.leads and desk in names:
            return desk
        if desk == "new" and out.get("new_desk_name"):
            label = str(out["new_desk_name"]).strip()[:40]
            p = self.proposals.setdefault(label.lower(), {"label": label, "keywords": str(out.get("new_desk_keywords", ""))[:200],
                                                          "reason": str(out.get("reason", ""))[:300], "examples": []})
            if item.title not in p["examples"]:
                p["examples"] = (p["examples"] + [item.title])[-6:]
            return None  # no existing desk: scored by the rules' pick (usually General) until the owner approves
        return rule

    # ---- memory across restarts -----------------------------------------------------------

    def save_state(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"embedder": self.embedder_name, "leads": self.router.state()}))
        tmp.replace(path)

    def load_state(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            d = json.loads(path.read_text())
        except json.JSONDecodeError:
            return
        self.router.restore(d.get("leads", {}), keep_fingerprints=d.get("embedder") == self.embedder_name)

    # ---- owner's controls -------------------------------------------------------------------

    def use_controls(self, controls: Controls, now: datetime) -> None:
        self.controls = controls
        for name, d in controls.desks.items():  # desks the owner approved
            if name not in self.leads:
                self.leads[name] = LeadProfile(name, self.domain, d["description"], (),
                                               d.get("guidance") or f"Owner-created desk for: {d['description']}.", 0.6)
                self.router.add_lead(name, self.domain, [d["description"]], now)

    def profile(self, name: str) -> LeadProfile:
        """The desk's profile with the owner's written instruction and rulings added to its guidance."""
        lead = self.leads[name]
        extra = []
        if text := self.controls.instruction(name):
            extra.append(f"Owner's instruction: {text}")
        for r in self.controls.rulings_for(name)[-5:]:
            extra.append(f'Owner\'s ruling (example): "{r["headline"]}" is {r["direction"]} for {_coin(r["symbol"])}.')
        return replace(lead, guidance=lead.guidance + ("\n" + "\n".join(extra) if extra else "")) if extra else lead

    def adjust(self, s: ScoredNews) -> ScoredNews:
        """Apply the owner's rulings and the desk's strictness to a score (cached or new)."""
        rule = self.controls.ruling(f"{s.item.item_id}:{s.symbol}")
        if rule:
            d = Direction(rule["direction"])
            return replace(s, direction=d, confidence=max(s.confidence, 0.8),
                           actionable=d != Direction.NEUTRAL and s.magnitude >= 0.3, reason=f"owner's ruling: {d.value}")
        min_c, min_m = self.controls.threshold(s.lead, "min_confidence"), self.controls.threshold(s.lead, "min_magnitude")
        if s.actionable and ((min_c is not None and s.confidence < min_c) or (min_m is not None and s.magnitude < min_m)):
            return replace(s, actionable=False, reason=f"{s.reason} (below the {s.lead} desk's strictness)")
        return s

    # ---- work -----------------------------------------------------------------------------

    def run(self, items: list[NewsItem], now: datetime) -> list[ScoredNews]:
        horizon = now - timedelta(hours=self.cfg.news_window_h)
        tracked = set(self.cfg.symbols)
        jobs_by_lead: dict[str, list[tuple[NewsItem, str]]] = defaultdict(list)
        held: dict[str, int] = defaultdict(int)  # items waiting at paused desks
        scored: list[ScoredNews] = []
        budget = self.cfg.max_new_scores_per_cycle
        fresh = [i for i in items if horizon <= i.published <= now]
        self._escalations = 0
        self.board.set("news_manager", "working", f"Sorting {len(fresh)} news items to the expert desks", now)
        self.board.flush()
        for item in sorted(fresh, key=lambda i: i.published, reverse=True):
            targets = [s for s in item.symbols if s in tracked]
            if not item.symbols and item.event_type in ("macro", "regulatory", "etf"):
                targets = [MARKET]
            for sym in targets:
                cached = self.cache.get(item, sym)
                if cached is not None:
                    scored.append(self.adjust(cached))
                    continue
                if budget <= 0:
                    continue
                self._pending = item
                try:
                    routed = self.router.route(f"{item.event_type}: {item.title}", self.domain, now)
                except Exception as e:  # embedding service failed mid-cycle: the rules route this one
                    log.info("routing failed (%s); rule-based", e)
                    routed = None
                self._pending = None
                name = routed.lead.name if routed and routed.lead.name in self.leads else lead_for(item).name
                if routed and routed.how == "escalated_existing" and name == "general":
                    self.unmatched.append((item.published, item.title))
                if self.controls.paused(f"lead:{name}"):
                    held[name] += 1  # not scored, so it is picked up when the desk is resumed
                    continue
                budget -= 1
                jobs_by_lead[name].append((item, sym))

        new: list[ScoredNews] = []
        for name, jobs in jobs_by_lead.items():
            self.board.set(f"lead:{name}", "working", f"{len(jobs)} worker job(s): scoring "
                           + ", ".join(sorted({_coin(sym) for _, sym in jobs})) + " news", now)
        self.board.set("news_manager", "working", f"Sent {sum(map(len, jobs_by_lead.values()))} items to {len(jobs_by_lead)} desks", now)
        self.board.flush()
        for name, jobs in jobs_by_lead.items():
            worker = Worker(self.profile(name), self.scorer)
            self.workers_spawned += 1
            done = worker.run(jobs)
            for s in done:
                self.cache.put(s)
                s = self.adjust(s)
                scored.append(s)
                new.append(s)
                self.board.log(f"lead:{name}", f'{_coin(s.symbol)} "{s.item.title[:90]}" → {s.direction.value}, '
                               f"{_strength(s.magnitude)}, {s.confidence:.0%} sure{', act on it' if s.actionable else ''}", now)
            good = sum(s.direction == Direction.BULLISH for s in done)
            bad = sum(s.direction == Direction.BEARISH for s in done)
            self.board.set(f"lead:{name}", "done", f"Scored {len(done)} item(s): {good} good, {bad} bad, {len(done) - good - bad} neutral", now)
        self.router.sweep_dormant(now)
        for lead in self.router.leads.values():
            aid = f"lead:{lead.name}"
            if self.controls.paused(aid):
                self.board.set(aid, "paused", f"Paused by you · {held[lead.name]} item(s) waiting", now)
            elif lead.dormant:
                self.board.set(aid, "sleeping", "Sleeping: no matching news for weeks (wakes up by itself)", now)
            elif lead.name not in jobs_by_lead:
                self.board.set(aid, "idle", "No new news for this desk this cycle", now)
        self.board.set("news_manager", "done", f"{len(fresh)} fresh items; {len(new)} newly scored by {len(jobs_by_lead)} desk(s)"
                       + (f"; {sum(held.values())} held at paused desks" if held else ""), now)
        self._ask(new, now)
        return scored

    def _ask(self, new: list[ScoredNews], now: datetime) -> None:
        """Questions for the owner: headlines a desk is unsure about, and news no desk fits."""
        open_q = [q for q in self.questions.all() if q["id"] not in self.controls.answered]
        room = max(0, min(self.MAX_NEW_QUESTIONS, self.MAX_OPEN_QUESTIONS - len(open_q)))
        lo, hi = self.UNSURE
        for s in sorted(new, key=lambda s: -s.magnitude):
            if room <= 0:
                break
            key = f"{s.item.item_id}:{s.symbol}"
            if (s.lead in ("general", "social") or s.direction == Direction.NEUTRAL or s.magnitude < 0.4
                    or not lo <= s.confidence < hi or self.controls.ruling(key)):
                continue
            desk = self.leads[s.lead]
            if self.questions.ask(
                f"ruling:{key}", f"lead:{s.lead}", "ruling", f'"{s.item.title[:120]}": good or bad for '
                + ("the whole market" if s.symbol == MARKET else _coin(s.symbol)) + "?",
                f"The desk read it as {s.direction.value} but is only {s.confidence:.0%} sure (trading needs 50%). "
                f"Your answer is used from now on and becomes an example for the desk.",
                ["bearish", "neutral", "bullish"],
                {"key": key, "headline": s.item.title[:200], "symbol": s.symbol, "lead": desk.name, "url": s.item.url}, now):
                room -= 1
        for key, p in list(self.proposals.items()):  # new desks the language model suggested
            if room <= 0:
                break
            name = "".join(ch if ch.isalnum() else "_" for ch in key).strip("_")
            if name in self.leads or len(p["examples"]) < 2:
                continue  # wait until the topic shows up at least twice
            if self.questions.ask(
                f"desk:{name}", "news_manager", "desk", f"Create a new expert desk: \"{p['label']}\"?",
                f"Gemini suggests it: {p['reason']} Approve to create it (you can change the name and keywords).",
                ["approve", "refuse"], {"examples": p["examples"], "suggested_label": p["label"], "suggested_description": p["keywords"]}, now):
                room -= 1
            del self.proposals[key]
        week = now - timedelta(days=7)
        self.unmatched = [(t, h) for t, h in self.unmatched if t >= week][-50:]
        if len(self.unmatched) >= 5 and room > 0:
            examples = list(dict.fromkeys(h for _, h in self.unmatched))[:6]
            self.questions.ask(
                f"desk:{now:%G-W%V}", "news_manager", "desk", "Create a new expert desk?",
                f"{len(self.unmatched)} news items this week didn't fit any desk well and went to General. "
                "If they share a topic, name a new desk for it and describe it in a few keywords.",
                ["approve", "refuse"], {"examples": examples}, now)


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
    signals: tuple[tuple[str, str, int, float], ...] = ()  # (desk, kind, direction, strength) from the desks
    day: str = ""  # the last finished daily candle the desks looked at


def _num(x: float) -> str:
    return f"{x:,.0f}" if abs(x) >= 1000 else f"{x:,.2f}" if abs(x) >= 1 else f"{x:.4g}"


PRICE_DESKS = ("trend", "momentum", "patterns")


class PriceManager:
    """Price & Technical section: three desks read each coin's finished daily candles.

    trend     closing price above (bullish) or below (bearish) both its 50- and 200-day averages
    momentum  the last 20 days' move, when bigger than 2%
    patterns  a candle pattern on the last finished candle: engulfing, hammer / shooting star,
              breakout / breakdown of the last 10 days' range

    Their votes are weighted by the brain's scorecards (desks whose signals proved right count more).
    """

    def run(self, frame: pd.DataFrame, now: datetime | None = None, weight=None) -> PriceView | None:
        if frame is None or len(frame) < 60:
            return None
        if now is not None and len(frame) > 1:  # finished candles only: the forming one can still change
            step = pd.Series(frame.index).diff().median()
            t = pd.Timestamp(now).tz_convert(None) if pd.Timestamp(now).tzinfo else pd.Timestamp(now)
            done = frame[frame.index + step <= t]
            frame = done if len(done) >= 60 else frame
        c = frame["close"]
        rets = c.pct_change().dropna()
        sma50 = c.rolling(50).mean().iloc[-1]
        sma200 = c.rolling(200).mean().iloc[-1] if len(c) >= 200 else float("nan")
        last = c.iloc[-1]
        mom20 = last / c.iloc[-21] - 1
        w = weight or (lambda desk, kind: 1.0)

        sig: list[tuple[str, str, int, float]] = []
        above = [last > sma50] + ([] if math.isnan(sma200) else [last > sma200])
        if all(above):
            sig.append(("trend", "above_averages", 1, 1.0))
        elif not any(above):
            sig.append(("trend", "below_averages", -1, 1.0))
        if abs(mom20) > 0.02:
            sig.append(("momentum", "rising_20d" if mom20 > 0 else "falling_20d", 1 if mom20 > 0 else -1, min(1.0, abs(mom20) / 0.15)))
        from ..backtest.signals import _patterns

        ups = [k for k, v in _patterns(frame.tail(15), 10).items() if bool(v.iloc[-1])]
        downs = [k for k, v in _patterns(frame.tail(15), 10, short=True).items() if bool(v.iloc[-1])]
        names = {"engulfing": ("bullish_engulfing", "bearish_engulfing"), "wick": ("hammer", "shooting_star"),
                 "breakout": ("breakout", "breakdown")}
        if ups and not downs:
            sig.append(("patterns", names[ups[-1]][0], 1, 1.0))
        elif downs and not ups:
            sig.append(("patterns", names[downs[-1]][1], -1, 1.0))

        score = sum(w(d, k) * di * st for d, k, di, st in sig)
        total = sum(w(d, k) * st for d, k, _, st in sig)
        if score > 0 or (score == 0 and last > sma50):
            bias = Direction.BULLISH
        else:
            bias = Direction.BEARISH
        confidence = 0.55 + 0.30 * abs(score) / total if total else 0.55
        reason = (f"close {_num(last)} vs 50d avg {_num(sma50)}"
                  + (f", 200d avg {_num(sma200)}" if not math.isnan(sma200) else "") + f", 20d momentum {mom20:+.1%}"
                  + (f", pattern {sig[-1][1].replace('_', ' ')}" if sig and sig[-1][0] == "patterns" else ""))
        return PriceView(bias, round(min(confidence, 0.85), 3), float(last), float(sma50), float(sma200),
                         float(rets.tail(20).std()), float(rets.tail(180).std()), reason, tuple(sig), str(frame.index[-1].date()))


class RiskManager:
    def __init__(self, cfg: ResearchConfig) -> None:
        self.cfg = cfg

    def market_mood(self, market_frame: pd.DataFrame | None) -> str | None:
        """"down" when the market leader is below its long average, "up" when above, None when unknown or off."""
        if not self.cfg.market_filter or market_frame is None or len(market_frame) < self.cfg.market_ma_days:
            return None
        c = market_frame["close"]
        return "down" if c.iloc[-1] < c.rolling(self.cfg.market_ma_days).mean().iloc[-1] else "up"

    def market_downtrend(self, market_frame: pd.DataFrame | None) -> bool:
        return self.market_mood(market_frame) == "down"

    def flags(self, symbol: str, news: list[ScoredNews], price: PriceView | None, downtrend: bool, now: datetime,
              uptrend: bool = False) -> tuple[str, ...]:
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
            out.append("market_downtrend")  # blocks buys
        if uptrend:
            out.append("market_uptrend")  # blocks shorts
        return tuple(out)

    @staticmethod
    def signals(flags: tuple[str, ...]) -> list[tuple[str, str, int, float]]:
        """Risk & Portfolio section's desks, as directional signals the brain can check:
        events (hack, delisting), mood (whole market falling / rising). Wild swings has no direction."""
        out = []
        for f in flags:
            if f in ("hack", "delisting"):
                out.append(("events", f, -1, 1.0))
            elif f == "market_downtrend":
                out.append(("mood", "market_falling", -1, 1.0))
            elif f == "market_uptrend":
                out.append(("mood", "market_rising", 1, 1.0))
        return out


# ------------------------------------------------------------------------ cluster agent


@dataclass
class ClusterAgent:
    """Persistent per-coin agent: combines the managers' views and the coin's memory into one snapshot."""

    symbol: str
    cfg: ResearchConfig
    memory: SharedMemory | None = None
    refinements: object | None = None  # learning.Refinements: confidence cuts for clusters that keep losing
    brain: object | None = None  # brain.Brain: trust per desk and kind of news, learned from outcomes

    def news_signal(self, news: list[ScoredNews], now: datetime) -> tuple[NewsSignal | None, float, ScoredNews | None]:
        total, confs, top, top_w = 0.0, [], None, 0.0
        for s in news:
            if s.symbol not in (self.symbol, MARKET) or s.direction == Direction.NEUTRAL:
                continue
            age_h = max(0.0, (now - s.item.published).total_seconds() / 3600)
            w = s.magnitude * s.confidence * 0.5 ** (age_h / self.cfg.news_half_life_h)
            if self.brain is not None:
                w *= self.brain.weight("news", s.lead, s.item.event_type)  # type: ignore[attr-defined]
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
        if self.refinements is not None:
            conf *= self.refinements.factor(SECTORS.get(self.symbol, "unknown"), lead_item.item.event_type)  # type: ignore[attr-defined]
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
    market_uptrend: bool = False


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
        refinements: object | None = None,
        llm: object | None = None,
        embedder: object | None = None,
    ) -> None:
        self.cfg = cfg
        self.news_store, self.snapshots, self.feed, self.memory = news_store, snapshots, feed, memory
        self.sources = sources
        self.news = NewsManager(scorer or KeywordScorer(), cache or ScoreCache(None), cfg, memory, embedder=embedder, llm=llm)
        self.price = PriceManager()
        self.risk = RiskManager(cfg)
        self.brain = Brain()
        self.clusters = {s: ClusterAgent(s, cfg, memory, refinements, self.brain) for s in cfg.symbols}
        self.board = self.news.board
        self.controls = Controls()

    def use_brain(self, brain: Brain) -> None:
        self.brain = brain
        for agent in self.clusters.values():
            agent.brain = brain

    def attach(self, board: Board | None = None, questions: QuestionLog | None = None) -> None:
        """Report to the Agents page (live board + questions for the owner)."""
        if board is not None:
            self.board = self.news.board = board
        if questions is not None:
            self.news.questions = questions

    def run_cycle(self, now: datetime | None = None, collect_news: bool = True, controls: Controls | None = None) -> CycleReport:
        now = now or datetime.now(timezone.utc)
        if controls is not None:
            self.controls = controls
        self.news.use_controls(self.controls, now)
        board = self.board
        report = CycleReport(at=now)
        board.cycle(started_at=now.isoformat(), running=True)
        if collect_news and self.sources:
            from ..news.store import collect

            board.set("orchestrator", "working", f"Collecting news from {len(self.sources)} sources", now)
            board.flush()
            res = collect(self.sources, self.news_store, self.memory.events if self.memory else None)
            report.news_collected, report.news_errors = len(res.new_items), res.errors
        items = self.news_store.items(since=now - timedelta(hours=self.cfg.news_window_h), until=now)
        board.set("orchestrator", "working", f"{report.news_collected} new news items; handing the work out", now)
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

        # The brain checks what happened after earlier signals (only signals whose 3 days are over).
        settled = self.brain.settle(lambda sym: close_series(f) if (f := frame(sym)) is not None and len(f) else None, now)
        for sc in scored:
            if sc.direction != Direction.NEUTRAL:
                self.brain.record(Signal(f"news:{sc.item.item_id}:{sc.symbol}", sc.item.published.isoformat(), "news", sc.lead,
                                         sc.item.event_type, sc.symbol, 1 if sc.direction == Direction.BULLISH else -1,
                                         round(sc.magnitude * sc.confidence, 3), sc.item.title[:160]))
        desk_notes: dict[str, list[str]] = defaultdict(list)
        mood = self.risk.market_mood(frame(self.cfg.market_symbol))
        report.market_downtrend, report.market_uptrend = mood == "down", mood == "up"
        views, flag_notes = [], []
        for sym, agent in self.clusters.items():
            aid = f"coin:{sym}"
            f = frame(sym)
            pv = self.price.run(f, now, lambda d, k: self.brain.weight("price", d, k)) if f is not None else None
            if pv is not None:
                for desk, kind, di, st in pv.signals:
                    desk_notes[f"price:{desk}"].append(f"{_coin(sym)} {kind.replace('_', ' ')}")
                    self.brain.record(Signal(f"price:{desk}:{kind}:{sym}:{pv.day}", now.isoformat(), "price", desk, kind, sym, di, st))
            views.append(f"{_coin(sym)} {'no data' if pv is None else 'rising' if pv.bias == Direction.BULLISH else 'falling'}")
            if pv is not None:
                board.log("price_manager", f"{_coin(sym)}: {pv.bias.value} ({pv.reason})", now)
            flags = self.risk.flags(sym, scored, pv, report.market_downtrend, now, report.market_uptrend)
            day = pv.day if pv is not None else now.date().isoformat()
            for desk, kind, di, st in self.risk.signals(flags):
                if desk != "mood":
                    desk_notes[f"risk:{desk}"].append(f"{_coin(sym)} {kind}")
                self.brain.record(Signal(f"risk:{desk}:{kind}:{sym}:{day}", now.isoformat(), "risk", desk, kind, sym, di, st))
            if "high_volatility" in flags:
                desk_notes["risk:swings"].append(f"{_coin(sym)} swinging twice as much as usual")
            coin_flags = [x for x in flags if x not in ("market_downtrend", "market_uptrend")]
            if coin_flags:
                flag_notes.append(f"{_coin(sym)}: {', '.join(coin_flags)}")
            if self.controls.paused(aid):
                board.set(aid, "paused", "Paused by you: no new verdicts, so no new trades on this coin", now)
                continue
            snap = agent.run(scored, pv, flags, now)
            report.snapshots.append(snap)
            verdict = f"Verdict: {snap.direction_bias.value} {snap.confidence:.2f}" + (" · news says act" if snap.news and snap.news.actionable else "")
            board.set(aid, "done", verdict, now)
            board.log(aid, f"{verdict}. {snap.rationale[:300]}", now)
        board.set("price_manager", "done", " · ".join(views), now)
        mood_word = "falling" if report.market_downtrend else "rising" if report.market_uptrend else "unknown"
        desk_notes["risk:mood"].append(f"whole market {mood_word}")
        idle = {"price:trend": "No coin clearly above or below both averages", "price:momentum": "No coin moved more than 2% in 20 days",
                "price:patterns": "No candle pattern on the last finished candle", "risk:events": "No hacks or delistings in the last 24 h",
                "risk:swings": "No coin swinging unusually"}
        for aid in ("price:trend", "price:momentum", "price:patterns", "risk:events", "risk:mood", "risk:swings"):
            notes = desk_notes.get(aid)
            board.set(aid, "done" if notes else "idle", "; ".join(notes) if notes else idle[aid], now)
            if notes:
                board.log(aid, "; ".join(notes), now)
        board.set("brain", "done", f"{self.brain.summary()['signals']} signals written down, {len(self.brain.outcomes)} checked "
                  f"against what the price did" + (f" ({settled} new)" if settled else ""), now)
        market = ("whole market falling (Bitcoin below its 200-day average)" if report.market_downtrend
                  else "whole market rising" if report.market_uptrend else "market mood unknown")
        board.set("risk_manager", "done", f"{market.capitalize()}" + (f"; flags: {'; '.join(flag_notes)}" if flag_notes else "; no coin flags"), now)
        if flag_notes:
            board.log("risk_manager", "; ".join(flag_notes), now)
        self.snapshots.publish(report.snapshots)
        board.set("orchestrator", "done", f"Cycle done: {report.news_collected} new news, {report.scored} scores, "
                  f"{len(report.snapshots)} coin verdicts", now)
        board.log("orchestrator", f"Cycle: {report.news_collected} new news, {report.scored} scores, {report.workers} worker(s)", now)
        board.cycle(last_at=now.isoformat(), running=False)
        board.flush()
        return report

"""Runs the whole system: research loop + Trading Agent + mistake loop, with everything saved in one folder.

Folder layout (default ./runs):
  news.jsonl         every news item collected
  scores.jsonl       news scores already paid for
  events.jsonl       memory diary (news, trade outcomes)
  memory.json        memory shelves (lessons, coin notes)
  snapshots/         latest.json + history.jsonl
  trades.jsonl       trade log (open + close)
  paper_broker.json  paper account (cash, positions)
  refinements.json   confidence cuts for losing clusters + tasks
  status.json        heartbeat for the dashboard
  agents.json        live board for the Agents page: who is doing what (written here)
  leads.json         team leads' fingerprints, last activity and sleeping state (kept across restarts)
  questions.jsonl    the agents' open questions for the owner (written here)
  controls.json      the owner's applied changes from the Agents page (written by the website only)
  settings.json      settings saved from the website (rules, stop-loss, market filter, shorts, trading on/off)
  best_setting.json  optional: settings from the hidden-period search (used if settings.json is absent)
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import AgentConfig, RiskConfig
from .control import Board, Controls, QuestionLog
from .execution.broker import PaperBroker
from .execution.resilient import ResilientExecutor
from .learning import MistakeLoop, Refinements
from .market import CandleFeed
from .memory import EventLog, SharedMemory
from .news.sources import default_sources
from .news.store import NewsStore
from .research.hierarchy import Orchestrator, ResearchConfig, ScoreCache
from .research.sentiment import default_scorer
from .research.snapshots import SnapshotStore
from .trade_log import TradeLog
from .trading_agent.agent import TickReport, TradingAgent

log = logging.getLogger(__name__)
INTERVAL_S = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}


@dataclass
class RunConfig:
    data_dir: Path = Path("runs")
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT")
    broker: str = "paper"  # paper | binance-testnet
    interval: str = "1d"
    research_every_s: float = 900
    trade_every_s: float = 60
    usdt_inr: float = float(os.environ.get("TU_USDT_INR", "88"))
    paper_cash_usdt: float = 1000.0
    risk_per_trade_inr: float = 250.0


@dataclass
class Status:
    started_at: str = ""
    last_research_at: str = ""
    last_trade_tick_at: str = ""
    research_cycles: int = 0
    trade_ticks: int = 0
    scorer: str = ""
    broker: str = ""
    equity_usdt: float = 0.0
    cash_usdt: float = 0.0
    open_positions: dict[str, float] = field(default_factory=dict)
    market_downtrend: bool = False
    shorts: bool = False  # short selling switched on
    trading_on: bool = False  # the owner switched trading on (off while the research brain learns)
    last_events: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class Runner:
    def __init__(self, cfg: RunConfig, feed: CandleFeed | None = None, sources: list | None = None) -> None:
        self.cfg = cfg
        d = cfg.data_dir
        d.mkdir(parents=True, exist_ok=True)
        self.memory = SharedMemory(EventLog(d / "events.jsonl"))
        if (d / "memory.json").exists():
            self.memory.load(d / "memory.json")
        self.news = NewsStore(d / "news.jsonl")
        self.snapshots = SnapshotStore(d / "snapshots")
        self.trade_log = TradeLog(d / "trades.jsonl")
        # Learning-agent suggestions wait for the owner's OK on the Agents page.
        self.refinements = Refinements(d / "refinements.json", require_approval=True)
        self.board = Board(d / "agents.json")
        self.questions = QuestionLog(d / "questions.jsonl")
        self.controls = Controls()
        self.feed = feed or CandleFeed(interval=cfg.interval, lookback_days=400, ttl_s=60)
        best = d / "settings.json" if (d / "settings.json").exists() else d / "best_setting.json"  # website settings win
        saved = json.loads(best.read_text()) if best.exists() else {}

        scorer = default_scorer()
        self.orchestrator = Orchestrator(
            ResearchConfig(symbols=cfg.symbols, market_filter=bool(saved.get("market_filter", True))), self.news, self.snapshots, self.feed, scorer=scorer,
            memory=self.memory, cache=ScoreCache(d / "scores.jsonl"),
            sources=default_sources() if sources is None else sources, refinements=self.refinements,
        )
        self.orchestrator.attach(self.board, self.questions)
        # Team leads remember their fingerprints and sleeping state across restarts.
        self.orchestrator.news.use_controls(Controls.load(d / "controls.json"), _now())
        self.orchestrator.news.load_state(d / "leads.json")

        self.agent_cfg = AgentConfig(risk=RiskConfig(risk_per_trade=cfg.risk_per_trade_inr, stop_loss_pct=0.03, quote_to_inr=cfg.usdt_inr),
                                     candle_interval_s=INTERVAL_S.get(cfg.interval),
                                     # a snapshot counts as fresh until the next research cycle is due (+50% slack)
                                     max_snapshot_age_crypto_s=cfg.research_every_s * 1.5)
        if all(k in saved for k in ("trend_window", "breakout_window", "triggers", "stop_loss_pct")):
            from .backtest.engine import Setting
            from .backtest.optimize import apply_setting

            s = saved
            self.agent_cfg = apply_setting(self.agent_cfg, Setting(s["trend_window"], s["breakout_window"], tuple(s["triggers"]), s["stop_loss_pct"]))
        allow_short = bool(saved.get("allow_short", False))
        if allow_short and cfg.broker != "paper":
            # Binance spot can't short; shorts need the futures market, which is not connected yet.
            log.warning("short selling is only available with the paper broker for now; keeping it off")
            allow_short = False
        self.agent_cfg.risk.allow_short = allow_short

        if cfg.broker == "binance-testnet":
            from .execution.binance import BinanceBroker

            self.broker = BinanceBroker.from_env()
            self.broker.adopt_positions({r.symbol: r.quantity for r in self.trade_log.open_trades()})
        else:
            self.broker = PaperBroker(starting_cash=cfg.paper_cash_usdt, slippage_bps=5, fee_bps=10)
            if (d / "paper_broker.json").exists():
                self.broker.restore(json.loads((d / "paper_broker.json").read_text()))
        self.agent = TradingAgent(self.agent_cfg, ResilientExecutor(self.broker), self.trade_log)
        self.learner = MistakeLoop(self.memory, self.trade_log, self.refinements, d / "learned.json")
        self.status = Status(started_at=_now().isoformat(), scorer=scorer.name, broker=cfg.broker, shorts=allow_short)
        prev = d / "status.json"
        if prev.exists():  # keep counters and history across restarts
            try:
                old = json.loads(prev.read_text())
                for k in ("last_research_at", "last_trade_tick_at", "research_cycles", "trade_ticks", "market_downtrend", "last_events", "errors"):
                    if k in old:
                        setattr(self.status, k, old[k])
            except (json.JSONDecodeError, OSError):
                pass

    # ---------------------------------------------------------------- steps

    def _load_controls(self) -> Controls:
        self.controls = Controls.load(self.cfg.data_dir / "controls.json")
        self.refinements.approved = self.controls.refinements
        return self.controls

    def research(self, now: datetime | None = None) -> None:
        now = now or _now()
        self.board.cycle(every_s=self.cfg.research_every_s,
                         next_at=datetime.fromtimestamp(now.timestamp() + self.cfg.research_every_s, timezone.utc).isoformat())
        rep = self.orchestrator.run_cycle(now, controls=self._load_controls())
        self.status.research_cycles += 1
        self.status.last_research_at = now.isoformat()
        self.status.market_downtrend = rep.market_downtrend
        for src, err in rep.news_errors.items():
            self._error(f"news source {src}: {err}")
        self._event(f"research: {rep.news_collected} new news, {rep.scored} scored, {len(rep.snapshots)} snapshots")
        self.memory.save(self.cfg.data_dir / "memory.json")
        self.orchestrator.news.save_state(self.cfg.data_dir / "leads.json")
        self._save()

    def trade(self, now: datetime | None = None) -> TickReport:
        now = now or _now()
        controls = self._load_controls()
        for sym, at in controls.unwatch.items():  # "stop watching" from the Agents page
            entry = self.agent.watch.get(sym)
            if entry is not None and entry.opened_at <= datetime.fromisoformat(at):
                self.agent.watch.resolve(sym)
                self.board.log("trading", f"Stopped watching {sym} (your change)", now)
        # Trading is off until the owner switches it on in Settings (brain first); the Agents page can
        # also pause it. Either way open trades and stop-losses are still managed.
        self.status.trading_on = self._trading_switched_on()
        paused = controls.paused("trading") or not self.status.trading_on
        watched_before = {e.symbol for e in self.agent.watch}
        rep = self.agent.tick(self.snapshots.latest(), self.feed, now, allow_entries=not paused)
        self.status.trade_ticks += 1
        self.status.last_trade_tick_at = now.isoformat()
        for e in rep.events:
            if e.kind in ("opened", "closed", "rejected", "degraded", "expired"):
                self._event(f"{e.symbol} {e.kind}: {e.detail}")
        if any(e.kind == "closed" for e in rep.events):
            learned = self.learner.run(now)
            for text in learned.lessons_written:
                self._event(f"lesson: {text}")
                self.board.log("learning", f"Lesson: {text}", now)
            self.board.set("learning", "done", f"Learned from {learned.trades_learned} closed trade(s); "
                           f"{len(learned.lessons_written)} lesson(s) up to date", now)
            self.memory.save(self.cfg.data_dir / "memory.json")
        self._ask_refinements(now)
        self._report_trading(rep, paused, watched_before, now)
        if isinstance(self.broker, PaperBroker):
            for sym in list(self.broker.positions()):
                candles = self.feed.candles(sym)
                if candles:
                    self.broker.mark(sym, candles[-1].close)
            (self.cfg.data_dir / "paper_broker.json").write_text(json.dumps(self.broker.state()))
        self._save()
        return rep

    def loop(self, max_seconds: float | None = None, sleep=time.sleep) -> None:
        start = time.time()
        next_research = next_trade = 0.0
        while max_seconds is None or time.time() - start < max_seconds:
            t = time.time()
            try:
                if t >= next_research:
                    self.research()
                    next_research = t + self.cfg.research_every_s
                if t >= next_trade:
                    self.trade()
                    next_trade = t + self.cfg.trade_every_s
            except Exception as e:  # keep running; a bad cycle is reported, not fatal
                log.exception("cycle failed")
                self._error(f"{type(e).__name__}: {e}")
                self._save()
            sleep(max(1.0, min(next_research, next_trade) - time.time()))

    # --------------------------------------------------------------- helpers

    def _trading_switched_on(self) -> bool:
        path = self.cfg.data_dir / "settings.json"
        try:
            return bool(json.loads(path.read_text()).get("trading_enabled", False)) if path.exists() else False
        except (json.JSONDecodeError, OSError):
            return False

    def _report_trading(self, rep: TickReport, paused: bool, watched_before: set[str], now: datetime) -> None:
        b = self.board
        watching = [{"symbol": e.symbol, "action": e.action.value, "event_type": e.event_type,
                     "since": e.opened_at.isoformat(), "until": e.expires_at.isoformat()} for e in self.agent.watch]
        open_trades = [{"symbol": r.symbol, "action": r.action, "entry": r.entry_price, "stop": r.stop_price}
                       for r in self.trade_log.open_trades()]
        for e in rep.events:
            if e.kind in ("opened", "closed", "rejected", "expired", "degraded"):
                b.log("trading", f"{e.symbol} {e.kind}: {e.detail}", now)
            elif e.kind == "watching" and e.symbol not in watched_before:
                b.log("trading", f"{e.symbol}: news says yes, waiting for the chart ({e.detail})", now)
        opened = sum(e.kind == "opened" for e in rep.events)
        closed = sum(e.kind == "closed" for e in rep.events)
        summary = f"{len(open_trades)} open trade(s) · {len(watching)} coin(s) on watch"
        if paused:
            why = "Trading is switched off in Settings (brain first)" if not self.status.trading_on else "Paused by you"
            b.set("trading", "paused", f"{why}: still managing stop-losses; no new trades · {summary}", now,
                  watching=watching, open_trades=open_trades)
        else:
            b.set("trading", "done", f"Checked the coins: {opened} opened, {closed} closed · {summary}", now,
                  watching=watching, open_trades=open_trades)
        if not self.board.data["agents"].get("learning"):
            b.set("learning", "idle", "Waiting for finished trades to learn from", now)
        b.flush()

    def _ask_refinements(self, now: datetime) -> None:
        """Learning-agent suggestions ("trust this kind of news less") become questions for the owner."""
        for k, p in self.refinements.proposed.items():
            qid = f"refine:{k}:{p['since'][:10]}"
            if k in self.controls.refinements or self.questions.asked(qid):
                continue
            self.questions.ask(
                qid, "learning", "refinement", f"Trust {p['event_type']} news on {p['sector']} coins less?",
                f"{p['losses']} of the last {p['sample']} trades after {p['event_type']} news on {p['sector']} coins lost money. "
                f"Suggestion: count that news at {p['multiplier']:.0%} of its normal weight until it recovers.",
                ["accept", "reject"], {"key": k, **p}, now)
            self.board.log("learning", f"Suggested: trust {p['event_type']} news on {p['sector']} coins less", now)
            self.board.set("learning", "waiting", "Waiting for your answer on a suggestion", now)

    def _event(self, text: str) -> None:
        log.info(text)
        self.status.last_events = (self.status.last_events + [f"{_now():%Y-%m-%d %H:%M} {text}"])[-50:]

    def _error(self, text: str) -> None:
        self.status.errors = (self.status.errors + [f"{_now():%Y-%m-%d %H:%M} {text}"])[-20:]

    def _save(self) -> None:
        try:
            cash = self.broker.cash()
        except Exception:
            cash = self.status.cash_usdt
        self.status.cash_usdt = round(cash, 2)
        self.status.open_positions = self.broker.positions()
        if isinstance(self.broker, PaperBroker):
            self.status.equity_usdt = round(self.broker.equity(), 2)
        tmp = self.cfg.data_dir / "status.json.tmp"
        tmp.write_text(json.dumps(asdict(self.status), indent=1))
        tmp.replace(self.cfg.data_dir / "status.json")


def _now() -> datetime:
    return datetime.now(timezone.utc)

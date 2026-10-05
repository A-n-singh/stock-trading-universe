"""The time machine: replay the past day by day, let the brain learn, then test it on a year it never saw.

Every day of the replay the research team runs exactly as it does live, but it only sees what was
known that day: the daily candles that had already closed and the news published before that moment.
The brain writes down every signal and, 3 days later, checks what the price did. Learning stops at
the cutoff (`--exam-days` before the end); the remaining period is the exam: the trust weights stay
frozen and we measure how right the signals were. Optionally the Trading Agent makes pretend trades
during the exam.

Usage:
  python -m trading_universe.time_machine --no-news                     # prices only
  python -m trading_universe.time_machine --news archive.parquet       # with a news archive
  python -m trading_universe.time_machine --news https://.../file.parquet --start 2019-10-01

A news archive is any parquet / CSV / JSON-lines file with a time column (published_on, published,
datetime, date...) and a title or text column; body, url and source are used when present. Archives
that only give the date are treated as known at the end of that day (no peeking). Downloads and
price candles are kept in ./data/cache (not saved to git).

Output (default ./runs/time_machine): brain/ (signals and outcomes) and report.json, which the
Brain page on the website shows.
"""

from __future__ import annotations

import argparse
import bisect
import json
import logging
import shutil
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .brain import Brain, Tally, _ts
from .config import AgentConfig, RiskConfig
from .execution.broker import PaperBroker
from .execution.resilient import ResilientExecutor
from .models import Action, Candle
from .news.models import NewsItem
from .research.hierarchy import Orchestrator, ResearchConfig, ScoreCache
from .research.sentiment import KeywordScorer
from .research.snapshots import SnapshotStore
from .trade_log import TradeLog
from .trading_agent.agent import TradingAgent

log = logging.getLogger(__name__)
CACHE = Path("data/cache")
DAY = timedelta(days=1)


# ------------------------------------------------------------------------- news archive

TIME_COLS = ("published_on", "published_at", "published", "datetime", "date", "time", "timestamp", "created_at")
TITLE_COLS = ("title", "headline", "text")
BODY_COLS = ("body", "summary", "description", "content")


def _download(url: str, cache: Path = CACHE / "news") -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    name = url.rstrip("/").split("/")[-1].split("?")[0] or "archive"
    target = cache / f"{abs(hash(url)) % 10**8}-{name}"
    if not target.exists():
        log.info("downloading %s", url)
        with urllib.request.urlopen(url, timeout=300) as r, target.open("wb") as f:  # noqa: S310 (owner-given URL)
            shutil.copyfileobj(r, f)
    return target


def _read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".parquet" or path.name.endswith(".parquet"):
        return pd.read_parquet(path)
    if suffix in (".jsonl", ".json"):
        return pd.read_json(path, lines=suffix == ".jsonl")
    return pd.read_csv(path)


def _times(col: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(col):
        unit = "ms" if col.dropna().median() > 1e11 else "s"
        return pd.to_datetime(col, unit=unit, utc=True, errors="coerce")
    return pd.to_datetime(col, utc=True, errors="coerce", format="mixed")


def load_archive(source: str | Path, start: datetime | None = None, end: datetime | None = None) -> list[NewsItem]:
    """Read a news archive (file path or URL) into news items, oldest first."""
    path = _download(str(source)) if str(source).startswith(("http://", "https://")) else Path(source)
    df = _read_table(path)
    cols = {c.lower(): c for c in df.columns}
    pick = lambda names: next((cols[n] for n in names if n in cols), None)  # noqa: E731
    tcol, title_col = pick(TIME_COLS), pick(TITLE_COLS)
    if tcol is None or title_col is None:
        raise ValueError(f"{path}: needs a time column ({', '.join(TIME_COLS)}) and a title/text column")
    body_col, url_col, src_col = pick(BODY_COLS), pick(("url", "link")), pick(("source", "source_name"))
    ts = _times(df[tcol])
    known = ts.dropna()
    if len(known) and (known.dt.hour == 0).all() and (known.dt.minute == 0).all() and (known.dt.second == 0).all():
        ts = ts + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)  # date only: count it as known at the end of that day
    df = df.assign(_ts=ts).dropna(subset=["_ts"])
    if start is not None:
        df = df[df["_ts"] >= pd.Timestamp(start) - pd.Timedelta(days=3)]
    if end is not None:
        df = df[df["_ts"] <= pd.Timestamp(end)]
    col = lambda c: df[c].fillna("").astype(str).tolist() if c else [""] * len(df)  # noqa: E731
    out = []
    for when, title, body, url, src in zip(df["_ts"], col(title_col), col(body_col), col(url_col), col(src_col)):
        title = title.strip()
        if not title:
            continue
        if body_col is None:  # one text column: its first part is the headline
            title = title[:200]
        out.append(NewsItem.make(src or "archive", title, url, when.to_pydatetime(), summary=body[:300]))
    return sorted(out, key=lambda i: i.published)


class ArchiveNews:
    """A read-only news store over an archive, fast to query by time window."""

    def __init__(self, items: Iterable[NewsItem] = ()) -> None:
        self._items = sorted(items, key=lambda i: i.published)
        self._ts = [i.published for i in self._items]

    def add(self, item: NewsItem) -> bool:
        return False

    def items(self, *, symbol: str | None = None, since: datetime | None = None, until: datetime | None = None) -> list[NewsItem]:
        lo = bisect.bisect_left(self._ts, since) if since else 0
        hi = bisect.bisect_right(self._ts, until) if until else len(self._ts)
        out = self._items[lo:hi]
        if symbol is not None:
            out = [i for i in out if symbol in i.symbols]
        return out[::-1]

    def __len__(self) -> int:
        return len(self._items)


# ------------------------------------------------------------------------------ prices


class AsOfFeed:
    """Daily candles as they were known at `now`: only candles that had already closed."""

    def __init__(self, frames: dict[str, pd.DataFrame], lookback: int = 400) -> None:
        self.now: datetime | None = None
        self.lookback = lookback
        self._frames, self._closes, self._candles = {}, {}, {}
        for sym, df in frames.items():
            df = df.sort_index()
            idx = pd.DatetimeIndex(df.index)
            idx = idx.tz_convert(None) if idx.tz is not None else idx
            df = df.set_axis(idx)
            step = (idx[1:] - idx[:-1]).median() if len(idx) > 1 else pd.Timedelta(days=1)
            self._frames[sym] = df
            self._closes[sym] = (idx + step).to_numpy()
            self._candles[sym] = [Candle(ts.to_pydatetime(), r.open, r.high, r.low, r.close, r.volume)
                                  for ts, r in zip(df.index, df.itertuples())]

    def _k(self, symbol: str) -> int:
        if symbol not in self._frames:
            return 0
        if self.now is None:
            return len(self._closes[symbol])
        t = np.datetime64(pd.Timestamp(self.now).tz_convert(None))
        return int(np.searchsorted(self._closes[symbol], t, side="right"))

    def frame(self, symbol: str) -> pd.DataFrame:
        k = self._k(symbol)
        if k == 0:
            raise KeyError(f"no closed candles for {symbol} yet")
        return self._frames[symbol].iloc[max(0, k - self.lookback):k]

    def candles(self, symbol: str) -> list[Candle]:
        k = self._k(symbol)
        return self._candles[symbol][max(0, k - self.lookback):k] if k else []

    def last_close(self, symbol: str) -> float | None:
        k = self._k(symbol)
        return self._candles[symbol][k - 1].close if k else None


def load_prices(symbols: Iterable[str], start: datetime, cache: Path = CACHE / "prices") -> dict[str, pd.DataFrame]:
    """Binance daily candles from `start` (minus 400 days for the long averages), cached on disk."""
    from .backtest.data import fetch, load_csv, save_csv

    cache.mkdir(parents=True, exist_ok=True)
    first = (pd.Timestamp(start) - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
    out = {}
    for sym in symbols:
        path = cache / f"{sym}-1d-{first}.csv"
        fresh = path.exists() and datetime.now().timestamp() - path.stat().st_mtime < 86400
        if fresh:
            out[sym] = load_csv(path)
            continue
        try:
            df = fetch(sym, "1d", first)
        except Exception as e:  # noqa: BLE001
            log.warning("no prices for %s: %s", sym, e)
            continue
        save_csv(df, path)
        out[sym] = df
    return out


# ------------------------------------------------------------------------------ replay


@dataclass
class TimeMachineConfig:
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT")
    start: datetime = datetime(2019, 10, 1, tzinfo=timezone.utc)
    end: datetime | None = None  # default: the last closed daily candle
    exam_days: int = 365
    trades: bool = True  # pretend trades during the exam
    shorts: bool = True
    usdt_inr: float = 88.0
    risk_per_trade_inr: float = 250.0
    stop_loss_pct: float = 0.03
    run_at: timedelta = field(default_factory=lambda: timedelta(minutes=5))  # each day just after the daily close


def _exam_summary(brain: Brain, since: datetime, until: datetime) -> dict:
    t, num, den = Tally(), 0.0, 0.0
    for sid, r in brain.outcomes.items():
        s = brain.signals.get(sid)
        if s is None or not since <= _ts(s.at) < until:
            continue
        t.add(s, r["r3"])
        w = brain.weight(s.section, s.desk, s.kind)  # the weights frozen at the cutoff
        num += w * (s.direction * r["r3"] > 0)
        den += w
    cards = [t.card(k) for k in t.stats]
    n = sum(c.n for c in cards)
    hits, base = sum(c.hits for c in cards), sum(c.base_hits for c in cards)
    return {"signals": n, "hit_rate": round(hits / n, 3) if n else 0.0, "base_rate": round(base / n, 3) if n else 0.0,
            "edge": round((hits - base) / n, 3) if n else 0.0, "weighted_hit_rate": round(num / den, 3) if den else 0.0}


def _trade_summary(log_: TradeLog, feed: AsOfFeed, cfg: TimeMachineConfig, cutoff: datetime, end: datetime) -> dict:
    total_r = profit = 0.0
    won = 0
    trades = log_.all()
    for rec in trades:
        pnl = rec.pnl
        if pnl is None:  # still open at the end: count it at the last close
            px = feed.last_close(rec.symbol) or rec.entry_price
            pnl = (px - rec.entry_price) * rec.quantity * (1 if rec.action == Action.BUY.value else -1)
        total_r += pnl / rec.risk_amount if rec.risk_amount else 0.0
        profit += pnl
        won += pnl > 0
    # Just holding: one trade-sized position in each coin, bought at the cutoff and held to the end.
    hold_r = 0.0
    for sym in cfg.symbols:
        feed.now = cutoff
        a = feed.last_close(sym)
        feed.now = end
        b = feed.last_close(sym)
        if a and b:
            hold_r += (b / a - 1) / cfg.stop_loss_pct
    return {"trades": len(trades), "won": won, "total_r": round(total_r, 2), "profit_inr": round(profit * cfg.usdt_inr, 2),
            "hold_r": round(hold_r, 2)}


def replay(cfg: TimeMachineConfig, frames: dict[str, pd.DataFrame], news: list[NewsItem], out: Path,
           scorer: object | None = None, llm: object | None = None,
           progress: Callable[[str], None] = print) -> dict:
    """Run the research team once a day from cfg.start to the end, learning until the cutoff, then sit the exam."""
    feed = AsOfFeed(frames)
    if not feed._frames:
        raise ValueError("no price data")
    last_close = max(feed._closes[s][-1] for s in feed._frames)
    end = cfg.end or pd.Timestamp(last_close).tz_localize("UTC").to_pydatetime()
    end = min(end, datetime.now(timezone.utc))  # never replay a day that hasn't happened (today's candle is still forming)
    start = cfg.start
    cutoff = end - timedelta(days=cfg.exam_days)
    if cutoff <= start + timedelta(days=30):
        raise ValueError("the learning period is too short: move --start earlier or use fewer --exam-days")

    out.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(out / "brain", ignore_errors=True)  # every replay starts with an empty brain
    brain = Brain(out / "brain")
    scorer = scorer or KeywordScorer()
    store = ArchiveNews(i for i in news if i.published <= end)
    orch = Orchestrator(ResearchConfig(symbols=cfg.symbols), store, SnapshotStore(None), feed, scorer=scorer,  # type: ignore[arg-type]
                        cache=ScoreCache(out / "scores.jsonl" if llm else None), llm=llm)
    orch.use_brain(brain)

    agent = trade_log = None
    if cfg.trades:
        acfg = AgentConfig(risk=RiskConfig(risk_per_trade=cfg.risk_per_trade_inr, stop_loss_pct=cfg.stop_loss_pct,
                                           quote_to_inr=cfg.usdt_inr, allow_short=cfg.shorts),
                           candle_interval_s=86400, max_snapshot_age_crypto_s=1.5 * 86400, default_watch_window_s=3 * 86400)
        broker = PaperBroker(starting_cash=10_000, slippage_bps=5, fee_bps=10)
        trade_log = TradeLog(None)
        agent = TradingAgent(acfg, ResilientExecutor(broker), trade_log)

    learned: list[dict] = []
    day = datetime(start.year, start.month, start.day, tzinfo=timezone.utc) + cfg.run_at
    days = 0
    while day <= end + cfg.run_at:
        feed.now = day
        if brain.frozen_at is None and day >= cutoff:
            learned = brain.scorecard()
            brain.freeze(day)
            progress(f"{day:%Y-%m-%d}: learning stops here; the exam starts ({brain.summary()['settled']:,} signals checked so far)")
        rep = orch.run_cycle(day, collect_news=False)
        if agent is not None and brain.frozen_at is not None:
            agent.tick({s.symbol: s for s in rep.snapshots}, feed, day)
            for sym in list(agent.executor.broker.positions()):
                px = feed.last_close(sym)
                if px:
                    agent.executor.broker.mark(sym, px)
        days += 1
        if days % 90 == 0:
            progress(f"{day:%Y-%m-%d}: {brain.summary()['signals']:,} signals written down, {len(brain.outcomes):,} checked")
        day += DAY

    report = {
        "period": {"start": start.isoformat(), "cutoff": cutoff.isoformat(), "end": end.isoformat()},
        "days": days,
        "news_items": len(store.items(since=start, until=end)),
        "symbols": [s for s in cfg.symbols if s in feed._frames],
        "signals": len(brain.signals),
        "learned": learned,
        "exam": brain.scorecard_between(cutoff, end),
        "exam_summary": _exam_summary(brain, cutoff, end),
        "trades": _trade_summary(trade_log, feed, cfg, cutoff, end) if trade_log is not None else None,
        "scorer": getattr(scorer, "name", "keywords"),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    (out / "report.json").write_text(json.dumps(report, indent=1))
    return report


# --------------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m trading_universe.time_machine", description=__doc__.split("\n\n")[0])
    p.add_argument("--news", help="news archive: a parquet/CSV/JSON-lines file or a URL to one")
    p.add_argument("--no-news", action="store_true", help="prices only")
    p.add_argument("--start", default="2019-10-01")
    p.add_argument("--end", help="default: the last closed daily candle")
    p.add_argument("--exam-days", type=int, default=365)
    p.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT")
    p.add_argument("--no-trades", action="store_true", help="skip the pretend trades in the exam")
    p.add_argument("--no-shorts", action="store_true")
    p.add_argument("--gemini", action="store_true", help="read the news with Gemini (needs GEMINI_API_KEY; costs API calls)")
    p.add_argument("--out", default="runs/time_machine")
    a = p.parse_args(argv)
    if not a.news and not a.no_news:
        p.error("give --news ARCHIVE or --no-news")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    utc = lambda s: pd.Timestamp(s, tz="UTC").to_pydatetime()  # noqa: E731
    cfg = TimeMachineConfig(symbols=tuple(a.symbols.split(",")), start=utc(a.start), end=utc(a.end) if a.end else None,
                            exam_days=a.exam_days, trades=not a.no_trades, shorts=not a.no_shorts)
    scorer = llm = None
    if a.gemini:
        from .research.llm import GeminiLLM
        from .research.sentiment import LLMScorer

        llm = GeminiLLM()
        scorer = LLMScorer(llm)
    print("Loading prices…")
    frames = load_prices(cfg.symbols, cfg.start)
    news: list[NewsItem] = []
    if a.news:
        print("Loading news…")
        news = load_archive(a.news, cfg.start, cfg.end)
        print(f"{len(news):,} news items")
    rep = replay(cfg, frames, news, Path(a.out), scorer=scorer, llm=llm)
    e = rep["exam_summary"]
    print(f"\nExam ({rep['period']['cutoff'][:10]} → {rep['period']['end'][:10]}): {e['signals']:,} signals, "
          f"right {e['hit_rate']:.0%} (would be right anyway {e['base_rate']:.0%}, edge {e['edge'] * 100:+.0f} pts), "
          f"counting trusted signals more: {e['weighted_hit_rate']:.0%}")
    if rep["trades"]:
        t = rep["trades"]
        print(f"Pretend trades: {t['trades']} ({t['won']} won), {t['total_r']:+.1f} R; just holding: {t['hold_r']:+.1f} R")
    print(f"Report: {Path(a.out) / 'report.json'}")


if __name__ == "__main__":
    main()

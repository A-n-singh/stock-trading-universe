"""HTTP API for the web app (React frontend in `web/`), plus the built website itself.

Run:  python -m trading_universe.api          (http://localhost:8000)
Data folder: TU_RUNS_DIR (default ./runs), shared with `python -m trading_universe run`.
TU_AUTORUN=1 also runs the agent (research every 15 min, trading every minute) inside this server,
so one always-on host gives you both the website and non-stop paper trading.
TU_PASSWORD protects the site with a login (see auth.py). Set it before exposing the site online.
"""

from __future__ import annotations

import json
import math
import os
import threading
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..control import LOCKED, ChangeBook, ChangeError, Controls, QuestionLog, agent_tree, is_pausable
from .auth import COOKIE, OPEN_PATHS, Auth

ROOT = Path(__file__).resolve().parents[3]
WEB_DIST = Path(os.environ.get("TU_WEB_DIST", ROOT / "web" / "dist"))
DEFAULT_COINS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")


def runs_dir() -> Path:
    d = Path(os.environ.get("TU_RUNS_DIR", ROOT / "runs"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _clean(x: Any) -> Any:
    """JSON-safe: NaN/inf -> None, numpy scalars -> Python numbers."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if hasattr(x, "item") and not isinstance(x, (str, bytes)):
        x = x.item()
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    return x


# ------------------------------------------------------------------------ settings


class Settings(BaseModel):
    risk_per_trade_inr: float = Field(250, ge=200, le=300)
    stop_loss_pct: float = Field(0.03, gt=0, lt=0.5)
    trend_window: int = Field(20, ge=2, le=400)
    breakout_window: int = Field(10, ge=1, le=100)
    triggers: list[str] = ["engulfing", "wick", "breakout"]
    coins: list[str] = list(DEFAULT_COINS)
    market_filter: bool = True
    usdt_inr: float = Field(88.0, gt=0)
    allow_short: bool = False  # roadmap step 2: paper trading only for now
    trading_enabled: bool = False  # off while the research brain learns; the owner switches it on


class Suggestion(BaseModel):
    kind: str  # pause | min_confidence | min_magnitude | instruction | unwatch
    agent: str
    value: Any = None


class Answer(BaseModel):
    value: str
    label: str = ""  # new desk only
    description: str = ""
    guidance: str = ""


def _trade_rows(records: list, marks: dict[str, float], now: pd.Timestamp) -> list[dict]:
    """Trades for the Trades page, with money invested, live profit on open trades, % and R, time held,
    and the expert desk whose news started the trade. Money is in USDT (the page converts to ₹)."""
    from ..control import DESK_LABELS
    from ..research.sentiment import lead_for_event

    rows = []
    for r in records:
        d = dict(r.__dict__)
        invested = r.quantity * r.entry_price
        sign = 1 if r.action == "buy" else -1
        live_price = live_pnl = None
        if not r.closed and r.symbol in marks:
            live_price = marks[r.symbol]
            live_pnl = sign * (live_price - r.entry_price) * r.quantity - r.fees
        profit = r.pnl if r.closed else live_pnl
        end = pd.Timestamp(r.closed_at) if r.closed else now
        desk = lead_for_event(r.event_type).name
        d.update(invested=invested, live_price=live_price, live_pnl=live_pnl,
                 pct=None if profit is None or not invested else profit / invested,
                 r_multiple=None if profit is None or not r.risk_amount else profit / r.risk_amount,
                 held_s=max(0.0, (end - pd.Timestamp(r.opened_at)).total_seconds()),
                 event_type=r.event_type, desk=DESK_LABELS.get(desk, desk.title()))
        rows.append(d)
    return rows


SYSTEM_DEFAULTS = {"min_confidence": 0.5, "min_magnitude": 0.3}  # the Trading Agent's news check
RECENT_S = 20 * 60


def _agents_view(coins: list[str]) -> dict:
    """Everything the Agents page shows: the team with live status, questions, pending changes, history."""
    d = runs_dir()
    board = _read_json(d / "agents.json", {"agents": {}, "cycle": {}})
    controls = Controls.load(d / "controls.json").data
    book = ChangeBook(d / "agent_changes.json", d / "controls.json")
    pending = book.pending()
    pending_q = {p.get("question_id") for p in pending if p.get("question_id")}
    questions = [{**q, "pending": q["id"] in pending_q} for q in QuestionLog(d / "questions.jsonl").all()
                 if q["id"] not in controls["answered"]]
    asks: dict[str, int] = {}
    for q in questions:
        asks[q["agent"]] = asks.get(q["agent"], 0) + 1
    now = pd.Timestamp.now(tz="UTC")
    agents = []
    for a in agent_tree(coins, controls["desks"]):
        live = board["agents"].get(a["id"], {})
        status = live.get("status", "idle")
        updated = live.get("updated_at")
        if status == "done":
            status = "active" if updated and (now - pd.Timestamp(updated)).total_seconds() < RECENT_S else "idle"
        if controls["paused"].get(a["id"]):
            status = "paused"
        elif asks.get(a["id"]):
            status = "waiting"
        desk = a["id"].removeprefix("lead:") if a["id"].startswith("lead:") else None
        agents.append({
            **a, "status": status, "doing": live.get("doing") or "Not started yet", "updated_at": updated,
            "log": live.get("log", []), "questions": asks.get(a["id"], 0), "pausable": is_pausable(a["id"]),
            "paused": bool(controls["paused"].get(a["id"])),
            "watching": live.get("watching", []), "open_trades": live.get("open_trades", []),
            "thresholds": None if desk is None else {k: controls["thresholds"].get(desk, {}).get(k) for k in SYSTEM_DEFAULTS},
            "instruction": None if desk is None else controls["instructions"].get(desk, ""),
        })
    history = [{k: v for k, v in h.items() if k != "undo"} for h in book.history()[:60]]
    return {"cycle": board.get("cycle", {}), "agents": agents, "questions": questions, "pending": pending,
            "history": history, "defaults": SYSTEM_DEFAULTS, "locked": LOCKED}


class Login(BaseModel):
    password: str = Field(max_length=500)


class BacktestRequest(BaseModel):
    symbols: list[str] = list(DEFAULT_COINS)
    holdout_days: int = 365
    min_trades: int = 30
    market_filter: bool = True
    shorts: bool = False  # also short sell while the market is falling (roadmap step 2)
    fair_exam: bool = True  # also pass a setting that lost much less than holding the coins (roadmap step 3)


def load_settings() -> Settings:
    return Settings(**_read_json(runs_dir() / "settings.json", {}))


# ---------------------------------------------------------------------------- prices


@lru_cache(maxsize=64)
def _prices_cached(symbol: str, interval: str, start: str, hour_bucket: int) -> pd.DataFrame:
    from ..backtest.data import fetch

    return fetch(symbol, interval, start)


def prices(symbol: str, interval: str = "1d", start: str = "2020-01-01") -> pd.DataFrame:
    import time

    return _prices_cached(symbol.upper(), interval, start, int(time.time() // 900))  # refresh every 15 min


def _daily_curve(r: pd.Series, first: pd.Timestamp, last: pd.Timestamp) -> list[dict]:
    """Running total of R with one point per day, so charts show real time spacing."""
    days = pd.date_range(first.normalize(), last.normalize(), freq="D")
    total = r.groupby(r.index.normalize()).sum().cumsum().reindex(days).ffill().fillna(0.0)
    return [{"time": int(t.timestamp()), "value": round(float(v), 3)} for t, v in total.items()]


def _summary(sym: str, df: pd.DataFrame) -> dict:
    c = df["close"]
    daily = c.resample("1D").last().dropna()

    def back(days: int) -> float | None:
        past = daily[daily.index <= daily.index[-1] - pd.Timedelta(days=days)]
        return float(c.iloc[-1] / past.iloc[-1] - 1) if len(past) else None

    ma200 = daily.rolling(200).mean().iloc[-1]
    spark = daily.tail(90)
    return {
        "symbol": sym, "last": float(c.iloc[-1]), "change_1d": back(1), "change_30d": back(30), "change_1y": back(365),
        "ma200": None if pd.isna(ma200) else float(ma200),
        "mood": None if pd.isna(ma200) else ("rising" if daily.iloc[-1] > ma200 else "falling"),
        "spark": [float(v) for v in spark.values], "from": df.index[0].date().isoformat(), "to": df.index[-1].date().isoformat(),
    }


# ------------------------------------------------------------------------------ app


def create_app() -> FastAPI:
    auth = Auth()
    # No CORS headers: the website is served from this same address (and in development through
    # Vite's proxy), so other websites can't call the API from a visitor's browser.
    app = FastAPI(title="Trading Universe API", version="1.0",
                  docs_url=None if auth.required else "/docs", redoc_url=None, openapi_url=None if auth.required else "/openapi.json")
    if not auth.required:
        import logging

        logging.getLogger(__name__).warning("TU_PASSWORD is not set: the website has no login. Don't expose it to the internet.")

    @app.middleware("http")
    async def require_login(request: Request, call_next):
        path = request.url.path
        if auth.required and path.startswith("/api/") and path not in OPEN_PATHS and not auth.valid(request.cookies.get(COOKIE)):
            return JSONResponse({"detail": "login required"}, status_code=401)
        return await call_next(request)

    @app.get("/api/auth")
    def auth_state(request: Request) -> dict:
        return {"required": auth.required, "logged_in": auth.valid(request.cookies.get(COOKIE))}

    @app.post("/api/login")
    def login(body: Login, request: Request, response: Response) -> dict:
        if not auth.required:
            return {"ok": True}
        who = request.client.host if request.client else "?"
        if auth.locked(who):
            raise HTTPException(429, "too many wrong passwords; try again in 15 minutes")
        if not auth.check_password(who, body.password):
            raise HTTPException(401, "wrong password")
        https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "") == "https"
        response.set_cookie(COOKIE, auth.issue(), max_age=int(auth.session_s), httponly=True, samesite="strict", secure=https, path="/")
        return {"ok": True}

    @app.post("/api/logout")
    def logout(response: Response) -> dict:
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}
    lock = threading.Lock()  # one research/trade/backtest action at a time
    runner_box: dict[str, Any] = {}

    def runner(coins: tuple[str, ...]):
        from ..runner import RunConfig, Runner

        s = load_settings()
        key = (coins, runs_dir())
        if runner_box.get("key") != key:
            runner_box["key"] = key
            runner_box["runner"] = Runner(RunConfig(data_dir=runs_dir(), symbols=coins, usdt_inr=s.usdt_inr,
                                                    risk_per_trade_inr=s.risk_per_trade_inr))
        return runner_box["runner"]

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/settings")
    def get_settings() -> dict:
        return load_settings().model_dump()

    @app.put("/api/settings")
    def put_settings(s: Settings) -> dict:
        bad = set(s.triggers) - {"engulfing", "wick", "breakout"}
        if bad or not s.triggers:
            raise HTTPException(422, "triggers must be a non-empty subset of engulfing, wick, breakout")
        (runs_dir() / "settings.json").write_text(json.dumps(s.model_dump(), indent=1))
        runner_box.clear()  # rebuild with the new settings on the next action
        return s.model_dump()

    @app.get("/api/markets")
    def markets(symbols: str = Query(",".join(DEFAULT_COINS))) -> dict:
        out, errors = [], {}
        for sym in [s.strip().upper() for s in symbols.split(",") if s.strip()]:
            try:
                out.append(_summary(sym, prices(sym)))
            except Exception as e:
                errors[sym] = str(e)
        return _clean({"items": out, "errors": errors})

    @app.get("/api/candles/{symbol}")
    def candles(symbol: str, interval: str = "1d", days: int = 365) -> dict:
        from ..backtest.signals import long_signals

        s = load_settings()
        try:
            df = prices(symbol, interval)
        except Exception as e:
            raise HTTPException(502, f"couldn't load {symbol}: {e}") from e
        entries, _ = long_signals(df, s.trend_window, s.breakout_window, tuple(s.triggers))
        sma = df["close"].rolling(s.trend_window).mean()
        view = df[df.index >= df.index[-1] - pd.Timedelta(days=days)]
        t = lambda ts: int(ts.timestamp())  # noqa: E731
        return _clean({
            "symbol": symbol.upper(),
            "candles": [{"time": t(i), "open": r.open, "high": r.high, "low": r.low, "close": r.close, "volume": r.volume}
                        for i, r in zip(view.index, view.itertuples())],
            "trend": [{"time": t(i), "value": v} for i, v in sma.loc[view.index].items() if not pd.isna(v)],
            "buys": [t(i) for i in view.index[entries.loc[view.index].to_numpy()]],
            "trend_window": s.trend_window,
        })

    @app.get("/api/snapshots")
    def snapshots() -> dict:
        return _read_json(runs_dir() / "snapshots" / "latest.json", {})

    @app.get("/api/news")
    def news(coins: str = "", limit: int = 150) -> list[dict]:
        want = {c.strip().upper() for c in coins.split(",") if c.strip()}
        scores = {r["key"]: r for r in _read_jsonl(runs_dir() / "scores.jsonl")}
        items = sorted(_read_jsonl(runs_dir() / "news.jsonl"), key=lambda n: n["published"], reverse=True)
        out = []
        for n in items:
            if want and not set(n["symbols"]) & want:
                continue
            n["scores"] = [scores[f"{n['item_id']}:{c}"] for c in (n["symbols"] or ["MARKET"]) if f"{n['item_id']}:{c}" in scores]
            out.append(n)
            if len(out) >= limit:
                break
        return out

    # ---- Agents page ------------------------------------------------------------------
    changes_lock = threading.Lock()  # the website is the only writer of controls/changes; one edit at a time

    def book() -> ChangeBook:
        return ChangeBook(runs_dir() / "agent_changes.json", runs_dir() / "controls.json")

    @app.get("/api/agents")
    def agents() -> dict:
        return _clean(_agents_view(load_settings().coins))

    @app.post("/api/agents/suggest")
    def suggest(sg: Suggestion) -> dict:
        if sg.kind not in ("pause", "min_confidence", "min_magnitude", "instruction", "unwatch"):
            raise HTTPException(422, "use the question's answer buttons for this")
        with changes_lock:
            try:
                return book().suggest(sg.model_dump())
            except (ChangeError, ValueError, TypeError) as e:
                raise HTTPException(422, str(e)) from e

    @app.post("/api/agents/questions/{qid:path}/answer")
    def answer(qid: str, a: Answer) -> dict:
        q = next((q for q in QuestionLog(runs_dir() / "questions.jsonl").all() if q["id"] == qid), None)
        if q is None:
            raise HTTPException(404, "no such question")
        if a.value not in q["options"]:
            raise HTTPException(422, f"answer must be one of {q['options']}")
        change = {"kind": q["kind"], "agent": q["agent"], "value": a.value, "question_id": qid, "payload": q["payload"],
                  "label": a.label, "description": a.description, "guidance": a.guidance}
        with changes_lock:
            try:
                return book().suggest(change)
            except (ChangeError, KeyError) as e:
                raise HTTPException(422, str(e)) from e

    @app.delete("/api/agents/pending/{change_id}")
    def drop_pending(change_id: str) -> dict:
        with changes_lock:
            book().drop(change_id)
        return {"ok": True}

    @app.delete("/api/agents/pending")
    def drop_all_pending() -> dict:
        with changes_lock:
            book().drop(None)
        return {"ok": True}

    @app.post("/api/agents/apply")
    def apply_changes() -> dict:
        with changes_lock:
            try:
                applied = book().apply()
            except ChangeError as e:
                raise HTTPException(422, str(e)) from e
        return {"applied": len(applied)}

    @app.post("/api/agents/history/{change_id}/undo")
    def undo_change(change_id: str) -> dict:
        with changes_lock:
            try:
                book().undo(change_id)
            except ChangeError as e:
                raise HTTPException(422, str(e)) from e
        return {"ok": True}

    @app.get("/api/brain")
    def brain() -> dict:
        """What the brain has learned: scorecards per section, desk and kind of signal."""
        from ..brain import Brain

        b = Brain(runs_dir() / "brain")
        replay = _read_json(runs_dir() / "time_machine" / "report.json", None)
        return _clean({"summary": b.summary(), "scorecard": b.scorecard(), "time_machine": replay})

    @app.get("/api/status")
    def status() -> dict:
        return _read_json(runs_dir() / "status.json", {})

    @app.get("/api/trades")
    def trades() -> list[dict]:
        from ..trade_log import TradeLog

        p = runs_dir() / "trades.jsonl"
        if not p.exists():
            return []
        # Latest prices the paper account saw (updated every trading minute).
        marks = {k: float(v) for k, v in _read_json(runs_dir() / "paper_broker.json", {}).get("marks", {}).items()}
        return _clean(_trade_rows(TradeLog(p).all(), marks, pd.Timestamp.now(tz="UTC")))

    @app.get("/api/memory")
    def memory() -> dict:
        return {"memory": _read_json(runs_dir() / "memory.json", {"records": [], "dormant": []}),
                "refinements": _read_json(runs_dir() / "refinements.json", {"multipliers": {}, "tasks": []})}

    @app.get("/api/roadmap")
    def roadmap() -> dict:
        p = ROOT / "ROADMAP.md"
        return {"markdown": p.read_text() if p.exists() else ""}

    @app.post("/api/research/run")
    def run_research() -> dict:
        s = load_settings()
        with lock:
            r = runner(tuple(s.coins))
            r.research()
        return {"status": asdict(r.status), "snapshots": snapshots()}

    @app.post("/api/trade/step")
    def trade_step() -> dict:
        s = load_settings()
        with lock:
            r = runner(tuple(s.coins))
            rep = r.trade()
        return {"events": [{"symbol": e.symbol, "kind": e.kind, "detail": e.detail} for e in rep.events], "status": asdict(r.status)}

    @app.post("/api/backtest")
    def backtest(req: BacktestRequest) -> dict:
        from ..backtest.engine import CRYPTO, Setting, build_grid
        from ..backtest.optimize import optimize
        from ..backtest.plots import hidden_year_curves

        s = load_settings()
        data = {}
        for sym in req.symbols:
            try:
                data[sym.upper()] = prices(sym)
            except Exception as e:
                raise HTTPException(502, f"couldn't load {sym}: {e}") from e
        leader = None
        if req.shorts and not req.market_filter:
            raise HTTPException(422, "short selling needs the market mood filter")
        if req.market_filter:
            leader = data.get("BTCUSDT") if "BTCUSDT" in data else prices("BTCUSDT")
        profile = CRYPTO
        current = Setting(s.trend_window, s.breakout_window, tuple(t for t in ("engulfing", "wick", "breakout") if t in s.triggers), s.stop_loss_pct)
        with lock:
            try:
                rep = optimize(data, build_grid(stop_losses=profile.stop_losses), holdout_days=req.holdout_days,
                               min_practice_trades=req.min_trades, current=current, costs=profile.costs, market_filter=leader,
                               max_loss_vs_hold=0.25 if req.fair_exam else None, shorts=req.shorts)
            except ValueError as e:
                raise HTTPException(422, str(e)) from e
            curves = hidden_year_curves(rep, data, profile.costs)
        first = min(df.index.min() for df in data.values())
        last = max(df.index.max() for df in data.values())

        def res(r, rank: str) -> dict:
            return {"rank": rank, "setting": asdict(r.setting), "passed": r.passed, "reason": r.reason,
                    "practice": asdict(r.practice), "exam": asdict(r.exam), "hold_r": r.hold_r, "pass_kind": r.pass_kind}

        return _clean({
            "cutoff": rep.cutoff.isoformat(), "practice_period": [t.isoformat() for t in rep.practice_period],
            "exam_period": [t.isoformat() for t in rep.exam_period], "settings_tested": rep.settings_tested,
            "settings_eligible": rep.settings_eligible,
            "rows": [res(w, f"#{i + 1}") for i, w in enumerate(rep.winners)] + ([res(rep.current, "current")] if rep.current else []),
            "chosen": asdict(rep.chosen) if rep.chosen else None,
            "curves": [{"name": name, "color": color, "points": _daily_curve(r, first, last)} for name, color, r in curves],
            "risk_inr": s.risk_per_trade_inr,
            "hold_returns": rep.hold_returns or {},
        })

    @app.post("/api/settings/apply-best")
    def apply_best(setting: dict) -> dict:
        s = load_settings()
        s.trend_window, s.breakout_window = int(setting["trend_window"]), int(setting["breakout_window"])
        s.triggers, s.stop_loss_pct = list(setting["triggers"]), float(setting["stop_loss_pct"])
        return put_settings(s)

    # ---- optional: run the agent inside the web server --------------------------
    if os.environ.get("TU_AUTORUN") == "1":
        import time as _time

        def autorun() -> None:
            next_research = next_trade = 0.0
            while True:
                try:
                    s = load_settings()
                    now = _time.time()
                    with lock:
                        r = runner(tuple(s.coins))
                        if now >= next_research:
                            r.research()
                            next_research = now + r.cfg.research_every_s
                        if now >= next_trade:
                            r.trade()
                            next_trade = now + r.cfg.trade_every_s
                except Exception:  # never let one bad cycle stop the loop; the runner records problems
                    import logging

                    logging.getLogger(__name__).exception("autorun cycle failed")
                _time.sleep(5)

        threading.Thread(target=autorun, name="agent-autorun", daemon=True).start()

    # ---- the website itself -------------------------------------------------
    if WEB_DIST.exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = WEB_DIST / path
            return FileResponse(f if path and f.is_file() else WEB_DIST / "index.html")

    return app


app = create_app()

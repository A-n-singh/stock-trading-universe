from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

pd = pytest.importorskip("pandas")

from trading_universe.backtest.data import synthetic_prices  # noqa: E402
from trading_universe.market import CandleFeed  # noqa: E402
from trading_universe.memory import EventLog, SharedMemory  # noqa: E402
from trading_universe.models import Direction  # noqa: E402
from trading_universe.news.models import NewsItem  # noqa: E402
from trading_universe.news.store import NewsStore  # noqa: E402
from trading_universe.research.hierarchy import Orchestrator, ResearchConfig, ScoreCache  # noqa: E402
from trading_universe.research.llm import ClaudeLLM, LLMUnavailable  # noqa: E402
from trading_universe.research.sentiment import LEAD_BY_NAME, KeywordScorer, LLMScorer  # noqa: E402
from trading_universe.research.snapshots import SnapshotStore  # noqa: E402

NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)


def item(title: str, hours_ago: float = 1, kind: str = "news") -> NewsItem:
    return NewsItem.make("test", title, f"https://x.test/{abs(hash(title))}", NOW - timedelta(hours=hours_ago), "", kind)


def feed(trend: dict[str, float]) -> CandleFeed:
    f = CandleFeed()
    for i, (sym, drift) in enumerate(trend.items()):
        df = synthetic_prices(400, seed=i, drift=drift, vol=0.01, start_date="2025-08-22")
        f.put(sym, df)
    return f


def orchestrator(news: list[NewsItem], trend: dict[str, float], tmp_path=None, scorer=None, memory=None) -> Orchestrator:
    store = NewsStore()
    for n in news:
        store.add(n)
    cfg = ResearchConfig(symbols=tuple(trend))
    return Orchestrator(cfg, store, SnapshotStore(tmp_path), feed(trend), scorer=scorer, memory=memory)


def test_listing_news_plus_uptrend_gives_actionable_bullish_snapshot(tmp_path):
    news = [item("Binance Will List Solana (SOL) perpetuals with record high demand", kind="announcement")]
    o = orchestrator(news, {"BTCUSDT": 0.003, "SOLUSDT": 0.003}, tmp_path)
    r = o.run_cycle(NOW, collect_news=False)
    sol = next(s for s in r.snapshots if s.symbol == "SOLUSDT")
    assert sol.news and sol.news.actionable and sol.direction_bias == Direction.BULLISH
    assert sol.confidence > 0.6 and "listing" == sol.news.event_type
    assert r.workers >= 1
    # published for the Trading Agent, readable from disk
    assert SnapshotStore(tmp_path).latest()["SOLUSDT"].snapshot_id == sol.snapshot_id


def test_market_mood_filter_flags_every_coin_when_bitcoin_falls():
    o = orchestrator([], {"BTCUSDT": -0.004, "ETHUSDT": 0.003})
    r = o.run_cycle(NOW, collect_news=False)
    assert r.market_downtrend
    assert all("market_downtrend" in s.risk_flags for s in r.snapshots)


def test_hack_news_raises_risk_flag_and_old_news_is_ignored():
    news = [item("Solana DeFi protocol drained in $80M exploit, funds stolen"), item("Solana rally", hours_ago=100)]
    r = orchestrator(news, {"BTCUSDT": 0.003, "SOLUSDT": 0.003}).run_cycle(NOW, collect_news=False)
    sol = next(s for s in r.snapshots if s.symbol == "SOLUSDT")
    assert "hack" in sol.risk_flags and sol.news.direction == Direction.BEARISH
    assert r.scored == 1  # the 100-hour-old item is outside the window


def test_each_item_is_scored_only_once(tmp_path):
    calls = []

    class CountingScorer(KeywordScorer):
        def score(self, it, sym, lead):
            calls.append(it.item_id)
            return super().score(it, sym, lead)

    news = [item("Ethereum upgrade goes live")]
    o = orchestrator(news, {"BTCUSDT": 0.001, "ETHUSDT": 0.001}, scorer=CountingScorer())
    o.news.cache = ScoreCache(tmp_path / "scores.jsonl")
    o.run_cycle(NOW, collect_news=False)
    o.run_cycle(NOW + timedelta(minutes=5), collect_news=False)
    assert len(calls) == 1
    assert ScoreCache(tmp_path / "scores.jsonl").get(news[0], "ETHUSDT") is not None


def test_macro_news_without_a_coin_reaches_all_coins_at_lower_weight():
    news = [item("Federal Reserve announces surprise rate cut, stocks and crypto rally")]
    r = orchestrator(news, {"BTCUSDT": 0.001, "ETHUSDT": 0.001}).run_cycle(NOW, collect_news=False)
    assert all(s.news is not None and s.news.direction == Direction.BULLISH for s in r.snapshots)


def test_memory_notes_appear_in_rationale():
    mem = SharedMemory(EventLog())
    mem.for_agent("cluster:ETH", writes={"ETHUSDT"}).add_asset_note("ETHUSDT", "ETH tends to lag BTC by a day", [], NOW - timedelta(days=1))
    r = orchestrator([], {"BTCUSDT": 0.001, "ETHUSDT": 0.001}, memory=mem).run_cycle(NOW, collect_news=False)
    assert "lag BTC" in next(s for s in r.snapshots if s.symbol == "ETHUSDT").rationale


# ------------------------------------------------------------------------------ LLM


class FakeLLM:
    name = "fake"

    def __init__(self, out=None, fail=False):
        self.out, self.fail, self.prompts = out, fail, []

    def complete_json(self, system, prompt, schema):
        self.prompts.append((system, prompt))
        if self.fail:
            raise LLMUnavailable("down")
        return self.out


def test_llm_scorer_uses_lead_guidance_and_falls_back():
    it = item("SEC approves spot Solana ETF")
    llm = FakeLLM({"direction": "bullish", "magnitude": 1.4, "confidence": 0.9, "actionable": True, "reason": "ETF approval"})
    s = LLMScorer(llm).score(it, "SOLUSDT", LEAD_BY_NAME["regulatory"])
    assert s.direction == Direction.BULLISH and s.magnitude == 1.0 and s.scorer == "fake"
    assert "regulatory desk" in llm.prompts[0][0] and "Coin: SOL" in llm.prompts[0][1]
    fb = LLMScorer(FakeLLM(fail=True)).score(it, "SOLUSDT", LEAD_BY_NAME["regulatory"])
    assert fb.scorer == "keywords"


class FakeMessages:
    def __init__(self, response):
        self.response, self.kwargs = response, None

    def create(self, **kw):
        self.kwargs = kw
        return self.response


def fake_client(text="{}", stop="end_turn"):
    msgs = FakeMessages(SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)]))
    return SimpleNamespace(beta=SimpleNamespace(messages=msgs)), msgs


def test_claude_llm_request_shape_and_refusal():
    pytest.importorskip("anthropic")
    client, msgs = fake_client('{"direction": "neutral"}')
    llm = ClaudeLLM(model="claude-opus-5", effort="low", client=client)
    assert llm.complete_json("sys", "hi", {"type": "object"}) == {"direction": "neutral"}
    kw = msgs.kwargs
    assert kw["model"] == "claude-opus-5" and kw["fallbacks"] == "default"
    assert kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": {"type": "object"}}}
    refusing, _ = fake_client(stop="refusal")
    with pytest.raises(LLMUnavailable):
        ClaudeLLM(client=refusing).complete_json("s", "p", {})

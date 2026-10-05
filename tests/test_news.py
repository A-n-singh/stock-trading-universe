from __future__ import annotations

import json
from datetime import datetime, timezone

from trading_universe.memory.event_log import EventLog
from trading_universe.news.models import classify_event, tag_symbols
from trading_universe.news.sources import BinanceAnnouncements, RSSSource
from trading_universe.news.store import MARKET, NewsStore, collect

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Solana ETF approved by SEC</title><link>https://x.test/a</link>
<pubDate>Sat, 26 Sep 2026 12:17:00 +0000</pubDate><description>&lt;p&gt;Big day for &lt;b&gt;SOL&lt;/b&gt;&lt;/p&gt;</description></item>
<item><title>Fed holds interest rates steady</title><link>https://x.test/b</link><pubDate>Sat, 26 Sep 2026 10:00:00 +0000</pubDate></item>
</channel></rss>"""

BINANCE = {"data": {"catalogs": [{"catalogName": "New Cryptocurrency Listing", "articles": [
    {"title": "Binance Will List Hyperliquid (HYPE) with Seed Tag Applied", "code": "abc", "releaseDate": 1790235038608}]}]}}


def test_tagging_and_event_types():
    assert tag_symbols("Bitcoin and Ether rally; SOL lags") == ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    assert tag_symbols("Binance Will List Hyperliquid (HYPE)") == ("HYPEUSDT",)
    assert tag_symbols("A bank solves solvency issues") == ()  # no 'sol' inside other words
    assert classify_event("Exchange drained in $80M exploit") == "hack"
    assert classify_event("Binance will delist XYZ") == "delisting"
    assert classify_event("Bank syntax update") == "general"  # 'ban'/'tax' only at word starts
    assert classify_event("India raises crypto taxes") == "regulatory"


def test_rss_and_binance_parsing():
    items = RSSSource("t", "u", get=lambda url: RSS).fetch()
    assert [i.title for i in items] == ["Solana ETF approved by SEC", "Fed holds interest rates steady"]
    assert items[0].symbols == ("SOLUSDT",) and items[0].event_type == "etf"
    assert items[0].summary == "Big day for SOL"
    assert items[0].published == datetime(2026, 9, 26, 12, 17, tzinfo=timezone.utc)
    ann = BinanceAnnouncements(catalogs=(48,), get=lambda url: json.dumps(BINANCE).encode()).fetch()
    assert ann[0].kind == "announcement" and ann[0].event_type == "listing" and ann[0].symbols == ("HYPEUSDT",)


class Broken:
    name = "broken"

    def fetch(self):
        raise ConnectionError("down")


def test_collect_dedupes_isolates_failures_and_fills_diary(tmp_path):
    store, diary = NewsStore(tmp_path / "news.jsonl"), EventLog()
    src = RSSSource("t", "u", get=lambda url: RSS)
    r1 = collect([Broken(), src], store, diary)
    r2 = collect([src], store, diary)
    assert "broken" in r1.errors and len(r1.new_items) == 2 and not r2.new_items
    assert {e.symbol for e in diary.events()} == {"SOLUSDT", MARKET}
    assert len(NewsStore(tmp_path / "news.jsonl")) == 2  # persisted
    assert [i.title for i in store.items(symbol=MARKET)] == ["Fed holds interest rates steady"]


def test_finnhub_alphavantage_and_x_sources():
    import json as _json

    from trading_universe.news.sources import AlphaVantageSource, FinnhubSource, XSource, default_sources

    fin = FinnhubSource("k", get=lambda url: _json.dumps([
        {"headline": "Binance will list a new Solana (SOL) pair", "datetime": 1790000000, "url": "https://f/1", "source": "CoinDesk", "summary": ""}]).encode())
    (a,) = fin.fetch()
    assert a.source == "finnhub:CoinDesk" and "SOLUSDT" in a.symbols and a.event_type == "listing"

    t = [0.0]
    av = AlphaVantageSource(key="k", clock=lambda: t[0], get=lambda url: _json.dumps({"feed": [
        {"title": "SEC sues exchange over Ethereum (ETH) staking", "url": "https://a/1", "time_published": "20260901T101500",
         "summary": "", "source": "Reuters", "overall_sentiment_score": -0.4}]}).encode())
    (b,) = av.fetch()
    assert b.published.hour == 10 and b.extra["av_sentiment"] == -0.4
    assert av.fetch() == []  # free tier: asked again only after 2 hours
    t[0] += 2 * 3600
    assert len(av.fetch()) == 1

    seen = {}

    def get_x(url, headers=None):
        seen["auth"] = (headers or {}).get("Authorization")
        return _json.dumps({"data": [{"id": "9", "text": "Exchange hacked,\n BTC withdrawals paused", "created_at": "2026-09-01T10:00:00Z",
                                      "public_metrics": {"like_count": 5, "retweet_count": 2}}]}).encode()

    (c,) = XSource(bearer="tok", get=get_x).fetch()
    assert seen["auth"] == "Bearer tok" and c.kind == "social" and "\n" not in c.title and c.extra["likes"] == 5

    names = {s.name for s in default_sources()}
    assert not {"finnhub", "alphavantage", "x"} & names  # no keys set in tests

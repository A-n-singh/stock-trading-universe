"""Where news comes from. Every source returns NewsItems and never crashes the collector.

Free, no key:   RSS feeds (Cointelegraph, Decrypt, CoinDesk), Binance announcements
Free key:       CryptoPanic (CRYPTOPANIC_TOKEN), NewsAPI (NEWSAPI_KEY), Finnhub (FINNHUB_API_KEY),
                Alpha Vantage (ALPHAVANTAGE_API_KEY; 25 calls a day, so asked at most every 2 hours)
Paid key:       Twitter/X recent search (TWITTER_BEARER_TOKEN; query TU_X_QUERY)
Best effort:    Reddit public JSON (often blocked for servers)
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
import re
from typing import Protocol

from .models import NewsItem

UA = {"User-Agent": "Mozilla/5.0 (trading-universe news collector)"}


def http_get(url: str, headers: dict[str, str] | None = None, timeout: float = 20) -> bytes:
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _clean(html: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html or ""))).strip()


def _parse_date(text: str | None) -> datetime:
    if not text:
        return datetime.now(timezone.utc)
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class NewsSource(Protocol):
    name: str

    def fetch(self) -> list[NewsItem]: ...


@dataclass
class RSSSource:
    name: str
    url: str
    kind: str = "news"
    get: object = http_get

    def fetch(self) -> list[NewsItem]:
        root = ET.fromstring(self.get(self.url))  # type: ignore[operator]
        items = []
        for it in root.iter("item"):
            title = _clean(it.findtext("title") or "")
            if not title:
                continue
            items.append(NewsItem.make(
                self.name, title, (it.findtext("link") or "").strip(), _parse_date(it.findtext("pubDate")),
                _clean(it.findtext("description") or ""), self.kind,
            ))
        # Atom feeds
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("a:entry", ns):
            link = entry.find("a:link", ns)
            items.append(NewsItem.make(
                self.name, _clean(entry.findtext("a:title", "", ns)), link.get("href", "") if link is not None else "",
                _parse_date(entry.findtext("a:updated", None, ns)), _clean(entry.findtext("a:summary", "", ns)), self.kind,
            ))
        return items


@dataclass
class BinanceAnnouncements:
    """New listings, delistings and other official Binance news (catalog 48 = listings, 161 = delistings)."""

    name: str = "binance"
    catalogs: tuple[int, ...] = (48, 161, 49)
    page_size: int = 20
    get: object = http_get

    def fetch(self) -> list[NewsItem]:
        items = []
        for cat in self.catalogs:
            url = f"https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId={cat}&pageNo=1&pageSize={self.page_size}"
            data = json.loads(self.get(url))  # type: ignore[operator]
            for catalog in (data.get("data") or {}).get("catalogs", []):
                for a in catalog.get("articles", []):
                    items.append(NewsItem.make(
                        self.name, a["title"], f"https://www.binance.com/en/support/announcement/{a['code']}",
                        datetime.fromtimestamp(a["releaseDate"] / 1000, timezone.utc), "", "announcement",
                        catalog=catalog.get("catalogName", ""),
                    ))
        return items


@dataclass
class CryptoPanicSource:
    token: str
    name: str = "cryptopanic"
    get: object = http_get

    def fetch(self) -> list[NewsItem]:
        url = f"https://cryptopanic.com/api/v1/posts/?auth_token={urllib.parse.quote(self.token)}&public=true&kind=news"
        data = json.loads(self.get(url))  # type: ignore[operator]
        out = []
        for p in data.get("results", []):
            votes = p.get("votes", {})
            out.append(NewsItem.make(
                f"cryptopanic:{(p.get('source') or {}).get('title', '')}", p.get("title", ""), p.get("url", ""),
                _parse_date(p.get("published_at")), "", "news",
                votes={k: votes.get(k, 0) for k in ("positive", "negative", "important", "liked", "disliked")},
            ))
        return out


@dataclass
class NewsAPISource:
    key: str
    query: str = "bitcoin OR ethereum OR crypto OR solana"
    name: str = "newsapi"
    get: object = http_get

    def fetch(self) -> list[NewsItem]:
        url = f"https://newsapi.org/v2/everything?q={urllib.parse.quote(self.query)}&language=en&sortBy=publishedAt&pageSize=50"
        data = json.loads(self.get(url, {"X-Api-Key": self.key}))  # type: ignore[operator]
        return [
            NewsItem.make(f"newsapi:{(a.get('source') or {}).get('name', '')}", a.get("title") or "", a.get("url") or "",
                          _parse_date(a.get("publishedAt")), a.get("description") or "", "news")
            for a in data.get("articles", []) if a.get("title")
        ]


@dataclass
class FinnhubSource:
    """Finnhub's crypto news feed (free key at finnhub.io)."""

    key: str
    name: str = "finnhub"
    get: object = http_get

    def fetch(self) -> list[NewsItem]:
        url = f"https://finnhub.io/api/v1/news?category=crypto&token={urllib.parse.quote(self.key)}"
        data = json.loads(self.get(url))  # type: ignore[operator]
        return [
            NewsItem.make(f"finnhub:{a.get('source', '')}", a.get("headline") or "", a.get("url") or "",
                          datetime.fromtimestamp(int(a.get("datetime") or 0), timezone.utc), a.get("summary") or "", "news")
            for a in (data if isinstance(data, list) else []) if a.get("headline")
        ]


@dataclass
class _Throttled:
    """Asks the service at most once per `every_s` seconds (free tiers allow few calls a day)."""

    every_s: float = 0.0
    clock: object = time.time
    _last: float = -1e18

    def due(self) -> bool:
        now = self.clock()  # type: ignore[operator]
        if now - self._last < self.every_s:
            return False
        self._last = now
        return True


@dataclass
class AlphaVantageSource(_Throttled):
    """Alpha Vantage news & sentiment for crypto tickers (free key; 25 calls a day)."""

    key: str = ""
    tickers: str = "CRYPTO:BTC,CRYPTO:ETH,CRYPTO:SOL,CRYPTO:BNB"
    name: str = "alphavantage"
    get: object = http_get
    every_s: float = 2 * 3600

    def fetch(self) -> list[NewsItem]:
        if not self.due():
            return []
        url = (f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers={urllib.parse.quote(self.tickers)}"
               f"&limit=50&apikey={urllib.parse.quote(self.key)}")
        data = json.loads(self.get(url))  # type: ignore[operator]
        out = []
        for a in data.get("feed", []):
            t = a.get("time_published") or ""
            try:
                published = datetime.strptime(t, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
            except ValueError:
                published = _parse_date(None)
            if a.get("title"):
                out.append(NewsItem.make(f"alphavantage:{a.get('source', '')}", a["title"], a.get("url") or "", published,
                                         a.get("summary") or "", "news", av_sentiment=a.get("overall_sentiment_score")))
        return out


@dataclass
class XSource(_Throttled):
    """Twitter/X recent search (needs a paid API plan's bearer token)."""

    bearer: str = ""
    query: str = "(bitcoin OR ethereum OR solana OR bnb OR crypto) (hack OR listing OR sec OR etf OR exploit) -is:retweet lang:en"
    name: str = "x"
    get: object = http_get
    every_s: float = 15 * 60

    def fetch(self) -> list[NewsItem]:
        if not self.due():
            return []
        url = (f"https://api.twitter.com/2/tweets/search/recent?query={urllib.parse.quote(self.query)}"
               "&max_results=50&tweet.fields=created_at,public_metrics")
        data = json.loads(self.get(url, {"Authorization": f"Bearer {self.bearer}"}))  # type: ignore[operator]
        out = []
        for t in data.get("data", []):
            text = re.sub(r"\s+", " ", t.get("text", "")).strip()
            m = t.get("public_metrics") or {}
            out.append(NewsItem.make(self.name, text[:280], f"https://x.com/i/web/status/{t.get('id', '')}",
                                     _parse_date(t.get("created_at")), "", "social",
                                     likes=m.get("like_count", 0), reposts=m.get("retweet_count", 0)))
        return out


@dataclass
class RedditSource:
    subreddit: str = "CryptoCurrency"
    name: str = ""
    get: object = http_get

    def __post_init__(self) -> None:
        self.name = self.name or f"reddit:r/{self.subreddit}"

    def fetch(self) -> list[NewsItem]:
        data = json.loads(self.get(f"https://www.reddit.com/r/{self.subreddit}/new.json?limit=50"))  # type: ignore[operator]
        out = []
        for child in data.get("data", {}).get("children", []):
            p = child.get("data", {})
            out.append(NewsItem.make(
                self.name, p.get("title", ""), "https://www.reddit.com" + p.get("permalink", ""),
                datetime.fromtimestamp(p.get("created_utc", 0), timezone.utc), (p.get("selftext") or "")[:500], "social",
                score=p.get("score", 0), comments=p.get("num_comments", 0),
            ))
        return out


def default_sources() -> list[NewsSource]:
    """Free sources always; keyed sources when their key is set in the environment."""
    sources: list[NewsSource] = [
        RSSSource("cointelegraph", "https://cointelegraph.com/rss"),
        RSSSource("decrypt", "https://decrypt.co/feed"),
        RSSSource("coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=xml"),
        BinanceAnnouncements(),
        RedditSource("CryptoCurrency"),
    ]
    if os.environ.get("CRYPTOPANIC_TOKEN"):
        sources.append(CryptoPanicSource(os.environ["CRYPTOPANIC_TOKEN"]))
    if os.environ.get("NEWSAPI_KEY"):
        sources.append(NewsAPISource(os.environ["NEWSAPI_KEY"]))
    if os.environ.get("FINNHUB_API_KEY"):
        sources.append(FinnhubSource(os.environ["FINNHUB_API_KEY"]))
    if os.environ.get("ALPHAVANTAGE_API_KEY"):
        sources.append(AlphaVantageSource(key=os.environ["ALPHAVANTAGE_API_KEY"]))
    if os.environ.get("TWITTER_BEARER_TOKEN"):
        x = XSource(bearer=os.environ["TWITTER_BEARER_TOKEN"])
        if os.environ.get("TU_X_QUERY"):
            x.query = os.environ["TU_X_QUERY"]
        sources.append(x)
    return sources

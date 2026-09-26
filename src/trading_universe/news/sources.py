"""Where news comes from. Every source returns NewsItems and never crashes the collector.

Free, no key:   RSS feeds (Cointelegraph, Decrypt, CoinDesk), Binance announcements
Needs a key:    CryptoPanic (CRYPTOPANIC_TOKEN), NewsAPI (NEWSAPI_KEY)
Best effort:    Reddit public JSON (often blocked for servers)
"""

from __future__ import annotations

import json
import os
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
    return sources

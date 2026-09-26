"""News items and the coin / event-type tagging applied to them."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

# Coin names people actually write in headlines -> Binance symbol.
COIN_ALIASES: dict[str, tuple[str, ...]] = {
    "BTCUSDT": ("bitcoin", "btc"),
    "ETHUSDT": ("ethereum", "ether", "eth"),
    "SOLUSDT": ("solana", "sol"),
    "BNBUSDT": ("bnb", "binance coin", "bnb chain"),
    "XRPUSDT": ("xrp", "ripple"),
    "DOGEUSDT": ("dogecoin", "doge"),
    "ADAUSDT": ("cardano", "ada"),
    "AVAXUSDT": ("avalanche", "avax"),
    "LINKUSDT": ("chainlink", "link token"),
    "DOTUSDT": ("polkadot",),
    "TONUSDT": ("toncoin",),
    "TRXUSDT": ("tron", "trx"),
    "SUIUSDT": ("sui network", "sui"),
    "LTCUSDT": ("litecoin", "ltc"),
}

SECTORS: dict[str, str] = {
    "BTCUSDT": "store_of_value",
    "ETHUSDT": "layer1",
    "SOLUSDT": "layer1",
    "ADAUSDT": "layer1",
    "AVAXUSDT": "layer1",
    "DOTUSDT": "layer1",
    "SUIUSDT": "layer1",
    "TONUSDT": "layer1",
    "TRXUSDT": "layer1",
    "BNBUSDT": "exchange",
    "XRPUSDT": "payments",
    "LTCUSDT": "payments",
    "DOGEUSDT": "meme",
    "LINKUSDT": "oracle",
}

# Keyword -> event type. First match wins, so the most specific come first.
EVENT_TYPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("hack", ("hack", "exploit", "stolen", "drained", "breach", "attacker")),
    ("delisting", ("delist", "will remove", "cease trading")),
    ("listing", ("will list", "lists ", "listing", "launchpool", "added to", "will add")),
    ("etf", ("etf", "exchange-traded")),
    ("regulatory", ("sec ", "sec's", "regulator", "lawsuit", "ban ", "bans", "banned", "sebi", "rbi", "legal", "court", "compliance", "tax", "cftc", "mica")),
    ("macro", ("fed ", "federal reserve", "inflation", "interest rate", "cpi", "recession", "tariff")),
    ("upgrade", ("upgrade", "hard fork", "mainnet", "testnet launch", "network update")),
    ("partnership", ("partner", "integrat", "collaborat", "adopt")),
    ("whale", ("whale", "treasury", "buys ", "bought ", "accumulat", "sells ", "sold ")),
)

_PAREN_TICKER = re.compile(r"\(([A-Z0-9]{2,10})\)")


def _word_hit(text: str, alias: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text) is not None


def tag_symbols(text: str) -> tuple[str, ...]:
    low = text.lower()
    found = [sym for sym, names in COIN_ALIASES.items() if any(_word_hit(low, n) for n in names)]
    # Binance announcements name coins like "Hyperliquid (HYPE)".
    found += [f"{t}USDT" for t in _PAREN_TICKER.findall(text) if t not in ("USD", "USDT", "AI", "ETF", "SEC", "CEO", "US", "UK", "EU")]
    return tuple(dict.fromkeys(found))


def classify_event(text: str) -> str:
    low = f" {text.lower()} "
    for event_type, words in EVENT_TYPES:
        # Keywords must start at a word boundary ("tax" matches "taxes", not "syntax").
        if any(re.search(rf"(?<![a-z0-9]){re.escape(w)}", low) for w in words):
            return event_type
    return "general"


@dataclass(frozen=True)
class NewsItem:
    source: str
    title: str
    url: str
    published: datetime  # timezone-aware UTC
    summary: str = ""
    kind: str = "news"  # news | announcement | social
    symbols: tuple[str, ...] = ()
    event_type: str = "general"
    item_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def make(source: str, title: str, url: str, published: datetime, summary: str = "", kind: str = "news", **extra: Any) -> NewsItem:
        text = f"{title}. {summary}"
        return NewsItem(
            source=source,
            title=title.strip(),
            url=url,
            published=published,
            summary=summary.strip()[:1000],
            kind=kind,
            symbols=tag_symbols(text),
            event_type=classify_event(text),
            item_id=hashlib.sha1((url or f"{source}:{title}").encode()).hexdigest()[:16],
            extra=extra,
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["published"] = self.published.isoformat()
        d["symbols"] = list(self.symbols)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NewsItem:
        d = dict(d)
        d["published"] = datetime.fromisoformat(d["published"])
        d["symbols"] = tuple(d.get("symbols", ()))
        return cls(**d)

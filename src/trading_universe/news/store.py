"""Collect news from all sources, de-duplicate, keep it, and write it into the memory diary."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..memory.event_log import EventLog, MarketEvent
from .models import SECTORS, NewsItem
from .sources import NewsSource

MARKET = "MARKET"  # pseudo-symbol for news that isn't about one coin (macro, regulation...)


class NewsStore:
    """Append-only JSONL of every news item seen, keyed by item_id."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._items: dict[str, NewsItem] = {}
        if self.path and self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    item = NewsItem.from_dict(json.loads(line))
                    self._items[item.item_id] = item

    def add(self, item: NewsItem) -> bool:
        if item.item_id in self._items:
            return False
        self._items[item.item_id] = item
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(json.dumps(item.to_dict()) + "\n")
        return True

    def items(self, *, symbol: str | None = None, since: datetime | None = None, until: datetime | None = None) -> list[NewsItem]:
        out = [
            i for i in self._items.values()
            if (symbol is None or symbol in i.symbols or (symbol == MARKET and not i.symbols))
            and (since is None or i.published >= since)
            and (until is None or i.published <= until)
        ]
        return sorted(out, key=lambda i: i.published, reverse=True)

    def __len__(self) -> int:
        return len(self._items)


@dataclass
class CollectReport:
    new_items: list[NewsItem] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    per_source: dict[str, int] = field(default_factory=dict)


def collect(sources: list[NewsSource], store: NewsStore, diary: EventLog | None = None) -> CollectReport:
    report = CollectReport()
    for src in sources:
        try:
            items = src.fetch()
        except Exception as e:  # one broken feed must never stop the others
            report.errors[src.name] = f"{type(e).__name__}: {e}"
            continue
        count = 0
        for item in items:
            if store.add(item):
                count += 1
                report.new_items.append(item)
                if diary is not None:
                    for sym in item.symbols or (MARKET,):
                        eid = f"news:{item.item_id}:{sym}"
                        if diary.get(eid) is None:
                            diary.append(MarketEvent(eid, sym, item.published, item.event_type, item.title,
                                                     SECTORS.get(sym, "market" if sym == MARKET else "unknown"),
                                                     {"source": item.source, "url": item.url, "kind": item.kind}))
        report.per_source[src.name] = count
    return report

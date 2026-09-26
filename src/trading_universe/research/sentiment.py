"""Multi-dimensional news scoring (SDD §News & Sentiment): direction, magnitude, confidence.

Each team lead has its own profile, because a listing announcement, a regulator's statement
and a Reddit post need to be read differently.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass

from ..models import Direction
from ..news.models import NewsItem, tag_symbols
from .llm import JSONLLM, LLMUnavailable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LeadProfile:
    name: str
    domain: str
    description: str  # used for task routing (embedding fingerprint)
    event_types: tuple[str, ...]
    guidance: str  # how this lead reads news
    source_trust: float  # base confidence for its typical sources


LEADS: tuple[LeadProfile, ...] = (
    LeadProfile("listings", "news", "exchange listing delisting new coin trading pair launchpool", ("listing", "delisting"),
                "Exchange listings usually cause a short, sharp rise; delistings a sharp fall. Official exchange announcements are highly reliable.", 0.9),
    LeadProfile("regulatory", "news", "regulator sec lawsuit ban law court tax compliance government policy", ("regulatory", "etf"),
                "Regulatory news moves the whole market or one coin for days. ETF approvals are bullish, bans and lawsuits bearish. Rumours are common; weigh officials above commentators.", 0.7),
    LeadProfile("security", "news", "hack exploit stolen funds breach attacker drained", ("hack",),
                "Hacks are bearish for the affected coin or platform, often sharply. Size of the loss matters.", 0.8),
    LeadProfile("macro", "news", "federal reserve interest rates inflation cpi recession tariff economy", ("macro",),
                "Macro news moves all risk assets. Rate cuts and easing are bullish, hikes and inflation surprises bearish.", 0.6),
    LeadProfile("flows", "news", "whale treasury company buys sells accumulation etf inflows outflows", ("whale",),
                "Large buyers are bullish, large sellers bearish; the effect is usually modest unless the size is huge.", 0.6),
    LeadProfile("tech", "news", "network upgrade hard fork mainnet partnership integration adoption", ("upgrade", "partnership"),
                "Upgrades and partnerships are mildly bullish unless they slip or fail.", 0.5),
    LeadProfile("social", "news", "social media reddit twitter hype community sentiment", ("social",),
                "Social posts move faster than official news but are noisy and often wrong. Keep confidence low unless many independent sources agree.", 0.3),
    LeadProfile("general", "news", "general crypto market news analysis", ("general",),
                "General news rarely justifies a trade on its own.", 0.4),
)
LEAD_BY_NAME = {lead.name: lead for lead in LEADS}


def lead_for_event(event_type: str) -> LeadProfile:
    if event_type == "social":
        return LEAD_BY_NAME["social"]
    return next((lead for lead in LEADS if event_type in lead.event_types), LEAD_BY_NAME["general"])


def lead_for(item: NewsItem) -> LeadProfile:
    if item.kind == "social":
        return LEAD_BY_NAME["social"]
    return next((lead for lead in LEADS if item.event_type in lead.event_types), LEAD_BY_NAME["general"])


@dataclass(frozen=True)
class ScoredNews:
    item: NewsItem
    symbol: str
    direction: Direction
    magnitude: float  # 0..1
    confidence: float  # 0..1
    actionable: bool
    reason: str
    lead: str
    scorer: str


# ---------------------------------------------------------------------------- rule-based

BULLISH = ("approve", "approval", "surge", "soar", "rally", "record high", "all-time high", "will list", "launchpool", "adopt",
           "partnership", "inflow", "buys", "bought", "accumulat", "upgrade", "bullish", "gain", "jump", "rate cut", "etf approved")
BEARISH = ("hack", "exploit", "stolen", "drained", "delist", "ban", "lawsuit", "sues", "charges", "crash", "plunge", "slump",
           "outflow", "sells", "sold", "bearish", "fall", "drop", "liquidat", "fraud", "rate hike", "reject", "delay", "slips")


def _count(text: str, words: Sequence[str]) -> int:
    return sum(1 for w in words if re.search(rf"(?<![a-z]){re.escape(w)}", text))


class KeywordScorer:
    """Offline fallback: counts bullish/bearish words, trusts the lead's source reliability."""

    name = "keywords"

    def score(self, item: NewsItem, symbol: str, lead: LeadProfile) -> ScoredNews:
        text = f"{item.title} {item.summary}".lower()
        up, down = _count(text, BULLISH), _count(text, BEARISH)
        if item.event_type == "listing":
            up += 2
        elif item.event_type in ("delisting", "hack"):
            down += 2
        net = up - down
        direction = Direction.BULLISH if net > 0 else Direction.BEARISH if net < 0 else Direction.NEUTRAL
        magnitude = min(1.0, 0.2 + 0.2 * abs(net)) if net else 0.1
        confidence = lead.source_trust * (0.9 if item.kind == "announcement" else 0.7)
        actionable = direction != Direction.NEUTRAL and magnitude >= 0.4 and lead.name not in ("general", "social")
        if symbol != "MARKET" and symbol not in tag_symbols(item.title):
            # The coin is only mentioned in passing (summary, not headline): weak evidence about it.
            magnitude, actionable = magnitude * 0.5, False
        return ScoredNews(item, symbol, direction, round(magnitude, 3), round(confidence, 3), actionable,
                          f"{up} bullish / {down} bearish cues", lead.name, self.name)


def default_scorer():
    """Gemini (or Claude) when a key is set, keyword scoring otherwise or whenever the API call fails."""
    from .llm import default_llm

    llm = default_llm()
    return LLMScorer(llm) if llm else KeywordScorer()


# ------------------------------------------------------------------------------- Claude

SCHEMA = {
    "type": "object",
    "properties": {
        "direction": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
        "magnitude": {"type": "number", "description": "0 = irrelevant, 1 = market-moving"},
        "confidence": {"type": "number", "description": "0..1, how reliable / corroborated"},
        "actionable": {"type": "boolean"},
        "reason": {"type": "string", "description": "one short sentence"},
    },
    "required": ["direction", "magnitude", "confidence", "actionable", "reason"],
    "additionalProperties": False,
}

SYSTEM = (
    "You are a crypto market research analyst on the {lead} desk. {guidance}\n"
    "Score how one news item affects the price of one coin over the next 1-3 days. "
    "direction: bullish, bearish or neutral for that coin. magnitude: 0 (irrelevant) to 1 (market-moving). "
    "confidence: 0 to 1, how reliable the source and the claim are. actionable: true only if a trader should act "
    "on it now, given everything above. reason: one short sentence. Judge only from the text given."
)


class LLMScorer:
    def __init__(self, llm: JSONLLM, fallback: KeywordScorer | None = None) -> None:
        self.llm = llm
        self.fallback = fallback or KeywordScorer()
        self.name = llm.name

    def score(self, item: NewsItem, symbol: str, lead: LeadProfile) -> ScoredNews:
        coin = "the whole crypto market" if symbol == "MARKET" else symbol.removesuffix("USDT")
        prompt = (f"Coin: {coin}\nSource: {item.source} ({item.kind})\nPublished: {item.published:%Y-%m-%d %H:%M} UTC\n"
                  f"Headline: {item.title}\nSummary: {item.summary[:800] or '(none)'}")
        try:
            out = self.llm.complete_json(SYSTEM.format(lead=lead.name, guidance=lead.guidance), prompt, SCHEMA)
        except LLMUnavailable as e:
            log.info("LLM unavailable (%s); %s scoring %s", e, self.fallback.name, item.item_id)
            return self.fallback.score(item, symbol, lead)
        clamp = lambda v: max(0.0, min(1.0, float(v)))  # noqa: E731
        return ScoredNews(item, symbol, Direction(out["direction"]), clamp(out["magnitude"]), clamp(out["confidence"]),
                          bool(out["actionable"]), str(out["reason"])[:300], lead.name, self.name)

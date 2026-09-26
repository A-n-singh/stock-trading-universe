"""Multi-dimensional news scoring (SDD §News & Sentiment): direction, magnitude, confidence.

Each team lead has its own profile, because a listing announcement, a regulator's statement
and a Reddit post need to be read differently.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass

import os
from collections.abc import Callable

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


# ------------------------------------------------------------------- free local model

DEFAULT_NEWS_MODEL = "ProsusAI/finbert"  # trained on financial news; ~440 MB, runs on a normal CPU
POSITIVE, NEGATIVE = ("positive", "bullish"), ("negative", "bearish")
EVENT_BIAS = {"listing": 0.5, "delisting": -0.5, "hack": -0.5}  # the model can't know these by tone alone


def _default_classifier(model: str) -> Callable[[list[str]], list[dict[str, float]]]:
    from transformers import pipeline  # heavy; only when the model scorer is actually used

    pipe = pipeline("text-classification", model=model, top_k=None, truncation=True)

    def classify(texts: list[str]) -> list[dict[str, float]]:
        return [{d["label"].lower(): float(d["score"]) for d in out} for out in pipe(texts)]

    return classify


class ModelScorer:
    """Free news scorer, no API key: a small sentiment model (downloaded once from Hugging Face) combined
    with the keyword and event rules.

    Tested on crypto headlines, small models alone are not good enough: FinBERT reads tone well
    ("network suffers outage" → negative, which keywords miss) but calls "SEC approves spot Ether ETFs"
    neutral and can't know that an exchange listing lifts a price. So the model's tone (60%) is blended
    with the keyword cues (40%) plus the listing / delisting / hack rules. Better than keywords alone,
    well short of Claude or another LLM. Model: TU_NEWS_MODEL, default ProsusAI/finbert.
    """

    def __init__(self, model: str | None = None, classify: Callable[[list[str]], list[dict[str, float]]] | None = None) -> None:
        self.model = model or os.environ.get("TU_NEWS_MODEL", DEFAULT_NEWS_MODEL)
        self.name = f"model:{self.model.split('/')[-1]}+keywords"
        self._classify = classify or _default_classifier(self.model)
        self._seen: dict[str, dict[str, float]] = {}  # one item is often scored for several coins

    def probs(self, item: NewsItem) -> dict[str, float]:
        if item.item_id not in self._seen:
            text = item.title if not item.summary else f"{item.title}. {item.summary[:400]}"
            self._seen[item.item_id] = self._classify([text])[0]
            if len(self._seen) > 5000:
                self._seen.pop(next(iter(self._seen)))
        return self._seen[item.item_id]

    def score(self, item: NewsItem, symbol: str, lead: LeadProfile) -> ScoredNews:
        p = self.probs(item)
        pos = sum(v for k, v in p.items() if k in POSITIVE)
        neg = sum(v for k, v in p.items() if k in NEGATIVE)
        text = f"{item.title} {item.summary}".lower()
        up, down = _count(text, BULLISH), _count(text, BEARISH)
        cues = max(-2, min(2, up - down)) / 2  # -1..1
        net = 0.6 * (pos - neg) + 0.4 * cues + EVENT_BIAS.get(item.event_type, 0.0)
        direction = Direction.BULLISH if net >= 0.25 else Direction.BEARISH if net <= -0.25 else Direction.NEUTRAL
        magnitude = min(1.0, abs(net)) if direction != Direction.NEUTRAL else 0.1
        certainty = max(pos, neg, 1 - pos - neg)  # how sure the model is of its own label
        confidence = lead.source_trust * (0.9 if item.kind == "announcement" else 0.7) * (0.5 + 0.5 * certainty)
        actionable = direction != Direction.NEUTRAL and magnitude >= 0.4 and lead.name not in ("general", "social")
        if symbol != "MARKET" and symbol not in tag_symbols(item.title):
            magnitude, actionable = magnitude * 0.5, False  # coin only mentioned in passing
        return ScoredNews(item, symbol, direction, round(magnitude, 3), round(confidence, 3), actionable,
                          f"tone {pos:.0%} positive / {neg:.0%} negative; {up} bullish / {down} bearish cues", lead.name, self.name)


def local_model_scorer() -> ModelScorer | None:
    """The free model if it can be loaded here (needs `pip install -e '.[newsmodel]'`), else None.
    TU_NEWS_MODEL=off disables it."""
    if os.environ.get("TU_NEWS_MODEL", "").lower() in ("off", "none", "0"):
        return None
    try:
        return ModelScorer()
    except Exception as e:  # not installed, no disk or no internet for the first download
        log.info("free news model unavailable (%s); using keywords", e)
        return None


def default_scorer():
    """Best available: Claude or another LLM → free local model → keywords. Each falls back to the next."""
    from .llm import default_llm

    local = local_model_scorer()
    base = local or KeywordScorer()
    llm = default_llm()
    return LLMScorer(llm, fallback=base) if llm else base


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
    def __init__(self, llm: JSONLLM, fallback: KeywordScorer | ModelScorer | None = None) -> None:
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

"""Three-part training-example wrapper (TDD §Model Training Approach).

1. context  — flexible, domain-specific facts
2. question — strict: the question plus a fixed list of allowed answers
3. output   — constant shape across domains: one allowed answer + confidence in [0, 1]
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..trade_log import TradeRecord


@dataclass(frozen=True)
class Question:
    text: str
    allowed_answers: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.allowed_answers) < 2 or len(set(self.allowed_answers)) != len(self.allowed_answers):
            raise ValueError("allowed_answers needs at least two distinct options")


@dataclass(frozen=True)
class Output:
    answer: str
    confidence: float

    def validate(self, q: Question) -> None:
        if self.answer not in q.allowed_answers:
            raise ValueError(f"answer {self.answer!r} not in {q.allowed_answers}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")


@dataclass(frozen=True)
class TrainingExample:
    context: dict[str, Any]
    question: Question
    output: Output
    # Not shown to the model; used for RL reward and evaluation.
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.output.validate(self.question)

    def prompt(self) -> str:
        return json.dumps(
            {
                "context": self.context,
                "question": self.question.text,
                "allowed_answers": list(self.question.allowed_answers),
                "respond_with": {"answer": "<one of allowed_answers>", "confidence": "<0..1>"},
            },
            sort_keys=True,
        )

    def target(self) -> str:
        return json.dumps({"answer": self.output.answer, "confidence": self.output.confidence})

    def to_jsonl(self) -> str:
        return json.dumps({"prompt": self.prompt(), "completion": self.target(), "meta": self.meta})


GATE_QUESTIONS: dict[str, Question] = {
    "news": Question("Is this news actionable for a trade in the snapshot's direction?", ("act", "watch", "ignore")),
    "technical": Question("Does price action confirm entry now?", ("confirm", "wait", "reject")),
    "risk": Question("Clear this trade under the per-trade risk budget?", ("clear", "block")),
    "trade": Question("Given this snapshot, what should the Trading Agent do?", ("buy", "sell", "hold")),
}


def trade_context(rec: TradeRecord) -> dict[str, Any]:
    snap = rec.snapshot
    return {
        "symbol": rec.symbol,
        "asset_class": snap.get("asset_class"),
        "sector": snap.get("sector"),
        "direction_bias": snap.get("direction_bias"),
        "snapshot_confidence": snap.get("confidence"),
        "risk_flags": snap.get("risk_flags", []),
        "news": snap.get("news"),
        "technical": next((v["details"] for v in rec.votes if v["name"] == "technical"), {}),
        "entry_price": rec.entry_price,
    }


def example_from_trade(rec: TradeRecord) -> TrainingExample:
    """Label a closed trade with what the agent *should* have done, based on the realised outcome."""
    if not rec.closed or rec.pnl is None:
        raise ValueError(f"trade {rec.trade_id} is not closed")
    won = rec.pnl > 0
    answer = rec.action if won else "hold"
    # SFT target confidence scales with how decisive the outcome was, in units of risk taken.
    r_multiple = rec.pnl / rec.risk_amount if rec.risk_amount else 0.0
    confidence = max(0.5, min(0.95, 0.5 + 0.15 * abs(r_multiple)))
    return TrainingExample(
        context=rec.context or trade_context(rec),
        question=GATE_QUESTIONS["trade"],
        output=Output(answer, round(confidence, 3)),
        meta={"trade_id": rec.trade_id, "time": rec.opened_at, "taken_action": rec.action, "pnl": rec.pnl, "risk_amount": rec.risk_amount, "closed_at": rec.closed_at},
    )

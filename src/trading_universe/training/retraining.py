"""Automated retraining loop (TDD §Automated Retraining Pipeline).

extract -> trigger (≥ N new labelled trades) -> train -> evaluate on held-out recent trades
-> promote only if the candidate beats the live model -> monitor.
Live trading keeps running in real time; only this batch is periodic.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from ..trade_log import TradeLog
from .calibration import expected_calibration_error, reward
from .schema import Output, TrainingExample, example_from_trade


class DecisionModel(Protocol):
    model_id: str

    def decide(self, example: TrainingExample) -> Output: ...


class Trainer(Protocol):
    """Kicks off SFT (+ RL) on a rented GPU and returns the trained, quantized model."""

    def train(self, dataset: Path, base: DecisionModel | None) -> DecisionModel: ...


@dataclass(frozen=True)
class EvalResult:
    model_id: str
    n: int
    profit: float
    mean_reward: float
    accuracy: float
    ece: float


def realised_pnl(answer: str, ex: TrainingExample) -> float:
    """Counterfactual P&L of `answer` on a logged trade.

    Same side as taken -> the realised P&L; hold -> 0; opposite side -> unknown, so scored
    pessimistically as a full loss of the realised move.
    """
    taken, pnl = ex.meta["taken_action"], ex.meta["pnl"]
    if answer == taken:
        return pnl
    if answer == "hold":
        return 0.0
    return -abs(pnl)


def evaluate(model: DecisionModel, holdout: Sequence[TrainingExample]) -> EvalResult:
    profit = total_reward = correct = 0.0
    calib = []
    for ex in holdout:
        out = model.decide(ex)
        out.validate(ex.question)
        ok = out.answer == ex.output.answer
        pnl = realised_pnl(out.answer, ex)
        profit += pnl
        total_reward += reward(pnl, ex.meta["risk_amount"], out.confidence, ok)
        correct += ok
        calib.append((out.confidence, ok))
    n = len(holdout)
    return EvalResult(
        model_id=model.model_id,
        n=n,
        profit=profit,
        mean_reward=total_reward / n if n else 0.0,
        accuracy=correct / n if n else 0.0,
        ece=expected_calibration_error(calib),
    )


@dataclass
class PipelineState:
    watermark: str = ""  # closed_at of the newest trade already used for training
    pending: int = 0
    live_model_id: str | None = None


@dataclass(frozen=True)
class RunResult:
    status: str  # waiting | promoted | rejected
    new_examples: int
    candidate: EvalResult | None = None
    live: EvalResult | None = None


class RetrainingPipeline:
    def __init__(
        self,
        trade_log: TradeLog,
        trainer: Trainer,
        workdir: Path,
        live_model: DecisionModel | None = None,
        min_new_examples: int = 1000,
        holdout_fraction: float = 0.2,
        max_ece_regression: float = 0.05,
    ) -> None:
        self.trade_log, self.trainer, self.workdir = trade_log, trainer, Path(workdir)
        self.live_model = live_model
        self.min_new_examples, self.holdout_fraction = min_new_examples, holdout_fraction
        self.max_ece_regression = max_ece_regression
        self.workdir.mkdir(parents=True, exist_ok=True)
        self._state_path = self.workdir / "state.json"
        self.state = PipelineState(**json.loads(self._state_path.read_text())) if self._state_path.exists() else PipelineState()

    def _save(self) -> None:
        self._state_path.write_text(json.dumps(asdict(self.state)))

    def extract(self) -> list[TrainingExample]:
        closed = sorted(self.trade_log.closed_trades(), key=lambda r: r.closed_at or "")
        return [example_from_trade(r) for r in closed]

    def run_once(self) -> RunResult:
        examples = self.extract()
        new = [e for e in examples if e.meta["closed_at"] > self.state.watermark]
        self.state.pending = len(new)
        if len(new) < self.min_new_examples:
            self._save()
            return RunResult("waiting", len(new))

        # Hold out the most recent trades: the candidate must generalise forward in time.
        cut = int(len(examples) * (1 - self.holdout_fraction))
        train, holdout = examples[:cut], examples[cut:]
        dataset = self.workdir / f"train-{new[-1].meta['closed_at'].replace(':', '')}.jsonl"
        dataset.write_text("\n".join(e.to_jsonl() for e in train) + "\n")

        candidate = self.trainer.train(dataset, self.live_model)
        cand_eval = evaluate(candidate, holdout)
        live_eval = evaluate(self.live_model, holdout) if self.live_model else None

        self.state.watermark = new[-1].meta["closed_at"]
        self.state.pending = 0
        beats = live_eval is None or (
            cand_eval.profit > live_eval.profit and cand_eval.ece <= live_eval.ece + self.max_ece_regression
        )
        if beats:
            self.live_model = candidate
            self.state.live_model_id = candidate.model_id
        self._save()
        return RunResult("promoted" if beats else "rejected", len(new), cand_eval, live_eval)

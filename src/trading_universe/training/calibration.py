"""RL reward: profit plus a Brier-style calibration term (TDD §Calibration reward).

Downstream code branches on the model's confidence, so it must learn how sure to be,
not only what to decide. Overconfident-and-wrong costs more than uncertain-and-wrong.
"""

from __future__ import annotations

import math
from collections.abc import Iterable


def brier(confidence: float, correct: bool) -> float:
    return (confidence - (1.0 if correct else 0.0)) ** 2


def reward(
    pnl: float,
    risk_amount: float,
    confidence: float,
    correct: bool,
    profit_weight: float = 1.0,
    calibration_weight: float = 1.0,
    overconfidence_penalty: float = 2.0,
) -> float:
    """Reward for one decision.

    - profit term: realised P&L in units of risk taken (R-multiple), squashed to [-1, 1]
    - calibration term: negative Brier score, doubled (by default) when wrong
    """
    if not 0 <= confidence <= 1:
        raise ValueError("confidence must be in [0, 1]")
    r = pnl / risk_amount if risk_amount > 0 else 0.0
    profit_term = math.tanh(r)
    penalty = brier(confidence, correct) * (1.0 if correct else overconfidence_penalty)
    return profit_weight * profit_term - calibration_weight * penalty


def expected_calibration_error(pairs: Iterable[tuple[float, bool]], bins: int = 10) -> float:
    """Weighted gap between stated confidence and realised accuracy across confidence bins."""
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    items = list(pairs)
    for c, ok in items:
        buckets[min(bins - 1, int(c * bins))].append((c, ok))
    if not items:
        return 0.0
    return sum(
        len(b) / len(items) * abs(sum(c for c, _ in b) / len(b) - sum(ok for _, ok in b) / len(b)) for b in buckets if b
    )

"""Spot-check historical news/price pairs against an independent price source before trusting them.

A wrong historical label trains the model on wrong ground truth (BRD assumption, SDD safeguards).
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class PricedNews:
    symbol: str
    day: date
    close: float
    headline: str = ""


@dataclass
class SpotCheckReport:
    sampled: int
    missing_reference: int
    mismatches: list[tuple[PricedNews, float]] = field(default_factory=list)

    @property
    def checked(self) -> int:
        return self.sampled - self.missing_reference

    @property
    def mismatch_rate(self) -> float:
        return len(self.mismatches) / self.checked if self.checked else 1.0

    def trusted(self, max_mismatch_rate: float = 0.02, min_checked: int = 50) -> bool:
        return self.checked >= min_checked and self.mismatch_rate <= max_mismatch_rate


def spot_check(
    rows: Sequence[PricedNews],
    reference_close: Callable[[str, date], float | None],
    sample_size: int = 100,
    rel_tolerance: float = 0.005,
    seed: int | None = 0,
) -> SpotCheckReport:
    """Compare a random sample of the dataset's closes with `reference_close` (e.g. a second exchange's prices)."""
    rng = random.Random(seed)
    sample = rng.sample(list(rows), min(sample_size, len(rows)))
    report = SpotCheckReport(sampled=len(sample), missing_reference=0)
    for row in sample:
        ref = reference_close(row.symbol, row.day)
        if ref is None:
            report.missing_reference += 1
            continue
        if abs(row.close - ref) > rel_tolerance * max(abs(ref), 1e-9):
            report.mismatches.append((row, ref))
    return report

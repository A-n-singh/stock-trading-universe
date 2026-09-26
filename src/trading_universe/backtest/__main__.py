"""Command line: python -m trading_universe.backtest prices/INFY.csv prices/TCS.csv [--holdout-days 365]

Each CSV needs a date column and open/high/low/close (a Yahoo Finance export works).
Pass --demo to run on generated prices instead (for trying it out only).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from ..config import AgentConfig
from .data import load_csv, synthetic_prices
from .optimize import optimize, setting_from_config


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m trading_universe.backtest")
    ap.add_argument("csv", nargs="*", help="one CSV of daily candles per symbol (file name = symbol)")
    ap.add_argument("--demo", action="store_true", help="use generated prices instead of CSVs")
    ap.add_argument("--holdout-days", type=int, default=365, help="how much recent history to hide (default 365)")
    ap.add_argument("--top", type=int, default=5, help="how many practice winners sit the hidden-year exam")
    ap.add_argument("--min-trades", type=int, default=30, help="ignore settings with fewer practice trades")
    ap.add_argument("--risk", type=float, default=250.0, help="₹ risk per trade, for converting R to rupees")
    ap.add_argument("--save", type=Path, help="write the chosen setting to this JSON file")
    args = ap.parse_args()

    if args.demo:
        data = {f"DEMO{i}": synthetic_prices(5 * 252, seed=i) for i in range(5)}
    elif args.csv:
        data = {Path(p).stem.upper(): load_csv(p) for p in args.csv}
    else:
        ap.error("give one or more CSV files, or --demo")

    t0 = time.perf_counter()
    report = optimize(data, holdout_days=args.holdout_days, top_k=args.top, min_practice_trades=args.min_trades, current=setting_from_config(AgentConfig()))
    print(report.to_text(args.risk))
    print(f"\n(took {time.perf_counter() - t0:.1f}s for {len(data)} symbols)")
    if args.save and report.chosen:
        s = report.chosen
        args.save.write_text(json.dumps({"trend_window": s.trend_window, "breakout_window": s.breakout_window, "triggers": list(s.triggers), "stop_loss_pct": s.stop_loss_pct}, indent=2))
        print(f"saved to {args.save}")


if __name__ == "__main__":
    main()

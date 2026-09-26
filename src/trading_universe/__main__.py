"""Command line for the whole system.

  python -m trading_universe run                  research + trading + learning, forever (paper money)
  python -m trading_universe run --minutes 30     stop after 30 minutes
  python -m trading_universe research             one research cycle, print the snapshots
  python -m trading_universe trade                one trading tick
  python -m trading_universe status               what the running system is doing

Options: --data runs  --coins BTCUSDT,ETHUSDT  --broker paper|binance-testnet
Backtests: python -m trading_universe.backtest ...
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from .runner import RunConfig, Runner


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m trading_universe")
    ap.add_argument("command", choices=["run", "research", "trade", "status"])
    ap.add_argument("--data", type=Path, default=Path("runs"))
    ap.add_argument("--coins", default="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT")
    ap.add_argument("--broker", choices=["paper", "binance-testnet"], default="paper")
    ap.add_argument("--minutes", type=float, help="stop 'run' after this many minutes")
    ap.add_argument("--research-every", type=float, default=15, help="minutes between research cycles")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    if args.command == "status":
        path = args.data / "status.json"
        print(path.read_text() if path.exists() else f"No status yet in {path}. Start with: python -m trading_universe run")
        return

    cfg = RunConfig(data_dir=args.data, symbols=tuple(c.strip().upper() for c in args.coins.split(",") if c.strip()),
                    broker=args.broker, research_every_s=args.research_every * 60)
    runner = Runner(cfg)
    if args.command == "research":
        runner.research()
        for s in runner.snapshots.latest().values():
            print(json.dumps({"symbol": s.symbol, "bias": s.direction_bias.value, "confidence": s.confidence,
                              "flags": list(s.risk_flags), "rationale": s.rationale}, indent=1))
    elif args.command == "trade":
        for e in runner.trade().events:
            print(e.symbol, e.kind, e.detail)
    else:
        print(f"Running: scorer={runner.status.scorer}, broker={cfg.broker}, data in {cfg.data_dir}/ (Ctrl+C to stop)")
        runner.loop(max_seconds=args.minutes * 60 if args.minutes else None)


if __name__ == "__main__":
    main()

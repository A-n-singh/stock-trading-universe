"""Command line.

  python -m trading_universe.backtest BTCUSDT ETHUSDT SOLUSDT          # download from Binance, then search
  python -m trading_universe.backtest prices/BTCUSDT.csv               # use CSV files you already have
  python -m trading_universe.backtest --demo                           # generated prices, just to try it

Crypto is the default. Add --market stock for stock settings (weekday prices, lower fees, tighter stops).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from ..config import AgentConfig
from .data import fetch_binance, load_csv, save_csv, synthetic_prices
from .engine import PROFILES, build_grid
from .optimize import optimize, setting_from_config


def load(sources: list[str], interval: str, start: str, cache: Path) -> dict:
    data = {}
    for src in sources:
        p = Path(src)
        if p.suffix.lower() == ".csv" and p.exists():
            data[p.stem.upper()] = load_csv(p)
            continue
        cached = cache / f"{src.upper()}-{interval}.csv"
        if cached.exists():
            print(f"{src}: using saved {cached}")
            data[src.upper()] = load_csv(cached)
            continue
        print(f"{src}: downloading {interval} candles from Binance since {start} ...")
        df = fetch_binance(src, interval, start)
        cache.mkdir(parents=True, exist_ok=True)
        save_csv(df, cached)
        data[src.upper()] = df
    return data


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m trading_universe.backtest")
    ap.add_argument("sources", nargs="*", help="Binance symbols (BTCUSDT) or CSV files")
    ap.add_argument("--demo", action="store_true", help="use generated prices instead")
    ap.add_argument("--market", choices=sorted(PROFILES), default="crypto")
    ap.add_argument("--interval", default="1d", help="candle size for downloads: 1d, 4h, 1h ... (default 1d)")
    ap.add_argument("--start", default="2020-01-01", help="download history from this date")
    ap.add_argument("--cache", type=Path, default=Path("prices"), help="folder for downloaded CSVs")
    ap.add_argument("--holdout-days", type=int, default=365, help="how much recent history to hide (default 365)")
    ap.add_argument("--top", type=int, default=5, help="how many practice winners sit the hidden-year exam")
    ap.add_argument("--min-trades", type=int, default=30, help="ignore settings with fewer practice trades")
    ap.add_argument("--risk", type=float, default=250.0, help="₹ risk per trade, for converting R to rupees")
    ap.add_argument("--save", type=Path, help="write the chosen setting to this JSON file")
    args = ap.parse_args()

    profile = PROFILES[args.market]
    if args.demo:
        calendar = "24/7" if args.market == "crypto" else "weekdays"
        data = {f"DEMO{i}": synthetic_prices(5 * 365, seed=i, vol=0.035 if args.market == "crypto" else 0.015, calendar=calendar) for i in range(5)}
    elif args.sources:
        data = load(args.sources, args.interval, args.start, args.cache)
    else:
        ap.error("give Binance symbols (e.g. BTCUSDT) or CSV files, or --demo")

    cfg = AgentConfig()
    t0 = time.perf_counter()
    report = optimize(
        data,
        build_grid(stop_losses=profile.stop_losses),
        holdout_days=args.holdout_days,
        top_k=args.top,
        min_practice_trades=args.min_trades,
        current=setting_from_config(cfg),
        costs=profile.costs,
    )
    print(f"\nMarket: {profile.name}  (fees {profile.costs.fees:.2%} per side, stop-losses tried: {', '.join(f'{s:.0%}' for s in profile.stop_losses)})")
    print(report.to_text(args.risk))
    print(f"\n(took {time.perf_counter() - t0:.1f}s for {len(data)} symbols)")
    if args.save and report.chosen:
        s = report.chosen
        args.save.write_text(json.dumps({"trend_window": s.trend_window, "breakout_window": s.breakout_window, "triggers": list(s.triggers), "stop_loss_pct": s.stop_loss_pct}, indent=2))
        print(f"saved to {args.save}")


if __name__ == "__main__":
    main()

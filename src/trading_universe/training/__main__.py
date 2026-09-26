"""Training command line.

  python -m trading_universe.training build   --coins BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT --out data/
      -> data/train.jsonl, data/test.jsonl (history bootstrap + logged snapshots + closed trades), baselines
  python -m trading_universe.training sft     --train data/train.jsonl --base Qwen/Qwen2.5-1.5B-Instruct --out models/sft
  python -m trading_universe.training rl      --train data/train.jsonl --base models/sft-merged --out models/rl
  python -m trading_universe.training merge   --adapter models/sft --out models/sft-merged
  python -m trading_universe.training evaluate --model models/rl-merged --test data/test.jsonl
  python -m trading_universe.training retrain --runs runs --min-new 1000
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .retraining import evaluate


def _baselines(test):
    from .models import ConstantModel

    for m in (ConstantModel("buy"), ConstantModel("hold")):
        r = evaluate(m, test)
        print(f"  {m.model_id:14} profit {r.profit:+8.1f} R  accuracy {r.accuracy:.0%}  calibration error {r.ece:.2f}")


def cmd_build(a) -> None:
    import pandas as pd

    from ..backtest.data import fetch_binance, load_csv, save_csv
    from ..backtest.signals import long_signals
    from ..news.store import NewsStore
    from ..research.snapshots import snapshot_from_dict
    from ..trade_log import TradeLog
    from .dataset import examples_from_history, examples_from_snapshots, split_by_time, write_jsonl
    from .schema import example_from_trade

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    frames = {}
    for sym in [c.strip().upper() for c in a.coins.split(",") if c.strip()]:
        cache = out / f"{sym}-1d.csv"
        frames[sym] = load_csv(cache) if cache.exists() else fetch_binance(sym, "1d", a.start)
        save_csv(frames[sym], cache)
    entries = {s: long_signals(df, a.trend, a.breakout, ("engulfing", "wick", "breakout"))[0] for s, df in frames.items()}
    runs = Path(a.runs)
    news = NewsStore(runs / "news.jsonl") if (runs / "news.jsonl").exists() else None
    examples = examples_from_history(frames, entries, news, stop_pct=a.stop)
    hist = runs / "snapshots" / "history.jsonl"
    if hist.exists():
        snaps = [snapshot_from_dict(json.loads(line)) for line in hist.read_text().splitlines() if line.strip()]
        examples += examples_from_snapshots(snaps, frames, stop_pct=a.stop)
    if (runs / "trades.jsonl").exists():
        examples += [example_from_trade(r) for r in TradeLog(runs / "trades.jsonl").closed_trades()]
    train, test = split_by_time(examples, 0.2)
    write_jsonl(train, out / "train.jsonl")
    write_jsonl(test, out / "test.jsonl")
    buys = sum(e.output.answer == "buy" for e in examples)
    print(f"{len(examples)} examples ({buys} labelled buy) -> {len(train)} train / {len(test)} test (newest 20%) in {out}/")
    print("Baselines on the test set (a trained model must beat 'always-hold'):")
    _baselines(test)
    _ = pd  # pandas imported for the loaders above


def cmd_sft(a) -> None:
    from .train import TrainConfig, merge, sft

    adapter = sft(a.train, TrainConfig(base_model=a.base, output_dir=a.out, epochs=a.epochs, batch_size=a.batch,
                                       load_in_4bit=a.qlora, bf16=a.bf16, max_steps=a.max_steps))
    print("merged model:", merge(adapter, a.out + "-merged"))


def cmd_rl(a) -> None:
    from .train import TrainConfig, merge, rl

    adapter = rl(a.train, a.base, TrainConfig(base_model=a.base, output_dir=a.out, epochs=a.epochs, batch_size=a.batch,
                                              bf16=a.bf16, max_steps=a.max_steps), num_generations=a.generations)
    print("merged model:", merge(adapter, a.out + "-merged"))


def cmd_merge(a) -> None:
    from .train import QUANTIZE_HELP, merge

    print("merged model:", merge(a.adapter, a.out))
    print(QUANTIZE_HELP)


def cmd_evaluate(a) -> None:
    from .dataset import read_examples
    from .models import HFDecisionModel, HTTPDecisionModel

    test = read_examples(a.test)
    model = HTTPDecisionModel(a.model, a.served_name) if a.model.startswith("http") else HFDecisionModel(a.model)
    r = evaluate(model, test)
    print(f"{r.model_id}: profit {r.profit:+.1f} R over {r.n} decisions, accuracy {r.accuracy:.0%}, calibration error {r.ece:.2f}")
    print("Baselines:")
    _baselines(test)


def cmd_retrain(a) -> None:
    from ..trade_log import TradeLog
    from .models import HFDecisionModel
    from .retraining import RetrainingPipeline, ScriptTrainer
    from .train import TrainConfig

    runs = Path(a.runs)
    live = HFDecisionModel(a.live) if a.live else None
    pipe = RetrainingPipeline(TradeLog(runs / "trades.jsonl"), ScriptTrainer(TrainConfig(base_model=a.base)), runs / "retraining",
                              live_model=live, min_new_examples=a.min_new)
    res = pipe.run_once()
    print(f"status: {res.status} ({res.new_examples} new closed trades)")
    if res.candidate:
        print("candidate:", res.candidate)
        print("live:     ", res.live)


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m trading_universe.training")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--coins", default="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT")
    b.add_argument("--start", default="2020-01-01")
    b.add_argument("--out", default="data")
    b.add_argument("--runs", default="runs")
    b.add_argument("--trend", type=int, default=20)
    b.add_argument("--breakout", type=int, default=10)
    b.add_argument("--stop", type=float, default=0.03)
    for name in ("sft", "rl"):
        p = sub.add_parser(name)
        p.add_argument("--train", required=True)
        p.add_argument("--base", default="Qwen/Qwen2.5-1.5B-Instruct")
        p.add_argument("--out", required=True)
        p.add_argument("--epochs", type=float, default=2 if name == "sft" else 1)
        p.add_argument("--batch", type=int, default=8)
        p.add_argument("--bf16", action="store_true")
        p.add_argument("--max-steps", type=int, default=-1)
        if name == "sft":
            p.add_argument("--qlora", action="store_true", help="4-bit QLoRA, for 30-40B models on one GPU")
        else:
            p.add_argument("--generations", type=int, default=4)
    m = sub.add_parser("merge")
    m.add_argument("--adapter", required=True)
    m.add_argument("--out", required=True)
    e = sub.add_parser("evaluate")
    e.add_argument("--model", required=True, help="model folder, or http://.../v1/chat/completions")
    e.add_argument("--served-name", default="decision")
    e.add_argument("--test", required=True)
    r = sub.add_parser("retrain")
    r.add_argument("--runs", default="runs")
    r.add_argument("--base", default="Qwen/Qwen2.5-1.5B-Instruct")
    r.add_argument("--live", help="folder of the current live model")
    r.add_argument("--min-new", type=int, default=1000)
    a = ap.parse_args()
    {"build": cmd_build, "sft": cmd_sft, "rl": cmd_rl, "merge": cmd_merge, "evaluate": cmd_evaluate, "retrain": cmd_retrain}[a.cmd](a)


if __name__ == "__main__":
    main()

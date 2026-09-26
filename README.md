# stock-trading-universe

An AI-driven **crypto** trading agent for Binance (it also works for stocks), built end to end from the BRD, SDD and TDD.
It runs on **paper money** by default.

## How it fits together

```
 news feeds ─┐                                   ┌─> snapshots/latest.json ─┐
 (RSS, Binance│   SLOW LOOP: research team       │   per coin: bias,        │   FAST LOOP: Trading Agent
 announcements,├─> Orchestrator                  │   confidence, risk flags,├─> news ✓ + price ✓ + risk ✓
 CryptoPanic,  │    ├─ News manager → team leads │   news signal, reason    │   (+ decision model ✓)
 NewsAPI,      │    │   → disposable workers     │                          │   → order (paper / Binance testnet)
 Reddit)       │    ├─ Price manager             │                          │   → trade log
 Binance prices┘    ├─ Risk manager (market mood)│                          │
                    └─ one cluster agent per coin┘                          │
                              ▲                                              │
                              └── MISTAKE LOOP: trade outcomes → memory lessons, confidence cuts ◄──┘
 TRAINING: history + snapshots + trades → SFT → RL (profit + honest confidence) → exam → promote only if better
```

| Part | Where | What it does |
|---|---|---|
| News pipeline | `news/` | Collects crypto news (Cointelegraph, Decrypt, CoinDesk, Binance listings/delistings; CryptoPanic and NewsAPI with a key; Reddit best effort), tags coins and event type (listing, hack, regulatory, macro…), stores it and writes it into the memory diary |
| Research team | `research/` | Orchestrator → News / Price / Risk managers → team leads (listings, regulatory, security, macro, flows, tech, social) → disposable workers → per-coin cluster agents → snapshots. News is scored by **Claude** when `ANTHROPIC_API_KEY` is set, otherwise by a keyword scorer |
| Market mood filter | `research/hierarchy.py`, `backtest/` | Bitcoin below its 200-day average → `market_downtrend` flag → no new buys (roadmap step 1) |
| Trading Agent | `trading_agent/` | Reads snapshots only; news, price and risk must all agree (plus the trained model, when one is loaded); watch state; stop-loss; ₹200–300 risk per trade, converted to USDT |
| Brokers | `execution/` | Paper broker (default) and Binance spot (testnet by default; real money needs an explicit switch); rate limits, retries, circuit breaker, no duplicate orders |
| Runner | `runner.py`, `python -m trading_universe` | Research every 15 min, trading every minute, learning after each closed trade; everything saved in `runs/` |
| Mistake loop | `learning.py` | Trade outcomes → memory; proven lessons and coin notes; losing clusters get their news confidence cut |
| Shared memory | `memory/` | One library, a shelf per agent, no peeking into the future |
| Settings search | `backtest/` | VectorBT, 525 settings, last year hidden for the exam |
| Decision model | `training/` | Dataset (history + snapshots + trades) → SFT → GRPO → merge → exam vs baselines → automatic retraining |
| Website | `web/` (React) + `api/` (FastAPI) | Overview, markets, news & research, live agent, strategy lab, trades, memory, settings, roadmap |

## Quick start

```bash
pip install -e '.[backtest,research,web]'
(cd web && npm install && npm run build)     # build the website once
python -m trading_universe.api               # website + API on http://localhost:8000
python -m trading_universe run               # research + paper trading + learning, until Ctrl+C
python -m trading_universe status            # what it's doing
```

Keys (all optional; set them as environment variables, never in files):

| Variable | Turns on |
|---|---|
| `ANTHROPIC_API_KEY` | Claude scores the news instead of the keyword scorer (`TU_LLM_MODEL`, default `claude-opus-5`; `TU_LLM_EFFORT`, default `low`) |
| `CRYPTOPANIC_TOKEN`, `NEWSAPI_KEY` | Extra news sources |
| `BINANCE_API_KEY`, `BINANCE_API_SECRET` | `--broker binance-testnet` (fake money on testnet.binance.vision) |
| `TU_USDT_INR` | ₹ per USDT for the risk budget (default 88) |

## Website (control room)

A React web app (`web/`) served by a Python API (`src/trading_universe/api/`). Pages:

| Page | What you see and do |
|---|---|
| **Overview** | Account, open positions, market mood, coin cards with sparklines and research verdicts, recent activity; buttons to run research and a trading step |
| **Markets** | Candlestick charts (TradingView lightweight-charts) with the agent's trend line and ▲ buy signals; crypto (Binance) or stocks (Yahoo); add any symbol |
| **News & research** | One snapshot card per coin (bias, confidence, risk flags, reasoning) and the scored news feed with filters |
| **Live agent** | Paper account, positions, activity log, problems; run one trading step |
| **Strategy lab** | The hidden-period settings search with the market mood filter, results table, profit chart, "use this setting" |
| **Trades / Memory** | Trade log in USDT and ₹; lessons, coin notes and refinement tasks |
| **Settings** | Risk per trade (₹200–300), stop-loss, ₹ per USDT, market filter, price rules, coins |
| **Roadmap** | `ROADMAP.md` |

Works on computer, iPad and phone.

**Run it on a computer:**
```bash
pip install -e '.[backtest,research,web]'
cd web && npm install && npm run build && cd ..
python -m trading_universe.api              # open http://localhost:8000
```
While changing the website: `python -m trading_universe.api` in one terminal and `cd web && npm run dev` in another (http://localhost:5173).

**Put it online (one container, website + agent running 24/7):**
- `Dockerfile` builds the website and the API into one image. `TU_AUTORUN=1` also runs research every 15 minutes and paper trading every minute inside it.
- `render.yaml` deploys it on Render.com: New → Blueprint → pick this repository. It uses the Frankfurt region, because Binance refuses US servers. Paste API keys in Render's dashboard, never in the repository. The always-on plan costs about $7/month; the free plan sleeps when nobody visits, which pauses the agent.
- Any other Docker host works too: `docker build -t trading-universe . && docker run -p 8000:8000 -e TU_AUTORUN=1 -v tu-data:/data trading-universe`.

## Run it on Google Colab

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/A-n-singh/stock-trading-universe/blob/claude/new-session-uimdbt/notebooks/colab_workspace.ipynb)

`notebooks/colab_workspace.ipynb` pulls the latest code from GitHub, runs the tests, downloads Binance prices, runs the settings search with the hidden year, and draws the charts. Open it with the badge, then choose **Runtime → Run all**.

- **Private repository:** the badge link can't open it directly. In Colab choose **File → Open notebook → GitHub**, tick *Include private repos*, and pick this repository. Also add a `GITHUB_TOKEN` secret (🔑 in the Colab sidebar) so the Setup cell can clone the code.
- **Binance from Colab:** Colab's servers are in the USA, where Binance's live API is blocked. The downloader then falls back automatically to Binance's public archive (`data.binance.vision`). No Binance account or API key is needed to download prices.
- **Colab is for development, not live trading.** It shuts down after a few hours or when idle.

## Training your own decision model

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/A-n-singh/stock-trading-universe/blob/claude/new-session-uimdbt/notebooks/train_decision_model.ipynb)

```bash
pip install -e '.[backtest,training]'
python -m trading_universe.training build --out data            # history + snapshots + trades, newest 20% held out
python -m trading_universe.training sft --train data/train.jsonl --base Qwen/Qwen2.5-1.5B-Instruct --out models/sft
python -m trading_universe.training rl  --train data/train.jsonl --base models/sft-merged --out models/rl
python -m trading_universe.training evaluate --model models/rl-merged --test data/test.jsonl
python -m trading_universe.training retrain --runs runs --live models/rl-merged   # after ~1,000 new trades
```

The exam compares the model with "always buy" and "always hold" on the newest data. On the price-only history,
"always buy" lost money in some periods, so **a model is only useful if it beats "always hold"**. Start with a small
model on a free Colab GPU; the 30–40B target (e.g. `Qwen/Qwen2.5-32B-Instruct` with `--qlora`) needs a rented A100/H100.

## Shared memory in plain words

Think of it as one library that every agent uses:

- **Diary** (`EventLog`): everything that happened, written once and never edited.
- **Team lead shelf**: general lessons such as "earnings beats usually push the price up". A lesson must cite at least two real diary events as proof.
- **Coin shelf**: notes about one coin (e.g. BTCUSDT). They point to team-lead lessons instead of copying them.
- **Scratchpad**: a worker's rough notes for one task, thrown away afterwards.

Rules the code enforces:

1. **Read anything, write only your own shelf.** `memory.for_agent("earnings-lead", writes={"earnings-lead"})`. Writing anywhere else raises `PermissionError`.
2. **No peeking into the future.** Every read takes `as_of`. When the agent practises on 2020 data, it cannot see a lesson learned in 2022.
3. **Only proven lessons.** Real trade results are recorded against each lesson. A lesson that keeps losing is retired automatically, but it stays visible when replaying earlier dates.
4. **Same lesson twice is merged**, not saved as a duplicate.
5. **The Trading Agent never uses memory.** It reads only the snapshot, and a test checks this.
6. When a team lead goes idle, its shelf goes dormant with it. It comes back when a similar task appears.

The default embedder and vector store need no extra packages. Sentence-transformers or Chroma can replace them behind the same interfaces (`memory/vectors.py`).

## Finding better settings (VectorBT + hidden year)

The price rules have settings: trend line length, breakout window, which candlestick patterns count, and the stop-loss %. Instead of guessing them:

```bash
pip install -e '.[backtest]'
python -m trading_universe.backtest BTCUSDT ETHUSDT SOLUSDT --save best.json   # downloads daily candles from Binance
python -m trading_universe.backtest BTCUSDT --interval 4h                     # 4-hour candles
python -m trading_universe.backtest prices/BTCUSDT.csv                        # your own CSV files
python -m trading_universe.backtest --demo      # try it on generated prices
```

What happens:

1. **Hide the last year.** The last 365 days are cut off and not used during the search.
2. **Practice.** VectorBT tests 525 settings on the earlier years, all at once. Settings with fewer than 30 trades or a loss are dropped. The top 5 are kept.
3. **Exam.** The hidden year is opened **once**, and only those 5 winners (plus the current setting, for comparison) are tested on it. The code refuses to open it twice or for more than a handful of settings, so it can never become part of the search.
4. **Decide.** The best practice winner that still makes money on the hidden year, and keeps at least half its practice profit per trade, is chosen. If none passes, nothing changes.

Crypto is the default (`--market stock` switches): prices every day including weekends, 0.1% fee per side, and wider stop-losses (2–10%). Crypto moves several % a day, so a 2% stop gets hit by normal noise.

Results are in **R**: 1 R = one stop-loss hit = your ₹200–300 risk budget. `apply_setting(cfg, report.chosen)` puts the winner into the agent's config.

Tests prove that the search never looked at the hidden year (scrambling the hidden year leaves the winners unchanged) and that the backtest uses the same rule as the live agent, bar by bar. The backtest covers only the price rules. News and the full three-check gate still need the replay step.

## Guarantees enforced in code

- `RiskConfig` refuses any `risk_per_trade` outside ₹200–300. The ₹ budget is converted to the quote currency (USDT) before sizing, and the ₹300 ceiling is re-checked before every approval.
- The Trading Agent never researches: a stale or missing snapshot means it skips that coin.
- A single signal is never enough, even a very confident one. News, price and risk must all agree (and the decision model, when loaded).
- Entry patterns use finished candles only, exactly like the backtest. Stop-losses watch the live price.
- Exchange failures degrade gracefully: no crash, no duplicate orders; stop-loss exits bypass the rate limiter.
- Paper trading by default; Binance testnet by default; real money needs `live=True` in code and the live URL.
- No peeking into the future: memory reads, training examples and the backtest exam only use data that existed at the time.

## Run the tests

```bash
pip install -e '.[dev]'
pytest
```

## Still open

See `ROADMAP.md` for findings and next steps (short selling, a fairer exam, calibrating the watch windows from
paper-trading data, a dated news archive for replaying the full system on history, and the SDD's open questions).

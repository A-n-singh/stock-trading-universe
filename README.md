# stock-trading-universe

An AI-driven **crypto** trading agent for **Binance**, built from the owner's BRD, SDD and TDD
(current version: [`docs/BRD_SDD_TDD_v2.md`](docs/BRD_SDD_TDD_v2.md), original `docs/BRD_SDD_TDD_v2.docx`).
The repository name is historical: the system is **crypto only**, with no stock support.

- **Goal:** earn real money, safely. Every step must first be proven on history after all costs, then in shadow mode,
  then with paper (fake) money, and only then with a small real amount.
- **Today:** trading is **paused** ("brain first"), and paper money is the default. The research team runs and learns
  what moves prices.
- **Coins:** BTC, ETH, SOL, BNB and XRP (USDT pairs).
- **Findings and next steps:** [`ROADMAP.md`](ROADMAP.md).

## How it fits together

```
 news feeds ──┐                                       ┌─> per-coin snapshot ──┐
 (RSS, Binance │   SLOW LOOP: the research team       │   (bias, confidence,  │   FAST LOOP: Trading Agent
 announcements,├─> Orchestrator                       │   risk flags, news,   ├─> news ✓ + price ✓ + risk ✓
 CryptoPanic,  │    ├─ News manager → expert desks    │   reasons)            │   (all three must agree)
 NewsAPI,      │    │   → disposable workers          │                       │   → daily stop, risk limits
 Finnhub, X…)  │    ├─ Price manager → 3 chart desks  │                       │   → order (paper / Binance testnet)
 Binance prices┘    ├─ Risk manager → 3 risk desks    │                       │   → trade log
                    └─ one coin agent per coin ───────┘                       │
                              ▲         ▲                                     │
            BRAIN: every signal is      │                                     │
            checked 1 and 3 days later  └── MISTAKE LOOP: trade results → lessons, proposals for the owner ◄┘
            → scorecards → trust weights
```

| Part | Where | What it does |
|---|---|---|
| News pipeline | `news/` | Collects crypto news: Cointelegraph, Decrypt and CoinDesk (RSS), Binance listing/delisting announcements, CryptoPanic, NewsAPI, Finnhub, Alpha Vantage, X/Twitter (each when its key is set), Reddit (best effort). Tags the coin and the kind of news (listing, hack, regulatory, macro…) |
| Research team | `research/` | Orchestrator → News / Price / Risk managers → expert desks → disposable workers → one coin agent per coin → snapshots. **Gemini** reads and scores the news (keywords if no key) |
| News desks | `research/hierarchy.py`, `research/team_leads.py` | 8 desks (listings, regulation, hacks & security, macro economy, big buyers/sellers, tech upgrades, social media, general). Headlines are routed by **fingerprints** (Gemini embeddings); unclear ones are decided by a Gemini call. Gemini proposes new desks, and the owner approves them. Unused desks go to sleep and wake up when similar news returns |
| Price desks | `research/hierarchy.py` | Trend (above/below the averages), momentum (20-day move), candle patterns (engulfing, hammer/shooting star, breakout/breakdown), on finished daily candles only |
| Risk desks | `research/hierarchy.py` | Event risk (hacks, delistings), market mood (Bitcoin vs its 200-day average), wild swings |
| Brain | `brain.py` | Writes down every news, chart and risk signal, then checks the price 1 and 3 days later. Keeps a scorecard per desk and kind of signal (right %, "would be right anyway" %, edge) and gives proven signals more weight (0.5–1.5) |
| Trading Agent | `trading_agent/` | Reads snapshots only. News, price and risk must all agree. Watch state, stop-loss, ₹200–300 risk per trade (converted to USDT), at most 5 trades and 2 shorts open, **daily stop** at 2% |
| Brokers | `execution/` | Paper broker (default) and Binance spot (testnet by default; real money needs an explicit switch). Rate limits, retries, circuit breaker, no duplicate orders |
| Runner | `runner.py`, `python -m trading_universe` | Research every 15 min, trading every minute, learning after each closed trade. Everything is saved in `runs/` |
| Mistake loop | `learning.py` | Trade results → memory, proven lessons, coin notes. Cuts in trust are only **proposed**; the owner approves them |
| Shared memory | `memory/` | One library with a shelf per agent, and no peeking into the future |
| Owner controls | `control.py` | Questions from the agents, suggested changes, **Apply**, History and **Undo** |
| Time machine | `time_machine.py` | Replays past years day by day without peeking, learns, then sits an exam on the hidden last year |
| Proving it makes money | `proof.py` | Data check, edge check after all costs, comparison with simple strategies, robustness. See below |
| Experiment log | `experiments.py` | Every test run gets an ID with its settings and results. Nothing is overwritten |
| Settings search | `backtest/` | VectorBT, 525 price-rule settings, last year hidden for the exam (Strategy lab) |
| Website | `web/` (React) + `api/` (FastAPI) | The owner's control room (pages below) |

## Quick start

```bash
pip install -e '.[backtest,research,web]'
(cd web && npm install && npm run build)     # build the website once
python -m trading_universe.api               # website + API on http://localhost:8000
python -m trading_universe run               # research + (paused) trading + learning, until Ctrl+C
python -m trading_universe status            # what it's doing
```

Other commands: `python -m trading_universe research` (one research cycle), `... trade` (one trading check),
`--coins BTCUSDT,ETHUSDT,...`, `--broker binance-testnet`.

**Trading is off until you switch it on** (Settings → Trading). While it's off, the research team and the brain keep
working, and open trades keep their stop-losses.

### Keys

All keys are optional. Set them as environment variables on the server (`deploy/.env`), **never in a file in the
repository** (the repository is public).

| Variable | Turns on |
|---|---|
| `TU_PASSWORD` | Login for the website. **Required before the site is reachable from the internet** |
| `GEMINI_API_KEY` | Gemini reads and scores the news, routes unclear headlines and proposes new desks (free key from aistudio.google.com; `TU_GEMINI_MODEL`, default `gemini-2.5-flash`) |
| `ANTHROPIC_API_KEY` | An Anthropic model reads the news instead (optional, later). Gemini wins if both are set |
| `CRYPTOPANIC_TOKEN`, `NEWSAPI_KEY`, `FINNHUB_API_KEY`, `ALPHAVANTAGE_API_KEY` | Extra news sources (free keys; Alpha Vantage is asked at most every 2 hours) |
| `TWITTER_BEARER_TOKEN` | X/Twitter posts (paid plan); search words in `TU_X_QUERY` |
| `BINANCE_API_KEY`, `BINANCE_API_SECRET` | `--broker binance-testnet` (fake money). For real money later: **never allow withdrawals** on the key, and limit it to the server's IP |
| `TU_USDT_INR` | ₹ per USDT for the risk budget (default 88) |

With no LLM key, or when a call fails, a keyword scorer reads the news. The Overview page shows which one
is in use.

## Website (control room)

| Page | What you see and do |
|---|---|
| **Overview** | Account, open positions, market mood, coin cards with research verdicts, recent activity; run research or a trading step |
| **Markets** | Candlestick charts with the agent's trend line and buy signals |
| **News & research** | One snapshot per coin (bias, confidence, risk flags, reasons) and the scored news feed |
| **Agents** | The whole team as a live chart: orchestrator, managers, news / price / risk desks, coin agents, trading and learning agents, the brain. What each is doing, recent work, questions for you, and controls (pause/resume, strictness, written instructions, stop watching a coin, approve new desks). Every change waits for **Apply**; History has **Undo**. Risk budget, stop-losses and paper/real money are locked |
| **Brain** | What the research team has learned: scorecards per section (news, price, risk), best and weakest signals, and the time machine's latest exam |
| **Live agent** | Paper account, positions, activity log, problems |
| **Strategy lab** | Hidden-year settings search for the price rules, next to "just holding the coins" |
| **Trades** | Every trade: money in, entry/exit, profit in ₹, % and R, time held, the news and desk behind it; profit by desk |
| **Memory** | Lessons, coin notes, sleeping desks, proposals waiting for approval |
| **Settings** | Trading on/off, risk per trade (₹200–300), stop-loss, ₹ per USDT, market filter, short selling, price rules, coins |
| **Roadmap** | `ROADMAP.md` |

Works on computer, tablet and phone.

For website development, run `python -m trading_universe.api` in one terminal and `cd web && npm run dev` in another
(http://localhost:5173). Typecheck with `cd web && npx tsc -b`.

**Login.** With `TU_PASSWORD` set you get a 7-day login cookie, and 5 wrong tries lock that address out for 15 minutes.
`/api/health` stays open for uptime checks. Without a password the site is open to anyone who can reach it, which is
only fine on your own computer. HTTPS must come from the host (Caddy on your own server; see `deploy/`).

## Running it 24/7 (Oracle Cloud)

`deploy/` has everything for a free Oracle Cloud VM (India region; Binance refuses US servers):

1. Create the VM (Ubuntu), copy this repository to it, and run `bash deploy/setup-oracle.sh` once.
2. Fill in `deploy/.env` (password, Gemini key; never commit it).
3. Run `cd deploy && docker compose up -d --build`. The agent and website then run 24/7 with auto-restart. By default
   the site is reachable only through an SSH tunnel; optional HTTPS goes through Caddy with your own domain.
4. To update later, run `bash deploy/update.sh`.

`Dockerfile` (one image: website and API, `TU_AUTORUN=1` runs the agent inside) and `render.yaml` (Render.com,
Frankfurt) also work.

## Proving it makes money (rollout gates 1–3)

```bash
python -m trading_universe.proof                 # writes runs/proof/report.json and logs the experiment
python -m trading_universe.proof --no-universe   # skip the "coins as they were each month" test (faster)
```

The test walks through ~7 years of Binance daily prices, keeping the **last year hidden as the exam**:

- **Costs on every trade:** exchange fee (0.1% each side), half the buy/sell price gap, slippage (more when prices swing
  wildly), funding on shorts. Each signal is filled **one candle later**, on purpose.
- **The same limits as the live agent:** at most 5 trades and 2 shorts open, daily stop at 2%.
- **Compared with simple strategies:** just holding, a momentum rule and a moving-average rule.
- **Switch-off tests:** without the market-mood filter, without shorts, and without the open-trade limits.
- **Robustness:** costs doubled; results by market type (rising / falling / flat, wild / calm) and by coin; the 5 most
  traded coins of each month, including coins that later collapsed (survivorship test).
- **Data check:** samples 100 price rows (and news/price pairs when news is given). More than 3% broken fails.
- **Safety variants** (fewer trades open, a dip brake) are chosen on the practice years only, then sit the exam once.

Results are in **R**: 1 R = one stop-loss hit = the ₹200–300 risk budget. The pass rules (at least 30 exam trades,
positive average profit after costs, worst dip within 3% of the account, beats every simple strategy) are fixed before
the run and written into `runs/experiments.jsonl`, together with how often the exam year has been looked at.

What can't be tested on history yet, because there's no old news: the full system (news + chart + risk), a news-only
strategy, the brain's weights, and Gemini (never used on history, because it may know how old events ended). These are
measured going forward, in shadow mode and paper trading.

## Time machine

```bash
python -m trading_universe.time_machine --no-news              # prices only (the agreed setup for now)
python -m trading_universe.time_machine --news archive.parquet # with a news archive (file or URL)
```

Replays Oct 2019 → today, one day at a time. The research team sees only candles that had already closed and news
already published. The brain learns until one year before the end; then its trust weights are frozen and it sits the
exam. It writes `runs/time_machine/report.json`, which the Brain page shows. A news archive can be any
parquet/CSV/JSON-lines file with a time column and a headline column. Archives with dates only count each item as
known at the end of that day.

## Finding better price-rule settings (Strategy lab)

```bash
python -m trading_universe.backtest BTCUSDT ETHUSDT SOLUSDT --save best.json
python -m trading_universe.backtest --demo      # generated prices
```

1. **Hide the last year.**
2. **Practice:** VectorBT tests 525 settings on the earlier years.
3. **Exam:** only the top 5 (plus the current setting) see the hidden year, once.
4. A winner must still make money there (or, in a falling year, lose much less than just holding).

Options: `--market-filter` (buy only while Bitcoin is above its 200-day average) and `--shorts`.

## Shared memory in plain words

One library that every agent uses:

- **Diary** (`EventLog`): everything that happened, written once and never edited.
- **Desk shelf:** general lessons, such as "listing news usually pushes the price up". A lesson must cite at least two
  real diary events.
- **Coin shelf:** notes about one coin. They point to desk lessons instead of copying them.
- **Scratchpad:** a worker's rough notes for one task, thrown away afterwards.

Rules the code enforces: read anything, but write only your own shelf; no peeking into the future (every read takes
`as_of`); only proven lessons are used; duplicate lessons are merged; the Trading Agent never uses memory (it reads
only the snapshot); and a sleeping desk's shelf sleeps with it.

## Guarantees enforced in code

- Risk per trade must be within ₹200–300, converted to USDT before sizing and re-checked before every order.
- The Trading Agent never researches: a stale or missing snapshot means it skips that coin.
- A single signal is never enough: news, price and risk must all agree.
- **Daily stop:** once the account (closed and open trades) is 2% below the day's start, no new trades until the next
  day. Stop-losses keep working. It survives a restart.
- At most 5 trades open and at most 2 of them short. Shorts only while the whole market is falling, never during wild
  swings, and without borrowing beyond your own money. Shorts are paper only for now: Binance spot can't short, and
  Binance Futures isn't connected yet.
- Entry patterns use finished candles only, exactly like the tests.
- Exchange failures degrade gracefully: no crash, no duplicate orders, and stop-loss exits skip the rate limiter.
- Paper trading by default and Binance testnet by default. Real money needs an explicit switch in code.
- No peeking into the future: the brain, memory, time machine and every exam only use data that existed at the time.
- Nothing about the agents changes without the owner pressing **Apply**, and every applied change can be undone.

## Run the tests

```bash
pip install -e '.[backtest,research,web,dev]'
python -m pytest -q
```

## Not used (kept for reference)

- `training/` and `notebooks/train_decision_model.ipynb`: the earlier plan to train an in-house decision model. The
  BRD/SDD/TDD version 2 replaces it with **Gemini as the tie-breaker** (not built yet), so no model is trained.
- `notebooks/colab_workspace.ipynb`: the Google Colab workspace from the start of the project, for development only.

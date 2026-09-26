# Roadmap and notes

A running record of findings and agreed next steps, so they can be recalled in any later session.
Ask Claude to "recall the roadmap" or "what are the next steps" to get this back.

## Finding: first real Binance test (26 Sep 2026)

Daily candles for BTCUSDT, ETHUSDT, SOLUSDT and BNBUSDT, Jan 2020 → Sep 2026. Last 365 days hidden.

- **No setting passed the hidden-year exam**, so the current settings were kept.
- Practice years were a huge bull market (BTC 15×, ETH 31×, SOL 62×, BNB 70×). All 525 settings made money there,
  so practice could not tell good settings from lucky ones.
- The hidden year was a falling market (BTC −23%, ETH −33%, SOL −41%, BNB −19%; drops of 53–74% along the way).
  The agent only buys, so every setting lost.
- Best practice setting (trend 50, breakout 5, wick+breakout, stop 3%): +1,311 R in practice, −32 R (≈ −₹8,000) in the hidden year.
- Most practice profit came from a few giant 2021 trades (one BNB trade = +440 R). Without them, profits shrink a lot.
- Good news: in a year when coins fell 20–40%, stop-losses and the fixed ₹250 risk kept the loss to about ₹7,000–8,000.

## Finding: market mood filter on the same data (26 Sep 2026)

Only buy while Bitcoin is above its 200-day average. Same coins, same hidden year:

| Hidden year | Without filter | With filter |
|---|---|---|
| Best practice setting | −32 R (−₹8,050) | −4.6 R (−₹1,140) |
| Current setting (trend 20, breakout 10, all patterns, stop 2%) | −29 R (−₹7,159) | +12.5 R (+₹3,116), passes the exam |

Encouraging but a small sample (15 trades in the hidden year). The filter is now built into the live system
(`market_downtrend` risk flag) and the backtest (`--market-filter`, dashboard switch).

## Agreed next steps (in this order)

1. ~~**Market mood filter**~~ **Done.** Only buy when Bitcoin is above its long-term average (200 days).
   In falling markets the agent mostly sits in cash instead of losing.
2. **Short selling** (later, riskier). Make money when prices fall, via Binance futures. Needs extra risk rules first.
3. **Fairer exam.** Also pass a setting if it loses much less than the coins themselves did in the hidden year.

## Built (end to end, 26 Sep 2026)

- **News pipeline:** RSS (Cointelegraph, Decrypt, CoinDesk), Binance announcements, CryptoPanic/NewsAPI with keys, Reddit best effort; coin and event-type tagging; memory diary.
- **Research team:** Orchestrator → News / Price / Risk managers → team leads → disposable workers → cluster agents → snapshots. Claude scores news when an API key is set; a keyword scorer otherwise.
- **Market mood filter** (step 1): live (`market_downtrend` flag) and in the backtest.
- **Live system:** `python -m trading_universe run` — research every 15 min, trading every minute, paper broker or Binance testnet, state saved in `runs/`.
- **Mistake loop:** trade outcomes into memory, proven lessons, coin notes, confidence cuts for losing clusters.
- **Decision model:** dataset builder, SFT, GRPO (profit + calibration reward), merge, exam vs baselines, automatic retraining, optional fourth check in the Trading Agent, Colab GPU notebook.
- **Dashboard:** prices, news & research, live agent, settings search, trade log, memory, roadmap.
- Fixed: the ₹ risk budget was being used as USDT (would have risked about ₹22,000 per trade). Now converted.

## Not built or not tested yet

- **Full-system replay on history.** The research team now runs on live news, but replaying News + Technical + Risk
  over past years needs a dated news archive (the collector builds one from today on; older news needs a paid source).
- **Claude scoring not yet run for real:** no API key in the development environment. Keyword scoring works but makes
  mistakes Claude wouldn't (e.g. "Hack VC" read as a hack).
- **Binance testnet not run for real:** the testnet refuses the US-based development server; tested with a stand-in.
  Should work from India.
- **A real decision model hasn't been trained yet:** the pipeline is tested end to end on a tiny model; needs a GPU
  (free Colab T4 for small models, rented A100/H100 for 30–40B).
- Watch-state windows and snapshot freshness still need calibrating from a month of paper trading.
- X (Twitter) needs a paid API; Reddit blocks many servers.
- Indian tax (1% TDS, 30% on gains) is not included in results.

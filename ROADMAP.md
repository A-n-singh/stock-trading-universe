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

## Built

- Dashboard (`app/dashboard.py`): prices for coins and stocks, market mood, settings search with the hidden period, trade log, memory and this roadmap. Can be hosted free on Streamlit Community Cloud.

## Not built or not tested yet

- **Research agents (news, social media, etc.) are not tested with real data.** The backtest only tests the price rules
  (the Technical check). The News check exists as code and is tested only with made-up snapshots. There is no news
  data source yet (e.g. CryptoPanic, exchange announcements, X/Reddit), no LLM research agents, and no historical
  news to replay. Testing the full News + Technical + Risk system on history needs a dated news archive first.
- Live paper trading on the Binance testnet.
- In-house decision model training (SFT → RL → quantize) — only the pipeline skeleton exists.
- Indian tax (1% TDS, 30% on gains) is not included in results.

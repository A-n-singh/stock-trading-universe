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

## Finding: fairer exam and short selling on the same data (26 Sep 2026)

Holding the four coins through the hidden year (one position per coin, sized like the agent's trades)
would have lost 39 R with a 3% stop, 59 R with a 2% stop.

| Hidden year | Buy only, no filter | Buy only + market filter | Buy + short, market filter |
|---|---|---|---|
| Current setting (trend 20, breakout 10, all patterns, stop 2%) | −29 R | +12.5 R (15 trades) | **+48.8 R (≈ +₹12,200, 76 trades)** |
| Best practice setting (trend 50, breakout 5, wick+breakout, stop 3%) | −32 R | −4.6 R | not in the top 5 with shorts |
| Top 5 with shorts | | | +12.6 to +17.0 R each |

- Of the +48.8 R, longs made +12.5 R and **shorts +36.4 R** (61 trades). Bitcoin was below its average 80% of the hidden year.
- The fairer exam lets the "lost 4.6 R while holding lost 39 R" settings pass. They still aren't chosen, because the
  current setting made money, and a "lost less" pass never replaces a setting that did better.
- With shorts, the top 5 made money but failed the "kept half its practice edge" rule: practice profits are
  inflated by a few giant 2021 trades, so almost nothing can keep half of that. Worth revisiting that rule.
- Careful: one falling year, four coins. Shorts on real Binance futures also face funding (included, 0.03%/day),
  sudden squeezes and exchange rules not in the backtest.

## Decisions (27 Sep 2026)

- **Crypto only.** The system is built for crypto (Binance) only. Stocks and stock exchanges are out of scope;
  where the BRD/SDD/TDD mention stocks (earnings, SEC filings, FNSPID, FirstRate), the crypto equivalent is built instead.
- **Jev is not used.** We looked at plugging the paid Jev model in directly as the Trading Agent's optional fourth
  check, and decided against it. The agent trades on three checks (news, price, risk).
- ~~No decision model / Jev replacement for now~~ (27 Sep). **Replaced on 5 Oct:** Gemini is the permanent
  tie-breaker (see below). The training code already built stays in the repository, unused.
- **Gemini only for reading news** for now (Claude later, when the card works). No local or open-source news model.
- **Short selling on** for paper trading: tick "Short selling" on the Settings page once the server runs
  (no code change; off by default in the code).
- **Server: Oracle Cloud** (free tier, India region: Mumbai or Hyderabad; Binance blocks US servers). The `deploy/`
  folder has the helper files. The owner got stuck setting it up; to be continued.
- **The learning agent no longer cuts trust in a kind of news on its own**; it asks on the Agents page and waits for OK.
- **Working agreement:** Claude asks before changing or saving anything in the repository, shows screenshots of
  website changes before saving, and explains in simple language.

## Decisions (5 Oct 2026): BRD/SDD/TDD version 2

The owner's version 2 document is the reference from now on: `docs/BRD_SDD_TDD_v2.docx` (text copy:
`docs/BRD_SDD_TDD_v2.md`). What changed:

- **Gemini is the permanent tie-breaker.** When News, Technical and Risk disagree, one live Gemini call decides
  (given similar past cases from our own memory, no web). After the trade ends, a second, fresh call reviews what
  happened (web search allowed, only to explain why). Its notes are theories until seen in 20–30 similar cases.
  Gemini timeout (2–3 s) or too few similar cases → hold, logged as a hold event. No in-house model, no training.
- **The time machine runs without Gemini** (it may know how old events ended). Conflicts → hold, saved as cases.
- **Success = average profit per trade after all costs** (fees, spread, slippage, funding), max drawdown 3% of the
  account. Win rate is only reported. It must beat simple strategies (just holding, momentum, moving average,
  chart-only, news-only), and each part must show what it adds (switch it off, measure the change).
- **Six gates in order:** data check (≤3% defects in ~100 news/price samples) → edge after costs on unseen data →
  works in rising/falling/flat/wild/calm markets and on each coin → shadow mode (live, no orders) → paper
  trading (~1 month) → small real money.
- **5 coins:** BTC, ETH, SOL, BNB and **XRP** (added 5 Oct).
- **No old news archive (option 3, decided 5 Oct).** The time machine and the "prove it makes money" check use prices
  only (chart + risk). The news part learns from the system's own live news collection from the day the server runs,
  and is tested in shadow mode and paper trading. (The CoinDesk archive is non-commercial; the other one has no times.)
- Safety: daily stop at 2–3% loss of the account, more automatic stops (stale data, mismatch with the exchange,
  exchange trouble, odd behaviour, server/Gemini down), order-status check after unclear replies, stop-losses
  placed on the exchange, risk also recorded as % of the account.
- Website: signal/trade/news markers on the chart (also blocked signals), click a trade to see the chart and each
  check's reasons, Decisions page, Backtest results page, "data is old" banner.
- Experiment log: every run gets an ID with its settings and results; nothing is overwritten.

### Agreed order of work (5 Oct)

- **A. Proving it makes money:** costs in the time machine, profit per trade, drawdown, simple-strategy comparisons,
  switch-off tests, market-type and per-coin results, coins as they were at each date, data check, experiment log.
- **B. Gemini tie-breaker:** decide + review calls, case library, hold records, hold-pattern rules with the
  candidate → validated → production → retired steps.
- **C. Safety switches** (daily stop, automatic stops, order checks, risk as %).
- **D. Website:** chart markers, trade drill-down, Decisions and Backtest pages, stale-data banner.
- **E. Shadow mode**, then paper trading.
- **F. Binance Futures** for real shorts (liquidation and funding checks).

### Finding: first time-machine run (5 Oct 2026, prices only, no news)

Oct 2019 → Oct 2026, 4 coins, learned until Oct 2025, exam on the last year: price and risk signals alone were right
50% of the time, exactly as often as the price moves that way anyway (no edge). Shooting star / hammer patterns
slightly better (+6 to +7 points, few cases), breakouts worse (−12 points). No pretend trades (the trading agent
needs news). Holding the coins lost about 50 R in that year. News is needed; the archive choice is open
(CoinDesk archive has true publish times but a non-commercial license).

### Finding: first "prove it makes money" check (5 Oct 2026, `python -m trading_universe.proof`)

5 coins (BTC, ETH, SOL, BNB, XRP), Jul 2019 → Oct 2026, exam = the last year (Oct 2025 → Oct 2026). Every trade pays
fees, spread, slippage (more in wild markets) and short funding, and is filled one candle late. ₹250 risk per trade,
₹88,000 paper account. Our chart + risk rules (trend 20, breakout 10, all patterns, stop 2%, market filter, shorts):

| Exam year | Trades | Profit | Avg per trade | Worst dip |
|---|---|---|---|---|
| Our chart + risk rules | 109 | **+57 R (≈ +₹14,300)** | +0.53 R | 8.0% of the account |
| Just holding the 5 coins | 5 | −101 R | | 28.6% |
| Momentum rule | 103 | −6 R | −0.05 R | 24.6% |
| Moving-average rule | 48 | +45 R | +0.93 R | 16.7% |
| Ours without the market-mood filter | 94 | −27 R | −0.28 R | 19.2% |
| Ours without short selling | 23 | +29 R | +1.25 R | 2.8% |
| Ours with costs doubled | 109 | +30 R | +0.27 R | 10.1% |
| Ours on the 5 most traded coins of each month (incl. collapsed coins) | 110 | +70 R | +0.64 R | 8.0% |

- **Data check passed** (0 of 100 sampled price rows broken).
- **Edge check failed only on the drawdown:** 8% of a ₹88,000 account (about 28 R) vs the 3% limit. Everything else
  passed: enough trades, profit after costs, beats all three simple strategies, still profitable with double costs,
  and on the coins as they were at each date.
- **Robustness failed on flat markets:** over the whole period, trades started in a flat market (Bitcoin neither
  clearly above nor below its 200-day average) lost −0.18 R on average (268 trades). Rising +1.58 R, falling +0.26 R;
  every coin made money.
- The market-mood filter is the most valuable part (without it: −27 R); shorts added about +29 R in the exam.
- Careful: a 3% drawdown with ₹250 risk needs an account of about ₹2.3 lakh for a 28 R dip; or fewer losing streaks.
  Any fix (e.g. skipping flat markets) must be chosen on practice years only and then tested once on the exam.

### Finding: the check now follows the live limits; fewer open trades tried (5 Oct 2026)

The first check let every coin trade on its own (up to 5 shorts at once); the live agent allows at most 5 trades
open and at most 2 shorts. With those limits (account $1,000 ≈ ₹88,000 as agreed, 3% = ₹2,640 ≈ 10.6 R):

| Exam year | Trades | Profit | Worst dip | Edge check | Robustness |
|---|---|---|---|---|---|
| Live rules (max 5 open, 2 short) | 66 | **+53 R (≈ +₹13,300)** | 15.7 R = 4.5% | fails only the 3% dip | **passes** |
| Chosen on practice years: max 3 open, 1 short | 42 | +21 R | 10.0 R = **2.9%** | fails: below the moving-average rule (+45 R) | fails: loses in falling/flat markets |

- The 8 limit combinations were tried on the practice years only (prices cut at the exam start), picked by profit
  per unit of worst dip; "3 open, 1 short" scored best there, then sat the exam once. It fixed the dip but gave up
  too much profit. So far **no version passes every gate**.
- With the owner's planned real account of **$2,000** (≈ ₹1.76 lakh), the live rules' worst dip (15.7 R ≈ ₹3,900) would
  be 2.2% and pass all three gates. Still to decide which account size the 3% rule is judged against.

### Finding: daily stop built; dip brake tried (6 Oct 2026)

- **Daily stop (live, 2%)**: the trading agent opens no new trades for the rest of the UTC day once the account (closed
  + open trades) is 2% below the day's start; stop-losses are still managed; it resets the next day and survives a
  restart (`daily_stop.json`, shown on the Agents page). Fixed in code, not changeable from the website.
- In the test year it **never triggered**: the worst single day lost 3.5 R (about 1% of a $1,000 account). The 4.5% dip
  builds up over weeks, so the daily stop protects against crash days but doesn't fix it.
- **Dip brake** (pause new trades for some days when the account is X% below its best; measured only, not live):
  9 versions tried on the practice years; best there was "pause 7 days at a 2.5% dip". In the exam it gave
  +54.5 R with the same 4.5% dip, and with double costs it lost (−12 R). **Not a fix; not adopted.**
- Where it stands with a $1,000 account: the live rules fail only the 3% dip (4.5%). Staying under 3% would need risk
  per trade of at most about ₹168 (below the ₹200–300 rule), or an account of about $1,500+ (at $2,000 it is 2.2%).

## What the owner still needs to provide

1. The Oracle server (created and reachable), then the deployment steps together with Claude.
2. A free Gemini API key (aistudio.google.com), set on the server as `GEMINI_API_KEY` (in `deploy/.env`, never in
   the repository).
3. A website password, set on the server as `TU_PASSWORD`.
4. A decision: judge the 3% dip rule against a **$2,000** paper account (keep ₹250 per trade), or stay at **$1,000**
   and lower the risk to about ₹150–160 per trade.
5. Later: Binance testnet keys; optional CryptoPanic / NewsAPI / Finnhub / Alpha Vantage keys; a Claude key.

## Plan: brain first, trading paused (agreed 27 Sep 2026)

Trading stays paused while the research "brain" is built and learns. Then paper trading, then small real money.

1. ~~Remove the stock code (crypto only).~~ **Done.**
2. ~~The brain's 3 sections with expert desks~~ **Done:** News (8 desks + Gemini proposes new ones for the owner to
   approve), Price (trend, momentum, candle patterns) and Risk (event risk, market mood, wild swings).
3. ~~Gemini routes unclear headlines; Gemini embeddings as desk fingerprints.~~ **Done** (not yet run with a real key).
4. ~~Desks remember their fingerprints and sleeping state across restarts.~~ **Done.**
5. ~~Every signal's outcome recorded; scorecards; useful signals get more weight.~~ **Done** (`brain.py`, Brain page).
6. ~~More crypto news: Alpha Vantage, Finnhub, X.~~ **Done** (each needs its key).
7. ~~Time machine~~ **Done** (`time_machine.py`), run on prices only: the owner chose no old news archive (option 3).
8. ~~Website: the 3 sections on the Agents page and the Brain page.~~ **Done.**
9. Later, when trading resumes: watch-time per news type calibrated from paper trading.

## Earlier steps

1. ~~**Market mood filter**~~ **Done.** Only buy when Bitcoin is above its long-term average (200 days).
   In falling markets the agent mostly sits in cash instead of losing.
2. ~~**Short selling**~~ **Done for paper trading and the backtest.** Earn when prices fall. Rules: only while
   Bitcoin is below its 200-day average, at most 2 shorts, no leverage, not during wild swings, same ₹ risk and stop.
   Switch: Settings page (off by default). **Still to do:** connect Binance futures (spot can't short).
3. ~~**Fairer exam**~~ **Done.** A setting also passes if, in a falling market, it lost at most a quarter of what
   holding the coins lost. Shown next to every result as "just holding".

## Next ideas (not agreed yet)

- Binance futures connection for real shorts (testnet first).
- Rethink "keep half the practice edge": maybe compare against practice without the biggest few trades.
- A month of paper trading with shorts on, then compare with the backtest.

## Built (end to end, 26 Sep 2026)

- **News pipeline:** RSS (Cointelegraph, Decrypt, CoinDesk), Binance announcements, CryptoPanic/NewsAPI with keys, Reddit best effort; coin and event-type tagging; memory diary.
- **Research team:** Orchestrator → News / Price / Risk managers → team leads → disposable workers → cluster agents → snapshots. Claude scores news when an API key is set; a keyword scorer otherwise.
- **Market mood filter** (step 1): live (`market_downtrend` flag) and in the backtest.
- **Live system:** `python -m trading_universe run` — research every 15 min, trading every minute, paper broker or Binance testnet, state saved in `runs/`.
- **Mistake loop:** trade outcomes into memory, proven lessons, coin notes, confidence cuts for losing clusters.
- **Decision model:** dataset builder, SFT, GRPO (profit + calibration reward), merge, exam vs baselines, automatic retraining, optional fourth check in the Trading Agent, Colab GPU notebook.
- **Website (React + API)**, replacing the Streamlit dashboard: overview, markets (candlestick charts), news & research, live agent, strategy lab, trades, memory, settings, roadmap. One Docker image serves the site and can run the agent 24/7 (`TU_AUTORUN=1`); `render.yaml` deploys it to Render (Frankfurt).
- Fixed: the ₹ risk budget was being used as USDT (would have risked about ₹22,000 per trade). Now converted.
- **Fairer exam** (step 3) and **short selling** (step 2, paper + backtest), as above.
- **Gemini reads the news for now** (`GEMINI_API_KEY`), because the Claude key isn't available yet. Claude stays
  in the code for later; keywords if neither key is set. Decision (26 Sep): no local or open-source news model
  as a fallback. The only model we train ourselves is the decision model that replaces Jev.
- **Website login:** `TU_PASSWORD` (7-day cookie, lockout after 5 wrong tries, API docs hidden). HTTPS still comes
  from the host.

## Built (27 Sep 2026)

- **Oracle deployment helpers** (`deploy/`): one-time server setup script, docker-compose (auto-restart, log limits,
  private by default, optional HTTPS through Caddy), keys-file template, update script.
- **Agents page:** the whole AI team as a live chart (boss, managers, 8 expert desks, coin agents, trading and learning
  agents) with what each is doing and its recent work. The agents ask the owner questions: a desk unsure about a
  headline (max 3 new per cycle, 10 open), the learning agent before trusting a kind of news less, the news manager
  before a new desk. Owner controls: pause/resume desks, coin agents and the trading agent (stop-losses keep working),
  per-desk strictness, written instructions for a desk (followed by Gemini), stop watching a coin, approve new desks.
  Everything waits for **Apply**; History with **Undo**. Risk budget, stop-losses and paper/real money are locked.
- **Trades page:** money put into each trade, live profit on open trades, profit in ₹, % and R, time held, the news and
  expert desk behind each trade, a running-profit chart and profit by expert desk.

## Built (5–6 Oct 2026)

- **BRD/SDD/TDD version 2** saved in `docs/`; XRP added as the 5th coin.
- **Time machine** (`python -m trading_universe.time_machine`): day-by-day replay without peeking, frozen weights for
  the exam year, optional pretend trades, report on the Brain page.
- **Proving it makes money** (`python -m trading_universe.proof`): data check, edge check after all costs with a
  one-candle delay, simple-strategy comparisons, switch-off tests, market-type / coin breakdowns, survivorship test,
  live limits (5 open, 2 short), safety variants chosen on practice years only.
- **Experiment log** (`runs/experiments.jsonl`): every run with an ID, code version, settings, pass rules and results.
- **Daily stop** (2%) in the live trading agent, kept across restarts and shown on the Agents page.
- README rewritten for the current system.

## Not built or not tested yet

Following the agreed order of work (A → F, see "Decisions (5 Oct 2026)"):

- **A (rest):** a results page for the edge check and time machine on the website; the 3% dip rule is still failed
  on a $1,000 account (waiting on the owner's decision above).
- **B: Gemini tie-breaker** (decide + review calls, case library, hold records, hold-pattern rules with the
  candidate → validated → production → retired steps). Not built yet.
- **C: other safety switches:** stale-data, exchange-mismatch, exchange-trouble, odd-behaviour and server/Gemini-down
  stops; order-status check after unclear replies; stop-losses placed on the exchange; risk also recorded as % of the
  account. The daily stop is done.
- **D: website:** signal / trade / news markers on the chart, click a trade to see each check's reasons, Decisions page,
  Backtest results page, "data is old" banner.
- **E: shadow mode**, then a month of paper trading.
- **F: Binance Futures** for real shorts (liquidation and funding checks).
- **Full system on history:** not possible without old news (option 3). News is learned from the live collection once
  the server runs.
- **Gemini / Claude not yet run for real:** no key in the development environment (tested with stand-ins).
- **Oracle Cloud server:** helper files ready; the owner got stuck creating the server.
- **Binance testnet not run for real:** the testnet refuses the US-based development server. It should work from India.
- Watch-state windows and snapshot freshness still need calibrating from paper trading.
- X (Twitter) needs a paid API; Reddit blocks many servers.
- Indian tax (1% TDS, 30% on gains) is not included in results.
- The in-house decision model (`training/`) is not used: version 2 replaces it with Gemini as the tie-breaker.

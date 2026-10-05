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
- **No decision model / Jev replacement for now** (decided 27 Sep, out of scope even though the BRD mentions it).
  The training code already built stays in the repository, unused. Planned base if revived: Qwen2.5-32B.
- **Gemini only for reading news** for now (Claude later, when the card works). No local or open-source news model.
- **Short selling on** for paper trading: tick "Short selling" on the Settings page once the server runs
  (no code change; off by default in the code).
- **Server: Oracle Cloud** (free tier, India region: Mumbai or Hyderabad; Binance blocks US servers). The `deploy/`
  folder has the helper files. The owner got stuck setting it up; to be continued.
- **The learning agent no longer cuts trust in a kind of news on its own**; it asks on the Agents page and waits for OK.
- **Working agreement:** Claude asks before changing or saving anything in the repository, shows screenshots of
  website changes before saving, and explains in simple language.

## What the owner still needs to provide

1. The Oracle server (created and reachable), then the deployment steps together with Claude.
2. A free Gemini API key (aistudio.google.com), set on the server as `GEMINI_API_KEY`, never in a file.
3. A website password, set on the server as `TU_PASSWORD`.
4. Later: Binance testnet keys; optional CryptoPanic / NewsAPI keys; a Claude key once the card works.

## Plan: brain first, trading paused (agreed 27 Sep 2026)

Trading stays paused while the research "brain" is built and learns. Then paper trading, then small real money.

1. Remove the stock code (crypto only).
2. The brain's 3 sections, each with expert desks: News (8 desks + Gemini proposes new ones for the owner to approve),
   Price (trend, momentum & volatility, candle patterns) and Risk (event risk, market mood, wild swings).
3. Gemini routes headlines that fit no desk clearly (the SDD's escalation), and Gemini embeddings as desk fingerprints.
4. Desks remember their fingerprints and sleeping state across restarts.
5. Every news item, chart signal and risk flag gets its outcome recorded (price move 1 and 3 days later); each desk
   keeps a scorecard of what really moves prices; useful signals get more weight.
6. More crypto news: Alpha Vantage, Finnhub (free keys), Twitter/X (paid key).
7. **Time machine:** replay Oct 2019 → early 2025 day by day on a free archive of ~229,000 crypto news articles
   (Hugging Face `maryamfakhari/crypto-news-coindesk-2020-2025`) plus Binance prices, never seeing the future;
   learn on 2019–2023, exam on the hidden last year. Word-matching first (fast), Gemini re-reading later (free tier).
8. Website: the 3 sections on the Agents page and a "What the brain has learned" view.
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

## Not built or not tested yet

- **Full-system replay on history.** The research team now runs on live news, but replaying News + Technical + Risk
  over past years needs a dated news archive (the collector builds one from today on; older news needs a paid source).
- **Gemini / Claude scoring not yet run for real:** no key in the development environment (tested with stand-ins).
- **Oracle Cloud server:** set-up directions and helper files ready; the owner got stuck creating the server.
- **Binance testnet not run for real:** the testnet refuses the US-based development server; tested with a stand-in.
  Should work from India.
- **A real decision model hasn't been trained yet** (parked; see Decisions): the pipeline is tested end to end on a tiny
  model; needs a GPU (free Colab T4 for small models, rented A100/H100 for 30–40B, about $10–50 per run).
- Watch-state windows and snapshot freshness still need calibrating from a month of paper trading.
- X (Twitter) needs a paid API; Reddit blocks many servers.
- Indian tax (1% TDS, 30% on gains) is not included in results.

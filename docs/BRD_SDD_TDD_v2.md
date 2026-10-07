<!-- Text copy of docs/BRD_SDD_TDD_v2.docx (the owner's document, 5 Oct 2026). The .docx is the original. -->

# Crypto Trading Agent — BRD, SDD & TDD

October 5, 2026

Documentation of the AI-driven crypto trading agent discussed so far: business requirements, system design, and technical design, across three parts.

## BRD — Business Requirements

### Purpose, Background & Goals

- Primary goal: earn real money. This is a profit-seeking, real-capital crypto trading agent — not a demo or a portfolio exercise.
- Originated as one of four AI x Quant project ideas (prediction market arbitrage, news-to-price diffusion, AI strategy search lab, backtest overfitting detector) explored for a data engineering job search portfolio. The resume/showcase value is a secondary benefit, not the driving goal.
- Targets crypto specifically, not traditional stocks: crypto trades 24/7 with no market-hours gaps, historical and live price data are freely available via exchange APIs, and social sentiment (Twitter/Reddit) maps more directly onto price moves — all of which make it a more practical, faster-to-iterate target for this architecture.
- Decision-making for the Trading Agent’s tie-breaker runs on an external model (Gemini) rather than an in-house trained model — no in-house training, no automated retraining pipeline; see Success Criteria for the finalized approach.

### Scope & Key Requirements

- Multi-tier AI agent hierarchy for continuous market research (Orchestrator → Domain Managers → Team Leads → Workers → Cluster Agents), paired with a parallel, low-latency Trading Agent for execution.
- Risk-managed trade execution, long and short: position sizing, stop-loss, rate limiting and error handling; a fixed ₹200–300 per-trade risk budget enforced at execution time, with short/leveraged positions sized and monitored separately for liquidation and funding-rate risk.
- Gemini as the permanent external tie-breaker for the Trading Agent’s News / Technical / Risk checks — called live whenever the three signals conflict; no in-house model, no training, no retraining loop. Gemini works in two separate calls: a decision call (no web access, uses similar past cases from the system’s own memory) and a later review call (checks what actually happened and why). See SDD and TDD.
- A data pipeline covering both historical bootstrap data (price + news history) and live/continuous data, used for the point-in-time backtest and for the historical pattern-weight research — not for training any in-house model.
- Key use cases: (1) continuous background research refining a per-coin snapshot; (2) real-time trade execution gated on News, Technical and Risk all agreeing; (3) self-improvement via the hold-pattern analysis pipeline, which turns logged paper-trading and live outcomes into new pattern-library rules (no model retraining involved).
- A historically-weighted scoring layer: a dedicated research pipeline analyzes 10–20 years of aligned price, news and pattern data to derive numeric weights and confidence levels per pattern-plus-news-type combination, which are applied to News’ and Technical’s scores before they reach the AND-gate (full detail in the TDD).

### Success Criteria, Constraints & Assumptions

- A point-in-time historical backtest (“time machine” replay, no lookahead, roughly the last 10 years of available crypto/exchange history) validates the strategy first; Phase 1 paper trading (~1 month, live real-time data, fake money) then confirms it holds up under live conditions, gated on net profitability after all costs, a capped drawdown and robustness checks (see TDD) before any live cutover. Win rate is tracked as a secondary metric only — a high win rate means nothing if the losses are bigger than the wins.
- Rollout plan (finalized): No in-house model and no automated retraining pipeline. Gemini runs permanently as the live tie-breaker/decision model whenever News, Technical and Risk conflict. This replaces the earlier Jev-then-cutover-to-in-house plan entirely.
- Primary success metric: net expectancy. Average profit per trade after trading fees, spread, slippage and (for perpetual futures) funding costs must be clearly positive over a large enough number of trades. Maximum drawdown (3% of equity) remains a hard ceiling. Win rate is reported but is not the gate.
- Baseline comparisons. The system must beat simple strategies on the same data, same period and same costs: buy-and-hold, a simple momentum rule, a moving-average rule, technical-only, and news-only. If a plain baseline matches or beats the full multi-agent system, the extra complexity is not justified and the design is simplified.
- Component contribution. The system must show which parts actually add value (news signal, technical signal, risk filter, historical weights, Gemini tie-breaker) by switching each off in turn and measuring the change in net profit.
- Staged rollout gates (all required, in order). (1) Data check — historical data passes the quality check; (2) Edge check — positive net expectancy after costs on out-of-sample data, beating the baselines; (3) Robustness — results hold across bull, bear, sideways, high-volatility and low-volatility periods, and across different coins; (4) Shadow mode — live signals and decisions are recorded without placing any orders; (5) Paper trading — live data, fake money; (6) Small-capital live — real money at a deliberately small size before scaling up. Failing any stage sends the work back to the previous stage.
- Constraint: ₹200–300 per-trade risk budget, non-negotiable at execution time (also tracked internally as a percentage of current equity, see TDD).
- Constraint: operation needs continuous/live data feeds (24/7 crypto markets) — distinct from the periodic (daily/weekly) batch cadence used for the slow research/pattern-discovery loop.
- Constraint: short selling requires a futures/margin account on the exchange (spot doesn’t support it), which introduces liquidation and funding-rate risk that spot longs don’t carry.
- Assumption: historical training data pulled from exchange APIs may have quality issues (gaps, mismatched timestamps across exchanges) and needs independent verification before being trusted as training ground truth.

### Owner Control Website — Purpose

The owner needs to see and steer the whole system without reading code or log files. A private website is the single control room: it shows what every agent is doing, every trade and its profit, what the system has learned, and lets the owner answer the agents’ questions and change their behaviour safely.

The system is built for crypto (Binance) only. Paper money (fake) is the default until the strategy is proven.

#### Scope & Key Requirements

- Visibility: live status of every agent in the hierarchy (Orchestrator, Domain Managers, Team Leads, Cluster Agents, Trading Agent, learning loop), the research snapshot per coin, the scored news feed, price charts, the paper account, and the full trade log.
- Profit per trade: money invested, entry and exit, profit or loss in ₹, % and R, live profit on open trades, time held, and the news and team lead behind each trade.
- Human in the loop: agents ask the owner when unsure (an ambiguous headline, a new team lead, a proposed confidence cut); the owner answers on the website.
- Owner controls: pause or resume team leads, cluster agents and the Trading Agent; per-team-lead strictness; written instructions to a team lead; stop watching a coin.
- Safe changes: every change waits for an explicit Apply, is logged, and can be undone.
- Strategy lab: test price-rule settings on years of Binance history with a hidden exam period, and adopt a winner in one click.
- Settings: risk per trade, stop-loss, ₹ per USDT, market mood filter, short selling, price rules, coins.
- Access: password-protected; works on computer, tablet and phone.

#### Key Use Cases

- Daily check: the owner opens Overview and Trades to see account value, market mood, open trades and profit.
- Steering the research team: the owner answers agent questions, gives a team lead a written instruction, or pauses a team lead whose news keeps losing money, then presses Apply.
- Reviewing results: the owner uses “Profit by expert desk” to see which kinds of news make money, and the Memory page to see proven lessons.
- Tuning the price rules: the owner runs the Strategy lab and adopts a setting only if it passes the hidden-period exam.
- Undoing a mistake: the owner opens History and presses Undo on any applied change.

#### Success Criteria, Constraints & Assumptions

- Success: the owner can answer “what is the system doing, what did it trade, and did it make money?” from the website alone, on a phone, in under a minute.
- Success: no agent behaviour changes without the owner pressing Apply, and every change can be undone.
- Constraint: the ₹200–300 per-trade risk budget, stop-losses and paper-vs-real money cannot be changed from the website.
- Constraint: the website must not be reachable from the internet without a password and HTTPS.
- Constraint: API keys and passwords live only on the server, never in the website or on GitHub.
- Assumption: one owner uses the website; there are no separate user roles.

### Phase 1 — Agent System & Monitoring UI, Built Together (UAT)

Since no agent code exists yet, Phase 1 builds the agent system and a read-only monitoring UI in parallel, against one shared data contract (see TDD), rather than building the agent logic blind and bolting on visibility later. This lets every stage of development be checked and UAT-tested on screen as it’s built, instead of only trusting logs.

#### Scope (Phase 1)

- Read-only dashboard — no owner controls (pause/resume, Apply/Undo) yet; that’s a later phase, once the agent design itself is validated.
- Pages: Overview, Agent Hierarchy, Decisions, Trades, News & Research, Backtest Results, Memory.
- Purpose: continuous UAT — every agent behaviour and every trade decision should be checkable on screen as the system is built, not just inferred from logs.

#### Success Criteria (Phase 1)

- At any point during development, the owner can open the dashboard and see, live, what every agent is doing and why the last trade decision was made.
- The dashboard and the agent system are built against the same data contract from day one, so there’s no separate “add visibility later” phase.

### Agent-Side Visibility — Live Charts & Trade Execution View

#### Purpose

Beyond agent status and a chronological decision/trade list, the owner needs to see the market exactly as the Technical component sees it, and see every trade placed directly on that same view, not just as rows in a separate log. This is what turns the dashboard from “the agent says X happened” into “here’s the chart, here’s where it fired, judge for yourself.”

#### Requirements

- Live price chart per coin — candlestick chart at the same interval the Technical component actually evaluates, with the trend line / moving average, breakout level, and whichever entry pattern (engulfing, hammer/wick, breakout) is currently configured, drawn directly on the chart, exactly as the agent’s price rules see them.
- Signal markers on the chart — every point where a price rule fired (buy/sell/short signal), marked directly on the candle it fired on, whether or not it turned into an actual trade (so a signal the Risk or News side vetoed is still visible, not silently dropped).
- Trade markers on the chart — every executed trade shown directly on the price chart at its entry candle and exit candle (arrow up for long entry, arrow down for short entry, a closing marker at exit), so the owner can see at a glance where trades actually landed relative to price action.
- News markers on the timeline — headlines that influenced a decision plotted at their publish time on the same chart, so a price move and the news behind it read together.
- Trade blotter (chronological log) — every trade as a row: coin, direction, entry time + price, exit time + price, size, P&L (₹ / % / R), close reason, and which team lead / news item was behind it.
- Drill-down from any trade — clicking a trade jumps to that exact point on the chart and opens the underlying decision: the News/Technical/Risk verdicts, their individual reasoning, and (if it fired) the LLM tie-breaker’s reasoning, all in one place.
- Live vs replay — the same chart+markers view works for a live/paper trading session and for stepping through a historical backtest run, since both use the same underlying data (per the point-in-time backtest’s shared-interface design).

#### Success Criteria

- The owner can pick any single trade from the blotter and, without leaving the dashboard, see the exact chart state, the signal that fired, and the reasoning that led to it.
- The owner can look at the chart alone and identify every point a signal fired, whether or not it became a trade, and why (vetoed by Risk, vetoed by News, or the AND-gate genuinely conflicted).
- Nothing the agent evaluates is invisible: if a rule looked at a candle and decided not to act, that decision is inspectable, not just the trades that went through.

## SDD — System Design

System design for the multi-tier research hierarchy and the parallel Trading Agent, including the Gemini-based tie-breaker used when its News / Technical / Risk checks conflict.

### Agent Hierarchy & Team Lead Layer

Original 4-tier hierarchy: Orchestrator -> Domain Managers (News & Sentiment, Price & Technical, Risk & Portfolio) -> Disposable Workers -> Persistent Cluster Agents. This assumed every worker is spun up fresh and torn down, which left two problems: no reuse of a worker for a recurring task type, and no clean routing without a heavyweight classifier.

Fix — a Team Lead layer, inserted between Domain Managers and Disposable Workers. Each domain manager owns several team leads; each team lead owns one narrow task-type cluster (e.g. under News & Sentiment: a Protocol-Events lead — mainnet upgrades, token unlocks, halvings — a Regulatory lead, a Social-Sentiment lead — illustrative, not fixed).

What it resolves:

- Matching — a task routes to whichever team lead’s expertise covers it, no global classifier needed.
- KT cost — a narrow scope means a lighter briefing to workers; no worker’s persistence or memory is ever assumed.
- Redundancy cleanup — the team lead decides when a worker is genuinely redundant, not a blanket rule.
- Approval flow — a team lead requests a worker spin-up via its domain manager, not the Orchestrator directly (avoids recreating the bottleneck the layer exists to remove).

Dynamic spawning. Team leads spawn dynamically rather than being fixed at design time. Matching is cheap: every team lead gets a compact semantic fingerprint (small set of embedding vectors); an incoming task is embedded and compared via similarity search (a vector lookup, not an LLM call). Only when a task falls below the similarity threshold against every existing lead does it escalate to an LLM judgment call on whether it’s genuinely new or just phrased differently.

Dormancy, not deletion. A team lead that hasn’t matched a new task in a few weeks gets its fingerprint and knowledge compressed and archived, then rehydrated if a similar task resurfaces.

### Two-Loop Architecture & Trading Agent

Slow research loop — Orchestrator -> Domain Managers -> Team Leads -> Workers -> Cluster Agents — runs continuously in the background on news, price and risk research. Intentionally slow: rushing research produces bad conclusions.

Fast loop = the Trading Agent, a parallel 6th component, not inside the hierarchy. It does no research or reasoning about direction — it only reads the Orchestrator’s consolidated per-coin snapshot (direction bias, confidence, risk flags, timestamped) and acts.

Freshness safety valve. A stale or missing snapshot means the Trading Agent skips that coin — it never falls back to live research (reintroduces latency) and never acts on stale data.

Mistake-loop closure. Every executed trade logs the snapshot it acted on, that snapshot’s rationale, and the actual outcome once the trade closes. This feeds back into the slow loop as its own recurring task type, routed to the owning team lead; a pattern of misses triggers a scoped refinement task for just that cluster, not a system-wide audit.

Trading Agent structure. Mirrors the three domains — News, Technical, Risk — but every counterpart is execution-only: none spins up a worker, researches, or asks a question. Shorting is enabled through a futures/margin account on a supporting exchange (e.g. Binance Futures) rather than spot — spot doesn’t support opening a short position.

- News — watches for news-tagged snapshots, triggers only when upstream research already flags something actionable.
- Technical — reads candlestick/price-pattern signals for entry/exit timing, on both bullish (long) and bearish (short) setups.
- Risk — owns position sizing for both long and short trades, enforces the ₹200–300 per-trade risk budget, and sizes/monitors short and leveraged positions separately given their liquidation and funding-rate risk.

AND-gate. All three must agree — not fastest-signal-wins. News flags it, Technical confirms it, Risk clears the sizing; only then does the Trading Agent act. Even a very confident single signal (e.g. news alone) is not enough; risk clearance is non-negotiable either way.

Historically-weighted scoring (see TDD). News and Technical do not treat every pattern or headline type as equally important. A dedicated historical research pipeline, covering 10–20 years of aligned price, news and pattern data, derives a numeric weight and confidence level for each pattern-plus-news-type combination, conditioned on context (time period, asset category, news category) where relevant. These weights live in the shared pattern library and are applied to News’ and Technical’s raw scores before they reach the AND-gate — the gate itself stays a three-way check (News, Technical, Risk); it does not become a fourth voting agent. Full pipeline detail is in the TDD, under “Historical Pattern-Weight Research.”

Watch state. News and technical confirmation often don’t arrive together — no fixed sync window, it varies by news type, asset category and timing. An unconfirmed news signal is tagged as a hypothesis and held in a watch state, rechecked without needing a fresh trigger. It resolves either when technical confirmation arrives (trade proceeds through the normal AND-gate) or when it ages out (treated as a non-event). The aging window isn’t guessed upfront — it’s calibrated empirically from Phase 1 paper trading data, per asset-category/event-type.

### Memory Partitioning

A single, undivided memory store doesn’t scale with continuous learning — signal gets buried under volume and older, rarer-but-important patterns become effectively invisible. Three layers instead:

- Raw event log — the permanent, unfiltered record: every news event, coin, timestamp, and eventual candlestick outcome, recorded exactly as it happened.
- Team lead pattern library — the general pattern distilled from the log (“this category of news tends to produce this kind of candlestick move”), independent of any single coin, owned by the relevant team lead.
- Cluster agent memory — coin-specific behavior, which references the relevant team lead’s pattern library rather than duplicating it — a single source of truth per pattern.

This also keeps the compression plan for cluster agents manageable: many smaller, coherent partitions, each only compressing its own narrow slice, instead of one large blob needing aggressive lossy compression.

### News & Sentiment Data Sourcing

Raw sources:

- Crypto news APIs — CryptoPanic, CryptoCompare’s news endpoint, NewsAPI’s crypto category (news taggable by coin).
- Direct exchange announcement feeds (e.g. Binance, Coinbase) for listings, delistings and protocol/regulatory announcements — highest-signal, fastest-moving events.
- Social sentiment — Twitter/X (crypto Twitter) and Reddit (e.g. r/CryptoCurrency, r/Bitcoin), where retail sentiment often moves faster than official news.

Sentiment scoring is multi-dimensional, not just positive/negative:

- Direction — bullish or bearish for the coin.
- Magnitude — how big a deal the news is.
- Confidence — how reliable or corroborated the source is.

Since the architecture already separates a Protocol-Events lead from a Regulatory lead from a Social-Sentiment lead, each team lead likely needs a differently tuned sentiment model — protocol-update sentiment reads very differently from a Reddit post’s tone.

### External Tie-Breaker Decision Model (Gemini) & Historical Data Use

Motivation. The Trading Agent’s News/Technical/Risk AND-gate checks don’t need open-ended reasoning most of the time — they read a snapshot and decide. When the three signals conflict, a single live call to Gemini acts as the tie-breaker: it’s handed each component’s verdict and reasoning, plus similar past conflict cases pulled from the system’s own memory, weighs the evidence, and returns one final decision plus its reasoning, which gets logged. No in-house model is trained and there is no in-house fast decision model; this avoids the cost and complexity of a training/retraining pipeline entirely.

Approach. Gemini is called live via API whenever News, Technical and Risk conflict, using a fixed prompt structure (context + similar past cases + question + fixed answer shape). No fine-tuning, no reinforcement learning, no quantization, no retraining pipeline — Gemini is used as-is, permanently.

Two-call design: decide, then review. Gemini is used in two separate, independent calls so that the reviewer is never defending its own earlier answer and each call keeps a small, clean context (less room to hallucinate):

- Call 1 — Decision (live, fast). Input: the News, Technical and Risk verdicts and reasoning, plus the most similar past conflict cases retrieved from the system’s own memory. No web or internet access. Output: buy, sell or hold with reasoning. The answer is logged and stored marked as Gemini’s guess, not as a fact.
- Call 2 — Review (after the trade ends). A new, fresh call, made only once the trade has actually ended (stop-loss hit, target hit, or a fixed time window such as a few hours — never judged after one second or one minute, where price moves are mostly noise). Input: the original inputs, Gemini’s Call 1 answer, and what really happened. This call may use web search to find out why the price moved, and writes a short note on what the first call got wrong or right.
- Source of truth for the outcome. The real price result always comes from the exchange (Binance) data, not from web search. Web search is used only to explain the “why”.
- The review is a theory, not a fact. The Call 2 note is stored as a lesson candidate. It only gets trusted after the same lesson shows up across about 20–30 similar cases (the same rule used for hold-pattern rules).
- Live only. Web search and Gemini decisions are used only in live and shadow mode. In backtests they would leak hindsight (see TDD), so backtests save only rule-based cases with real outcomes.

Case-based memory retrieval (no live web at decision time). When signals conflict, the system searches its own stored case library for situations most similar to the current one (similar signal combination, coin type and market conditions) and gives them to Gemini as evidence. Each stored case records the inputs, the real subsequent price outcome, and — separately — Gemini’s own guess and later review note. Only the real outcome counts as evidence; Gemini’s past answers are never reused as if they were facts. The case library has two sources: (a) rule-based backtest cases with real outcomes (no Gemini involved, so no hindsight contamination), and (b) live and shadow-mode cases. If too few similar cases exist (below the minimum in the TDD), the system flags thin evidence and defaults to hold.

Pattern validation lifecycle. Patterns and lessons never go straight into live use. Each moves through stages: candidate (just discovered, e.g. from hold events or a Call 2 review) → validated (passes on data it was not discovered from, with enough samples and a consistent edge after costs) → production (allowed to influence live trades) → retired (edge has faded or failed re-checks). A pattern must never be evaluated on the same data that created it, and the component that proposes a pattern is never the one that approves it.

Historical data use. The historical bootstrap (price + news history) is still used for the point-in-time backtest and for the historical pattern-weight research (see TDD) — it is no longer used to train any in-house model, since none is being trained.

Candidate data sources:

- Binance API (free) — the single source of truth for historical candlestick/kline data, back to listing date, down to minute-level granularity. No cross-exchange comparison for now.

Data-quality safeguards (given a wrong historical label would corrupt the point-in-time backtest and the historical pattern-weight research):

- Internal consistency check: sample ~100 news/price pairs and verify timestamps, gaps and values are internally consistent — no cross-exchange comparison, consistent with the Binance-only decision; more than 3% defects fails the check (see TDD).
- Treat live Phase 1 paper-trading data as a correction layer on top of the historical bootstrap.

Open questions carried from the original design:

- Snapshot source — direct cluster-agent read vs. Orchestrator-pushed consolidated view.
- Team lead spawn approval authority — domain manager vs. Orchestrator.
- Watch-state aging rule — per-category vs. one global default with overrides.
- Redundancy triggers for a worker within a team lead’s cluster, beyond “idle for weeks.”

### Owner Control Website

The website is a 7th component, beside the slow research loop and the fast Trading Agent, never inside either. It only reads what the agents publish and writes the owner’s approved changes; it never researches, trades or calls an exchange itself.

- Reads: agent status and recent work, open questions, research snapshots, news scores, the trade log, the paper account, memory, backtest results.
- Writes: settings and the owner’s approved agent controls. The agents pick these up at the start of their next cycle (research: every 15 minutes; trading: every minute).
- Runs: in the same server process as the agents (always-on mode) or on its own, sharing one data folder.

#### Page Map

| Page | Architecture component it shows |
|---|---|
| Overview | Paper account, market mood (Risk manager), per-coin snapshots (Cluster Agents) |
| Markets | Price & Technical view: candles, trend line, where the price rules fire |
| News & research | News & Sentiment manager output: scored news and per-coin snapshots |
| Agents | The whole hierarchy live: status, recent work, questions, owner controls, Apply, History, Undo |
| Live agent | Trading Agent: paper account, positions, activity log, errors |
| Strategy lab | Offline research: hidden-period settings search (VectorBT) |
| Trades | Trade log with profit per trade and per team lead (mistake-loop input) |
| Memory | Memory partitions: team lead pattern library, cluster (coin) notes, dormant leads, refinement tasks |
| Settings | Risk & execution parameters and the coin universe |
| Roadmap | Findings, decisions, next steps |

#### Owner Control Loop

Diagram: owner control loop — 6 steps, Apply gate, Undo.

Agents raise three kinds of questions: a team lead unsure whether a headline is good or bad (confidence 30–50%, strong news; at most 3 new per cycle, 10 open), the learning loop proposing a confidence cut for a losing news cluster, and the News manager proposing a new team lead when news keeps fitting none. An answer is a suggested change like any other and goes live only on Apply.

#### Design Decisions

- One writer per file. Agents write their status, questions and results; the website writes only settings and approved controls. The two never overwrite each other.
- Apply gate. Suggestions and answers queue as pending changes with before → after; Apply writes them all at once; each applied change stores the value it replaced, so Undo restores exactly that.
- Locked parameters. The ₹200–300 risk budget, stop-losses and paper-vs-real money are not exposed as controls.
- Pause semantics. A paused team lead holds its news unscored until resumed; a paused cluster agent publishes no new snapshot, so the Trading Agent skips that coin; a paused Trading Agent opens nothing new but still manages stop-losses.
- Learning needs approval. Confidence cuts for losing news clusters are proposals until the owner accepts them (previously automatic).

Answers to the SDD open questions:

| Open question | Decision |
|---|---|
| Snapshot source | Orchestrator-pushed consolidated view: cluster agents publish, the Trading Agent reads the latest set |
| Team lead spawn approval authority | The domain manager proposes; the owner approves on the Agents page |
| Watch-state aging rule | One global default (2 hours) with per sector / news-type overrides, to be calibrated from paper trading |
| Worker redundancy | Workers are disposable per batch; team leads go dormant after 3 weeks without matching news and wake when similar news returns |

## TDD — Technical Design

Technical design for the data pipeline, the Gemini-based tie-breaker, and the point-in-time backtest behind the Trading Agent’s AND-gate.

### Data Sources & Pipeline

News: CryptoPanic, CryptoCompare’s news endpoint, NewsAPI’s crypto category (coin-tagged); exchange announcement feeds (Binance, Coinbase) for listings, delistings and protocol updates; Twitter/X and Reddit APIs for social sentiment.

Historical price/candlestick:

- Binance API (free) — candlestick/kline history back to each coin’s listing date, down to minute-level granularity — the single source of truth for both historical and live price data.

Live data: crypto requires continuous/real-time feeds (24/7 markets) — separate from the periodic (daily/weekly) batch cadence used for the slow research/pattern-discovery loop. Live data drives trading decisions in real time; only the research batch is periodic.

Data-quality verification: Binance is the single source of truth for historical and live price data — no cross-exchange comparison against a second provider for now. Pass/fail threshold: sample-check ~100 news/price pairs for internal consistency (correct timestamps, no gaps, no obviously broken values) rather than against an independent source. If more than 3% of the sampled pairs show a defect (missing/mismatched timestamp, broken value), the dataset fails the check and needs remediation before being trusted for backtesting or pattern research.

Watchlist size (Phase 1). The agent tracks a fixed list of 5 coins in Phase 1, chosen from Binance’s top-liquidity coins and reviewed periodically rather than expanded dynamically. A small, fixed universe keeps Binance API rate-limit usage, Gemini tie-breaker call volume/cost, and order-book liquidity quality comfortably within safe margins for a single-operator system. The list can be widened in a later phase once Phase 1 paper-trading and live results validate the approach at this scale.

### Tie-Breaker Decision Model (Gemini) — Superseded In-House Training Design

Finalized approach: no in-house model. The in-house fine-tuned model, its training stages, and the automated retraining pipeline described below were the original design and are no longer being built. The tie-breaker is now Gemini, called live via API whenever News, Technical and Risk conflict — same input (each component’s verdict and reasoning) and output shape (final decision plus reasoning, logged for review), just backed by a hosted model instead of a trained one. The sections below are kept for historical reference only.

### Trading Agent Execution Logic & Testing Strategy

Decision loop: read the latest data -> run it through the strategy/AND-gate for a signal (long, short, hold, or close) -> place the order through the exchange’s futures/margin API -> log what was done.

Cheap-vs-expensive split at the decision point. When News, Technical and Risk all agree (unanimous long, short, or hold), the gate fires purely on rule-based logic — no model call needed, this is the default, high-frequency path. When the three signals disagree (a conflicted state — e.g. Technical says long, News says hold, Risk says long), that’s the trigger for a single LLM tie-breaking call: it’s handed each component’s verdict and the reasoning behind it, weighs the evidence, and returns one final decision (trade or don’t) plus its reasoning, which gets logged for later review of how good its tie-breaking judgment was. A unanimous don’t-trade is a clean consensus, not a conflict, and never fires the LLM. This mirrors the same cheap-lookup-first, expensive-call-only-on-ambiguity philosophy already used for news routing (semantic fingerprinting) in the SDD.

Tie-breaker retrieval, minimum evidence and two-call flow. Before Gemini’s Call 1, the system retrieves similar past conflict cases from its own memory (by embedding similarity over the signal combination, coin type and market conditions). A minimum number of similar cases is required before Gemini is allowed to rely on them (default 20–30, matching the pattern-rule sample rule; configurable). With fewer than the minimum, the case is flagged as thin evidence and the cycle defaults to hold, or trades at reduced size only if the rule-based signals are otherwise unanimous. Cases are stored with: inputs, real price outcome measured from Binance data at trade end, Gemini’s Call 1 answer (marked as a guess), and the Call 2 review note (marked as a theory). Call 2 runs after the trade closes or after a fixed window, in a fresh context, with web search allowed — live and shadow mode only.

Tie-breaker timeout — fail closed, but never lost. If the live Gemini call does not return within a short timeout (2-3 seconds), the current cycle defaults to hold and does not force a trade on an incomplete decision. This hold is never silently discarded: it is logged as a structured hold event and handed to the slow research loop for analysis, not re-attempted as a late trade on the same opportunity (by the time analysis finishes, price has moved — there is nothing to act on retroactively).

Hold event record. Every hold — whether from a Gemini timeout, an AND-gate conflict resolved to hold, or any other cause — is logged with: timestamp, coin, each of News/Technical/Risk’s verdict and reasoning, the specific reason for the hold, and the actual price movement in the window afterward (e.g. next 1-24 hours), so its outcome can be judged after the fact.

Hold-pattern analysis pipeline (slow loop). On a regular cadence (e.g. daily or weekly), a dedicated research task groups logged holds by shape — the same combination of cause, conflict pattern, and context (coin category, market conditions) — and checks what would have happened if a trade had fired instead. A pattern only becomes a rule once it clears a minimum sample size (e.g. at least 20-30 similar hold events) and shows a consistent, statistically meaningful edge after costs — not a rule drawn from two lucky instances. To avoid overfitting and leakage, every pattern follows the candidate → validated → production → retired lifecycle: it is discovered on one slice of data, then must pass on a separate, later slice it has never seen, and is re-checked periodically after going live.

Output: a conditional action rule, stored in the pattern library. Once a hold-shape clears that bar, it is written into the shared pattern library in the same condition -> weight/confidence format as the historical pattern-weight research, but as an explicit if-then instruction the live Trading Agent can act on next time that shape recurs — not just a passive weight adjustment.

Worked example: Suppose over several weeks, every time Gemini times out while Technical says long, News is neutral, and the coin is a top-10-by-market-cap coin, the price rises more than 1% in the next hour in 24 out of 30 such cases. That clears the sample-size and consistency bar, so the research loop writes a rule: “IF Gemini tie-breaker times out AND Technical=long AND News=neutral AND coin is top-10-by-market-cap, THEN treat as long with reduced position size (e.g. half the normal per-trade risk budget), without waiting for Gemini.” This rule then lives in the pattern library and the live Trading Agent applies it automatically the next time that exact shape occurs — no Gemini call needed for that specific, already-proven pattern. A second example: if timeouts during a News=bearish, Technical=long conflict show no consistent edge either way across enough samples, the rule instead becomes “IF this shape recurs, THEN keep holding, no override” — confirming hold was already the right call, not something to fix.

Risk management:

Risk as a percentage of equity. The fixed ₹200–300 per-trade budget stays the execution rule, but the system also records every trade’s risk as a percentage of current equity, so results and limits stay comparable as the account grows or shrinks (₹200 is a very different risk on a small account than on a large one). Internal limits and reports use the percentage; the rupee figure is the cap enforced at order time.

Position sizing — how much of the portfolio to risk on any single trade, long or short, never all-in.

Stop-loss — an automatic rule that closes the position if it moves past a set percentage against it, in either direction.

Short-specific risk — leveraged/short positions carry liquidation risk and (on perpetual futures) ongoing funding-rate costs that spot longs don’t have; sized and monitored separately.

Rate limiting & error handling — exchange APIs can fail or throttle; the agent must degrade gracefully rather than crash or spam orders.

Order reconciliation (failed/ambiguous order placement). If an order-placement call to the exchange times out or returns an ambiguous error, the agent never assumes the outcome and never blindly retries. Every order is placed with a client-generated order ID up front; on any ambiguous response, the agent immediately queries the exchange’s order-status/open-orders endpoint using that client order ID to establish ground truth (did it fill, is it open, or did it never reach the exchange), and only then decides to retry, cancel, or log it as executed. This check happens before any other action is taken on that position.

Additional circuit breakers. Beyond the daily loss limit, trading halts automatically (no new entries, existing positions managed under their stop-losses) when any of these trip: stale data — the price or news feed has not updated within its allowed window; order/position mismatch — the system’s own record of positions or orders disagrees with the exchange after reconciliation; exchange degraded — repeated API errors, rate-limit throttling or abnormal latency; strategy anomaly — live behaviour drifts well outside what was seen in testing (e.g. trade frequency or loss streak far beyond the backtest range); infrastructure — the server, database or Gemini service is unreachable for longer than a set limit. Each trip is logged and shown on the dashboard, and needs a manual reset or a documented auto-recovery condition.

Binance-down / rate-limit fallback. Binance is the sole price source, so a fallback plan is required: (1) on rate limiting, back off with increasing delays and reduce polling to essential symbols; (2) if the feed is stale beyond its window, the stale-data circuit breaker trips and no new trades open; (3) open positions keep their exchange-side stop-loss orders so protection does not depend on the agent being online; (4) while Binance is down, the system does not substitute another exchange’s prices for trade decisions (consistent with the single-source decision), it simply waits and alerts the owner; (5) after recovery, the system reconciles orders and positions and re-checks for gaps in the stored candles before resuming.

Kill switch (daily circuit breaker). Per-trade risk sizing alone is not sufficient to stop a losing streak from compounding across a day. A system-level daily circuit breaker tracks cumulative realized plus unrealized P&L against current account equity (not a fixed rupee figure, so the ceiling scales up or down as the account grows or draws down); if losses on the day reach 2-3% of current equity, all new trade entries halt automatically until the next trading day or a manual reset. Existing open positions may still be managed or closed under their own stop-losses while the breaker is tripped.

Point-in-time backtest (the “time machine”). Before risking real capital, the strategy runs against historical data behind a simulated clock: at each simulated moment, the engine can only see price and news data that would genuinely have existed at that moment — no peeking at what happens next. The clock advances through history like a replay, the AND-gate makes real trade decisions against only what’s visible so far, and the resulting P&L stays hidden until the run finishes, so nothing about what actually happened next leaks into the decision logic while it’s being tested.

Backtest runs WITHOUT Gemini. Gemini’s training data includes articles and analysis written after historical events, so replaying old headlines through it can leak hindsight into its decisions — most of all for famous events and for exactly the high-stakes conflict cases where it is called. This cannot be reliably prompted away. Therefore: the backtest uses only the rule-based system; conflict cases are handled by a fixed rule (default hold) and saved with their real outcomes to build the case library; Gemini’s value is measured separately in shadow mode and paper trading on live, unseen data (compare outcomes with and without the Gemini call). Stripping names and dates from old headlines is at best a partial fix and is not relied on.

Transaction costs are first-class in the backtester. Every simulated trade pays: exchange fees (maker/taker as applicable), bid-ask spread, slippage (larger for bigger orders and in volatile or thin markets), and funding payments on perpetual futures held across funding times. Execution assumptions are deliberately pessimistic (e.g. fills at the worse side of the spread, orders delayed by one candle, extra slippage in high-volatility periods). Results are reported net of all costs, and a strategy that only works under optimistic cost assumptions is rejected.

Historical news availability. Free news APIs rarely provide reliable, publish-timestamped coverage going back 10 years. The technical-only backtest can use the full Binance history. The news-based backtest uses whatever historical news can be verified with true publish times; otherwise it starts from the system’s own live collection going forward. This limit is stated in every backtest report.

Survivorship bias in the coin list. The fixed 5-coin Phase 1 watchlist was chosen with hindsight. Backtests must also be run on a point-in-time coin universe (e.g. the top coins by market cap as they were at each date, including coins that later collapsed or were delisted), and results on the fixed watchlist are reported alongside it.

Regime breakdown. Results are broken down by market regime (bull, bear, sideways, high-volatility, low-volatility) and by coin, so a strategy that only worked in one kind of market is visible.

Why this matters. A backtest that loads all the data upfront quietly lets a strategy “see the future” — the model, or the person tuning it, can shape decisions around outcomes it already knows. A strict point-in-time view is what makes the eventual result trustworthy: if it makes money here, it’s because the logic worked, not because hindsight leaked in.

How lookahead is actually prevented — the rules. The historical data all sits in one database; nothing is physically deleted. What stops the cheating is a hard rule enforced in the code, not in the data:

- One clock, one rule. The engine holds a single “simulated current time.” Every data request — price, news, anything — passes that time along, and only gets back rows timestamped at or before it. No code path is allowed to skip this filter.
- Feed it like a drip, not a fire hose. The engine walks forward one candle or one news item at a time; the strategy’s code is never handed tomorrow’s row to begin with, so there’s nothing to accidentally peek at.
- Publish time, not event time. Some datasets timestamp news by when something happened rather than when it became public. Features are built off publish time — the moment it was actually knowable — not the event date.
- No whole-series math. Indicators like moving averages are computed only from candles up to “now,” never a centered or whole-history calculation that secretly bakes in future values.
- A locked-away final test period. History is split into a “practice” stretch used for building and tuning, and a final, untouched stretch (the most recent years) run exactly once at the end — this is what actually stops the strategy from being unconsciously tweaked until it happens to beat the past.
- Hide the running score. Cumulative P&L isn’t shown while the replay is in progress — only once the full run finishes — so nothing nudges decisions based on how a trade is about to turn out.

Fast-forward vs. simulated time. These are two different clocks, and only one of them needs to move at real speed. The simulated clock (the one all the rules above are anchored to) ticks forward exactly in timestamp order, one event at a time — but wall-clock time, how fast your computer actually gets through it, can run as fast as the hardware allows, since it’s just replaying already-recorded history rather than waiting for the market to actually move. Ten years of history can realistically replay in minutes to a few hours, not ten years.

Shared interface (the “middle layer”). The trading engine talks to one common interface for both modes — something like “give me the next price update,” “give me the next news item,” “place this order” — regardless of whether it’s backtesting or live. In backtest mode, that middle layer reads from the stored historical data and hands events to the engine one at a time, as fast as it can, still honoring the point-in-time rules above. In live mode, the exact same interface instead listens to the real exchange feed and hands events over as they actually happen. Because the trading engine never knows or cares which mode it’s in, the exact logic that got validated across years of fast-forwarded history is the same logic that runs live later — no risk of the backtest secretly behaving differently from the real thing.

Coverage note. For crypto, roughly the last 10 years of exchange history is realistic (Bitcoin’s usable exchange data starts around 2013); 20 years doesn’t apply to crypto the way it might to stocks, since crypto itself doesn’t go back that far.

Slow-loop batch cadence during the historical replay. Running full pattern-discovery (domain managers + team leads) fresh at every single historical event would be slow and redundant, since patterns don’t meaningfully shift tick-to-tick. Instead the slow loop runs in batches as simulated time advances: weekly batches for the earliest years (least mature pattern library, needs tightest refresh), monthly for the middle years, and quarterly for the most recent years as the pattern library matures and needs less frequent refinement. The fast loop (Trading Agent) still runs dense, at every decision point, using whatever pattern library exists as of that point in simulated time — only the research/discovery side is batched.

Backtest timing estimate (assumption, to be validated). The slow loop’s batched runs are cheap in aggregate — well under a couple of days total even on the slower end. The dominant cost is the fast loop, since it runs at every decision point across the full history and every tracked coin; single-threaded this could span roughly one to several weeks depending on per-decision latency, but since each coin’s timeline is independent this parallelizes cleanly across coins, bringing wall-clock time down to roughly one to six days. The main lever is keeping per-decision cost low (cached embeddings, rule-based checks, the cheap-vs-expensive split above) rather than a heavy model call on every decision.

Paper trading (Phase 1). After the historical time-machine run validates the logic, Phase 1 paper trading (~1 month, live real-time data, fake money, on a futures/margin testnet where available) confirms it holds up under live conditions and generates the calibration data used for the watch-state aging rule.

Shadow mode (before paper trading). After the backtest passes, the system runs on live data and records every signal, Gemini call and would-be trade without placing any order, not even on the testnet. Shadow mode checks data feeds, timing, latency and Gemini’s behaviour in real conditions, and is where Gemini’s added value is first measured fairly.

Numeric gates for the staged rollout. Win rate is no longer the primary gate. Each stage must pass before the next begins: (1) Data check — the sample quality check passes (defects at or below 3%); (2) Edge check — on out-of-sample data, net expectancy per trade after all costs is positive with a sufficient trade count, and beats the buy-and-hold, momentum, moving-average, technical-only and news-only baselines; (3) Robustness — still positive across regimes and coins and under pessimistic cost assumptions; (4) Shadow mode — live decisions match backtest behaviour within expected ranges with no feed or logic failures; (5) Paper trading (~1 month, live data, fake money) — maximum drawdown never exceeds 3% of account equity (peak-to-trough and on any single trade) and net expectancy stays positive; win rate and profit factor are reported but not gated; (6) Small-capital live — real money at a deliberately small size, scaled up only after it also holds. Failing a stage keeps the system in the previous one. The exact trade-count and expectancy thresholds are set before testing starts and recorded in the experiment registry, so they cannot be adjusted after seeing results.

### Owner Control Website — Stack & Deployment

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript, Vite, Tailwind CSS, TanStack Query (data fetching and refresh), React Router, TradingView lightweight-charts (candles, profit curves), lucide icons |
| Backend | Python FastAPI app serving the JSON API and the built website from one address |
| Agents in the same process | TU_AUTORUN=1 runs research every 15 minutes and trading every minute inside the web server |
| Packaging | One Docker image: a Node build stage for the website, a Python 3.11 runtime stage |
| Hosting | Oracle Cloud VM (India region) via docker-compose: auto-restart, capped log files, website bound to the server only (reached through an SSH tunnel) and optional HTTPS through Caddy; Render.com blueprint as an alternative |
| Data | One data folder (/data in Docker) holding all JSON/JSONL state; survives restarts and updates |

#### API Endpoints

All under /api; every endpoint except health and login requires a logged-in session when a password is set.

| Method | Path | Purpose |
|---|---|---|
| GET | /health | Uptime check (always open) |
| GET / POST / POST | /auth, /login, /logout | Session state, log in, log out |
| GET / PUT | /settings | Read or save the agent’s rules |
| POST | /settings/apply-best | Adopt a Strategy lab winner |
| GET | /markets | Coin summary cards |
| GET | /candles/{symbol} | Candles, trend line and buy signals for a coin |
| GET | /snapshots | Latest research snapshot per coin |
| GET | /news | Scored news feed |
| GET | /status | Agent heartbeat: account, positions, last cycles, events, errors |
| GET | /trades | Trade log with money in, live profit, %, R, time held, team lead |
| GET | /memory | Lessons, coin notes, dormant leads, refinements |
| GET | /roadmap | Project notes |
| POST | /research/run, /trade/step | Run one research cycle or one trading check now |
| POST | /backtest | Strategy lab search |
| GET | /agents | Team with live status, questions, pending changes, history |
| POST | /agents/suggest | Suggest a control change (pause, strictness, instruction, stop watching) |
| POST | /agents/questions/{id}/answer | Answer an agent’s question |
| DELETE | /agents/pending, /agents/pending/{id} | Discard all or one pending change |
| POST | /agents/apply | Apply all pending changes |
| POST | /agents/history/{id}/undo | Undo one applied change |

#### Data Files

Each file has exactly one writer, so the agent process and the website never overwrite each other.

| File | Holds | Written by |
|---|---|---|
| status.json | Heartbeat: account, positions, cycle counters, events, errors | Agents |
| agents.json | Live board: each agent’s status, current task, recent work | Agents |
| questions.jsonl | Agents’ questions for the owner (append-only, each asked once) | Agents |
| news.jsonl, scores.jsonl | Collected news and their scores | Agents |
| snapshots/ | Latest and historical per-coin snapshots | Agents |
| trades.jsonl, paper_broker.json | Trade log; paper account and latest prices | Agents |
| events.jsonl, memory.json, refinements.json | Raw event log, pattern library and coin notes, proposed confidence cuts | Agents |
| settings.json | Owner’s rules (risk, stop-loss, filters, shorts, price rules, coins) | Website |
| controls.json | Owner’s applied agent controls: pauses, strictness, instructions, rulings, accepted cuts, new team leads | Website |
| agent_changes.json | Pending changes and applied history with undo values | Website |

Writes use a temporary file and an atomic rename, so a reader never sees a half-written file.

Staleness indicator. If the agent process crashes or stalls, its data files simply stop updating — the dashboard would otherwise keep showing old numbers as if they were current. Every page shows a “last updated” timestamp read from the underlying data file; if that timestamp is older than roughly double the page’s normal refresh interval (see Refresh Rates below), the UI flags it visually (e.g. a stale-data banner), so frozen data is never mistaken for live data.

#### Security, Refresh Rates & Testing

Security

- Password from the server setting TU_PASSWORD; login gives a signed session cookie (HMAC-SHA256, 7 days), HttpOnly and SameSite=Strict; changing the password logs everyone out.
- 5 wrong passwords from one address lock it out for 15 minutes; API docs are hidden when a password is set; no cross-site (CORS) access.
- Keys (Gemini, Binance) live only in the server’s environment file, never in the website or on GitHub.

Refresh rates

| Data | Refreshes every |
|---|---|
| Agents page | 5 seconds |
| Status | 15 seconds |
| Snapshots, trades | 30 seconds |
| Markets, candles, news | 60 seconds |

Testing

- Automated tests cover the API, login and lockout, the Apply / Undo flow, pause behaviour, question limits, trade profit numbers and the backtest (129 passing).
- Every website change is typechecked, built, and clicked through in a real browser (computer and phone sizes) before it is saved.

### Experiment Registry & Versioning

Every backtest, shadow run and paper-trading run is logged with a unique experiment ID that records: the code version, the strategy and pattern-library version, the data period and coin universe, the cost assumptions, the parameters used, whether Gemini was on or off, and the resulting metrics. Nothing is overwritten. This makes results reproducible, makes it obvious how many variants have been tried (important for judging overfitting), and lets the dashboard compare runs side by side. The final locked test period is run once and its experiment ID is recorded as such.

### Asset-Class Extensibility

Phase 1 is crypto only, on Binance, with a 5-coin watchlist. The design keeps exchange, data source and asset class behind common interfaces (the same middle layer used for backtest and live mode), so other assets such as stocks or other exchanges can be added later without rewriting the decision logic. Asset-specific details (trading hours, fees, margin rules, data sources) live in per-asset configuration. No other asset class, exchange or LLM is built in Phase 1; this note only guides interface design.

### Data Contract (Phase 1)

The shared file format between the agent system (writer) and the monitoring UI (reader). Plain JSON/JSONL, one file per data type; the UI is read-only in Phase 1.

| File | Format | Holds |
|---|---|---|
| agent_status.json | JSON | One row per agent: id, type, status (idle/working/paused/dormant), current task, last active time, mode (backtest/paper/live) |
| decisions.jsonl | JSONL, append-only | Every AND-gate evaluation: coin, News/Technical/Risk verdicts + reasoning, gate result (agree/conflict), LLM tie-breaker call + reasoning when conflicted |
| trades.jsonl | JSONL, append-only | Trade id, coin, direction, entry/exit, size, P&L (₹/%/R), status, close reason, linked decision id |
| news.jsonl | JSONL, append-only | Headline, source, publish time, coins tagged, type, score |
| backtest_runs.json | JSON | Run id, date range, cadence config used, results vs the hidden exam period |
| memory.json | JSON | Learned pattern library: pattern, evidence count, win rate, active/retired |

#### Rules

- Shared time fields. Every entry carries both simulated_time and wall_time, so backtest-mode logs and live-mode logs share one schema — consistent with the point-in-time backtest’s shared-interface design.
- Atomic writes. Temp file + rename, so the UI never reads a half-written file mid-write.
- Single writer, Phase 1. The agent system writes all six files; the UI only reads. Owner controls (writing back settings/pauses) are a later phase.

#### UI Stack

Built on React from the start, one single codebase across every phase, not a Phase 1 prototype that gets thrown away and rebuilt later. Phase 1’s dashboard is read-only (renders the six data-contract files above via a lightweight API layer, e.g. FastAPI); later phases (owner controls, Apply/Undo, live settings changes) extend that same React app rather than replacing it.

#### Pages

- Overview — mode, simulated/wall time, agent health at a glance, today’s P&L
- Agent Hierarchy — tree view, status per agent
- Decisions — the AND-gate feed, conflicts flagged, tie-breaker reasoning
- Trades — log + running P&L chart
- News & Research — scored feed
- Backtest Results — run history vs the hidden exam period
- Memory — pattern library

#### Market Data (Chart Feed)

Added to the Phase 1 data contract to support the live/replay chart and signal markers required in the BRD.

| File | Format | Holds |
|---|---|---|
| candles.json | JSON, one array per coin | OHLCV candles at the interval the Technical component evaluates, plus computed indicator values (trend line, breakout level) and a technical_signal flag per candle (buy/sell/short/null) — the raw feed the chart renders, with trades, decisions and news overlaid on top |

Chart linkage. Trades, decisions and news all carry the same coin + timestamp fields as candles, so the UI joins them by matching those keys directly — no separate linking table needed.

### Agent Memory Architecture — Approach 2: Per-Agent Separated Memory

An alternative to a single undifferentiated memory blob: one shared memory store, logically one place, but organized into separate partitions so each agent’s own learning stays distinct rather than pooled together.

- Team lead pattern library — each team lead (e.g. a hack-news team lead, a regulation team lead) keeps its own partition of proven patterns and evidence, separate from other team leads’ partitions.
- Cluster/coin notes — per-coin learned notes, kept separate from the team-lead partitions.
- Dormant leads — when a team lead goes dormant (no matching news for 3 weeks), its accumulated pattern library is parked here rather than wiped, so it resumes with full context on waking rather than starting cold.
- Refinement tasks — proposed learning updates (e.g. confidence cuts) awaiting owner approval, kept separate from settled, active patterns.

Worker agents (spun up for one task, e.g. reading one headline or one coin’s exposure) are disposable and do not get their own memory partition — they read from the relevant team lead’s partition and shared context, report back, and are torn down; only team leads carry persistent, partitioned memory across their lifecycle.

This is recorded as a second, distinct approach alongside the existing single shared-memory design above — not a replacement for it.

### Future Direction — Strategy / Pattern-Library Capability (Currently Inside Technical)

For now, classical chart-pattern and documented-strategy matching (e.g. head and shoulders, moving average crossovers, RSI divergence, and other book-sourced technical strategies) lives inside the existing Technical agent/check, alongside its current candlestick-pattern logic (engulfing, hammer/wick, breakout).

Noted for the future: this may be split out into its own separate, fourth agent running alongside News, Technical and Risk in the AND-gate — a dedicated Strategy/Pattern-Library agent that checks the current setup against a curated library of named, documented trading strategies, distinct from Technical’s more reactive in-the-moment price-action reading. This would change the gate from a three-way to a four-way check. Not yet implemented as a separate agent — recorded here as a planned future direction only.

### Historical Pattern-Weight Research (Supersedes the Separate Fourth-Agent Idea)

Instead of adding a fourth, separate “Strategy” agent to the AND-gate, the chosen approach is a dedicated historical research pipeline that feeds learned weights directly into the existing News and Technical agents, keeping the gate at three checks (News, Technical, Risk).

Pipeline:

- Aligned historical dataset — 10 to 20 years of price candles, news headlines, and detected candlestick/chart patterns, all matched up on one shared timeline (by coin and timestamp).
- Pattern-plus-news combination analysis — a statistical or model-based study that asks, for every pattern-plus-news-type combination, what the actual forward return was historically when that combination occurred, and how consistent that result was.
- Weight and confidence per combination — each combination gets a numeric weight (how much it should count) and a confidence level, conditioned on context where relevant (e.g. only strong during high-volume periods, only alongside certain news categories, or only for certain coins) — not a flat, one-size-fits-all importance score.
- Stored in the pattern library — these weights live in the same shared memory/pattern-library structure already used for team lead patterns and coin notes.
- Applied at scoring time — when News scores a headline or Technical detects a pattern, its raw score is multiplied/adjusted by the historically-learned weight for that combination before the result is passed into the AND-gate.

Effect: this replaces the earlier fourth-agent idea (a separate Strategy/Pattern-Library agent voting in the gate) — the gate itself stays a three-way check, but each of News and Technical becomes historically weighted rather than treating every pattern or headline type as equally important. The dedicated Technical Future Direction note above (a possible fourth agent) is superseded by this approach.

## Appendix A — Changes since version 1, decisions taken while building, and open gaps

Updated 7 October 2026. Version 1 (22 September 2026, "Stock Trading Agent — BRD, SDD & TDD") was written for stocks first. This appendix records what version 2 removed or replaced from version 1, the decisions taken while building that the main text does not yet show, and what is still missing. Where this appendix and the main text differ, this appendix is the more recent.

### A.1 Removed or replaced from version 1

| Area | Version 1 (22 Sep) | Now (version 2 + build) |
|---|---|---|
| Market | Stocks first, extensible to crypto; per-stock snapshots | Crypto only, on Binance; per-coin snapshots. Stock exchanges, tickers and stock data sources are out of scope |
| Example news desks | Earnings lead, Regulatory lead, Social-Sentiment lead | Protocol-Events (upgrades, unlocks, halvings), Regulatory, Social-Sentiment; built as 8 desks (see A.2) |
| News sources | NewsAPI, Alpha Vantage, Finnhub; exchange feeds for filings and earnings; Reddit r/WallStreetBets | CryptoPanic, CryptoCompare, NewsAPI crypto; Binance/Coinbase announcements; X and Reddit (r/CryptoCurrency, r/Bitcoin). Finnhub and Alpha Vantage kept as extra sources |
| Decision model | In-house ~30–40B open model: supervised fine-tuning, reinforcement learning on profit with a calibration (honest confidence) reward, quantization; benchmark against Jev | No in-house model and no training. Gemini is the live tie-breaker when News / Technical / Risk disagree (decision call + later review call). The training code stays in the repository, unused |
| Automated retraining | Weekly extraction, training after ~1,000 trades on a rented GPU, deploy only if better, post-deployment monitoring | Removed. Replaced by the hold-pattern analysis pipeline and pattern-library rules (candidate → validated → production → retired) |
| Jev | Long-term goal: pitch the in-house model to leadership as a Jev replacement | Removed. Jev is not used, and there is no replacement model |
| Training example format | Context block + question with a fixed list of answers + answer with a 0–1 confidence | Kept as the fixed prompt shape for Gemini (context + similar past cases + question + fixed answer shape) |
| Historical data | FNSPID (free, stock news + prices) and FirstRate Data (paid intraday stock prices), ~20 years, used as training labels | Binance klines only (crypto). Used for the point-in-time backtest and pattern-weight research, not for training. Binance data starts in 2017 (about 8–9 years, not 10–20) |
| Data-quality check | Spot-check ~100 news/price pairs against an independent source (e.g. Yahoo Finance); use two providers | Binance is the single source of truth. Internal-consistency check of ~100 samples; more than 3% defects fails |
| Success criteria | Paper trading validates; the model beats Jev on accuracy, speed and cost | Net profit per trade after all costs, maximum drawdown 3% of equity, beat simple baselines, show each component's contribution, six staged gates |
| Testing order | Paper trading / testnet (~1 month) first | Time-machine backtest → shadow mode → paper trading → small real money |
| Trade directions | Buy / sell / hold (spot) | Long and short; shorts need a futures/margin account with liquidation and funding-rate risk |
| Cadence constraint | Live data vs periodic model-retraining batches | Live data vs periodic research / pattern-discovery batches |
| Open questions | Snapshot source, spawn approval, watch-state aging, worker redundancy: open | Answered in the SDD (Orchestrator-pushed view; manager proposes, owner approves; 2 h default with overrides; desks sleep after 3 weeks) |

### A.2 Decisions taken while building (not yet in the main text)

| Topic | Decision |
|---|---|
| Coins | Five: BTC, ETH, SOL, BNB and XRP (USDT pairs) |
| Reading the news | Gemini scores every headline (direction, size, confidence). One model with written instructions per desk replaces "a differently tuned sentiment model per team lead". Keyword scoring if no key or a call fails. No local or open-source news model |
| Desks built | News: listings, regulation, hacks & security, macro economy, big buyers/sellers, tech upgrades, social media, general (Gemini proposes new desks; I approve them). Price: trend, momentum, candle patterns. Risk: event risk (hacks, delistings), market mood, wild swings |
| Routing | Desk fingerprints are Gemini embeddings; unclear headlines go to a Gemini routing call (at most 20 per cycle). Desks remember fingerprints and sleeping state across restarts |
| The brain | Every news, chart and risk signal is recorded and checked against the price 1 and 3 days later. Scorecards show hit rate, the rate the price moved that way anyway, and the edge; proven signals get a trust weight between 0.5 and 1.5. This is the first version of the historical pattern-weight research |
| Brain first | Trading is switched off (Settings → Trading) while the brain learns; open trades keep their stop-losses |
| No old news archive | The time machine and the edge check use prices only. The best free archive (CoinDesk 2019–2025) is licensed for non-commercial use only, and the other free one has dates without times. News is learned from the system's own live collection, and tested in shadow mode and paper trading |
| Market mood filter | Buy only while Bitcoin is above its 200-day average; short only while it is below |
| Short-selling rules | At most 2 shorts open, never during wild swings, no borrowing beyond own equity, same ₹ risk and stop-loss. Paper only until Binance Futures is connected |
| Open-trade limit | At most 5 trades open at once |
| Daily stop | 2% (the lower end of 2–3%): no new trades for the rest of the UTC day; open trades keep their stop-losses; kept across restarts |
| Accounts | Paper account $1,000 (≈ ₹88,000); planned real start $2,000. Which one the 3% drawdown rule is judged against is still to decide |
| Backtest costs | 0.1% fee per side, half the bid-ask spread (0.02%) per side, slippage 0.05% per side (up to 3× in wild markets), short funding 0.03% per day, every fill one candle late |
| Exam period | The last 365 days are the locked final test; safety variants are chosen on earlier years only and then tested once |
| Survivorship test | Each month, the 5 most traded coins from a list that includes later-collapsed ones (e.g. LUNA, FTT) |
| Candles | Price rules work on finished daily candles |
| Replay cadence | The time machine runs the research team every simulated day (more often than the weekly / monthly / quarterly batches in the TDD; a full replay takes minutes) |
| Owner controls | Built early: pause/resume, strictness, written instructions, stop watching a coin, approve new desks, Apply / History / Undo (the TDD planned these for after Phase 1) |
| Hosting | Oracle Cloud, India region; website private by default (SSH tunnel), optional HTTPS through Caddy |
| Confidence check (kept from version 1) | Every Gemini answer comes with a confidence (0–1). Each answer is stored with what really happened (Binance price at trade end). Answers are grouped by stated confidence (50–60%, 60–70%, …) and each group's stated confidence is compared with how often it was really right; the overall Brier score is compared with "always 50%". Once a group has 20–30 cases, Gemini's confidence is corrected to the measured rate before the system uses it. If Gemini's confidence is no better than "always 50%", conflicts default to hold. The same check runs on the news scores (confidence per desk). Measured first in shadow mode, shown on the Brain page. In version 1 this was a training reward; now it is a measurement and correction |

### A.3 Findings so far (6 October 2026)

| Test | Result |
|---|---|
| Time machine (prices only, exam Oct 2025 → Oct 2026) | Chart and risk signals alone were right 50% of the time, the same as chance: no edge without news |
| Edge check, live rules (max 5 open, 2 short, daily stop 2%) | +53 R (≈ +₹13,300) in the exam year over 66 trades, after all costs; beats just holding (−101 R), momentum (−6 R) and moving average (+45 R); robust to doubled costs, market types and coins. Fails only the 3% drawdown on a $1,000 account (4.5%); it would be 2.2% on $2,000 |
| Fewer open trades (3 open, 1 short) | Drawdown 2.9%, but profit falls to +21 R, below the moving-average baseline. Not adopted |
| Dip brake (pause 7 days after a 2.5% dip) | No smaller drawdown in the exam, and a loss with doubled costs. Not adopted |
| Daily stop | Never triggered in the exam year (worst single day ≈ 1%): it protects against crash days, not slow slides |

### A.4 Still missing (gaps against version 2)

| Area | What is missing |
|---|---|
| Gemini tie-breaker | Decision call, review call, case library, minimum similar cases (20–30), 2–3 s timeout → hold, hold-event records, hold-pattern analysis, pattern lifecycle |
| Safety switches | Stale-data, exchange-mismatch, exchange-degraded, strategy-anomaly and infrastructure circuit breakers; order-status reconciliation after unclear replies; stop-loss orders placed on the exchange; risk recorded as % of equity; Binance-down fallback steps |
| Futures | Binance Futures connection for real shorts, liquidation and funding-rate monitoring |
| Shadow mode | Not built |
| Website | Signal / trade / news markers on the chart (including vetoed signals), trade drill-down, Decisions page, Backtest Results page, stale-data banner; refresh rates (Agents 5 s) to check |
| Data contract | decisions.jsonl, simulated_time + wall_time on every entry, candles.json; experiment results are in experiments.jsonl rather than backtest_runs.json |
| Full system on history | Not possible without dated old news (see A.2); measured going forward |
| Watch-state calibration | Aging windows per news type to be calibrated from paper trading |
| Confidence check | Decided to keep (see A.2); not built yet. Part of the Gemini tie-breaker work |
| Independent price check | Version 1 cross-checked prices against a second source; version 2 dropped this (Binance only). Accepted risk |
| Tests | The TDD's "129 passing" is now 154 automated tests |


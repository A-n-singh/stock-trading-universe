# stock-trading-universe

An AI-driven trading agent for stocks, built so it can extend to crypto. It has two loops:

- **Slow research loop.** Orchestrator → Domain Managers → Team Leads → Workers → Cluster Agents. It runs continuously in the background and produces a per-symbol **snapshot**: direction bias, confidence, risk flags and a timestamp.
- **Fast loop (the Trading Agent).** It runs in parallel to the research loop. It only reads snapshots and never researches. It trades only when the **News, Technical and Risk** checks all agree (the AND-gate).

This repo holds the Phase 1 core from the BRD, SDD and TDD. It runs in paper-trading mode by default.

## Layout

| Module | Covers (doc reference) |
|---|---|
| `trading_agent/agent.py` | Tick loop, freshness check, AND-gate, stop-loss and reversal exits (SDD: Two-Loop Architecture; TDD: Execution Logic) |
| `trading_agent/news.py`, `technical.py`, `risk.py` | The three execution-only gate checks. `risk.py` enforces the **₹200–300 per-trade risk budget** |
| `trading_agent/watch.py` | Watch state. A news hypothesis is held until price confirms it or it ages out, with a window per (sector, event type) |
| `execution/broker.py` | `Broker` protocol and `PaperBroker` (slippage, fees, idempotent `client_order_id`) |
| `execution/resilient.py` | Token-bucket rate limiter, retry with backoff, circuit breaker. Stop-loss exits bypass the limiter and breaker |
| `trade_log.py` | Append-only JSONL log of the snapshot, rationale, votes and outcome, plus scoped `refinement_tasks` (SDD: Mistake-loop closure) |
| `training/schema.py` | Three-part training example: context / question with fixed answers / output as {answer, confidence} (TDD) |
| `training/calibration.py` | Profit reward plus a Brier calibration term. Being overconfident and wrong costs more (TDD) |
| `training/retraining.py` | Pull new trades from the log → wait for N new ones → train → test on held-out recent trades → promote the new model only if it beats the live one |
| `training/data_quality.py` | Spot-checks about 100 historical news/price pairs against an independent price source |
| `memory/` | **Shared memory**: one library, one shelf per agent. A diary of events (`event_log.py`), team-lead lessons and per-stock notes (`shared.py`), and a throwaway worker scratchpad. Details below |
| `research/team_leads.py` | Routes tasks to team leads by embedding similarity, calls the LLM only below the threshold, needs domain-manager approval to spawn a lead, and handles dormancy and rehydration |

## Shared memory in plain words

Think of it as one library that every agent uses:

- **Diary** (`EventLog`): everything that happened, written once and never edited.
- **Team lead shelf**: general lessons such as "earnings beats usually push the price up". A lesson must cite at least two real diary events as proof.
- **Stock shelf**: notes about one stock. They point to team-lead lessons instead of copying them.
- **Scratchpad**: a worker's rough notes for one task, thrown away afterwards.

Rules the code enforces:

1. **Read anything, write only your own shelf.** `memory.for_agent("earnings-lead", writes={"earnings-lead"})`. Writing anywhere else raises `PermissionError`.
2. **No peeking into the future.** Every read takes `as_of`. When the agent practises on 2020 data, it cannot see a lesson learned in 2022.
3. **Only proven lessons.** Real trade results are recorded against each lesson. A lesson that keeps losing is retired automatically, but it stays visible when replaying earlier dates.
4. **Same lesson twice is merged**, not saved as a duplicate.
5. **The Trading Agent never uses memory.** It reads only the snapshot, and a test checks this.
6. When a team lead goes idle, its shelf goes dormant with it. It comes back when a similar task appears.

The default embedder and vector store need no extra packages. Sentence-transformers or Chroma can replace them behind the same interfaces (`memory/vectors.py`).

## Guarantees enforced in code

- `RiskConfig` refuses any `risk_per_trade` outside ₹200–300. Sizing is `floor(budget / |entry − stop|)` and is capped by the position fraction and by cash. The risk check also re-verifies the ₹300 ceiling before it approves.
- A snapshot that is stale or missing (15 min for stocks, 5 min for crypto) means the agent skips that symbol. It never falls back to research.
- A single signal is never enough, even a very confident one. All three votes must approve.
- An exchange failure means graceful degradation: the tick reports `degraded` and retries later. It never crashes and never sends duplicate orders.
- `paper_trading=True` by default. Short selling is off by default.

## Run the tests

```bash
pip install -e '.[dev]'
pytest
```

## Minimal usage

```python
from trading_universe.config import AgentConfig
from trading_universe.execution.broker import PaperBroker
from trading_universe.execution.resilient import ResilientExecutor
from trading_universe.trade_log import TradeLog
from trading_universe.trading_agent.agent import TradingAgent

agent = TradingAgent(AgentConfig(), ResilientExecutor(PaperBroker()), TradeLog("runs/trades.jsonl"))
report = agent.tick(snapshots, market_data, now)   # snapshots come from the Orchestrator
```

## Not built yet (next steps)

- LLM-backed Orchestrator, Domain Managers, Workers and Cluster Agents. Team-lead routing and the shared memory exist; the LLM agents that read and write that memory do not yet.
- Data connectors: NewsAPI, Alpha Vantage, Finnhub, exchange filings, X and Reddit, FNSPID, FirstRate Data, and a live broker adapter (for example Zerodha Kite) or a crypto exchange testnet.
- The actual SFT → RL → quantization job for the ~30–40B decision model. `Trainer` is only an interface.
- Calibrating the watch-state windows and snapshot freshness limits from Phase 1 paper-trading data. The current values are placeholders.
- Open questions from the SDD: where snapshots come from, who approves spawning a team lead, whether aging is per-category or a global default, and what triggers worker redundancy.

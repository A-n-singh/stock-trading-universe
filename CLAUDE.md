# Notes for Claude

- The user prefers explanations in simple, everyday language.
- The project is built for **crypto only** (Binance). No stocks or stock exchanges: don't plan, suggest or build
  stock features (decided 27 Sep 2026).
- Ask the user before changing or saving anything in the repository; show screenshots of website changes first.
- The BRD/SDD/TDD must be fully covered (for crypto). The current version is `docs/BRD_SDD_TDD_v2.docx`
  (text copy `docs/BRD_SDD_TDD_v2.md`). Check new work against it point by point.
- Read `ROADMAP.md` at the start of a session. It holds the findings so far and the agreed next steps.
  When the user asks to "recall" the points or next steps, answer from it, and keep it updated when new
  findings or decisions come up.
- Run tests with `python -m pytest -q` (needs `pip install -e '.[backtest,research,web,dev]'`).
- The website is React in `web/` (`npm run build`, typecheck with `npx tsc -b`) served by `python -m trading_universe.api`.

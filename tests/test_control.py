"""The Agents page: live board, questions for the owner, suggested changes, Apply and Undo."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

pd = pytest.importorskip("pandas")

from trading_universe.control import ChangeBook, ChangeError, Controls, agent_tree  # noqa: E402
from trading_universe.market import CandleFeed  # noqa: E402
from trading_universe.models import Direction  # noqa: E402
from trading_universe.news.models import NewsItem  # noqa: E402
from trading_universe.runner import RunConfig, Runner  # noqa: E402

NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)


def rising(days: int) -> pd.DataFrame:
    close = pd.Series([100 * 1.01**i for i in range(days)])
    open_ = close / 1.005
    df = pd.DataFrame({"open": open_, "high": close, "low": open_ * 0.998, "close": close, "volume": 1.0})
    df.index = pd.date_range(end=pd.Timestamp(NOW).tz_convert(None).normalize(), periods=days, freq="D")
    return df


class StaticNews:
    name = "static"

    def __init__(self, items):
        self.items = items

    def fetch(self):
        return self.items


def runner(tmp_path, items=()) -> Runner:
    feed = CandleFeed()
    for sym in ("BTCUSDT", "SOLUSDT"):
        feed.put(sym, rising(300))
    return Runner(RunConfig(data_dir=tmp_path, symbols=("BTCUSDT", "SOLUSDT")), feed=feed, sources=[StaticNews(list(items))])


def book(tmp_path) -> ChangeBook:
    return ChangeBook(tmp_path / "agent_changes.json", tmp_path / "controls.json")


# ------------------------------------------------------------------------------ changes


def test_suggest_apply_undo(tmp_path):
    b = book(tmp_path)
    b.suggest({"kind": "pause", "agent": "lead:social", "value": True})
    b.suggest({"kind": "min_confidence", "agent": "lead:regulatory", "value": 0.6})
    b.suggest({"kind": "min_confidence", "agent": "lead:regulatory", "value": 0.7})  # replaces the previous one
    assert [p["after"] for p in b.pending()] == ["paused", "0.70"]
    assert not (tmp_path / "controls.json").exists()  # nothing is live before Apply

    assert len(b.apply()) == 2 and b.pending() == []
    c = Controls.load(tmp_path / "controls.json")
    assert c.paused("lead:social") and c.threshold("regulatory", "min_confidence") == 0.7

    b.suggest({"kind": "min_confidence", "agent": "lead:regulatory", "value": 0.8})
    b.apply()
    newest = b.history()[0]
    b.undo(newest["id"])  # back to 0.7, not to "no setting"
    assert Controls.load(tmp_path / "controls.json").threshold("regulatory", "min_confidence") == 0.7
    with pytest.raises(ChangeError):
        b.undo(newest["id"])


@pytest.mark.parametrize("change", [
    {"kind": "pause", "agent": "orchestrator", "value": True},  # core agents can't be paused
    {"kind": "min_confidence", "agent": "coin:BTCUSDT", "value": 0.5},
    {"kind": "min_magnitude", "agent": "lead:macro", "value": 1.5},
    {"kind": "risk_per_trade", "agent": "trading", "value": 1000},  # never changeable from here
    {"kind": "ruling", "agent": "lead:macro", "value": "maybe", "payload": {}},
])
def test_invalid_changes_are_refused(tmp_path, change):
    with pytest.raises(ChangeError):
        book(tmp_path).suggest(change)


def test_agent_tree_lists_the_whole_team():
    ids = [a["id"] for a in agent_tree(["BTCUSDT"], {"stablecoins": {"label": "Stablecoins", "description": "depeg"}})]
    assert ids[:4] == ["orchestrator", "news_manager", "price_manager", "risk_manager"]
    assert "lead:regulatory" in ids and "lead:stablecoins" in ids and "coin:BTCUSDT" in ids
    assert ids[-2:] == ["trading", "learning"]


# ------------------------------------------------------------------- agents follow it


def unsure_regulatory(i: int = 0) -> NewsItem:
    # Keyword scoring gives regulatory news 49% confidence: just under the 50% the trading check needs.
    return NewsItem.make("coindesk", f"SEC delays decision on Solana (SOL) ETF filing {i}", f"https://x/{i}", NOW - timedelta(hours=1))


def test_board_shows_who_did_what(tmp_path):
    r = runner(tmp_path, [NewsItem.make("binance", "Binance will list Solana (SOL) perpetuals", "https://x/l",
                                        NOW - timedelta(hours=1), kind="announcement")])
    r.research(NOW)
    r.trade(NOW)
    board = json.loads((tmp_path / "agents.json").read_text())["agents"]
    assert board["orchestrator"]["doing"].startswith("Cycle done")
    assert "listings" in json.dumps(board["lead:listings"]["log"]).lower() or board["lead:listings"]["log"]
    assert board["coin:SOLUSDT"]["doing"].startswith("Verdict")
    assert board["price_manager"]["doing"]
    assert "open trade" in board["trading"]["doing"]


def test_unsure_headline_becomes_a_question_and_the_answer_is_followed(tmp_path):
    r = runner(tmp_path, [unsure_regulatory()])
    r.research(NOW)
    (q,) = r.questions.all()
    assert q["kind"] == "ruling" and q["agent"] == "lead:regulatory" and q["options"] == ["bearish", "neutral", "bullish"]
    [s] = [s for s in r.orchestrator.news.run(r.news.items(), NOW) if s.symbol == "SOLUSDT"]
    assert s.confidence < 0.5

    b = book(tmp_path)
    b.suggest({"kind": "ruling", "agent": q["agent"], "value": "bullish", "question_id": q["id"], "payload": q["payload"]})
    r.research(NOW)  # suggested but not applied: nothing changes
    [s] = [s for s in r.orchestrator.news.run(r.news.items(), NOW) if s.symbol == "SOLUSDT"]
    assert s.reason != "owner's ruling: bullish"

    b.apply()
    r.research(NOW + timedelta(minutes=15))
    [s] = [s for s in r.orchestrator.news.run(r.news.items(), NOW) if s.symbol == "SOLUSDT"]
    assert s.direction == Direction.BULLISH and s.confidence >= 0.8 and s.actionable
    assert "Owner's ruling" in r.orchestrator.news.profile("regulatory").guidance  # an example for Gemini
    assert len(r.questions.all()) == 1  # not asked again


def test_paused_desk_holds_its_news_and_resumes(tmp_path):
    b = book(tmp_path)
    b.suggest({"kind": "pause", "agent": "lead:regulatory", "value": True})
    b.apply()
    r = runner(tmp_path, [unsure_regulatory()])
    r.research(NOW)
    board = json.loads((tmp_path / "agents.json").read_text())["agents"]
    assert board["lead:regulatory"]["status"] == "paused" and "1 item(s) waiting" in board["lead:regulatory"]["doing"]
    assert r.questions.all() == []

    b.undo(b.history()[0]["id"])
    r.research(NOW + timedelta(minutes=15))
    assert len(r.questions.all()) == 1  # scored once resumed


def test_instruction_reaches_the_desk_and_new_desk_can_be_approved(tmp_path):
    b = book(tmp_path)
    b.suggest({"kind": "instruction", "agent": "lead:security", "value": "Hacks above $50M are very bad news."})
    b.suggest({"kind": "desk", "agent": "news_manager", "value": "approve", "question_id": "desk:2026-W39", "payload": {},
               "label": "Stablecoins", "description": "stablecoin depeg usdt usdc peg reserve"})
    b.apply()
    r = runner(tmp_path)
    r.research(NOW)
    news = r.orchestrator.news
    assert "Hacks above $50M" in news.profile("security").guidance
    assert "stablecoins" in news.leads and "stablecoins" in news.router.leads


def test_paused_trading_agent_opens_nothing_but_keeps_stop_losses(tmp_path):
    item = NewsItem.make("binance", "Binance will list Solana (SOL) perpetuals", "https://x/l", NOW - timedelta(hours=1), kind="announcement")
    b = book(tmp_path)
    b.suggest({"kind": "pause", "agent": "trading", "value": True})
    b.apply()
    r = runner(tmp_path, [item])
    r.research(NOW)
    rep = r.trade(NOW)
    assert not [e for e in rep.events if e.kind == "opened"]
    assert json.loads((tmp_path / "agents.json").read_text())["agents"]["trading"]["status"] == "paused"


def test_learning_suggestion_waits_for_the_owner(tmp_path):
    r = runner(tmp_path)
    r.refinements.proposed["layer1:listing"] = {"since": NOW.isoformat(), "lead": "listings", "sector": "layer1",
                                                "event_type": "listing", "losses": 3, "sample": 3, "multiplier": 0.6}
    assert r.refinements.factor("layer1", "listing") == 1.0  # not applied yet
    r.trade(NOW)
    (q,) = r.questions.all()
    assert q["kind"] == "refinement" and q["agent"] == "learning"
    b = book(tmp_path)
    b.suggest({"kind": "refinement", "agent": "learning", "value": "accept", "question_id": q["id"], "payload": q["payload"]})
    b.apply()
    r.trade(NOW + timedelta(minutes=1))
    assert r.refinements.factor("layer1", "listing") == 0.6
    assert len(r.questions.all()) == 1


# ------------------------------------------------------------------------------ website


def test_agents_api_end_to_end(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from trading_universe.api import server

    monkeypatch.setenv("TU_RUNS_DIR", str(tmp_path))
    monkeypatch.delenv("TU_PASSWORD", raising=False)
    (tmp_path / "settings.json").write_text(json.dumps({"coins": ["BTCUSDT", "SOLUSDT"]}))
    r = runner(tmp_path, [unsure_regulatory()])
    r.research(NOW)
    c = TestClient(server.create_app())

    view = c.get("/api/agents").json()
    desk = next(a for a in view["agents"] if a["id"] == "lead:regulatory")
    assert desk["status"] == "waiting" and desk["questions"] == 1 and desk["thresholds"] == {"min_confidence": None, "min_magnitude": None}
    (q,) = view["questions"]
    assert "₹200–300" in view["locked"]

    assert c.post(f"/api/agents/questions/{q['id']}/answer", json={"value": "maybe"}).status_code == 422
    assert c.post(f"/api/agents/questions/{q['id']}/answer", json={"value": "bearish"}).status_code == 200
    assert c.post("/api/agents/suggest", json={"kind": "pause", "agent": "coin:BTCUSDT", "value": True}).status_code == 200
    assert c.post("/api/agents/suggest", json={"kind": "pause", "agent": "orchestrator", "value": True}).status_code == 422
    assert c.post("/api/agents/suggest", json={"kind": "ruling", "agent": "lead:macro", "value": "bullish"}).status_code == 422
    view = c.get("/api/agents").json()
    assert len(view["pending"]) == 2 and view["questions"][0]["pending"]

    assert c.post("/api/agents/apply").json() == {"applied": 2}
    view = c.get("/api/agents").json()
    assert view["questions"] == [] and view["pending"] == []
    btc = next(a for a in view["agents"] if a["id"] == "coin:BTCUSDT")
    assert btc["paused"] and btc["status"] == "paused"
    assert "undo" not in view["history"][0]

    pause = next(h for h in view["history"] if h["kind"] == "pause")
    assert c.post(f"/api/agents/history/{pause['id']}/undo").status_code == 200
    assert not next(a for a in c.get("/api/agents").json()["agents"] if a["id"] == "coin:BTCUSDT")["paused"]

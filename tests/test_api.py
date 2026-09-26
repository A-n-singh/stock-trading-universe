from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
pd = pytest.importorskip("pandas")

from fastapi.testclient import TestClient  # noqa: E402

from trading_universe.api import server  # noqa: E402
from trading_universe.backtest.data import synthetic_prices  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TU_RUNS_DIR", str(tmp_path))
    monkeypatch.delenv("TU_PASSWORD", raising=False)
    monkeypatch.setattr(server, "prices", lambda market, symbol, interval="1d", start="2020-01-01":
                        synthetic_prices(5 * 365, seed=sum(map(ord, symbol)), drift=0.003, vol=0.01))
    return TestClient(server.create_app())


def test_markets_and_candles(client):
    r = client.get("/api/markets", params={"symbols": "BTCUSDT,ETHUSDT"}).json()
    assert [i["symbol"] for i in r["items"]] == ["BTCUSDT", "ETHUSDT"]
    assert r["items"][0]["mood"] in ("rising", "falling") and len(r["items"][0]["spark"]) == 90
    c = client.get("/api/candles/BTCUSDT", params={"days": 60}).json()
    assert 55 <= len(c["candles"]) <= 62 and c["trend"] and isinstance(c["buys"], list)
    assert set(c["candles"][0]) == {"time", "open", "high", "low", "close", "volume"}


def test_settings_roundtrip_and_validation(client, tmp_path):
    s = client.get("/api/settings").json()
    assert s["risk_per_trade_inr"] == 250
    s["risk_per_trade_inr"] = 280
    assert client.put("/api/settings", json=s).status_code == 200
    assert json.loads((tmp_path / "settings.json").read_text())["risk_per_trade_inr"] == 280
    s["risk_per_trade_inr"] = 1000  # business rule: ₹200-300 only
    assert client.put("/api/settings", json=s).status_code == 422
    s["risk_per_trade_inr"], s["triggers"] = 250, []
    assert client.put("/api/settings", json=s).status_code == 422


def test_backtest_endpoint(client):
    pytest.importorskip("vectorbt")
    r = client.post("/api/backtest", json={"symbols": ["BTCUSDT", "ETHUSDT"], "min_trades": 5}).json()
    assert r["settings_tested"] == 525 and r["rows"] and r["rows"][-1]["rank"] == "current"
    assert r["curves"] and r["curves"][0]["points"][0]["value"] == 0.0
    assert set(r["hold_returns"]) == {"BTCUSDT", "ETHUSDT"} and r["rows"][0]["hold_r"] is not None
    r = client.post("/api/backtest", json={"symbols": ["BTCUSDT"], "min_trades": 5, "shorts": True}).json()
    assert r["settings_tested"] == 525
    assert client.post("/api/backtest", json={"symbols": ["BTCUSDT"], "shorts": True, "market_filter": False}).status_code == 422


def test_empty_state_endpoints(client):
    assert client.get("/api/snapshots").json() == {}
    assert client.get("/api/news").json() == []
    assert client.get("/api/trades").json() == []
    assert client.get("/api/status").json() == {}
    assert "Roadmap" in client.get("/api/roadmap").json()["markdown"]


def test_password_protects_the_api(tmp_path, monkeypatch):
    monkeypatch.setenv("TU_RUNS_DIR", str(tmp_path))
    monkeypatch.setenv("TU_PASSWORD", "correct horse")
    c = TestClient(server.create_app())
    assert c.get("/api/health").status_code == 200  # uptime checks still work
    assert c.get("/api/auth").json() == {"required": True, "logged_in": False}
    assert c.get("/api/status").status_code == 401
    assert c.put("/api/settings", json={}).status_code == 401
    assert "swagger" not in c.get("/docs").text.lower()  # no API docs page for strangers
    assert c.post("/api/login", json={"password": "wrong"}).status_code == 401
    r = c.post("/api/login", json={"password": "correct horse"})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert c.get("/api/auth").json()["logged_in"] and c.get("/api/status").status_code == 200
    c.post("/api/logout")
    assert c.get("/api/status").status_code == 401
    # A forged or expired cookie doesn't work.
    c.cookies.set("tu_session", "9999999999.deadbeef")
    assert c.get("/api/status").status_code == 401


def test_login_lockout_and_expiry():
    from trading_universe.api.auth import Auth

    t = [1000.0]
    a = Auth(password="pw", session_days=1, secret="", clock=lambda: t[0])
    for _ in range(5):
        assert not a.check_password("1.2.3.4", "guess")
    assert a.locked("1.2.3.4") and not a.locked("5.6.7.8")
    t[0] += 16 * 60
    assert not a.locked("1.2.3.4")
    token = a.issue()
    assert a.valid(token)
    assert not Auth(password="new", secret="", clock=lambda: t[0]).valid(token)  # password change logs out
    t[0] += 86400 + 1
    assert not a.valid(token)

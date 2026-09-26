from __future__ import annotations

import hashlib
import hmac
import json
import urllib.parse

import pytest

from trading_universe.execution.binance import LIVE, BinanceBroker
from trading_universe.execution.broker import BrokerError, OrderRequest, TransientBrokerError
from trading_universe.models import Action

INFO = {"symbols": [{"filters": [
    {"filterType": "LOT_SIZE", "stepSize": "0.00001000", "minQty": "0.00001000"},
    {"filterType": "NOTIONAL", "minNotional": "5.00000000"},
]}]}


class FakeBinance:
    def __init__(self, order_status=200):
        self.calls, self.orders, self.order_status = [], {}, order_status

    def __call__(self, method, url, headers, body):
        path = urllib.parse.urlparse(url).path
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query or (body or b"").decode()))
        self.calls.append((method, path, q, headers))
        if path == "/api/v3/exchangeInfo":
            return 200, json.dumps(INFO).encode()
        if path == "/api/v3/order" and method == "GET":
            o = self.orders.get(q["origClientOrderId"])
            return (200, json.dumps(o).encode()) if o else (400, b'{"code":-2013,"msg":"Order does not exist."}')
        if path == "/api/v3/order" and method == "POST":
            if self.order_status != 200:
                return self.order_status, b'{"code":-1003,"msg":"Too many requests"}'
            qty = float(q["quantity"])
            o = {"status": "FILLED", "executedQty": q["quantity"], "cummulativeQuoteQty": str(qty * 84000),
                 "fills": [{"price": "84000", "qty": q["quantity"], "commission": "0.0000001", "commissionAsset": "BTC"}]}
            self.orders[q["newClientOrderId"]] = o
            return 200, json.dumps(o).encode()
        if path == "/api/v3/account":
            return 200, json.dumps({"balances": [{"asset": "USDT", "free": "1234.5", "locked": "0"}]}).encode()
        return 404, b"{}"


def broker(fake):
    return BinanceBroker("key", "secret", http=fake, clock=lambda: 1_700_000_000.0)


def test_market_order_is_signed_rounded_and_filled():
    fake = FakeBinance()
    b = broker(fake)
    fill = b.place_order(OrderRequest("BTCUSDT:s1:buy", "BTCUSDT", Action.BUY, 0.00169876, 84000))
    method, path, q, headers = next(c for c in fake.calls if c[0] == "POST")
    assert headers["X-MBX-APIKEY"] == "key" and q["type"] == "MARKET" and q["side"] == "BUY"
    assert q["quantity"] == "0.00169"  # rounded down to the 0.00001 step
    unsigned = urllib.parse.urlencode({k: v for k, v in q.items() if k != "signature"})
    assert q["signature"] == hmac.new(b"secret", unsigned.encode(), hashlib.sha256).hexdigest()
    assert fill.quantity == pytest.approx(0.00169) and fill.price == pytest.approx(84000)
    assert fill.fee == pytest.approx(0.0000001 * 84000)
    assert b.positions() == {"BTCUSDT": pytest.approx(0.00169)}
    assert b.cash() == 1234.5


def test_retry_with_same_client_id_never_orders_twice():
    fake = FakeBinance()
    b = broker(fake)
    o = OrderRequest("BTCUSDT:s1:buy", "BTCUSDT", Action.BUY, 0.001, 84000)
    b.place_order(o)
    b2 = broker(fake)  # e.g. after a restart
    b2.place_order(o)
    assert sum(1 for c in fake.calls if c[0] == "POST") == 1


def test_too_small_orders_and_throttling():
    b = broker(FakeBinance())
    with pytest.raises(BrokerError, match="too small"):
        b.place_order(OrderRequest("x", "BTCUSDT", Action.BUY, 0.00002, 84000))  # $1.68 < $5 minimum
    with pytest.raises(TransientBrokerError):
        broker(FakeBinance(order_status=429)).place_order(OrderRequest("y", "BTCUSDT", Action.BUY, 0.001, 84000))


def test_real_money_needs_explicit_opt_in():
    with pytest.raises(ValueError, match="real money"):
        BinanceBroker("k", "s", base_url=LIVE)
    BinanceBroker("k", "s", base_url=LIVE, live=True)

"""Binance spot broker (signed REST). Defaults to the TESTNET, which uses fake money.

Keys come from the environment, never from code or notebooks:
  BINANCE_API_KEY / BINANCE_API_SECRET      (testnet keys: https://testnet.binance.vision)
  BINANCE_BASE_URL                          default https://testnet.binance.vision
Real money needs BINANCE_BASE_URL=https://api.binance.com AND live=True in code - both on purpose.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

from ..models import Action, utcnow
from .broker import BrokerError, Fill, OrderRequest, TransientBrokerError

TESTNET = "https://testnet.binance.vision"
LIVE = "https://api.binance.com"

Http = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]


def _urllib_http(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


@dataclass(frozen=True)
class SymbolRules:
    step: float  # quantity must be a multiple of this (LOT_SIZE / MARKET_LOT_SIZE)
    min_qty: float
    min_notional: float


@dataclass
class BinanceBroker:
    api_key: str
    api_secret: str
    base_url: str = TESTNET
    live: bool = False
    quote: str = "USDT"
    http: Http = _urllib_http
    clock: Callable[[], float] = time.time
    recv_window_ms: int = 5000
    # Positions this agent opened (a testnet account starts with coins it didn't buy).
    _positions: dict[str, float] = field(default_factory=dict)
    _rules: dict[str, SymbolRules] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.base_url.rstrip("/") == LIVE and not self.live:
            raise ValueError("refusing to trade real money: pass live=True explicitly to use api.binance.com")

    @classmethod
    def from_env(cls, live: bool = False) -> BinanceBroker:
        key, secret = os.environ.get("BINANCE_API_KEY"), os.environ.get("BINANCE_API_SECRET")
        if not key or not secret:
            raise BrokerError("set BINANCE_API_KEY and BINANCE_API_SECRET (testnet keys from testnet.binance.vision)")
        return cls(key, secret, os.environ.get("BINANCE_BASE_URL", TESTNET), live=live)

    # ---- low level -------------------------------------------------------------

    def _request(self, method: str, path: str, params: dict[str, object] | None = None, signed: bool = False) -> object:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        if signed:
            params["timestamp"] = int(self.clock() * 1000)
            params["recvWindow"] = self.recv_window_ms
        query = urllib.parse.urlencode(params)
        if signed:
            sig = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
            query = f"{query}&signature={sig}"
        headers = {"X-MBX-APIKEY": self.api_key}
        if method == "GET" or method == "DELETE":
            status, body = self.http(method, f"{self.base_url}{path}?{query}", headers, None)
        else:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            status, body = self.http(method, f"{self.base_url}{path}", headers, query.encode())
        try:
            data = json.loads(body or b"{}")
        except json.JSONDecodeError:
            data = {"msg": body[:200].decode(errors="replace")}
        if status in (418, 429) or status >= 500:
            raise TransientBrokerError(f"Binance {status}: {data}")
        if status >= 400:
            raise BrokerError(f"Binance {status}: {data}")
        return data

    # ---- exchange rules ----------------------------------------------------------

    def rules(self, symbol: str) -> SymbolRules:
        if symbol not in self._rules:
            info = self._request("GET", "/api/v3/exchangeInfo", {"symbol": symbol})
            filters = {f["filterType"]: f for f in info["symbols"][0]["filters"]}  # type: ignore[index]
            lot = filters.get("MARKET_LOT_SIZE") or filters.get("LOT_SIZE") or {}
            if float(lot.get("stepSize", 0) or 0) == 0:
                lot = filters.get("LOT_SIZE", {})
            notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}
            self._rules[symbol] = SymbolRules(float(lot.get("stepSize", 1e-8)), float(lot.get("minQty", 0)), float(notional.get("minNotional", 0)))
        return self._rules[symbol]

    def round_qty(self, symbol: str, qty: float) -> float:
        step = self.rules(symbol).step
        decimals = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 0
        return round(math.floor(qty / step + 1e-9) * step, decimals)

    # ---- Broker protocol -----------------------------------------------------------

    def place_order(self, order: OrderRequest) -> Fill:
        # Idempotency: if an earlier attempt with this client id reached Binance, return it instead.
        cid = hashlib.sha1(order.client_order_id.encode()).hexdigest()[:32]  # Binance limit: 36 chars
        try:
            existing = self._request("GET", "/api/v3/order", {"symbol": order.symbol, "origClientOrderId": cid}, signed=True)
        except BrokerError:
            existing = None  # -2013 "order does not exist"
        if existing and existing.get("status") == "FILLED":  # type: ignore[union-attr]
            return self._fill_from(order, existing, cid)  # type: ignore[arg-type]

        qty = self.round_qty(order.symbol, order.quantity)
        r = self.rules(order.symbol)
        if qty < r.min_qty or qty * order.price_hint < r.min_notional:
            raise BrokerError(f"order too small for {order.symbol}: qty {qty}, notional {qty * order.price_hint:.2f} < {r.min_notional}")
        res = self._request("POST", "/api/v3/order", {
            "symbol": order.symbol, "side": "BUY" if order.side == Action.BUY else "SELL", "type": "MARKET",
            "quantity": f"{qty:.8f}".rstrip("0").rstrip("."), "newClientOrderId": cid, "newOrderRespType": "FULL",
        }, signed=True)
        if res.get("status") != "FILLED":  # type: ignore[union-attr]
            raise TransientBrokerError(f"order not filled yet: {res.get('status')}")  # type: ignore[union-attr]
        return self._fill_from(order, res, cid)  # type: ignore[arg-type]

    def _fill_from(self, order: OrderRequest, res: dict, cid: str) -> Fill:
        executed = float(res.get("executedQty", 0))
        quote_spent = float(res.get("cummulativeQuoteQty", 0))
        price = quote_spent / executed if executed else order.price_hint
        fee_quote = 0.0
        for f in res.get("fills", []):
            commission = float(f.get("commission", 0))
            fee_quote += commission if f.get("commissionAsset") == self.quote else commission * float(f.get("price", price))
        signed_qty = executed if order.side == Action.BUY else -executed
        new = self._positions.get(order.symbol, 0.0) + signed_qty
        if abs(new) < 1e-12:
            self._positions.pop(order.symbol, None)
        else:
            self._positions[order.symbol] = new
        return Fill(order.client_order_id, order.symbol, order.side, executed, price, fee_quote, utcnow())

    def cash(self) -> float:
        acct = self._request("GET", "/api/v3/account", {"omitZeroBalances": "true"}, signed=True)
        return next((float(b["free"]) for b in acct.get("balances", []) if b["asset"] == self.quote), 0.0)  # type: ignore[union-attr]

    def positions(self) -> dict[str, float]:
        return dict(self._positions)

    def adopt_positions(self, positions: dict[str, float]) -> None:
        """After a restart, re-attach the positions the trade log says are still open."""
        self._positions.update({k: v for k, v in positions.items() if abs(v) > 0})

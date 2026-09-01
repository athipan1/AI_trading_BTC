from __future__ import annotations

import hashlib
import hmac
from decimal import ROUND_DOWN, Decimal
from urllib.parse import urlencode, urlparse

import requests

from app.models import Candle


class BinanceFuturesTestnetSafetyError(RuntimeError):
    """Raised when the Futures execution target is not the Binance demo host."""


class BinanceFuturesTestnetBroker:
    TESTNET_BASE_URL = "https://demo-fapi.binance.com"
    ALLOWED_HOST = "demo-fapi.binance.com"
    INTERVAL_MS = {
        "1m": 60_000,
        "5m": 300_000,
        "15m": 900_000,
        "30m": 1_800_000,
        "1h": 3_600_000,
        "4h": 14_400_000,
        "1d": 86_400_000,
    }

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        max_order_notional_usdt: float = 25.0,
        session: requests.Session | None = None,
        base_url: str = TESTNET_BASE_URL,
    ) -> None:
        if not api_key.strip() or not api_secret.strip():
            raise ValueError("Binance Futures demo API key and secret are required")
        if max_order_notional_usdt <= 0:
            raise ValueError("max_order_notional_usdt must be positive")
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.max_order_notional_usdt = float(max_order_notional_usdt)
        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")
        self._assert_testnet_url(self.base_url)

    @classmethod
    def _assert_testnet_url(cls, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != cls.ALLOWED_HOST:
            raise BinanceFuturesTestnetSafetyError(
                f"refusing futures URL: expected https://{cls.ALLOWED_HOST}"
            )

    @staticmethod
    def _symbol_parts(symbol: str) -> tuple[str, str, str]:
        normalized = symbol.upper().strip()
        if normalized.count("/") != 1:
            raise ValueError("symbol must use BASE/QUOTE format")
        base, quote = normalized.split("/", 1)
        if quote != "USDT":
            raise ValueError("USD-M Futures demo broker currently supports USDT quote only")
        return f"{base}{quote}", base, quote

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        signed: bool = False,
    ) -> dict | list:
        url = f"{self.base_url}{path}"
        self._assert_testnet_url(url)
        request_params = dict(params or {})
        headers: dict[str, str] = {}
        if signed:
            request_params["timestamp"] = self._server_time_ms()
            request_params["recvWindow"] = 5000
            query = urlencode(request_params)
            request_params["signature"] = hmac.new(
                self.api_secret.encode("utf-8"),
                query.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            headers["X-MBX-APIKEY"] = self.api_key
        try:
            response = self.session.request(
                method,
                url,
                params=request_params,
                headers=headers,
                timeout=10,
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Binance Futures demo network error: {exc.__class__.__name__}"
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"Binance Futures demo returned non-JSON HTTP {response.status_code}"
            ) from exc
        if not response.ok:
            code = payload.get("code") if isinstance(payload, dict) else None
            message = payload.get("msg") if isinstance(payload, dict) else None
            raise RuntimeError(
                f"Binance Futures demo API error HTTP {response.status_code}: "
                f"code={code} msg={message}"
            )
        if not isinstance(payload, (dict, list)):
            raise RuntimeError("Binance Futures demo returned unexpected response shape")
        return payload

    def _server_time_ms(self) -> int:
        payload = self._request("GET", "/fapi/v1/time")
        if not isinstance(payload, dict):
            raise RuntimeError("invalid Futures server time payload")
        server_time = payload.get("serverTime")
        if not isinstance(server_time, int) or server_time <= 0:
            raise RuntimeError("Futures demo did not return a valid server time")
        return server_time

    def _market(self, symbol: str) -> dict:
        exchange_symbol, _, _ = self._symbol_parts(symbol)
        payload = self._request("GET", "/fapi/v1/exchangeInfo")
        if not isinstance(payload, dict):
            raise RuntimeError("invalid Futures exchangeInfo payload")
        symbols = payload.get("symbols")
        if not isinstance(symbols, list):
            raise RuntimeError("Futures exchangeInfo is missing symbols")
        for market in symbols:
            if isinstance(market, dict) and market.get("symbol") == exchange_symbol:
                if market.get("status") != "TRADING":
                    raise ValueError(f"Futures symbol is not active: {symbol}")
                return market
        raise ValueError(f"symbol is not available on Binance Futures demo: {symbol}")

    @staticmethod
    def _market_step_size(market: dict) -> Decimal:
        filters = market.get("filters") or []
        for filter_type in ("MARKET_LOT_SIZE", "LOT_SIZE"):
            for item in filters:
                if not isinstance(item, dict) or item.get("filterType") != filter_type:
                    continue
                step = Decimal(str(item.get("stepSize", "0")))
                if step > 0:
                    return step
        raise RuntimeError("Futures market metadata is missing lot step size")

    @staticmethod
    def _format_decimal(value: Decimal) -> str:
        return format(value, "f")

    def current_price(self, symbol: str) -> float:
        exchange_symbol, _, _ = self._symbol_parts(symbol)
        payload = self._request(
            "GET",
            "/fapi/v1/ticker/price",
            params={"symbol": exchange_symbol},
        )
        if not isinstance(payload, dict):
            raise RuntimeError("invalid Futures ticker payload")
        price = Decimal(str(payload.get("price", "0")))
        if price <= 0:
            raise RuntimeError("Futures demo returned unusable price")
        return float(price)

    def fetch_closed_candles(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 240,
    ) -> list[Candle]:
        if interval not in self.INTERVAL_MS:
            raise ValueError(f"unsupported Futures interval: {interval}")
        if not 60 <= limit <= 500:
            raise ValueError("candle limit must be between 60 and 500")
        exchange_symbol, _, _ = self._symbol_parts(symbol)
        server_time = self._server_time_ms()
        payload = self._request(
            "GET",
            "/fapi/v1/klines",
            params={"symbol": exchange_symbol, "interval": interval, "limit": limit + 2},
        )
        if not isinstance(payload, list):
            raise RuntimeError("invalid Futures kline payload")
        candles: list[Candle] = []
        last_close_time: int | None = None
        for row in payload:
            if not isinstance(row, list) or len(row) < 7:
                raise RuntimeError("malformed Futures kline row")
            close_time = int(row[6])
            if close_time >= server_time:
                continue
            candles.append(
                Candle(
                    timestamp_ms=int(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
            )
            last_close_time = close_time
        candles = candles[-limit:]
        if len(candles) < 60 or last_close_time is None:
            raise RuntimeError("Futures demo returned too few closed candles")
        freshness_limit = self.INTERVAL_MS[interval] * 2 + 60_000
        if server_time - last_close_time > freshness_limit:
            raise RuntimeError("latest Futures demo candle is stale")
        return candles

    def account_snapshot(self, symbol: str) -> dict:
        payload = self._request("GET", "/fapi/v3/account", signed=True)
        if not isinstance(payload, dict):
            raise RuntimeError("invalid Futures account payload")
        return {
            "symbol": symbol.upper(),
            "wallet_balance_usdt": float(payload.get("totalWalletBalance", 0)),
            "available_balance_usdt": float(payload.get("availableBalance", 0)),
            "margin_balance_usdt": float(payload.get("totalMarginBalance", 0)),
            "unrealized_pnl_usdt": float(payload.get("totalUnrealizedProfit", 0)),
        }

    def preflight(self, symbol: str) -> dict:
        market = self._market(symbol)
        mode = self._request("GET", "/fapi/v1/positionSide/dual", signed=True)
        if not isinstance(mode, dict):
            raise RuntimeError("invalid Futures position mode payload")
        if bool(mode.get("dualSidePosition")):
            raise BinanceFuturesTestnetSafetyError(
                "Hedge Mode is not supported by this runner; switch Futures demo to One-way Mode"
            )
        snapshot = self.account_snapshot(symbol)
        return {
            "mode": "binance_usdm_futures_demo",
            "sandbox": True,
            "host": self.ALLOWED_HOST,
            "symbol": symbol.upper(),
            "exchange_status": market.get("status"),
            "one_way_mode": True,
            "wallet_balance_usdt": snapshot["wallet_balance_usdt"],
            "order_sent": False,
        }

    def _market_quantity(self, symbol: str, notional_usdt: float) -> Decimal:
        if not 0 < notional_usdt <= self.max_order_notional_usdt:
            raise ValueError(
                f"notional_usdt must be within hard demo cap "
                f"{self.max_order_notional_usdt:.2f} USDT"
            )
        market = self._market(symbol)
        step = self._market_step_size(market)
        price = Decimal(str(self.current_price(symbol)))
        quantity = (Decimal(str(notional_usdt)) / price / step).to_integral_value(
            rounding=ROUND_DOWN
        ) * step
        if quantity <= 0:
            raise ValueError("calculated Futures quantity is zero")
        return quantity

    def _order_result(self, order: dict, symbol: str, fallback_price: float) -> dict:
        order_id = order.get("orderId")
        quantity = Decimal(str(order.get("executedQty", order.get("origQty", "0"))))
        avg_price = Decimal(str(order.get("avgPrice", "0")))
        if avg_price <= 0:
            avg_price = Decimal(str(fallback_price))
        return {
            "mode": "binance_usdm_futures_demo",
            "sandbox": True,
            "host": self.ALLOWED_HOST,
            "order_sent": True,
            "order_id": order_id,
            "symbol": symbol.upper(),
            "side": str(order.get("side") or "").lower(),
            "status": order.get("status"),
            "filled": float(quantity),
            "average": float(avg_price),
        }

    def place_market_short(self, symbol: str, notional_usdt: float) -> dict:
        exchange_symbol, _, _ = self._symbol_parts(symbol)
        quantity = self._market_quantity(symbol, notional_usdt)
        fallback_price = self.current_price(symbol)
        payload = self._request(
            "POST",
            "/fapi/v1/order",
            params={
                "symbol": exchange_symbol,
                "side": "SELL",
                "type": "MARKET",
                "quantity": self._format_decimal(quantity),
                "newOrderRespType": "RESULT",
            },
            signed=True,
        )
        if not isinstance(payload, dict):
            raise RuntimeError("invalid Futures SHORT order response")
        return self._order_result(payload, symbol, fallback_price)

    def close_market_short(self, symbol: str, quantity: float) -> dict:
        if quantity <= 0:
            raise ValueError("close quantity must be positive")
        exchange_symbol, _, _ = self._symbol_parts(symbol)
        market = self._market(symbol)
        step = self._market_step_size(market)
        qty = (Decimal(str(quantity)) / step).to_integral_value(rounding=ROUND_DOWN) * step
        if qty <= 0:
            raise ValueError("rounded close quantity is zero")
        fallback_price = self.current_price(symbol)
        payload = self._request(
            "POST",
            "/fapi/v1/order",
            params={
                "symbol": exchange_symbol,
                "side": "BUY",
                "type": "MARKET",
                "quantity": self._format_decimal(qty),
                "reduceOnly": "true",
                "newOrderRespType": "RESULT",
            },
            signed=True,
        )
        if not isinstance(payload, dict):
            raise RuntimeError("invalid Futures close-SHORT order response")
        return self._order_result(payload, symbol, fallback_price)

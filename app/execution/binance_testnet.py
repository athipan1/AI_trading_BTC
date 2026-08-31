from __future__ import annotations

import hashlib
import hmac
from decimal import ROUND_DOWN, Decimal
from urllib.parse import urlencode, urlparse

import requests


class BinanceTestnetSafetyError(RuntimeError):
    """Raised when an execution target is not provably Binance Spot Testnet."""


class BinanceTestnetBroker:
    TESTNET_BASE_URL = "https://testnet.binance.vision"
    ALLOWED_SPOT_TESTNET_HOST = "testnet.binance.vision"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        max_order_notional_usdt: float = 25.0,
        session: requests.Session | None = None,
        base_url: str = TESTNET_BASE_URL,
    ) -> None:
        if not api_key.strip() or not api_secret.strip():
            raise ValueError("Binance Testnet API key and secret are required")
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
        if parsed.scheme != "https" or parsed.hostname != cls.ALLOWED_SPOT_TESTNET_HOST:
            raise BinanceTestnetSafetyError(
                f"refusing exchange URL: expected https://{cls.ALLOWED_SPOT_TESTNET_HOST}"
            )

    @staticmethod
    def _symbol_parts(symbol: str) -> tuple[str, str, str]:
        normalized = symbol.upper().strip()
        if normalized.count("/") != 1:
            raise ValueError("symbol must use BASE/QUOTE format, for example BTC/USDT")
        base, quote = normalized.split("/", 1)
        if not base.isalnum() or not quote.isalnum():
            raise ValueError("symbol contains unsupported characters")
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
            raise RuntimeError(f"Binance Testnet network error: {exc.__class__.__name__}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"Binance Testnet returned non-JSON HTTP {response.status_code}"
            ) from exc

        if not response.ok:
            code = payload.get("code") if isinstance(payload, dict) else None
            message = payload.get("msg") if isinstance(payload, dict) else None
            raise RuntimeError(
                f"Binance Testnet API error HTTP {response.status_code}: code={code} msg={message}"
            )
        if not isinstance(payload, (dict, list)):
            raise RuntimeError("Binance Testnet returned an unexpected response shape")
        return payload

    def _server_time_ms(self) -> int:
        payload = self._request("GET", "/api/v3/time")
        if not isinstance(payload, dict):
            raise RuntimeError("Binance Testnet returned invalid server time payload")
        server_time = payload.get("serverTime")
        if not isinstance(server_time, int) or server_time <= 0:
            raise RuntimeError("Binance Testnet did not return a valid server time")
        return server_time

    def _load_market(self, symbol: str) -> dict:
        exchange_symbol, base, quote = self._symbol_parts(symbol)
        payload = self._request(
            "GET",
            "/api/v3/exchangeInfo",
            params={"symbol": exchange_symbol},
        )
        if not isinstance(payload, dict):
            raise RuntimeError("Binance Testnet returned invalid exchange metadata")
        symbols = payload.get("symbols")
        if not isinstance(symbols, list) or len(symbols) != 1 or not isinstance(symbols[0], dict):
            raise ValueError(f"symbol is not available on Binance Spot Testnet: {symbol}")
        market = symbols[0]
        if market.get("status") != "TRADING":
            raise ValueError(f"symbol is not active: {symbol}")
        if market.get("isSpotTradingAllowed") is False:
            raise ValueError(f"spot trading is not allowed: {symbol}")
        if market.get("baseAsset") != base or market.get("quoteAsset") != quote:
            raise BinanceTestnetSafetyError("exchange symbol metadata does not match requested symbol")
        return market

    def _account(self) -> dict:
        account = self._request("GET", "/api/v3/account", signed=True)
        if not isinstance(account, dict):
            raise RuntimeError("Binance Testnet returned invalid account payload")
        if account.get("canTrade") is False:
            raise ValueError("Binance Testnet account is not allowed to trade")
        return account

    @staticmethod
    def _asset_balance(account: dict, asset: str) -> tuple[Decimal, Decimal]:
        balances = account.get("balances")
        if not isinstance(balances, list):
            raise RuntimeError("Binance Testnet account response is missing balances")
        for balance in balances:
            if isinstance(balance, dict) and balance.get("asset") == asset:
                free = Decimal(str(balance.get("free", "0")))
                locked = Decimal(str(balance.get("locked", "0")))
                return free, locked
        return Decimal("0"), Decimal("0")

    @classmethod
    def _free_balance(cls, account: dict, asset: str) -> Decimal:
        free, _ = cls._asset_balance(account, asset)
        return free

    def _book_price(self, exchange_symbol: str, side: str) -> Decimal:
        ticker = self._request(
            "GET",
            "/api/v3/ticker/bookTicker",
            params={"symbol": exchange_symbol},
        )
        if not isinstance(ticker, dict):
            raise RuntimeError("Binance Testnet returned invalid book ticker payload")
        field = "askPrice" if side == "buy" else "bidPrice"
        price = Decimal(str(ticker.get(field, "0")))
        if price <= 0:
            raise RuntimeError("Binance Testnet ticker did not return a usable price")
        return price

    def current_price(self, symbol: str) -> float:
        exchange_symbol, _, _ = self._symbol_parts(symbol)
        ticker = self._request(
            "GET",
            "/api/v3/ticker/price",
            params={"symbol": exchange_symbol},
        )
        if not isinstance(ticker, dict):
            raise RuntimeError("Binance Testnet returned invalid price ticker payload")
        price = Decimal(str(ticker.get("price", "0")))
        if price <= 0:
            raise RuntimeError("Binance Testnet ticker did not return a usable price")
        return float(price)

    def account_snapshot(self, symbol: str) -> dict:
        exchange_symbol, base, quote = self._symbol_parts(symbol)
        account = self._account()
        quote_free, quote_locked = self._asset_balance(account, quote)
        base_free, base_locked = self._asset_balance(account, base)
        price = Decimal(str(self.current_price(symbol)))
        open_orders = self._request(
            "GET",
            "/api/v3/openOrders",
            params={"symbol": exchange_symbol},
            signed=True,
        )
        if not isinstance(open_orders, list):
            raise RuntimeError("Binance Testnet returned invalid open-orders payload")
        quote_total = quote_free + quote_locked
        base_total = base_free + base_locked
        estimated_value = quote_total + (base_total * price)
        return {
            "symbol": symbol.upper(),
            "quote_asset": quote,
            "base_asset": base,
            "quote_free": float(quote_free),
            "quote_total": float(quote_total),
            "base_total": float(base_total),
            "reference_price": float(price),
            "estimated_portfolio_value_quote": float(estimated_value),
            "open_orders_count": len(open_orders),
        }

    @staticmethod
    def _min_notional(market: dict) -> Decimal | None:
        filters = market.get("filters") or []
        for item in filters:
            if not isinstance(item, dict):
                continue
            if item.get("filterType") in {"NOTIONAL", "MIN_NOTIONAL"}:
                value = item.get("minNotional")
                if value is not None:
                    return Decimal(str(value))
        return None

    @staticmethod
    def _market_step_size(market: dict) -> Decimal:
        filters = market.get("filters") or []
        preferred = ("MARKET_LOT_SIZE", "LOT_SIZE")
        for filter_type in preferred:
            for item in filters:
                if not isinstance(item, dict) or item.get("filterType") != filter_type:
                    continue
                step = Decimal(str(item.get("stepSize", "0")))
                if step > 0:
                    return step
        raise RuntimeError("Binance Testnet market metadata is missing a usable lot step size")

    @staticmethod
    def _format_decimal(value: Decimal) -> str:
        return format(value, "f")

    def preflight(self, symbol: str) -> dict:
        market = self._load_market(symbol)
        account = self._account()
        exchange_symbol, base, quote = self._symbol_parts(symbol)
        price = self._book_price(exchange_symbol, "buy")
        return {
            "mode": "binance_spot_testnet",
            "sandbox": True,
            "host": self.ALLOWED_SPOT_TESTNET_HOST,
            "symbol": symbol.upper(),
            "base": base,
            "quote": quote,
            "reference_price": float(price),
            "credentials_valid": True,
            "can_trade": account.get("canTrade", True),
            "order_sent": False,
            "exchange_status": market.get("status"),
        }

    def place_market_order(self, symbol: str, side: str, notional_usdt: float) -> dict:
        normalized_side = side.lower().strip()
        if normalized_side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if notional_usdt <= 0:
            raise ValueError("notional_usdt must be positive")
        if notional_usdt > self.max_order_notional_usdt:
            raise ValueError(
                f"notional_usdt exceeds hard Testnet cap of {self.max_order_notional_usdt:.2f} USDT"
            )

        market = self._load_market(symbol)
        exchange_symbol, base, quote = self._symbol_parts(symbol)
        if quote != "USDT":
            raise ValueError("this workflow only allows USDT-quoted spot symbols")

        requested_notional = Decimal(str(notional_usdt))
        min_notional = self._min_notional(market)
        if min_notional is not None and requested_notional < min_notional:
            raise ValueError(
                f"requested notional {requested_notional} is below exchange minimum {min_notional}"
            )

        account = self._account()
        order_params: dict[str, object] = {
            "symbol": exchange_symbol,
            "side": normalized_side.upper(),
            "type": "MARKET",
            "newOrderRespType": "FULL",
        }
        reference_price = self._book_price(exchange_symbol, normalized_side)

        if normalized_side == "buy":
            if market.get("quoteOrderQtyMarketAllowed") is False:
                raise ValueError("Binance Testnet does not allow quoteOrderQty for this market")
            available_quote = self._free_balance(account, quote)
            if available_quote < requested_notional:
                raise ValueError(f"insufficient {quote} Testnet balance")
            order_params["quoteOrderQty"] = self._format_decimal(requested_notional)
            estimated_notional = requested_notional
        else:
            step = self._market_step_size(market)
            raw_quantity = requested_notional / reference_price
            quantity = (raw_quantity / step).to_integral_value(rounding=ROUND_DOWN) * step
            if quantity <= 0:
                raise ValueError("rounded order quantity is zero")
            available_base = self._free_balance(account, base)
            if available_base < quantity:
                raise ValueError(f"insufficient {base} Testnet balance")
            estimated_notional = quantity * reference_price
            if estimated_notional > Decimal(str(self.max_order_notional_usdt)) * Decimal("1.001"):
                raise BinanceTestnetSafetyError(
                    "rounded quantity would exceed the hard Testnet notional cap"
                )
            order_params["quantity"] = self._format_decimal(quantity)

        order = self._request(
            "POST",
            "/api/v3/order",
            params=order_params,
            signed=True,
        )
        if not isinstance(order, dict):
            raise RuntimeError("Binance Testnet returned invalid order payload")
        order_id = order.get("orderId")
        executed_qty = Decimal(str(order.get("executedQty", "0")))
        quote_qty = Decimal(str(order.get("cummulativeQuoteQty", "0")))
        average = quote_qty / executed_qty if executed_qty > 0 else None

        return {
            "mode": "binance_spot_testnet",
            "sandbox": True,
            "host": self.ALLOWED_SPOT_TESTNET_HOST,
            "order_sent": True,
            "id": str(order_id) if order_id is not None else None,
            "order_id": order_id,
            "client_order_id": order.get("clientOrderId"),
            "symbol": symbol.upper(),
            "exchange_symbol": order.get("symbol") or exchange_symbol,
            "type": str(order.get("type") or "MARKET").lower(),
            "side": str(order.get("side") or normalized_side).lower(),
            "status": order.get("status"),
            "amount": float(executed_qty),
            "filled": float(executed_qty),
            "remaining": None,
            "average": float(average) if average is not None else None,
            "price": None,
            "cost": float(quote_qty),
            "timestamp": order.get("transactTime"),
            "datetime": None,
            "requested_notional_usdt": float(requested_notional),
            "estimated_notional_usdt": float(estimated_notional),
        }

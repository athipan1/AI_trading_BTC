from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlparse

import ccxt


class BinanceTestnetSafetyError(RuntimeError):
    """Raised when the exchange is not provably connected to Binance Spot Testnet."""


class BinanceTestnetBroker:
    ALLOWED_SPOT_TESTNET_HOST = "testnet.binance.vision"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        max_order_notional_usdt: float = 25.0,
        exchange_factory: Callable[[dict], object] | None = None,
    ) -> None:
        if not api_key.strip() or not api_secret.strip():
            raise ValueError("Binance Testnet API key and secret are required")
        if max_order_notional_usdt <= 0:
            raise ValueError("max_order_notional_usdt must be positive")

        factory = exchange_factory or ccxt.binance
        self.max_order_notional_usdt = float(max_order_notional_usdt)
        self.exchange = factory(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
                "options": {
                    "defaultType": "spot",
                    "adjustForTimeDifference": True,
                },
            }
        )

        # CCXT requires sandbox mode to be enabled immediately after construction,
        # before any network call. Keeping this here is a hard safety boundary.
        self.exchange.set_sandbox_mode(True)
        self._assert_spot_testnet_urls()

    def _assert_spot_testnet_urls(self) -> None:
        api_urls = getattr(self.exchange, "urls", {}).get("api")
        if not isinstance(api_urls, dict):
            raise BinanceTestnetSafetyError("CCXT did not expose Binance sandbox API URLs")

        for route in ("public", "private"):
            value = api_urls.get(route)
            if not isinstance(value, str):
                raise BinanceTestnetSafetyError(f"missing Binance Spot Testnet {route} URL")
            host = urlparse(value).hostname
            if host != self.ALLOWED_SPOT_TESTNET_HOST:
                raise BinanceTestnetSafetyError(
                    f"refusing exchange URL for {route}: expected {self.ALLOWED_SPOT_TESTNET_HOST}"
                )

    def _load_market(self, symbol: str) -> dict:
        self.exchange.load_markets()
        market = self.exchange.markets.get(symbol)
        if not market:
            raise ValueError(f"symbol is not available on Binance Spot Testnet: {symbol}")
        if market.get("spot") is False:
            raise ValueError(f"only spot symbols are allowed: {symbol}")
        if market.get("active") is False:
            raise ValueError(f"symbol is not active: {symbol}")
        return market

    @staticmethod
    def _positive_price(ticker: dict, side: str) -> float:
        candidates = (
            (ticker.get("ask"), ticker.get("last"), ticker.get("close"))
            if side == "buy"
            else (ticker.get("bid"), ticker.get("last"), ticker.get("close"))
        )
        for candidate in candidates:
            if candidate is not None and float(candidate) > 0:
                return float(candidate)
        raise RuntimeError("Binance Testnet ticker did not return a usable price")

    def preflight(self, symbol: str) -> dict:
        market = self._load_market(symbol)
        self.exchange.fetch_balance()
        ticker = self.exchange.fetch_ticker(symbol)
        price = self._positive_price(ticker, "buy")
        return {
            "mode": "binance_spot_testnet",
            "sandbox": True,
            "host": self.ALLOWED_SPOT_TESTNET_HOST,
            "symbol": symbol,
            "base": market.get("base"),
            "quote": market.get("quote"),
            "reference_price": price,
            "credentials_valid": True,
            "order_sent": False,
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
        if market.get("quote") != "USDT":
            raise ValueError("this workflow only allows USDT-quoted spot symbols")

        ticker = self.exchange.fetch_ticker(symbol)
        reference_price = self._positive_price(ticker, normalized_side)
        raw_amount = notional_usdt / reference_price
        amount = float(self.exchange.amount_to_precision(symbol, raw_amount))
        if amount <= 0:
            raise ValueError("rounded order quantity is zero")

        estimated_notional = amount * reference_price
        if estimated_notional > self.max_order_notional_usdt * 1.001:
            raise BinanceTestnetSafetyError("rounded quantity would exceed the hard Testnet notional cap")

        amount_limits = (market.get("limits") or {}).get("amount") or {}
        cost_limits = (market.get("limits") or {}).get("cost") or {}
        min_amount = amount_limits.get("min")
        min_cost = cost_limits.get("min")
        if min_amount is not None and amount < float(min_amount):
            raise ValueError(f"quantity {amount} is below exchange minimum amount {min_amount}")
        if min_cost is not None and estimated_notional < float(min_cost):
            raise ValueError(
                f"estimated notional {estimated_notional:.4f} is below exchange minimum cost {min_cost}"
            )

        balance = self.exchange.fetch_balance()
        free = balance.get("free") or {}
        base = market.get("base")
        quote = market.get("quote")
        if normalized_side == "buy":
            available = float(free.get(quote, 0) or 0)
            if available < estimated_notional:
                raise ValueError(f"insufficient {quote} Testnet balance")
        else:
            available = float(free.get(base, 0) or 0)
            if available < amount:
                raise ValueError(f"insufficient {base} Testnet balance")

        order = self.exchange.create_order(symbol, "market", normalized_side, amount)
        return {
            "mode": "binance_spot_testnet",
            "sandbox": True,
            "host": self.ALLOWED_SPOT_TESTNET_HOST,
            "order_sent": True,
            "id": order.get("id"),
            "client_order_id": order.get("clientOrderId"),
            "symbol": order.get("symbol") or symbol,
            "type": order.get("type") or "market",
            "side": order.get("side") or normalized_side,
            "status": order.get("status"),
            "amount": order.get("amount", amount),
            "filled": order.get("filled"),
            "remaining": order.get("remaining"),
            "average": order.get("average"),
            "price": order.get("price"),
            "cost": order.get("cost"),
            "timestamp": order.get("timestamp"),
            "datetime": order.get("datetime"),
            "requested_notional_usdt": float(notional_usdt),
            "estimated_notional_usdt": estimated_notional,
        }

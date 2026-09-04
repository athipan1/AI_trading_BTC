from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from app.execution.paper import PaperBroker
from app.market_data.service import MarketDataService
from app.models import Candle, TradeAction, TradeSignal
from app.monitoring.position_store import PositionStore
from app.risk.engine import RiskEngine
from app.strategies.baseline import BaselineStrategy
from app.strategies.triple_ema_breakout import TripleEMAAlignmentBreakoutStrategy
from app.strategies.triple_ema_short import TripleEMAShortStrategy


class MarketDataReader(Protocol):
    def fetch_candles(self, symbol: str, timeframe: str, limit: int = 250) -> list[Candle]: ...


class Hermes3DReadOnlyAdapter:
    """Read-only projection of trading state for Hermes3D.

    The adapter intentionally exposes no execution method and cannot place, cancel,
    or modify orders. It only reads market data, evaluates existing strategies and
    risk rules, and loads locally tracked positions.
    """

    MIN_STRATEGY_CANDLES = 201

    def __init__(
        self,
        *,
        market_data: MarketDataReader | MarketDataService,
        risk_engine: RiskEngine,
        paper_broker: PaperBroker,
        spot_position_store: PositionStore,
        futures_position_store: PositionStore,
        symbol: str,
        timeframe: str,
        market_data_limit: int,
    ) -> None:
        self.market_data = market_data
        self.risk_engine = risk_engine
        self.paper_broker = paper_broker
        self.spot_position_store = spot_position_store
        self.futures_position_store = futures_position_store
        self.symbol = symbol
        self.timeframe = timeframe
        self.market_data_limit = max(market_data_limit, self.MIN_STRATEGY_CANDLES)
        self.strategies = (
            BaselineStrategy(),
            TripleEMAAlignmentBreakoutStrategy(),
            TripleEMAShortStrategy(),
        )

    @classmethod
    def from_paths(
        cls,
        *,
        market_data: MarketDataReader | MarketDataService,
        risk_engine: RiskEngine,
        paper_broker: PaperBroker,
        spot_position_store_path: str | Path,
        futures_position_store_path: str | Path,
        symbol: str,
        timeframe: str,
        market_data_limit: int,
    ) -> Hermes3DReadOnlyAdapter:
        return cls(
            market_data=market_data,
            risk_engine=risk_engine,
            paper_broker=paper_broker,
            spot_position_store=PositionStore(spot_position_store_path),
            futures_position_store=PositionStore(futures_position_store_path),
            symbol=symbol,
            timeframe=timeframe,
            market_data_limit=market_data_limit,
        )

    @staticmethod
    def registry() -> dict[str, Any]:
        return {
            "runtime": "ai-trading-btc",
            "mode": "read_only",
            "capabilities": ["market_state", "strategies", "risk", "positions"],
            "trade_execution": False,
            "agents": [
                {"id": "market-data", "name": "Market Data", "role": "observer"},
                {"id": "baseline", "name": "Baseline Strategy", "role": "observer"},
                {"id": "triple_ema", "name": "Triple EMA Long", "role": "observer"},
                {"id": "triple_ema_short", "name": "Triple EMA Short", "role": "observer"},
                {"id": "risk-manager", "name": "Risk Manager", "role": "observer"},
                {"id": "positions", "name": "Positions", "role": "observer"},
            ],
        }

    def _strategy_state(
        self,
        *,
        strategy: Any,
        candles: list[Candle],
        equity: float,
    ) -> dict[str, Any]:
        signal, diagnostic = strategy.analyze_with_diagnostic(candles, self.symbol, self.timeframe)
        risk = self.risk_engine.evaluate_entry(signal, equity)
        return {
            "strategy_id": strategy.strategy_id,
            "exit_mode": strategy.exit_mode,
            "signal": signal.model_dump(mode="json"),
            "diagnostic": diagnostic.to_dict(),
            "risk": risk.model_dump(mode="json"),
        }

    @staticmethod
    def _risk_summary(strategy_states: list[dict[str, Any]]) -> dict[str, Any]:
        entries = [
            item
            for item in strategy_states
            if item["signal"]["action"] in {TradeAction.BUY.value, TradeAction.SHORT.value}
        ]
        return {
            "entry_signals": len(entries),
            "approved_entries": sum(bool(item["risk"]["approved"]) for item in entries),
            "execution_enabled": False,
            "decisions": {
                item["strategy_id"]: item["risk"]
                for item in strategy_states
            },
        }

    def state(self) -> dict[str, Any]:
        candles = self.market_data.fetch_candles(
            self.symbol,
            self.timeframe,
            self.market_data_limit,
        )
        if len(candles) < self.MIN_STRATEGY_CANDLES:
            raise ValueError(
                f"Hermes3D state requires at least {self.MIN_STRATEGY_CANDLES} candles"
            )

        latest = candles[-1]
        paper = self.paper_broker.snapshot(latest.close)
        strategy_states = [
            self._strategy_state(strategy=strategy, candles=candles, equity=paper.equity)
            for strategy in self.strategies
        ]
        baseline = strategy_states[0]["diagnostic"]
        triple_long = strategy_states[1]["diagnostic"]

        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "read_only": True,
            "permissions": {
                "market_read": True,
                "strategy_read": True,
                "risk_read": True,
                "positions_read": True,
                "trade_execution": False,
                "order_cancel": False,
                "position_modify": False,
            },
            "market": {
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "candle_timestamp_ms": latest.timestamp_ms,
                "price": latest.close,
                "ema20": baseline["ema_fast"],
                "ema50": baseline["ema_slow"],
                "ema200": triple_long["ema200"],
                "rsi14": baseline["rsi"],
                "momentum_pct": baseline["momentum_pct"],
                "atr14": baseline["atr"],
                "regime": strategy_states[0]["signal"]["regime"],
            },
            "strategies": strategy_states,
            "risk": self._risk_summary(strategy_states),
            "positions": {
                "paper": paper.model_dump(mode="json"),
                "spot_testnet": self.spot_position_store.active_positions(self.symbol),
                "futures_testnet_short": self.futures_position_store.active_positions(self.symbol),
            },
        }

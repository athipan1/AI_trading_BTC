from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from app.execution.paper import PaperBroker
from app.market_data.service import MarketDataService
from app.models import Candle, TradeAction
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
    RUNTIME_NAME = "AI Trading BTC"
    RUNTIME_VERSION = "phase-1.5"

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
            "models": {
                "readonly-observer": {
                    "name": "Read-only Observer",
                    "provider": "ai-trading-btc",
                }
            },
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
            "decisions": {item["strategy_id"]: item["risk"] for item in strategy_states},
        }

    @staticmethod
    def _strategy_status(strategy_state: dict[str, Any]) -> dict[str, Any]:
        signal = strategy_state["signal"]
        risk = strategy_state["risk"]
        action = str(signal["action"])
        is_entry = action in {TradeAction.BUY.value, TradeAction.SHORT.value}
        return {
            "status": "ENTRY_READY" if is_entry else action,
            "signal": action,
            "regime": signal["regime"],
            "risk_approved": bool(risk["approved"]) if is_entry else False,
            "detail": risk["reason"] if is_entry else signal["reasons"][0],
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
        risk_summary = self._risk_summary(strategy_states)
        spot_positions = self.spot_position_store.active_positions(self.symbol)
        futures_positions = self.futures_position_store.active_positions(self.symbol)
        open_positions = len(spot_positions) + len(futures_positions)
        strategy_by_id = {item["strategy_id"]: item for item in strategy_states}

        agent_statuses = {
            "market-data": {
                "status": "OBSERVING",
                "detail": f"{self.symbol} {self.timeframe} candle {latest.timestamp_ms}",
            },
            "baseline": self._strategy_status(strategy_by_id["baseline"]),
            "triple_ema": self._strategy_status(strategy_by_id["triple_ema"]),
            "triple_ema_short": self._strategy_status(strategy_by_id["triple_ema_short"]),
            "risk-manager": {
                "status": (
                    "PASS"
                    if risk_summary["entry_signals"] > 0
                    and risk_summary["approved_entries"] == risk_summary["entry_signals"]
                    else "WATCH"
                ),
                "detail": (
                    f"{risk_summary['approved_entries']}/{risk_summary['entry_signals']} "
                    "entry signals approved"
                ),
            },
            "positions": {
                "status": "OPEN" if open_positions else "FLAT",
                "detail": f"{open_positions} tracked testnet positions",
            },
        }

        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "profileName": "btc-trading-room",
            "registry_profile": "btc-trading-room",
            "runtime": {
                "name": self.RUNTIME_NAME,
                "version": self.RUNTIME_VERSION,
                "vendor": "athipan1",
                "status": "read_only",
                "active_model": "readonly-observer",
                "governance": "risk-engine-enforced",
            },
            "active": {
                "market-data": ["readonly-observer"],
                "baseline": ["readonly-observer"],
                "triple_ema": ["readonly-observer"],
                "triple_ema_short": ["readonly-observer"],
                "risk-manager": ["readonly-observer"],
                "positions": ["readonly-observer"],
            },
            "agent_statuses": agent_statuses,
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
            "risk": risk_summary,
            "positions": {
                "paper": paper.model_dump(mode="json"),
                "spot_testnet": spot_positions,
                "futures_testnet_short": futures_positions,
            },
        }

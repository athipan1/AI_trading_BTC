from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_research_promotion_gate_report() -> str:
    deployed = Path("/workspace/research/phase563_promotion_gate.json")
    if deployed.exists():
        return str(deployed)
    return "state/research/phase563_promotion_gate.json"


def _default_research_runtime_artifact(filename: str) -> str:
    deployed_dir = Path("/workspace/research")
    if deployed_dir.exists():
        return str(deployed_dir / filename)
    return str(Path("state/research") / filename)


def _default_research_integrity_report() -> str:
    return _default_research_runtime_artifact("phase565_evidence_integrity.json")


def _default_research_forward_oos_checkpoint() -> str:
    return _default_research_runtime_artifact("phase562_forward_oos_checkpoint.json")


def _default_research_scheduler_state() -> str:
    deployed = Path("/workspace/AI_trading_BTC/runtime/phase562_daily_scheduler_state.json")
    if deployed.parent.exists():
        return str(deployed)
    return "runtime/phase562_daily_scheduler_state.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AI Trading BTC"
    app_version: str = "0.1.0"
    exchange_id: str = "binance"
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    market_data_limit: int = Field(default=250, ge=60, le=5000)
    trading_mode: Literal["paper"] = "paper"

    starting_balance: float = Field(default=10_000.0, gt=0)
    risk_per_trade_pct: float = Field(default=0.005, gt=0, le=0.01)
    max_position_notional_pct: float = Field(default=0.25, gt=0, le=1)
    min_reward_risk: float = Field(default=1.5, gt=0)
    fee_rate: float = Field(default=0.001, ge=0, le=0.02)
    slippage_bps: float = Field(default=5.0, ge=0, le=100)

    hermes3d_spot_position_store: str = "state/binance-testnet-positions.json"
    hermes3d_futures_position_store: str = "state/binance-futures-testnet-short-positions.json"
    hermes3d_baseline_state_store: str = "state/binance-testnet-auto-baseline.json"
    hermes3d_triple_ema_state_store: str = "state/binance-testnet-auto-triple-ema.json"
    hermes3d_futures_short_state_store: str = "state/binance-futures-testnet-short-auto.json"
    hermes3d_event_journal: str = "state/hermes3d-events.jsonl"
    hermes3d_event_interval_seconds: float = Field(default=0.25, gt=0, le=10)
    hermes3d_validation_simulator_enabled: bool = False

    research_historical_trade_store: str = "state/research/historical-trades.json"
    research_promotion_gate_report: str = Field(
        default_factory=_default_research_promotion_gate_report
    )
    research_promotion_stale_after_seconds: float = Field(default=108_000.0, gt=0)
    research_integrity_report: str = Field(default_factory=_default_research_integrity_report)
    research_forward_oos_checkpoint: str = Field(
        default_factory=_default_research_forward_oos_checkpoint
    )
    research_scheduler_state: str = Field(default_factory=_default_research_scheduler_state)

    phase41_validation_trade_enabled: bool = False
    phase41_validation_position_store: str = "state/phase41-validation-positions.json"
    phase41_validation_notional_usdt: float = Field(default=10.0, gt=0, le=25)


@lru_cache
def get_settings() -> Settings:
    return Settings()

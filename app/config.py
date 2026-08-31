from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    return Settings()

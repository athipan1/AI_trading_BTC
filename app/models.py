from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Candle(StrictModel):
    timestamp_ms: int = Field(ge=0)
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)


class TradeAction(StrEnum):
    BUY = "BUY"
    SHORT = "SHORT"
    HOLD = "HOLD"
    EXIT = "EXIT"


class MarketRegime(StrEnum):
    BULL_TREND = "BULL_TREND"
    BEAR_TREND = "BEAR_TREND"
    SIDEWAYS = "SIDEWAYS"


class TradeSignal(StrictModel):
    symbol: str
    timeframe: str
    action: TradeAction
    confidence: float = Field(ge=0, le=1)
    regime: MarketRegime
    entry_price: float | None = Field(default=None, gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    take_profit: float | None = Field(default=None, gt=0)
    risk_reward: float | None = Field(default=None, gt=0)
    reasons: list[str] = Field(default_factory=list)


class RiskDecision(StrictModel):
    approved: bool
    quantity: float = Field(default=0, ge=0)
    max_loss: float = Field(default=0, ge=0)
    notional: float = Field(default=0, ge=0)
    reason: str


class PaperFill(StrictModel):
    accepted: bool
    side: str
    quantity: float = Field(ge=0)
    requested_price: float = Field(gt=0)
    fill_price: float | None = Field(default=None, gt=0)
    fee: float = Field(default=0, ge=0)
    reason: str


class PortfolioSnapshot(StrictModel):
    cash: float = Field(ge=0)
    position_qty: float = Field(ge=0)
    avg_entry: float = Field(ge=0)
    realized_pnl: float
    equity: float = Field(ge=0)


class CycleResult(StrictModel):
    mode: str = "paper"
    symbol: str
    timeframe: str
    signal: TradeSignal
    risk: RiskDecision | None = None
    fill: PaperFill | None = None
    portfolio: PortfolioSnapshot

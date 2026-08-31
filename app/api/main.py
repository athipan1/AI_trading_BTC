from __future__ import annotations

from fastapi import FastAPI, HTTPException

from app.config import get_settings
from app.execution.paper import PaperBroker
from app.market_data.service import MarketDataError, MarketDataService
from app.risk.engine import RiskEngine
from app.strategies.baseline import BaselineStrategy
from app.trading_cycle import TradingCycle

settings = get_settings()
app = FastAPI(title=settings.app_name, version=settings.app_version)

market_data = MarketDataService(settings.exchange_id)
strategy = BaselineStrategy()
risk = RiskEngine(
    risk_per_trade_pct=settings.risk_per_trade_pct,
    max_position_notional_pct=settings.max_position_notional_pct,
    min_reward_risk=settings.min_reward_risk,
)
broker = PaperBroker(settings.starting_balance, settings.fee_rate, settings.slippage_bps)
cycle = TradingCycle(market_data, strategy, risk, broker)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": settings.trading_mode, "version": settings.app_version}


@app.get("/portfolio")
def portfolio() -> dict:
    candles = market_data.fetch_candles(settings.symbol, settings.timeframe, 60)
    return broker.snapshot(candles[-1].close).model_dump()


@app.post("/paper/cycle")
def run_paper_cycle() -> dict:
    if settings.trading_mode != "paper":  # defensive; settings currently only accepts paper
        raise HTTPException(status_code=409, detail="Phase 1 only supports paper mode")
    try:
        result = cycle.run(settings.symbol, settings.timeframe, settings.market_data_limit)
    except MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return result.model_dump()

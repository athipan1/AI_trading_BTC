from __future__ import annotations

from fastapi import FastAPI, HTTPException

from app.config import get_settings
from app.execution.paper import PaperBroker
from app.integrations.hermes3d.events import Hermes3DEventStream
from app.integrations.hermes3d.journal import Hermes3DEventJournal
from app.integrations.hermes3d.projection import Hermes3DJournalStateProjection
from app.integrations.hermes3d.router import build_hermes3d_router
from app.market_data.service import MarketDataError, MarketDataService
from app.monitoring.position_store import PositionStore
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

hermes3d_journal = Hermes3DEventJournal(settings.hermes3d_event_journal)
hermes3d_spot_positions = PositionStore(settings.hermes3d_spot_position_store)
hermes3d_futures_positions = PositionStore(settings.hermes3d_futures_position_store)
hermes3d_auto_state_paths = {
    "baseline": settings.hermes3d_baseline_state_store,
    "triple_ema": settings.hermes3d_triple_ema_state_store,
    "triple_ema_short": settings.hermes3d_futures_short_state_store,
}
hermes3d_projection = Hermes3DJournalStateProjection(
    journal=hermes3d_journal,
    spot_position_store=hermes3d_spot_positions,
    futures_position_store=hermes3d_futures_positions,
    auto_state_paths=hermes3d_auto_state_paths,
    symbol=settings.symbol,
    timeframe=settings.timeframe,
)
hermes3d_events = Hermes3DEventStream(
    state_reader=hermes3d_projection,
    journal=hermes3d_journal,
    spot_position_store=hermes3d_spot_positions,
    futures_position_store=hermes3d_futures_positions,
    auto_state_paths=hermes3d_auto_state_paths,
    interval_seconds=settings.hermes3d_event_interval_seconds,
)
app.include_router(build_hermes3d_router(hermes3d_projection, hermes3d_events))


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

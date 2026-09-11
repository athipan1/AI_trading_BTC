from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException

from app.config import get_settings
from app.execution.binance_testnet import BinanceTestnetBroker
from app.execution.paper import PaperBroker
from app.integrations.hermes3d.analytics import Hermes3DTradingAnalyticsProjection
from app.integrations.hermes3d.events import Hermes3DEventStream
from app.integrations.hermes3d.journal import Hermes3DEventJournal
from app.integrations.hermes3d.projection import Hermes3DJournalStateProjection
from app.integrations.hermes3d.quant_analytics import Hermes3DQuantAnalyticsProjection
from app.integrations.hermes3d.router import build_hermes3d_router
from app.integrations.hermes3d.simulator import Hermes3DValidationEventSimulator
from app.market_data.service import MarketDataError, MarketDataService
from app.monitoring.binance_fill_reconciler import BinanceSpotFillSource, PositionFillReconciler
from app.monitoring.position_store import PositionStore
from app.monitoring.trade_path_observer import TradePathObserver
from app.research.historical_store import HistoricalResearchStore
from app.research.router import build_research_router
from app.risk.engine import RiskEngine
from app.strategies.baseline import BaselineStrategy
from app.trading_cycle import TradingCycle
from app.validation.phase41_trade import (
    Phase41ValidationTradeService,
    build_phase41_validation_router,
)

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
research_historical_trades = HistoricalResearchStore(settings.research_historical_trade_store)
phase41_validation_positions = PositionStore(settings.phase41_validation_position_store)
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
hermes3d_base_analytics = Hermes3DTradingAnalyticsProjection(
    journal=hermes3d_journal,
    spot_position_store=hermes3d_spot_positions,
    futures_position_store=hermes3d_futures_positions,
    auto_state_paths=hermes3d_auto_state_paths,
)
hermes3d_analytics = Hermes3DQuantAnalyticsProjection(
    base_projection=hermes3d_base_analytics,
    spot_position_store=hermes3d_spot_positions,
    futures_position_store=hermes3d_futures_positions,
    validation_position_store=phase41_validation_positions,
)
hermes3d_events = Hermes3DEventStream(
    state_reader=hermes3d_projection,
    journal=hermes3d_journal,
    spot_position_store=hermes3d_spot_positions,
    futures_position_store=hermes3d_futures_positions,
    auto_state_paths=hermes3d_auto_state_paths,
    interval_seconds=settings.hermes3d_event_interval_seconds,
)
hermes3d_validation_simulator = Hermes3DValidationEventSimulator(hermes3d_journal)
app.include_router(
    build_hermes3d_router(
        hermes3d_projection,
        hermes3d_events,
        analytics_reader=hermes3d_analytics,
        validation_simulator=hermes3d_validation_simulator,
        validation_simulator_enabled=settings.hermes3d_validation_simulator_enabled,
    )
)
app.include_router(
    build_research_router(
        spot_position_store=hermes3d_spot_positions,
        futures_position_store=hermes3d_futures_positions,
        historical_trade_store=research_historical_trades,
    )
)


def _phase41_validation_service() -> Phase41ValidationTradeService:
    broker = BinanceTestnetBroker(
        api_key=os.environ.get("BINANCE_TESTNET_API_KEY", ""),
        api_secret=os.environ.get("BINANCE_TESTNET_API_SECRET", ""),
        max_order_notional_usdt=25.0,
        max_exit_notional_usdt=100.0,
    )
    observer = TradePathObserver(phase41_validation_positions)
    reconciler = PositionFillReconciler(
        position_store=phase41_validation_positions,
        fill_source=BinanceSpotFillSource(broker),
    )
    return Phase41ValidationTradeService(
        broker=broker,
        position_store=phase41_validation_positions,
        trade_path_observer=observer,
        reconciler=reconciler,
        symbol=settings.symbol,
        timeframe=settings.timeframe,
        notional_usdt=settings.phase41_validation_notional_usdt,
    )


app.include_router(
    build_phase41_validation_router(
        service_factory=_phase41_validation_service,
        enabled=settings.phase41_validation_trade_enabled,
    )
)


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

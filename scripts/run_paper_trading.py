from __future__ import annotations

import json

from app.config import get_settings
from app.execution.paper import PaperBroker
from app.market_data.service import MarketDataService
from app.risk.engine import RiskEngine
from app.strategies.baseline import BaselineStrategy
from app.trading_cycle import TradingCycle


def main() -> None:
    settings = get_settings()
    broker = PaperBroker(settings.starting_balance, settings.fee_rate, settings.slippage_bps)
    cycle = TradingCycle(
        MarketDataService(settings.exchange_id),
        BaselineStrategy(),
        RiskEngine(
            settings.risk_per_trade_pct,
            settings.max_position_notional_pct,
            settings.min_reward_risk,
        ),
        broker,
    )
    result = cycle.run(settings.symbol, settings.timeframe, settings.market_data_limit)
    print(json.dumps(result.model_dump(), indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from app.backtest.engine import BacktestEngine
from app.config import get_settings
from app.market_data.service import MarketDataService
from app.risk.engine import RiskEngine
from app.strategies.baseline import BaselineStrategy


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchange", default=settings.exchange_id)
    parser.add_argument("--symbol", default=settings.symbol)
    parser.add_argument("--timeframe", default=settings.timeframe)
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()

    candles = MarketDataService(args.exchange).fetch_candles(args.symbol, args.timeframe, args.limit)
    result = BacktestEngine(
        BaselineStrategy(),
        RiskEngine(
            settings.risk_per_trade_pct,
            settings.max_position_notional_pct,
            settings.min_reward_risk,
        ),
        settings.starting_balance,
        settings.fee_rate,
        settings.slippage_bps,
    ).run(candles, args.symbol, args.timeframe)
    print(json.dumps(asdict(result), indent=2))


if __name__ == "__main__":
    main()

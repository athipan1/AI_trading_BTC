# AI Trading BTC

A production-minded BTC research and paper-trading baseline. Phase 1 deliberately contains **no live-order path**.

## Phase 1 flow

```text
CCXT public OHLCV
      ↓
EMA / RSI / ATR / Momentum
      ↓
Baseline long-only strategy
      ↓
Risk Engine (≤0.5% account risk/trade by default)
      ↓
PaperBroker
      ↓
Portfolio snapshot / Backtest metrics
```

The strategy may emit `BUY`, `HOLD`, or `EXIT`. `EXIT` only closes an existing long paper position. It never opens a short.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
pytest
uvicorn app.api.main:app --reload
```

Health check:

```bash
curl http://localhost:8000/health
```

Run one paper cycle using public market data:

```bash
python scripts/run_paper_trading.py
```

Backtest:

```bash
python scripts/run_backtest.py --exchange binance --symbol BTC/USDT --timeframe 1h --limit 1000
```

Download OHLCV:

```bash
python scripts/download_market_data.py --limit 1000 --output data/btc_usdt_1h.csv
```

## Safety defaults

- `TRADING_MODE=paper` is the only accepted Phase 1 mode.
- Public market-data reads need no exchange API key.
- There is no CCXT private-order call anywhere in Phase 1.
- A BUY requires a valid stop-loss and take-profit.
- Default risk budget is 0.5% of current paper equity per trade, capped again by maximum position notional.
- Repeated BUY signals cannot stack a second position in the same paper broker.
- Backtests include configurable fees and slippage and execute strategy decisions on the next candle open.

## API

- `GET /health`
- `GET /portfolio`
- `POST /paper/cycle`

The in-memory paper portfolio resets when the service restarts. Persistent storage and real exchange execution belong to later phases after the baseline is validated.

# AI Trading BTC

A production-minded BTC research and paper-trading baseline. The repository has **no Binance mainnet order path**. A separately gated Binance Spot Testnet lane can submit virtual orders for integration testing.

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

## Binance Spot Testnet GitHub Action

The manual workflow `.github/workflows/binance-testnet-order.yml` is isolated from the normal paper-trading cycle. It uses CCXT sandbox mode and refuses to continue unless both CCXT Spot routes resolve to `testnet.binance.vision`.

Create these GitHub repository secrets using credentials issued by Binance Spot Testnet:

- `BINANCE_TESTNET_API_KEY`
- `BINANCE_TESTNET_API_SECRET`

Then open **Actions → Binance Spot Testnet Order → Run workflow**.

Recommended first run:

- `mode = preflight`
- `side = buy`
- `notional_usdt = 10`
- leave confirmation empty

The preflight performs signed Testnet account validation and reads the Testnet ticker, but sends no order.

To submit a virtual market order:

- `mode = place_order`
- choose `buy` or `sell`
- set `notional_usdt` no higher than 25
- type `BINANCE_TESTNET` in the confirmation field

The workflow has a hard 25 USDT Testnet notional cap, does not print raw exchange responses, and uploads only a sanitized JSON report. Testnet API keys are different from production keys and are never interchangeable.

## Safety defaults

- `TRADING_MODE=paper` remains the only accepted application trading mode.
- Public market-data reads need no exchange API key.
- No Binance mainnet/private production endpoint is implemented.
- The Testnet execution module calls `set_sandbox_mode(True)` before any network request.
- The Testnet module fail-closes unless Spot public/private hosts are `testnet.binance.vision`.
- A manual confirmation token is required before the Testnet workflow can place an order.
- A BUY requires a valid stop-loss and take-profit in the normal paper strategy path.
- Default paper risk budget is 0.5% of current equity per trade, capped again by maximum position notional.
- Repeated BUY signals cannot stack a second position in the same paper broker.
- Backtests include configurable fees and slippage and execute strategy decisions on the next candle open.

## API

- `GET /health`
- `GET /portfolio`
- `POST /paper/cycle`

The in-memory paper portfolio resets when the service restarts. Binance Spot Testnet execution is intentionally a manual integration-testing lane and is not yet connected to autonomous strategy decisions.

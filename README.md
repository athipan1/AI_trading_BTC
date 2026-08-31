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

## Binance Spot Testnet

The Testnet execution lane is isolated from the normal paper-trading cycle. It uses signed Binance REST requests directly against `https://testnet.binance.vision` and fail-closes if the target host is not exactly the Spot Testnet host.

Required credentials:

- `BINANCE_TESTNET_API_KEY`
- `BINANCE_TESTNET_API_SECRET`

Preflight sends no order:

```bash
python scripts/run_binance_testnet_order.py \
  --mode preflight \
  --symbol BTC/USDT \
  --side buy \
  --notional-usdt 10
```

To submit a virtual Testnet market BUY:

```bash
python scripts/run_binance_testnet_order.py \
  --mode place_order \
  --symbol BTC/USDT \
  --side buy \
  --notional-usdt 10 \
  --confirm BINANCE_TESTNET
```

The Testnet lane has a hard 25 USDT notional cap by default and writes only sanitized order output.

### Termux / Android

The Testnet order and alert path does not require CCXT. Install only the lightweight dependencies:

```bash
pip install -r requirements-testnet-termux.txt
export PYTHONPATH=.
```

## Trading BTC LINE alerts

LINE Notify is not used. Alerts use the current LINE Messaging API push endpoint.

Configure a LINE Official Account Messaging API channel, add the Official Account as a friend (or add it to a group), then provide:

```bash
export LINE_CHANNEL_ACCESS_TOKEN='...'
export LINE_TARGET_ID='...'
```

Keep both values out of Git. `LINE_TARGET_ID` is the destination user ID, group ID, or multi-person chat ID obtained from LINE webhook events.

Test LINE independently before trading:

```bash
python scripts/test_line_messaging.py
```

A filled Testnet BUY is stored in `state/binance-testnet-positions.json` and can send a message headed **Trading BTC** containing:

- USDT account balance
- approximate BTC+USDT portfolio value
- entry price
- lot / filled BTC quantity
- TP
- SL
- Binance open-order count
- number of positions currently tracked by the alert monitor

Default alert thresholds are:

```bash
export BTC_TESTNET_TP_PCT=2
export BTC_TESTNET_SL_PCT=1
```

They can also be overridden per order with `--tp-pct` and `--sl-pct`.

Start the TP/SL monitor once:

```bash
python scripts/monitor_binance_testnet_positions.py
```

Or keep it running and check every 30 seconds:

```bash
python scripts/monitor_binance_testnet_positions.py --watch --interval-seconds 30
```

When the observed Testnet price reaches TP or SL, the monitor sends one LINE message for that event and stops monitoring that record. Notification delivery is retryable if LINE temporarily fails.

**Important:** the TP/SL values in this alert lane are monitoring thresholds only. They do not create protective Binance stop-loss or take-profit orders and do not automatically close the position.

## Binance Spot Testnet GitHub Action

The manual workflow `.github/workflows/binance-testnet-order.yml` is isolated from the normal paper-trading cycle and routes exchange traffic through the dedicated self-hosted runner label `binance-testnet`.

Create these GitHub repository secrets using credentials issued by Binance Spot Testnet:

- `BINANCE_TESTNET_API_KEY`
- `BINANCE_TESTNET_API_SECRET`

Then open **Actions → Binance Spot Testnet Order → Run workflow**.

Recommended first run:

- `mode = preflight`
- `side = buy`
- `notional_usdt = 10`
- leave confirmation empty

To submit a virtual market order:

- `mode = place_order`
- choose `buy` or `sell`
- set `notional_usdt` no higher than 25
- type `BINANCE_TESTNET` in the confirmation field

## Safety defaults

- `TRADING_MODE=paper` remains the only accepted application trading mode.
- Public market-data reads need no exchange API key.
- No Binance mainnet/private production endpoint is implemented.
- The Testnet execution module fail-closes unless the host is `testnet.binance.vision`.
- A manual confirmation token is required before the Testnet workflow can place an order.
- A BUY requires a valid stop-loss and take-profit in the normal paper strategy path.
- Default paper risk budget is 0.5% of current equity per trade, capped again by maximum position notional.
- Repeated BUY signals cannot stack a second position in the same paper broker.
- Backtests include configurable fees and slippage and execute strategy decisions on the next candle open.
- LINE credentials are optional and never committed; order execution is not blindly retried if post-order notification fails.

## API

- `GET /health`
- `GET /portfolio`
- `POST /paper/cycle`

The in-memory paper portfolio resets when the service restarts. Binance Spot Testnet execution remains an integration-testing lane and is not yet connected to autonomous strategy decisions.

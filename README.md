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

The strategy may emit `BUY`, `HOLD`, or `EXIT`. `EXIT` only closes an existing long position. It never opens a short.

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

The Testnet entry lane has a hard 25 USDT notional cap by default and writes only sanitized order output.

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
- number of positions currently tracked by the monitor

For manual Testnet orders, default alert thresholds are:

```bash
export BTC_TESTNET_TP_PCT=2
export BTC_TESTNET_SL_PCT=1
```

They can also be overridden per order with `--tp-pct` and `--sl-pct`.

Start the notification-only TP/SL monitor once:

```bash
python scripts/monitor_binance_testnet_positions.py
```

Or keep it running and check every 30 seconds:

```bash
python scripts/monitor_binance_testnet_positions.py --watch --interval-seconds 30
```

The standalone monitor only sends alerts. It does not submit exit orders.

## Automatic Binance Spot Testnet trading

The automatic loop is long-only and Testnet-only. It performs this flow:

```text
closed BTC/USDT candle
        ↓
EMA / RSI / ATR / Momentum
        ↓
BaselineStrategy
        ↓
RiskEngine
        ↓
BUY / HOLD / EXIT
        ↓
Binance Spot Testnet
        ↓
LINE notification
        ↓
live TP / SL monitoring
        ↓
automatic Testnet SELL on TP, SL, or strategy EXIT
```

The strategy is evaluated only once per **closed** candle. Live TP/SL checks run on every loop iteration. The automatic path allows at most one locally tracked open BTC/USDT position.

Recommended Testnet settings:

```bash
export BTC_TESTNET_AUTO_ENTRY_NOTIONAL_USDT=10
export BTC_TESTNET_AUTO_INTERVAL_SECONDS=30
export BTC_TESTNET_AUTO_CANDLE_LIMIT=120
export BTC_TESTNET_AUTO_REQUIRE_LINE=true
export BINANCE_TESTNET_MAX_NOTIONAL_USDT=25
export BINANCE_TESTNET_MAX_EXIT_NOTIONAL_USDT=100
```

Run one automatic decision cycle:

```bash
python scripts/run_binance_testnet_auto.py \
  --symbol BTC/USDT \
  --timeframe 1h \
  --confirm BINANCE_TESTNET_AUTO
```

Run continuously:

```bash
python scripts/run_binance_testnet_auto.py \
  --symbol BTC/USDT \
  --timeframe 1h \
  --watch \
  --interval-seconds 30 \
  --confirm BINANCE_TESTNET_AUTO
```

The automatic entry notional is capped three times: the configured auto-entry amount, `RiskEngine` sizing, and `BINANCE_TESTNET_MAX_NOTIONAL_USDT`.

### Automatic execution safety

- Only closed candles are used for strategy decisions.
- The same candle cannot submit the same BUY repeatedly.
- Only one tracked open position is allowed per BTC/USDT.
- TP/SL exits sell only the tracked quantity, rounded down to the exchange lot step.
- Automatic exits also have a separate Testnet exit-notional cap.
- Before an order is submitted, local state is written as `SUBMITTING`.
- If the process dies or the order result becomes uncertain, automation halts instead of blindly retrying.
- An unfinished `SUBMITTING`, `ACKED`, or `UNCERTAIN` attempt requires manual Binance Testnet reconciliation before automation can resume.
- LINE is required by default for automatic mode so Testnet orders are not opened silently.
- LINE delivery failure after a confirmed order never triggers a blind order retry.
- Binance mainnet endpoints are still not implemented.

Runtime state is stored under ignored `state/` files and therefore persists locally on the Termux device but is not committed to Git.

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
- Manual order submission requires an explicit confirmation token.
- Automatic Testnet trading requires the separate `BINANCE_TESTNET_AUTO` confirmation token at startup.
- Default risk budget is 0.5% of current equity per trade, capped again by maximum position notional.
- Backtests include configurable fees and slippage and execute strategy decisions on the next candle open.
- LINE credentials are never committed.

## API

- `GET /health`
- `GET /portfolio`
- `POST /paper/cycle`

The in-memory paper portfolio resets when the service restarts. Binance Spot Testnet automatic execution uses separate local state files and remains isolated from Binance mainnet.

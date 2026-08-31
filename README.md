# AI Trading BTC

Production-minded BTC trading research and paper-trading system.

## Phase 1

Phase 1 provides a safe baseline for BTC/USDT:

- Exchange market-data adapter via CCXT
- Technical features: EMA, RSI, ATR and momentum
- Baseline regime-aware strategy
- Risk sizing with a default maximum 0.5% account risk per trade
- In-memory paper execution only
- Backtest runner with fees and slippage
- FastAPI health and paper-cycle endpoints
- Pytest, Ruff and GitHub Actions CI
- Docker support

> Live order submission is intentionally not implemented in Phase 1.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
uvicorn app.api.main:app --reload
```

Run a paper cycle using public market data:

```bash
python scripts/run_paper_trading.py
```

Run a backtest:

```bash
python scripts/run_backtest.py --exchange binance --symbol BTC/USDT --timeframe 1h --limit 1000
```

## Safety defaults

- `TRADING_MODE=paper` is required.
- No exchange API key is required for public market data.
- The execution module refuses non-paper orders.
- Position sizing is derived from stop distance and account risk budget.
- Invalid or missing stop-loss values are rejected.

See `.env.example` for configuration.

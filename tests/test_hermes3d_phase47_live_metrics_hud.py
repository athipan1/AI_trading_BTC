from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "deploy/hermes3d/overlay/src/features/trading/ActiveTradePanel.tsx"


def test_phase47_hud_reads_live_metrics_from_read_only_state() -> None:
    source = PANEL.read_text(encoding="utf-8")

    assert 'const STATE_URL = "/api/trading-runtime?resource=state"' in source
    assert "market?: MarketState" in source
    assert "strategies?: StrategyState[]" in source
    assert "positions?: RuntimePositions" in source
    assert "risk?: RuntimeRisk" in source
    assert "data-live-market-metrics" in source
    assert "data-live-position-metrics" in source
    assert "data-risk-metrics" in source
    assert all(
        forbidden not in source.lower()
        for forbidden in (
            "binance_api_key",
            "binance_api_secret",
            "create_order",
            "cancel_order",
            "ccxt",
        )
    )


def test_phase47_hud_exposes_market_strategy_and_position_fields() -> None:
    source = PANEL.read_text(encoding="utf-8")

    for expected in (
        "ema20",
        "ema50",
        "ema200",
        "rsi14",
        "atr14",
        "entry_price",
        "stop_loss",
        "take_profit",
        "net_realized_pnl",
        "gross_realized_pnl",
        "calculateUnrealizedPnl",
        "circuit_breakers",
    ):
        assert expected in source


def test_phase47_hud_preserves_thai_english_and_collapsible_contract() -> None:
    source = PANEL.read_text(encoding="utf-8")

    assert 'price: "ราคา BTC"' in source
    assert 'unrealizedPnl: "PnL ยังไม่ปิด"' in source
    assert 'price: "BTC price"' in source
    assert 'unrealizedPnl: "Unrealized PnL"' in source
    assert "hermes3d-office-locale" in source
    assert "aria-expanded={expanded}" in source
    assert "max-h-[min(66dvh,34rem)]" in source

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "deploy/hermes3d/overlay/src/features/trading/ActiveTradePanel.tsx"


def test_phase467_collapsed_hud_is_single_row_summary() -> None:
    source = PANEL.read_text(encoding="utf-8")

    hud_start = source.index("<div data-active-trade-hud")
    drawer_start = source.index("{expanded ? (", hud_start)
    collapsed = source[hud_start:drawer_start]

    assert "items-center justify-between" in collapsed
    assert "{symbol}" in collapsed
    assert "{side}" in collapsed
    assert 'aria-controls="active-trade-panel-body"' in collapsed
    assert "strategyLabel(strategy)" not in collapsed
    assert "data-active-trade-lifecycle-strip" not in collapsed
    assert "trade?.correlation?.order_id" not in collapsed
    assert "stateText" not in collapsed


def test_phase467_moves_operational_detail_into_drawer() -> None:
    source = PANEL.read_text(encoding="utf-8")

    drawer_start = source.index("{expanded ? (")
    drawer = source[drawer_start:]

    assert 'data-active-trade-summary' in drawer
    assert "{labels.currentState}" in drawer
    assert "{stateText}" in drawer
    assert "strategyLabel(strategy)" in drawer
    assert "trade?.correlation?.order_id" in drawer
    assert 'data-active-trade-lifecycle-strip' in drawer
    assert 'id="active-trade-panel-body"' in drawer


def test_phase467_keeps_existing_read_only_runtime_contract() -> None:
    source = PANEL.read_text(encoding="utf-8")

    assert 'const STATE_URL = "/api/trading-runtime?resource=state"' in source
    assert 'fetch(STATE_URL, { cache: "no-store" })' in source

    forbidden = (
        "create_order",
        "cancel_order",
        "PositionStore",
        "RiskEngine",
        "BINANCE_TESTNET_API_KEY",
        "phase562",
    )
    for token in forbidden:
        assert token not in source

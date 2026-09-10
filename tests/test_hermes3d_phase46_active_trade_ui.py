from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "deploy/hermes3d/overlay/src/features/trading/ActiveTradePanel.tsx"
OFFICE_PAGE = ROOT / "deploy/hermes3d/overlay/src/app/office/page.tsx"
MOBILE_CSS = ROOT / "deploy/hermes3d/overlay/src/app/office/mobile.css"
BRIDGE = ROOT / "deploy/hermes3d/overlay/src/features/trading/TradingOfficeRealtimeBridge.tsx"


def test_phase46_panel_reads_only_runtime_state() -> None:
    source = PANEL.read_text(encoding="utf-8")

    assert 'const STATE_URL = "/api/trading-runtime?resource=state"' in source
    assert "fetch(STATE_URL" in source
    assert "active_trade" in source
    assert "trade_lifecycles" not in source
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


def test_phase46_panel_uses_monotonic_current_state_and_bilingual_labels() -> None:
    source = PANEL.read_text(encoding="utf-8")

    assert "STAGE_RANK" in source
    assert "POSITION_ACTIVE" in source
    assert "POSITION_CLOSED" in source
    assert "PNL_RECONCILED" in source
    assert 'title: "สถานะเทรดปัจจุบัน"' in source
    assert 'title: "Active Trade"' in source
    assert "hermes3d-office-locale" in source
    assert "currentRank >= rank" in source


def test_phase46_mounts_panel_without_changing_sse_only_bridge_contract() -> None:
    office_source = OFFICE_PAGE.read_text(encoding="utf-8")
    bridge_source = BRIDGE.read_text(encoding="utf-8")

    assert 'import { ActiveTradePanel } from "@/features/trading/ActiveTradePanel"' in office_source
    assert "<ActiveTradePanel />" in office_source
    assert 'new EventSource(EVENT_URL)' in bridge_source
    assert "fetch(" not in bridge_source


def test_phase46_panel_is_mobile_bounded_and_collapsible() -> None:
    panel_source = PANEL.read_text(encoding="utf-8")
    css_source = MOBILE_CSS.read_text(encoding="utf-8")

    assert "data-active-trade-panel" in panel_source
    assert "aria-expanded={expanded}" in panel_source
    assert "max-h-[min(66dvh,34rem)]" in panel_source
    assert "[data-active-trade-panel]" in css_source
    assert "max-height: min(52dvh, 26rem)" in css_source

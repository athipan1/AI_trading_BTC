from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "deploy/hermes3d/overlay/src/features/trading/TradingOfficeRealtimeBridge.tsx"
SIDEBAR = ROOT / "deploy/hermes3d/overlay/src/features/office/components/HQSidebar.tsx"


def test_phase182_localizes_visible_office_navigation() -> None:
    source = SIDEBAR.read_text(encoding="utf-8")
    for label in ("ศูนย์ควบคุม", "ตลาด", "วิเคราะห์", "สถานะงาน"):
        assert label in source


def test_phase182_localizes_trading_diagnostics_without_changing_event_contract() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    assert "ระบบเทรด" in source
    assert "เหตุการณ์ล่าสุด" in source
    assert 'const EVENT_URL = "/api/trading-runtime?resource=events"' in source
    assert "mapTradingEventToAnimations(event)" in source
    assert "event.event" in source


def test_phase182_frontend_remains_read_only() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in (BRIDGE, SIDEBAR)
    ).lower()
    forbidden = (
        "create_order",
        "cancel_order",
        "binance_api_key",
        "binance_api_secret",
        "ccxt",
    )
    assert all(token not in source for token in forbidden)

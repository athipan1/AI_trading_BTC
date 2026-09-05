from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = (
    ROOT
    / "deploy/hermes3d/overlay/src/features/office/mobile/MobileAgentRosterBridge.tsx"
)


def test_phase187_uses_single_anchor_button_for_toggle_and_drag() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    assert "data-mobile-agent-roster-toggle" in source
    assert "LONG_PRESS_MS = 350" in source
    assert "press.dragging = true" in source
    assert "แตะเพื่อแสดงหรือซ่อน กดค้างแล้วลากเพื่อย้ายตำแหน่ง" in source


def test_phase187_places_roster_below_anchor_with_above_fallback() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    assert "placeRosterByAnchor" in source
    assert "anchorRect.bottom + PANEL_GAP_PX" in source
    assert "anchorRect.top - rootRect.height - PANEL_GAP_PX" in source
    assert "belowY <= maxY ? belowY : aboveY" in source


def test_phase187_persists_anchor_position_and_expanded_state() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    assert "persist({ hidden: stored.hidden, x: rect.left, y: rect.top })" in source
    assert "persist({ hidden: true, x: rect.left, y: rect.top })" in source
    assert "persist({ hidden: false, x: rect.left, y: rect.top })" in source


def test_phase187_keeps_roster_attached_to_anchor_during_drag() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    assert "applyAnchorPosition(anchor, clamped.x, clamped.y)" in source
    assert "syncPanelToAnchor(stored.hidden)" in source
    assert "clampAnchorPosition" in source


def test_phase187_remains_presentation_only() -> None:
    source = BRIDGE.read_text(encoding="utf-8").lower()
    forbidden = (
        "create_order",
        "cancel_order",
        "binance_api_key",
        "binance_api_secret",
        "ccxt",
        "/api/trading-runtime",
        "buy_ready",
        "risk_pass",
        "order_open",
    )
    assert all(token not in source for token in forbidden)

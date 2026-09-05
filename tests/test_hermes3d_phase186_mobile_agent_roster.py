from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = (
    ROOT
    / "deploy/hermes3d/overlay/src/features/office/mobile/MobileAgentRosterBridge.tsx"
)
PAGE = ROOT / "deploy/hermes3d/overlay/src/app/office/page.tsx"


def test_phase186_mounts_mobile_agent_roster_bridge() -> None:
    page = PAGE.read_text(encoding="utf-8")
    assert "MobileAgentRosterBridge" in page
    assert "<MobileAgentRosterBridge />" in page


def test_phase186_supports_hide_restore_and_persistence() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    assert 'STORAGE_KEY = "hermes3d-mobile-agent-roster"' in source
    assert "hideRoster" in source
    assert "showRoster" in source
    assert "localStorage.setItem" in source
    assert "แสดงเอเจนต์" in source
    assert "ซ่อนเอเจนต์" in source


def test_phase186_supports_pointer_drag_and_viewport_clamping() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    assert "onPointerDown={onPointerDown}" in source
    assert "onPointerMove={onPointerMove}" in source
    assert "onPointerUp={finishPointer}" in source
    assert "DRAG_THRESHOLD_PX" in source
    assert "clampAnchorPosition" in source
    assert 'style={{ touchAction: "none" }}' in source


def test_phase186_targets_existing_upstream_roster_instead_of_replacing_it() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    assert 'document.querySelectorAll<SVGElement>("svg.lucide-users")' in source
    assert 'className.includes("border-amber-900/25")' in source
    assert 'className.includes("bg-[#1c1610]/92")' in source
    assert "COMPACT_AGENT_BADGE_LIMIT" not in source


def test_phase186_remains_presentation_only() -> None:
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

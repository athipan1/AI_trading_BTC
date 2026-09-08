from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "deploy/hermes3d/overlay/src/features/trading/tradingEventAnimation.ts"
BRIDGE = ROOT / "deploy/hermes3d/overlay/src/features/trading/TradingOfficeRealtimeBridge.tsx"
OFFICE_PAGE = ROOT / "deploy/hermes3d/overlay/src/app/office/page.tsx"


def test_phase17_animation_mapping_covers_trading_events() -> None:
    source = MAPPING.read_text(encoding="utf-8")
    for event_name in (
        "AGENT_ACTIVITY",
        "BUY_READY",
        "SHORT_READY",
        "RISK_PASS",
        "ORDER_OPEN",
        "TP_HIT",
        "SL_HIT",
        "CIRCUIT_BREAKER",
    ):
        assert event_name in source


def test_phase421_activity_mapping_uses_localized_speech_contract() -> None:
    source = MAPPING.read_text(encoding="utf-8")
    assert "activitySpeech" in source
    assert 'event.payload?.speech' in source
    assert 'phase: "activity"' in source
    assert 'state === "ERROR" ? "error" : "running"' in source


def test_phase422_activity_mapping_exposes_lifecycle_state() -> None:
    source = MAPPING.read_text(encoding="utf-8")
    assert "TradingActivityState" in source
    assert "normalizeActivityState" in source
    assert "activityState: state" in source


def test_phase17_bridge_is_read_only_event_source() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    assert 'new EventSource(EVENT_URL)' in source
    assert '/api/trading-runtime?resource=events' in source
    assert "fetch(" not in source
    assert "create_order" not in source
    assert "cancel_order" not in source
    assert "BINANCE" not in source


def test_phase17_bridge_queues_events_until_agents_hydrate() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    assert "pendingInstructions" in source
    assert "state.agents.some" in source
    assert "applyInstruction(pending.eventName, pending.instruction)" in source
    assert "delete pendingInstructions.current[agentId]" in source
    assert "queued:" in source


def test_phase422_bridge_preserves_visible_working_state() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    assert "MIN_WORKING_VISIBLE_MS" in source
    assert "workingVisibleUntil" in source
    assert "deferredTimers" in source
    assert 'instruction.activityState !== "WORKING"' in source
    assert "Hermes Gateway events แยกจาก Trading SSE" in source


def test_phase17_bridge_mounts_inside_office_agent_store() -> None:
    source = OFFICE_PAGE.read_text(encoding="utf-8")
    provider_pos = source.index("<AgentStoreProvider>")
    bridge_pos = source.index("<TradingOfficeRealtimeBridge />")
    office_pos = source.index("<OfficeScreen")
    assert provider_pos < bridge_pos < office_pos

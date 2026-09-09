from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "deploy/hermes3d/overlay/src/features/trading/TradingOfficeRealtimeBridge.tsx"


def test_phase423_state_snapshot_hydrates_agent_activity_speech() -> None:
    source = BRIDGE.read_text(encoding="utf-8")

    assert 'event.event !== "STATE_SNAPSHOT"' in source
    assert "payload.agent_statuses" in source
    assert 'event: "AGENT_ACTIVITY"' in source
    assert "rawActivity" in source
    assert "mapTradingEventToAnimations(mappedEvent)" in source


def test_phase423_snapshot_activity_reuses_native_stream_text_path() -> None:
    source = BRIDGE.read_text(encoding="utf-8")

    assert "const speechText = instruction.speech[readOfficeLocale()]" in source
    assert "streamText: speechText" in source
    assert 'status: state === "ERROR" ? "error" : "running"' not in source
    assert "pendingInstructions" in source

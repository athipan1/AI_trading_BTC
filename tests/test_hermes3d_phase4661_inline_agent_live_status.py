from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSPECTOR = ROOT / "deploy/hermes3d/overlay/src/features/trading/AgentLiveActivityInspector.tsx"
PATCH = ROOT / "deploy/hermes3d/overlay/scripts/apply-trading-speech-ux.mjs"


def test_phase4661_supports_inline_agent_status_variant() -> None:
    source = INSPECTOR.read_text(encoding="utf-8")

    assert 'variant?: "card" | "inline"' in source
    assert 'variant = "card"' in source
    assert 'const inline = variant === "inline"' in source
    assert "data-agent-live-status-inline" in source
    assert "ข้อมูลสด" in source
    assert "กำลังทำ: " in source
    assert "อัปเดต: " in source


def test_phase4661_moves_status_into_agent_chat_header() -> None:
    source = PATCH.read_text(encoding="utf-8")

    assert 'const agentChatTarget = "src/features/agents/components/AgentChatPanel.tsx"' in source
    assert 'AgentLiveActivityInspector } from "@/features/trading/AgentLiveActivityInspector"' in source
    assert '<AgentLiveActivityInspector agentId={agent.agentId} variant="inline" />' in source
    assert "agent live status import" in source
    assert "agent live status header" in source


def test_phase4661_removes_duplicate_office_level_inspector() -> None:
    source = PATCH.read_text(encoding="utf-8")

    assert "agent activity inspector open" not in source
    assert "agent activity inspector close" not in source
    assert "<AgentLiveActivityInspector agentId={focusedChatAgent.agentId} />" not in source


def test_phase4661_remains_read_only() -> None:
    source = INSPECTOR.read_text(encoding="utf-8")

    forbidden = (
        "create_order",
        "cancel_order",
        "PositionStore",
        "RiskEngine",
        "BINANCE_TESTNET_API_KEY",
    )
    for token in forbidden:
        assert token not in source

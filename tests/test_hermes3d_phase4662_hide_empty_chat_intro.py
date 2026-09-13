from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "deploy/hermes3d/overlay/scripts/apply-trading-speech-ux.mjs"


def test_phase4662_hides_only_empty_chat_intro_card() -> None:
    source = PATCH.read_text(encoding="utf-8")

    assert 'label: "hide empty chat intro card"' in source
    assert "data-trading-empty-chat-intro-hidden" in source
    assert 'ui-chat-assistant-card mt-2 hidden' in source
    assert "Try describing a task, bug, or question to get started." not in source


def test_phase4662_preserves_chat_and_trading_safety_contracts() -> None:
    source = PATCH.read_text(encoding="utf-8")

    assert 'const agentChatTarget = "src/features/agents/components/AgentChatPanel.tsx"' in source
    assert '<AgentLiveActivityInspector agentId={agent.agentId} variant="inline" />' in source

    forbidden = (
        "create_order",
        "cancel_order",
        "PositionStore",
        "RiskEngine",
        "BINANCE_TESTNET_API_KEY",
    )
    for token in forbidden:
        assert token not in source

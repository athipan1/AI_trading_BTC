from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSPECTOR = ROOT / "deploy/hermes3d/overlay/src/features/trading/AgentLiveActivityInspector.tsx"
PATCH = ROOT / "deploy/hermes3d/overlay/scripts/apply-trading-speech-ux.mjs"
PROJECTION = ROOT / "app/integrations/hermes3d/projection.py"


def test_phase466_reuses_existing_read_only_state_contract() -> None:
    source = INSPECTOR.read_text(encoding="utf-8")
    projection = PROJECTION.read_text(encoding="utf-8")

    assert 'const STATE_URL = "/api/trading-runtime?resource=state"' in source
    assert "agent_statuses" in source
    assert "activity" in source
    assert "lifecycle" in source
    assert '"agent_statuses": agent_statuses' in projection
    assert '"read_only": True' in projection


def test_phase466_surfaces_current_task_last_action_and_freshness() -> None:
    source = INSPECTOR.read_text(encoding="utf-8")

    assert "STALE_AFTER_MS" in source
    assert "data-agent-live-activity" in source
    assert "data-agent-current-task" in source
    assert "data-agent-last-action" in source
    assert "activity?.generated_at" in source
    assert "state.generated_at" in source
    assert "ข้อมูลล่าช้า" in source
    assert "กำลังทำ: " in source
    assert "อัปเดต: " in source


def test_phase466_has_agent_specific_observability_without_execution() -> None:
    source = INSPECTOR.read_text(encoding="utf-8")

    assert 'agentId === "market-data"' in source
    assert 'agentId === "positions"' in source
    assert 'agentId === "risk-manager"' in source
    assert "state.strategies?.find" in source
    assert "circuit_breakers" in source

    forbidden = (
        "create_order",
        "cancel_order",
        "PositionStore",
        "RiskEngine",
        "BINANCE_TESTNET_API_KEY",
    )
    for token in forbidden:
        assert token not in source


def test_phase466_patches_inspector_above_existing_agent_chat() -> None:
    source = PATCH.read_text(encoding="utf-8")

    assert 'AgentLiveActivityInspector } from "@/features/trading/AgentLiveActivityInspector"' in source
    assert "<AgentLiveActivityInspector agentId={focusedChatAgent.agentId} />" in source
    assert "<AgentChatPanel" in source
    assert "agent activity inspector open" in source
    assert "agent activity inspector close" in source


def test_phase466_inspector_is_compact_by_default() -> None:
    source = INSPECTOR.read_text(encoding="utf-8")

    assert "const [expanded, setExpanded] = useState(false)" in source
    assert "aria-expanded={expanded}" in source
    assert "{expanded ? (" in source
    assert "mx-3 mt-2" in source

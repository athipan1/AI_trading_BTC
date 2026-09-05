from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "deploy/hermes3d/overlay/src/features/trading/TradingOfficeRealtimeBridge.tsx"


def test_phase181_diagnostics_are_collapsed_by_default() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    assert "const [showDiagnostics, setShowDiagnostics] = useState(false);" in source
    assert "aria-expanded={showDiagnostics}" in source
    assert 'aria-controls="trading-realtime-diagnostics"' in source
    assert "STATUS_LABELS[diagnostics.status]" in source
    assert "diagnostics.received" in source


def test_phase181_expanded_panel_preserves_runtime_counters() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    for counter in (
        "diagnostics.received",
        "diagnostics.mapped",
        "diagnostics.applied",
        "diagnostics.lastEvent",
        "diagnostics.lastTargets",
    ):
        assert counter in source


def test_phase181_bridge_remains_read_only() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    assert 'new EventSource(EVENT_URL)' in source
    forbidden = (
        "fetch(",
        "create_order",
        "cancel_order",
        "ccxt",
        "BINANCE_API_KEY",
        "BINANCE_SECRET",
    )
    for token in forbidden:
        assert token not in source

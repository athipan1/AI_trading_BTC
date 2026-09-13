from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOBILE_CSS = ROOT / "deploy/hermes3d/overlay/src/app/office/mobile.css"
PANEL = ROOT / "deploy/hermes3d/overlay/src/features/trading/ActiveTradePanel.tsx"


def test_phase4671_collapsed_mobile_hud_stacks_details_above_trade_identity() -> None:
    css = MOBILE_CSS.read_text(encoding="utf-8")

    assert 'button[aria-expanded="false"]' in css
    assert "flex-direction: column" in css
    assert "align-items: flex-end" in css
    assert "order: 2" in css
    assert "justify-content: flex-end" in css
    assert "text-align: right" in css
    assert "order: 1" in css
    assert "align-self: flex-end" in css


def test_phase4671_preserves_trade_identity_and_details_contract() -> None:
    source = PANEL.read_text(encoding="utf-8")

    assert "{symbol}" in source
    assert "{side}" in source
    assert "{labels.details}" in source
    assert 'aria-controls="active-trade-panel-body"' in source
    assert "const [expanded, setExpanded] = useState(false)" in source

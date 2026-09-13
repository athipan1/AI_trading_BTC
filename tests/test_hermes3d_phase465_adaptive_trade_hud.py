from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "deploy/hermes3d/overlay/src/features/trading/ActiveTradePanel.tsx"
MOBILE_CSS = ROOT / "deploy/hermes3d/overlay/src/app/office/mobile.css"


def test_phase465_uses_existing_expand_contract() -> None:
    source = PANEL.read_text(encoding="utf-8")

    assert "const [expanded, setExpanded] = useState(false)" in source
    assert 'aria-expanded={expanded}' in source
    assert 'aria-controls="active-trade-panel-body"' in source
    assert "data-active-trade-hud" in source
    assert "data-active-trade-lifecycle-strip" in source


def test_phase465_collapsed_mobile_hud_hides_lifecycle_strip() -> None:
    css = MOBILE_CSS.read_text(encoding="utf-8")

    collapsed = '[data-active-trade-hud]:has(button[aria-expanded="false"])'
    assert collapsed in css
    assert f"{collapsed} [data-active-trade-lifecycle-strip]" in css
    assert "display: none;" in css
    assert "max-height: 6.25rem" in css


def test_phase465_expansion_keeps_details_available() -> None:
    panel = PANEL.read_text(encoding="utf-8")
    css = MOBILE_CSS.read_text(encoding="utf-8")

    assert "{expanded ? (" in panel
    assert 'id="active-trade-panel-body"' in panel
    assert "max-height: min(38dvh, 20rem)" in css
    assert "max-height: min(34dvh, 17rem)" in css


def test_phase465_compacts_small_phone_and_landscape_views() -> None:
    css = MOBILE_CSS.read_text(encoding="utf-8")

    assert "@media (max-width: 390px)" in css
    assert "max-height: 5.75rem" in css
    assert "@media (orientation: landscape) and (max-height: 520px)" in css
    assert "max-height: 5.5rem" in css


def test_phase465_is_visual_only() -> None:
    css = MOBILE_CSS.read_text(encoding="utf-8")

    forbidden = (
        "create_order",
        "PositionStore",
        "BINANCE_TESTNET_API_KEY",
        "phase562",
    )
    for token in forbidden:
        assert token not in css

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOBILE_CSS = ROOT / "deploy/hermes3d/overlay/src/app/office/mobile.css"


def test_phase4672_collapsed_mobile_panel_shrinks_to_content() -> None:
    css = MOBILE_CSS.read_text(encoding="utf-8")

    selector = '[data-active-trade-panel]:has([data-active-trade-hud] button[aria-expanded="false"])'
    assert selector in css
    assert "width: max-content !important" in css
    assert "max-width: calc(100vw - 1rem) !important" in css


def test_phase4672_trade_identity_does_not_force_full_panel_width() -> None:
    css = MOBILE_CSS.read_text(encoding="utf-8")

    identity_selector = (
        '[data-active-trade-hud]:has(button[aria-expanded="false"]) '
        "> div:first-child > div:first-child"
    )
    assert identity_selector in css
    assert "width: auto" in css
    assert "max-width: 100%" in css


def test_phase4672_expanded_panel_keeps_operational_width() -> None:
    css = MOBILE_CSS.read_text(encoding="utf-8")

    assert "width: min(92vw, 22.5rem) !important" in css
    assert "#active-trade-panel-body" in css

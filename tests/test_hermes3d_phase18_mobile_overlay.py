from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOBILE_CSS = ROOT / "deploy/hermes3d/overlay/src/app/office/mobile.css"
OFFICE_PAGE = ROOT / "deploy/hermes3d/overlay/src/app/office/page.tsx"
HQ_SIDEBAR = ROOT / "deploy/hermes3d/overlay/src/features/office/components/HQSidebar.tsx"


def test_phase18_mobile_styles_are_loaded_by_office_route() -> None:
    source = OFFICE_PAGE.read_text(encoding="utf-8")
    assert 'import "./mobile.css";' in source


def test_phase18_mobile_overlay_has_safe_area_and_phone_breakpoint() -> None:
    source = MOBILE_CSS.read_text(encoding="utf-8")
    assert "@media (max-width: 767px)" in source
    assert "env(safe-area-inset-bottom)" in source
    assert "100dvh" in source


def test_phase18_hq_sidebar_exposes_mobile_layout_hooks() -> None:
    source = HQ_SIDEBAR.read_text(encoding="utf-8")
    assert "data-hq-sidebar" in source
    assert "data-hq-mobile-nav" in source
    assert "data-hq-panel" in source
    assert "min-h-12" in source
    assert "md:[writing-mode:vertical-rl]" in source


def test_phase18_frontend_overlay_does_not_gain_execution_authority() -> None:
    combined = "\n".join(
        [
            MOBILE_CSS.read_text(encoding="utf-8"),
            OFFICE_PAGE.read_text(encoding="utf-8"),
            HQ_SIDEBAR.read_text(encoding="utf-8"),
        ]
    )
    for forbidden in ("create_order", "cancel_order", "modify_position", "ccxt", "BINANCE_API_KEY"):
        assert forbidden not in combined

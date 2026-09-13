from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "deploy/hermes3d/overlay/scripts/apply-trading-speech-ux.mjs"
MOBILE_CSS = ROOT / "deploy/hermes3d/overlay/src/app/office/mobile.css"


def test_phase464_patches_semantic_office_chat_hooks() -> None:
    source = PATCH.read_text(encoding="utf-8")

    for hook in (
        "data-office-chat-dock",
        "data-office-chat-workspace",
        "data-office-chat-roster",
        "data-office-chat-session",
        "data-office-chat-toggle",
    ):
        assert hook in source

    assert "src/features/office/screens/OfficeScreen.tsx" in source
    assert "mobile agents patch anchor not found" in source
    assert 'setChatOpen((prev) => !prev)' in source


def test_phase464_mobile_workspace_is_single_column_and_safe_area_aware() -> None:
    source = MOBILE_CSS.read_text(encoding="utf-8")

    assert "[data-office-chat-workspace]" in source
    assert "flex-direction: column !important" in source
    assert "height: min(68dvh, 36rem) !important" in source
    assert "max-height: calc(100dvh - 9rem - env(safe-area-inset-bottom)) !important" in source
    assert "bottom: calc(3.75rem + env(safe-area-inset-bottom)) !important" in source


def test_phase464_roster_becomes_horizontal_selector_on_mobile() -> None:
    source = MOBILE_CSS.read_text(encoding="utf-8")

    assert "[data-office-chat-roster]" in source
    assert "flex-direction: row !important" in source
    assert "overflow-x: auto !important" in source
    assert "overflow-y: hidden !important" in source
    assert "min-width: max-content" in source
    assert "-webkit-overflow-scrolling: touch" in source


def test_phase464_preserves_chat_session_as_primary_mobile_surface() -> None:
    source = MOBILE_CSS.read_text(encoding="utf-8")

    assert "[data-office-chat-session]" in source
    assert "min-height: 0" in source
    assert "flex: 1 1 auto" in source
    assert "overflow: hidden" in source
    assert "[data-office-chat-session] textarea" in source
    assert "max-width: 100%" in source


def test_phase464_keeps_desktop_rules_scoped_behind_mobile_breakpoint() -> None:
    source = MOBILE_CSS.read_text(encoding="utf-8")

    mobile_start = source.index("@media (max-width: 767px)")
    workspace_index = source.index("[data-office-chat-workspace]")
    next_media_index = source.index("@media (max-width: 390px)")

    assert mobile_start < workspace_index < next_media_index

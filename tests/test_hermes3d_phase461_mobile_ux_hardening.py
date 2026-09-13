from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "deploy/hermes3d/overlay/src/features/trading/ActiveTradePanel.tsx"
MOBILE_CSS = ROOT / "deploy/hermes3d/overlay/src/app/office/mobile.css"
LOCALIZATION = ROOT / "deploy/hermes3d/overlay/src/features/office/localization/OfficeLocalizationBridge.tsx"


def test_phase461_compact_hud_is_default_and_details_are_secondary() -> None:
    source = PANEL.read_text(encoding="utf-8")

    assert "const [expanded, setExpanded] = useState(false)" in source
    assert "data-active-trade-hud" in source
    assert "data-active-trade-lifecycle-strip" in source
    assert "data-trade-correlation-details" in source
    assert "aria-controls=\"active-trade-panel-body\"" in source
    assert "trade.correlation?.trade_id" in source
    assert "trade.agent_id" in source
    assert "trade.event" in source
    assert "trade.generated_at" in source


def test_phase461_primary_hud_surfaces_operational_fields() -> None:
    source = PANEL.read_text(encoding="utf-8")

    assert "const symbol =" in source
    assert "const side =" in source
    assert "strategyLabel(strategy)" in source
    assert "trade?.correlation?.order_id" in source
    assert "stageLabel(currentState, locale)" in source
    assert "currentRank >= rank || observedStates.has(stage)" in source


def test_phase461_mobile_bounds_restore_scene_visibility() -> None:
    css = MOBILE_CSS.read_text(encoding="utf-8")

    assert "max-height: 9.75rem" in css
    assert "max-height: min(38dvh, 20rem)" in css
    assert "max-height: min(34dvh, 17rem)" in css
    assert "max-height: min(30dvh, 16rem)" in css


def test_phase461_preserves_existing_locale_toggle_semantics() -> None:
    source = LOCALIZATION.read_text(encoding="utf-8")

    assert 'onClick={() => setLocale(oppositeLocale)}' in source
    assert '{locale === "th" ? "EN" : "TH"}' in source
    assert 'hermes3d-office-locale' in source

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCALIZER = ROOT / "deploy/hermes3d/overlay/src/features/office/localization/OfficeLocalizationBridge.tsx"
OFFICE_PAGE = ROOT / "deploy/hermes3d/overlay/src/app/office/page.tsx"


def test_phase183_mounts_bilingual_localization_bridge() -> None:
    page = OFFICE_PAGE.read_text(encoding="utf-8")
    assert "OfficeLocalizationBridge" in page
    assert "<OfficeLocalizationBridge />" in page


def test_phase183_supports_thai_and_english_with_persistence() -> None:
    source = LOCALIZER.read_text(encoding="utf-8")
    assert 'type OfficeLocale = "th" | "en";' in source
    assert 'const STORAGE_KEY = "hermes3d-office-locale";' in source
    assert "window.localStorage.getItem(STORAGE_KEY)" in source
    assert "window.localStorage.setItem(STORAGE_KEY, locale)" in source
    assert 'locale === "th" ? "EN" : "TH"' in source


def test_phase183_translates_upstream_visible_ui_without_changing_machine_contracts() -> None:
    source = LOCALIZER.read_text(encoding="utf-8")
    for label in (
        '"AGENT EVENT CONSOLE": "เหตุการณ์เอเจนต์"',
        '"KANBAN BOARD": "กระดานสถานะงาน"',
        '"Total Spend": "ค่าใช้จ่ายรวม"',
        '"Gateway is not connected.": "เกตเวย์ยังไม่ได้เชื่อมต่อ"',
        '"Positions": "สถานะออเดอร์"',
    ):
        assert label in source

    forbidden = (
        "create_order",
        "cancel_order",
        "binance_api_key",
        "binance_api_secret",
        "ccxt",
    )
    lowered = source.lower()
    assert all(token not in lowered for token in forbidden)


def test_phase183_preserves_exact_visible_text_translation_before_dynamic_rules() -> None:
    source = LOCALIZER.read_text(encoding="utf-8")
    assert "const normalized = normalize(value);" in source
    assert 'const dictionary = locale === "th" ? EN_TO_TH : TH_TO_EN;' in source
    assert "const direct = dictionary[value];" in source
    assert "if (direct) return direct;" in source
    assert "DYNAMIC_TRANSLATIONS" in source
    assert "const translated = translateNormalized(normalized, locale);" in source
    assert "MutationObserver" in source
    assert "NodeFilter.SHOW_TEXT" in source

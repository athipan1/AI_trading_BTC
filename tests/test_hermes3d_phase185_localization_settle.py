from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCALIZER = ROOT / "deploy/hermes3d/overlay/src/features/office/localization/OfficeLocalizationBridge.tsx"


def test_phase185_reapplies_translation_after_react_rerenders() -> None:
    source = LOCALIZER.read_text(encoding="utf-8")
    assert "SETTLE_DELAYS_MS" in source
    assert "scheduleSettledTranslation" in source
    assert "MutationObserver" in source
    assert 'document.addEventListener("visibilitychange", handleVisibility)' in source


def test_phase185_covers_marketplace_actions_and_metadata() -> None:
    source = LOCALIZER.read_text(encoding="utf-8")
    for pair in (
        '"Install deps": "ติดตั้งส่วนที่จำเป็น"',
        '"Enable gateway": "เปิดใช้เกตเวย์"',
        '"Open settings": "เปิดการตั้งค่า"',
        '"Remove for all agents": "นำออกสำหรับเอเจนต์ทั้งหมด"',
        '"Productivity": "ประสิทธิภาพงาน"',
        '"Gives agents a shared workspace TODO board with blocked-task tracking.": "ให้เอเจนต์ใช้กระดาน TODO ร่วมกัน พร้อมติดตามงานที่ติดขัด"',
    ):
        assert pair in source


def test_phase185_keeps_locale_toggle_above_marketplace_modal() -> None:
    source = LOCALIZER.read_text(encoding="utf-8")
    assert "z-[140]" in source
    assert 'locale === "th" ? "EN" : "TH"' in source


def test_phase185_remains_presentation_only() -> None:
    source = LOCALIZER.read_text(encoding="utf-8").lower()
    forbidden = (
        "create_order",
        "cancel_order",
        "binance_api_key",
        "binance_api_secret",
        "ccxt",
        "/api/trading-runtime",
    )
    assert all(token not in source for token in forbidden)

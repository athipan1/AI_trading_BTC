from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCALIZER = ROOT / "deploy/hermes3d/overlay/src/features/office/localization/OfficeLocalizationBridge.tsx"


def test_phase184_covers_marketplace_visible_labels() -> None:
    source = LOCALIZER.read_text(encoding="utf-8")
    expected_pairs = (
        ('"Skills Marketplace": "ตลาดสกิล"',),
        ('"Focus chat": "เปิดแชตเอเจนต์"',),
        ('"Settings": "ตั้งค่า"',),
        ('"Search skills, categories, or sources": "ค้นหาสกิล หมวดหมู่ หรือแหล่งที่มา"',),
        ('"Needs setup": "ต้องตั้งค่า"',),
        ('"Install skill": "ติดตั้งสกิล"',),
        ('"Details": "รายละเอียด"',),
    )
    for (needle,) in expected_pairs:
        assert needle in source


def test_phase184_translates_accessibility_and_placeholder_attributes() -> None:
    source = LOCALIZER.read_text(encoding="utf-8")
    assert 'TRANSLATABLE_ATTRIBUTES = ["placeholder", "aria-label", "title"]' in source
    assert "translateAttributes" in source
    assert "attributeFilter: [...TRANSLATABLE_ATTRIBUTES]" in source


def test_phase184_handles_dynamic_marketplace_labels() -> None:
    source = LOCALIZER.read_text(encoding="utf-8")
    assert "DYNAMIC_TRANSLATIONS" in source
    assert "Access mode:" in source
    assert "installs" in source
    assert "Needs setup" in source


def test_phase184_preserves_machine_contracts_and_read_only_boundary() -> None:
    source = LOCALIZER.read_text(encoding="utf-8").lower()
    forbidden = (
        "create_order",
        "cancel_order",
        "binance_api_key",
        "binance_api_secret",
        "ccxt",
        "/api/trading-runtime",
        "buy_ready",
        "risk_pass",
        "order_open",
    )
    assert all(token not in source for token in forbidden)

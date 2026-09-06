from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOBILE_CSS = ROOT / "deploy/hermes3d/overlay/src/app/office/mobile.css"


def test_mobile_canvas_reserves_gestures_for_3d_camera() -> None:
    source = MOBILE_CSS.read_text(encoding="utf-8")

    assert "canvas {" in source
    assert "touch-action: none;" in source
    assert "touch-action: manipulation;" not in source
    assert "overscroll-behavior: none;" in source
    assert "user-select: none;" in source

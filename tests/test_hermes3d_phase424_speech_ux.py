from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "deploy/hermes3d/Dockerfile"
PATCHER = ROOT / "deploy/hermes3d/overlay/scripts/apply-trading-speech-ux.mjs"


def test_phase424_build_applies_compact_speech_ux_patch() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert "RUN node scripts/apply-trading-speech-ux.mjs" in dockerfile


def test_phase424_compact_speech_patch_is_guarded_against_upstream_drift() -> None:
    source = PATCHER.read_text(encoding="utf-8")
    assert "Hermes3D speech UX patch anchor not found" in source
    assert "MAX_SPEECH_BUBBLE_TEXT_LENGTH = 96" in source
    assert "MAX_SPEECH_BUBBLE_LINES = 3" in source
    assert "Math.min(2.55, Math.max(1.25" in source
    assert "<Billboard position={[0, 1.12, 0]}>" in source
    assert "<planeGeometry args={[0.12, 0.12]} />" in source


def test_phase424_thai_speech_uses_unicode_aware_width_and_break_word() -> None:
    source = PATCHER.read_text(encoding="utf-8")
    assert "speechBubbleDisplayUnits" in source
    assert "char.codePointAt(0)" in source
    assert "> 0x7f ? 1.45 : 1" in source
    assert 'overflowWrap=\\"break-word\\"' in source

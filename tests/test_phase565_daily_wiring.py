from pathlib import Path


def test_phase565_runs_between_forward_oos_and_promotion_gate() -> None:
    script = Path("scripts/run_phase562_daily.sh").read_text(encoding="utf-8")

    phase562 = script.index("scripts/run_phase562_forward_oos_automation.py")
    phase565 = script.index("scripts/run_phase565_evidence_integrity.py")
    phase563 = script.index("scripts/run_phase563_oos_promotion_gate.py")

    assert phase562 < phase565 < phase563
    assert "phase565_evidence_integrity_state.json" in script
    assert "phase565_evidence_integrity.json" in script

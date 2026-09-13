from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.research.daily_scheduler import DailyResearchScheduler, DailySchedulerConfig


def _scheduler() -> DailyResearchScheduler:
    return DailyResearchScheduler(
        DailySchedulerConfig(
            timezone="Asia/Bangkok",
            run_hour=7,
            run_minute=10,
            poll_seconds=60,
        )
    )


def test_not_due_before_bangkok_schedule(tmp_path: Path) -> None:
    scheduler = _scheduler()
    # 00:09 UTC == 07:09 Asia/Bangkok.
    result = scheduler.run_once(
        runner=tmp_path / "runner.sh",
        state_path=tmp_path / "state.json",
        now=datetime(2026, 9, 13, 0, 9, tzinfo=UTC),
        executor=lambda _: 0,
    )
    assert result == "NOT_DUE"
    assert not (tmp_path / "state.json").exists()


def test_runs_once_after_schedule_and_marks_success(tmp_path: Path) -> None:
    scheduler = _scheduler()
    calls: list[list[str]] = []
    state_path = tmp_path / "state.json"

    result = scheduler.run_once(
        runner=tmp_path / "runner.sh",
        state_path=state_path,
        now=datetime(2026, 9, 13, 0, 10, tzinfo=UTC),
        executor=lambda command: calls.append(command) or 0,
    )

    assert result == "SUCCESS"
    assert calls == [["bash", str(tmp_path / "runner.sh")]]
    state = scheduler.load_state(state_path)
    assert state["last_run_local_date"] == "2026-09-13"
    assert state["last_result"] == "SUCCESS"

    second = scheduler.run_once(
        runner=tmp_path / "runner.sh",
        state_path=state_path,
        now=datetime(2026, 9, 13, 3, 0, tzinfo=UTC),
        executor=lambda command: calls.append(command) or 0,
    )
    assert second == "NOT_DUE"
    assert len(calls) == 1


def test_missed_schedule_runs_when_runtime_returns_later_that_day(tmp_path: Path) -> None:
    scheduler = _scheduler()
    result = scheduler.run_once(
        runner=tmp_path / "runner.sh",
        state_path=tmp_path / "state.json",
        # 06:00 UTC == 13:00 Bangkok, after the intended 07:10 run.
        now=datetime(2026, 9, 13, 6, 0, tzinfo=UTC),
        executor=lambda _: 0,
    )
    assert result == "SUCCESS"


def test_failed_attempt_is_retryable(tmp_path: Path) -> None:
    scheduler = _scheduler()
    state_path = tmp_path / "state.json"
    attempts = 0

    def fail_then_pass(_: list[str]) -> int:
        nonlocal attempts
        attempts += 1
        return 1 if attempts == 1 else 0

    first = scheduler.run_once(
        runner=tmp_path / "runner.sh",
        state_path=state_path,
        now=datetime(2026, 9, 13, 0, 10, tzinfo=UTC),
        executor=fail_then_pass,
    )
    assert first == "FAILED"
    assert scheduler.load_state(state_path).get("last_run_local_date") is None

    second = scheduler.run_once(
        runner=tmp_path / "runner.sh",
        state_path=state_path,
        now=datetime(2026, 9, 13, 0, 11, tzinfo=UTC),
        executor=fail_then_pass,
    )
    assert second == "SUCCESS"
    assert attempts == 2


def test_next_day_is_eligible_again(tmp_path: Path) -> None:
    scheduler = _scheduler()
    state_path = tmp_path / "state.json"
    scheduler.write_state(
        state_path,
        {
            "schema_version": scheduler.STATE_SCHEMA_VERSION,
            "last_run_local_date": "2026-09-13",
        },
    )

    result = scheduler.run_once(
        runner=tmp_path / "runner.sh",
        state_path=state_path,
        now=datetime(2026, 9, 14, 0, 10, tzinfo=UTC),
        executor=lambda _: 0,
    )
    assert result == "SUCCESS"

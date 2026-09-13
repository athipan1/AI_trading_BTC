from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, time as clock_time
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DailySchedulerConfig:
    timezone: str = "Asia/Bangkok"
    run_hour: int = 7
    run_minute: int = 10
    poll_seconds: int = 60

    def validate(self) -> None:
        if not 0 <= self.run_hour <= 23:
            raise ValueError("run_hour must be between 0 and 23")
        if not 0 <= self.run_minute <= 59:
            raise ValueError("run_minute must be between 0 and 59")
        if self.poll_seconds < 1:
            raise ValueError("poll_seconds must be >= 1")
        ZoneInfo(self.timezone)


class DailyResearchScheduler:
    """Persistent daily scheduler for environments where cron is unreliable.

    The scheduler is intentionally execution-agnostic: it only launches the
    existing Phase 5.6.2 daily runner. The runner and its checkpoint/lock remain
    the source of truth for OOS idempotency and research safety.
    """

    STATE_SCHEMA_VERSION = "phase562_daily_scheduler_state_v1"

    def __init__(self, config: DailySchedulerConfig | None = None) -> None:
        self.config = config or DailySchedulerConfig()
        self.config.validate()
        self._tz = ZoneInfo(self.config.timezone)

    def local_now(self, now: datetime | None = None) -> datetime:
        if now is None:
            return datetime.now(tz=self._tz)
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        return now.astimezone(self._tz)

    def scheduled_time(self) -> clock_time:
        return clock_time(hour=self.config.run_hour, minute=self.config.run_minute)

    @staticmethod
    def load_state(path: str | Path) -> dict[str, object]:
        state_path = Path(path)
        if not state_path.exists():
            return {}
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("scheduler state must contain a JSON object")
        return payload

    @staticmethod
    def write_state(path: str | Path, payload: dict[str, object]) -> None:
        state_path = Path(path)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = state_path.with_suffix(f"{state_path.suffix}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(state_path)

    def should_run(self, *, now: datetime, state: dict[str, object]) -> bool:
        local = self.local_now(now)
        today = local.date().isoformat()
        last_run_date = state.get("last_run_local_date")
        after_schedule = local.time().replace(tzinfo=None) >= self.scheduled_time()
        return after_schedule and last_run_date != today

    def run_once(
        self,
        *,
        runner: str | Path,
        state_path: str | Path,
        now: datetime | None = None,
        executor: Callable[[list[str]], int] | None = None,
    ) -> str:
        current = self.local_now(now)
        state = self.load_state(state_path)
        if not self.should_run(now=current, state=state):
            return "NOT_DUE"

        command = ["bash", str(Path(runner))]
        LOGGER.info("Running daily research pipeline: %s", command)
        if executor is None:
            completed = subprocess.run(command, check=False)
            return_code = completed.returncode
        else:
            return_code = executor(command)

        result = "SUCCESS" if return_code == 0 else "FAILED"
        self.write_state(
            state_path,
            {
                "schema_version": self.STATE_SCHEMA_VERSION,
                "timezone": self.config.timezone,
                "scheduled_local_time": f"{self.config.run_hour:02d}:{self.config.run_minute:02d}",
                "last_attempt_at": current.isoformat(),
                "last_attempt_local_date": current.date().isoformat(),
                "last_return_code": return_code,
                "last_result": result,
                # Mark a day complete only after a successful runner. A failed
                # attempt remains eligible for retry on the next poll.
                "last_run_local_date": current.date().isoformat() if return_code == 0 else state.get("last_run_local_date"),
            },
        )
        return result

    def run_forever(self, *, runner: str | Path, state_path: str | Path) -> None:
        LOGGER.info(
            "Daily scheduler started timezone=%s schedule=%02d:%02d poll=%ss",
            self.config.timezone,
            self.config.run_hour,
            self.config.run_minute,
            self.config.poll_seconds,
        )
        while True:
            try:
                result = self.run_once(runner=runner, state_path=state_path)
                if result != "NOT_DUE":
                    LOGGER.info("Daily scheduler attempt result=%s", result)
            except Exception:
                LOGGER.exception("Daily scheduler iteration failed")
            time.sleep(self.config.poll_seconds)

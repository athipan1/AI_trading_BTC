"""Independent research-only Candidate V2 monitor for Termux/VPS.

No exchange endpoints, trade APIs, V1 evidence mutations, or auto promotion.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.notifications.line_messaging import LineMessagingNotifier
from app.research.candidate_v2_alerts import CandidateV2AlertPolicy
from app.research.candidate_v2_integrity import CandidateV2IntegrityAuditor
from app.research.candidate_v2_watchdog import CandidateV2Watchdog

LOGGER = logging.getLogger("phase574_monitor")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 5.7.4 independent V2 integrity/watchdog")
    root = "state/research"
    parser.add_argument("--manifest", default=f"{root}/phase572_v2_manifest.json")
    parser.add_argument("--candidate-store", default=f"{root}/phase573_v2_candidate_oos.json")
    parser.add_argument("--baseline-store", default=f"{root}/phase573_v2_baseline_oos.json")
    parser.add_argument("--checkpoint", default=f"{root}/phase573_v2_checkpoint.json")
    parser.add_argument("--heartbeat", default=f"{root}/phase574_v2_heartbeat.json")
    parser.add_argument("--forward-report", default=f"{root}/phase573_v2_latest_report.json")
    parser.add_argument("--health", default=f"{root}/phase574_v2_health.json")
    parser.add_argument("--audit-state", default=f"{root}/phase574_v2_audit_state.json")
    parser.add_argument("--alert-state", default=f"{root}/phase574_v2_alert_state.json")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--line-alerts", action="store_true", help="LINE sends require credentials")
    return parser.parse_args()


def _read_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid monitoring state: {path.name}")
    return payload


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


@contextmanager
def _monitor_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Phase 5.7.4 monitor already running on these files") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def run_once(args: argparse.Namespace, *, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    audit_path = Path(args.audit_state)
    previous = _read_state(audit_path)
    auditor = CandidateV2IntegrityAuditor()
    audit, next_state = auditor.inspect(
        manifest_path=args.manifest,
        candidate_store_path=args.candidate_store,
        baseline_store_path=args.baseline_store,
        checkpoint_path=args.checkpoint,
        previous_state=previous,
        now=current,
    )
    health = CandidateV2Watchdog().evaluate(
        integrity=audit,
        heartbeat_path=args.heartbeat,
        report_path=args.forward_report,
        now=current,
    )
    # Health output may be consumed by the read-only API; contains no API keys.
    _atomic_json(Path(args.health), health)
    if next_state is not None:
        _atomic_json(audit_path, next_state)
    if args.line_alerts:
        alert_path = Path(args.alert_state)
        previous_alert = _read_state(alert_path)
        kind, pending = CandidateV2AlertPolicy.decision(health, previous_alert, now=current)
        if (
            kind == "RECOVERY"
            and previous_alert is not None
            and int(previous_alert.get("recovery_checks", 0)) < 1
        ):
            # Persist one good check but do not falsely mark LINE as delivered.
            preview = {**previous_alert, "recovery_checks": 1}
            _atomic_json(alert_path, preview)
        elif kind is not None:
            token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
            target = os.environ.get("LINE_TARGET_ID", "").strip()
            if token and target:
                # Never advance last_notified_at if LINE fails.
                LineMessagingNotifier(token, target).send_text(
                    CandidateV2AlertPolicy.message(health, kind)
                )
                _atomic_json(alert_path, pending)
            else:
                LOGGER.warning("LINE not configured; %s notification not acknowledged", kind)
    return health


def main() -> int:
    args = parse_args()
    if args.interval_seconds < 60:
        raise ValueError("monitor poll interval must be at least 60 seconds")
    paths = [args.manifest, args.candidate_store, args.baseline_store, args.checkpoint,
             args.heartbeat, args.forward_report, args.health, args.audit_state, args.alert_state]
    if len({Path(p).resolve() for p in paths}) != len(paths):
        raise ValueError("monitor inputs and outputs must have unique paths")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with _monitor_lock(Path(args.health)):
        while True:
            try:
                health = run_once(args)
                LOGGER.info("Phase 5.7.4 %s watcher=%s candidate=%s", health["operational_state"],
                            health["watcher_state"], (health["counts"] or {}).get("candidate_v2_closed"))
                if not args.watch:
                    print(json.dumps(health, ensure_ascii=False, indent=2, sort_keys=True))
                    return 2 if health["operational_state"] == "CRITICAL" else 0
            except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
                LOGGER.exception("Phase 5.7.4 iteration error: %s", exc)
                if not args.watch:
                    return 2
            if not args.watch:
                return 0
            try:
                time.sleep(args.interval_seconds)
            except KeyboardInterrupt:
                return 0


if __name__ == "__main__":
    raise SystemExit(main())
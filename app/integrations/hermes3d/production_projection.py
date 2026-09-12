from __future__ import annotations

from typing import Any

from app.integrations.hermes3d.projection import Hermes3DJournalStateProjection


class Hermes3DProductionJournalStateProjection(Hermes3DJournalStateProjection):
    """Production-facing Hermes3D projection with validation-event isolation.

    Validation events remain in the append-only journal for auditability and can still
    travel through the realtime event stream, but they must not become the durable
    production snapshot served by ``/state``.
    """

    VALIDATION_SOURCES = frozenset({"phase-1.7.2-live-office-validation"})

    @classmethod
    def _is_validation_record(cls, record: dict[str, Any]) -> bool:
        payload = record.get("payload")
        if not isinstance(payload, dict):
            return False
        if payload.get("validation") is True:
            return True
        source = str(payload.get("source") or "").strip()
        return source in cls.VALIDATION_SOURCES

    def _records(self) -> list[dict[str, Any]]:
        return [
            record
            for record in super()._records()
            if not self._is_validation_record(record)
        ]

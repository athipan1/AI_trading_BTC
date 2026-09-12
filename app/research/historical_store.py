from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class HistoricalResearchStore:
    """Persistent, idempotent research-only store for historical replay trades."""

    SCHEMA_VERSION = "historical_research_store_v1"
    _STORE_METADATA_FIELDS = {
        "data_origin",
        "replay_schema_version",
        "dataset_run_id",
        "source",
        "git_commit",
    }

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("historical research store must contain a JSON object")
        if payload.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("unsupported historical research store schema")
        trades = payload.get("trades", [])
        if not isinstance(trades, list):
            raise ValueError("historical research store trades must be a list")
        return [dict(item) for item in trades if isinstance(item, dict)]

    def _write(self, trades: list[dict[str, Any]]) -> None:
        ordered = sorted(
            trades,
            key=lambda item: (str(item.get("created_at") or ""), str(item.get("order_id") or "")),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(
                {"schema_version": self.SCHEMA_VERSION, "trades": ordered},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        temp_path.replace(self.path)

    @classmethod
    def _core_trade(cls, item: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in item.items()
            if key not in cls._STORE_METADATA_FIELDS
        }

    def upsert_replay(
        self,
        replay: dict[str, Any],
        *,
        dataset_run_id: str,
        source: str = "binance_ohlcv",
        git_commit: str | None = None,
    ) -> dict[str, int]:
        incoming = replay.get("trades", [])
        if not isinstance(incoming, list):
            raise ValueError("replay trades must be a list")

        existing = {str(item.get("order_id")): item for item in self.load() if item.get("order_id")}
        inserted = 0
        updated = 0
        for raw in incoming:
            if not isinstance(raw, dict):
                continue
            order_id = str(raw.get("order_id", "")).strip()
            if not order_id:
                raise ValueError("historical trade is missing order_id")
            item = {
                **raw,
                "data_origin": "historical_replay",
                "replay_schema_version": replay.get("schema_version"),
                "dataset_run_id": dataset_run_id,
                "source": source,
                "git_commit": git_commit,
            }
            if order_id in existing:
                if existing[order_id] != item:
                    existing[order_id] = item
                    updated += 1
            else:
                existing[order_id] = item
                inserted += 1

        self._write(list(existing.values()))
        return {"inserted": inserted, "updated": updated, "total": len(existing)}

    def append_immutable_replay(
        self,
        replay: dict[str, Any],
        *,
        dataset_run_id: str,
        minimum_entry_feature_timestamp_ms: int,
        source: str = "binance_ohlcv",
        git_commit: str | None = None,
    ) -> dict[str, int]:
        """Append fresh replay trades without ever modifying an existing order_id."""
        incoming = replay.get("trades", [])
        if not isinstance(incoming, list):
            raise ValueError("replay trades must be a list")

        existing = {str(item.get("order_id")): item for item in self.load() if item.get("order_id")}
        inserted = 0
        duplicate_skipped = 0
        filtered_before_boundary = 0

        for raw in incoming:
            if not isinstance(raw, dict):
                continue
            timestamp = int(raw.get("entry_feature_timestamp_ms") or 0)
            if timestamp < minimum_entry_feature_timestamp_ms:
                filtered_before_boundary += 1
                continue

            order_id = str(raw.get("order_id", "")).strip()
            if not order_id:
                raise ValueError("historical trade is missing order_id")

            current = existing.get(order_id)
            if current is not None:
                if self._core_trade(current) != self._core_trade(raw):
                    raise ValueError(
                        f"immutable research trade conflict for order_id={order_id}"
                    )
                duplicate_skipped += 1
                continue

            existing[order_id] = {
                **raw,
                "data_origin": "historical_replay",
                "replay_schema_version": replay.get("schema_version"),
                "dataset_run_id": dataset_run_id,
                "source": source,
                "git_commit": git_commit,
            }
            inserted += 1

        self._write(list(existing.values()))
        return {
            "inserted": inserted,
            "duplicate_skipped": duplicate_skipped,
            "filtered_before_boundary": filtered_before_boundary,
            "total": len(existing),
        }

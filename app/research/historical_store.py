from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class HistoricalResearchStore:
    """Persistent, idempotent research-only store for historical replay trades."""

    SCHEMA_VERSION = "historical_research_store_v1"

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

        trades = sorted(
            existing.values(),
            key=lambda item: (str(item.get("created_at") or ""), str(item.get("order_id") or "")),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(
                {"schema_version": self.SCHEMA_VERSION, "trades": trades},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        temp_path.replace(self.path)
        return {"inserted": inserted, "updated": updated, "total": len(trades)}

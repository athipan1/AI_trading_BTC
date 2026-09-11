from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class HistoricalDiagnosticsReport:
    """Read-only loader for the latest Phase 5.0.2 diagnostics artifact."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": "historical_dataset_diagnostics_v1",
                "status": "NOT_BUILT",
                "path": str(self.path),
            }
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("historical diagnostics report must contain a JSON object")
        return payload

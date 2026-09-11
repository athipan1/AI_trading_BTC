from __future__ import annotations

import json
from pathlib import Path

from app.research.historical_report import HistoricalDiagnosticsReport


def test_missing_historical_report_is_explicit(tmp_path: Path) -> None:
    report = HistoricalDiagnosticsReport(tmp_path / "missing.json")

    result = report.load()

    assert result["schema_version"] == "historical_dataset_diagnostics_v1"
    assert result["status"] == "NOT_BUILT"


def test_historical_report_loads_persisted_diagnostics(tmp_path: Path) -> None:
    path = tmp_path / "historical-diagnostics.json"
    payload = {
        "schema_version": "historical_dataset_diagnostics_v1",
        "readiness": {"dataset": "READY"},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = HistoricalDiagnosticsReport(path).load()

    assert result == payload

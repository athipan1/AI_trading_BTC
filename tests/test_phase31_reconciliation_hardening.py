from __future__ import annotations

from pathlib import Path

from app.integrations.hermes3d.analytics import Hermes3DTradingAnalyticsProjection
from app.integrations.hermes3d.journal import Hermes3DEventJournal
from app.monitoring.binance_fill_reconciler import FillSummary, PositionFillReconciler
from app.monitoring.position_store import PositionStore


class FlakyFillSource:
    source_name = "flaky-test-source"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_order_fills(self, symbol: str, order_id: str) -> FillSummary:
        self.calls.append(order_id)
        if self.calls.count(order_id) == 1:
            raise ValueError(f"no Binance fills found for order {order_id}")
        price = 100.0 if order_id == "entry" else 110.0
        return FillSummary(
            order_id=order_id,
            fill_count=1,
            filled_quantity=0.1,
            quote_quantity=price * 0.1,
            average_price=price,
            commission_by_asset={"USDT": 0.01},
            commission_quote_equivalent=0.01,
            commission_quote_complete=True,
            realized_pnl=None,
            trade_ids=[f"trade-{order_id}"],
        )


class AlwaysMissingFillSource:
    source_name = "missing-test-source"

    def fetch_order_fills(self, symbol: str, order_id: str) -> FillSummary:
        raise ValueError(f"no Binance fills found for order {order_id}")


def _closed_store(path: Path) -> PositionStore:
    store = PositionStore(path)
    store.add_long_position(
        order_id="entry",
        symbol="BTC/USDT",
        entry_price=100.0,
        quantity=0.1,
        take_profit=110.0,
        stop_loss=95.0,
    )
    store.mark_closed(
        "entry",
        exit_order_id="exit",
        exit_reason="TP_HIT",
        exit_price=110.0,
    )
    return store


def test_reconciler_retries_pending_fill_and_records_attempt_metadata(tmp_path: Path) -> None:
    store = _closed_store(tmp_path / "positions.json")
    source = FlakyFillSource()
    sleeps: list[float] = []
    reconciler = PositionFillReconciler(
        position_store=store,
        fill_source=source,
        retry_delays=(0.0, 0.25),
        sleep_fn=sleeps.append,
    )

    result = reconciler.reconcile_all()
    position = store.load()[0]

    assert result["reconciled"] == 1
    assert result["pending"] == 0
    assert result["attempts"] == 2
    assert result["error_count"] == 0
    assert sleeps == [0.25]
    assert position["reconciliation_status"] == "RECONCILED"
    assert position["reconciliation_attempts"] == 2
    assert position["last_reconciliation_attempt_at"] is not None
    assert position["last_reconciliation_error"] is None
    assert position["last_reconciliation_error_at"] is None


def test_reconciler_skips_terminal_reconciled_position(tmp_path: Path) -> None:
    store = _closed_store(tmp_path / "positions.json")
    source = FlakyFillSource()
    reconciler = PositionFillReconciler(
        position_store=store,
        fill_source=source,
        retry_delays=(0.0, 0.0),
        sleep_fn=lambda _: None,
    )
    first = reconciler.reconcile_all()
    calls_after_first = list(source.calls)
    second = reconciler.reconcile_all()

    assert first["reconciled"] == 1
    assert second["reconciled"] == 0
    assert second["skipped"] == 1
    assert second["attempts"] == 0
    assert source.calls == calls_after_first


def test_reconciler_exhaustion_stays_pending_and_persists_last_error(tmp_path: Path) -> None:
    store = _closed_store(tmp_path / "positions.json")
    reconciler = PositionFillReconciler(
        position_store=store,
        fill_source=AlwaysMissingFillSource(),
        retry_delays=(0.0, 0.0, 0.0),
        sleep_fn=lambda _: None,
    )

    result = reconciler.reconcile_all()
    position = store.load()[0]

    assert result["reconciled"] == 0
    assert result["pending"] == 1
    assert result["attempts"] == 3
    assert result["error_count"] == 1
    assert position["reconciliation_status"] == "PENDING"
    assert position["reconciliation_attempts"] == 3
    assert "no Binance fills found" in position["last_reconciliation_error"]
    assert position["last_reconciliation_error_at"] is not None


def test_analytics_exposes_pending_reconciliation_health(tmp_path: Path) -> None:
    spot_store = _closed_store(tmp_path / "spot.json")
    spot_store.mark_reconciliation_attempt("entry")
    spot_store.mark_reconciliation_error("entry", "temporary exchange lag")
    projection = Hermes3DTradingAnalyticsProjection(
        journal=Hermes3DEventJournal(tmp_path / "events.jsonl"),
        spot_position_store=spot_store,
        futures_position_store=PositionStore(tmp_path / "futures.json"),
        auto_state_paths={},
    )

    quality = projection.analytics()["data_quality"]

    assert quality["pending_reconciliation_trades"] == 1
    assert quality["reconciliation_error_count"] == 1
    assert quality["oldest_pending_age_seconds"] is not None
    assert quality["oldest_pending_age_seconds"] >= 0
    assert quality["last_reconciliation_at"] is None

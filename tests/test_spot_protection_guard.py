from __future__ import annotations

import pytest

from app.execution.binance_spot_protection_guard import BinanceSpotProtectionGuard
from app.execution.binance_spot_reconciliation import ProtectiveReconciliation
from app.execution.binance_testnet import BinanceTestnetSafetyError


class Reconciler:
    def __init__(self, state: str, safe: bool = False):
        self.state = state
        self.safe = safe
        self.calls = 0

    def reconcile(self, *, entry_order_id: str) -> ProtectiveReconciliation:
        self.calls += 1
        return ProtectiveReconciliation(
            entry_order_id=entry_order_id,
            state=self.state,
            safe_to_software_exit=self.safe,
            mutation_performed=self.state == "EXCHANGE_EXIT_RECONCILED",
            detail="test",
        )


class Service:
    def __init__(self):
        self.calls = 0

    def place_oco(self, **kwargs):
        self.calls += 1

        class Result:
            order_list_id = 77

        return Result()


POSITION = {
    "order_id": "3489476",
    "status": "OPEN",
    "side": "buy",
    "symbol": "BTC/USDT",
    "quantity": 0.00012,
    "take_profit": 78483.55,
    "stop_loss": 77059.52,
}


def test_unprotected_position_places_one_oco() -> None:
    service = Service()
    guard = BinanceSpotProtectionGuard(service, Reconciler("UNPROTECTED", safe=True))

    result = guard.ensure_protected(POSITION)

    assert result.state == "PROTECTION_PLACED"
    assert result.order_list_id == 77
    assert service.calls == 1


def test_existing_protection_is_idempotent() -> None:
    service = Service()
    guard = BinanceSpotProtectionGuard(service, Reconciler("PROTECTED"))

    result = guard.ensure_protected(POSITION)

    assert result.state == "ALREADY_PROTECTED"
    assert service.calls == 0


def test_incomplete_protection_fails_closed() -> None:
    service = Service()
    guard = BinanceSpotProtectionGuard(service, Reconciler("PROTECTION_INCOMPLETE"))

    with pytest.raises(BinanceTestnetSafetyError, match="PROTECTION_INCOMPLETE"):
        guard.ensure_protected(POSITION)
    assert service.calls == 0


def test_reconciled_exit_does_not_submit_oco() -> None:
    service = Service()
    guard = BinanceSpotProtectionGuard(service, Reconciler("EXCHANGE_EXIT_RECONCILED"))

    result = guard.ensure_protected(POSITION)

    assert result.state == "EXCHANGE_EXIT_RECONCILED"
    assert service.calls == 0


def test_software_sell_is_blocked_when_exchange_protected() -> None:
    guard = BinanceSpotProtectionGuard(Service(), Reconciler("PROTECTED", safe=False))

    with pytest.raises(BinanceTestnetSafetyError, match="PROTECTED"):
        guard.assert_software_exit_safe(POSITION)
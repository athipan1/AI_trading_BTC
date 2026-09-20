from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.execution.binance_spot_protection import BinanceSpotProtectiveExitService
from app.execution.binance_spot_reconciliation import BinanceSpotProtectionReconciler
from app.execution.binance_testnet import BinanceTestnetSafetyError


@dataclass(frozen=True)
class ProtectionGuardResult:
    state: str
    order_list_id: int | None
    detail: str


class BinanceSpotProtectionGuard:
    """Idempotent guard for fixed TP/SL Spot Testnet positions."""

    def __init__(
        self,
        service: BinanceSpotProtectiveExitService,
        reconciler: BinanceSpotProtectionReconciler,
    ) -> None:
        self.service = service
        self.reconciler = reconciler

    def ensure_protected(self, position: dict[str, Any]) -> ProtectionGuardResult:
        entry_order_id = str(position["order_id"])
        if position.get("status") != "OPEN":
            raise BinanceTestnetSafetyError("refusing protection for non-open position")
        if str(position.get("side", "")).lower() != "buy":
            raise BinanceTestnetSafetyError("Spot protection guard supports long positions only")
        if position.get("take_profit") is None:
            raise BinanceTestnetSafetyError("fixed protective exit requires take-profit")

        before = self.reconciler.reconcile(entry_order_id=entry_order_id)
        if before.state == "PROTECTED":
            return ProtectionGuardResult(
                state="ALREADY_PROTECTED",
                order_list_id=None,
                detail="existing exchange protection retained; no duplicate OCO submitted",
            )
        if before.state != "UNPROTECTED":
            raise BinanceTestnetSafetyError(
                f"refusing OCO placement from reconciliation state {before.state}"
            )

        placed = self.service.place_oco(
            symbol=str(position["symbol"]),
            entry_order_id=entry_order_id,
            quantity=float(position["quantity"]),
            take_profit=float(position["take_profit"]),
            stop_loss=float(position["stop_loss"]),
        )
        return ProtectionGuardResult(
            state="PROTECTION_PLACED",
            order_list_id=placed.order_list_id,
            detail="exchange-side OCO submitted after UNPROTECTED reconciliation",
        )

    def assert_software_exit_safe(self, position: dict[str, Any]) -> None:
        result = self.reconciler.reconcile(entry_order_id=str(position["order_id"]))
        if not result.safe_to_software_exit:
            raise BinanceTestnetSafetyError(
                f"software SELL blocked by exchange protection state {result.state}"
            )